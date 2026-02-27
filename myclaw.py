#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import json, logging, os
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn
from settings import (
    WS,
    OLLAMA_MODEL,
    OLLAMA_URL,
    SYSTEM_PROMPT,
    MYCLAW_API_KEY,
    MAX_TOOL_CALLS,
    MAX_PAYLOAD_SIZE,
    MDS,
    MYCLAW_HOST,
    MYCLAW_PORT,
)
from tools._loader import load_tools, invalidate_cache

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY)
CHECK_UPSTREAM = os.getenv("MYCLAW_CHECK_UPSTREAM", "").lower() in ("1", "true", "yes")

http = httpx.AsyncClient(timeout=300)
_t, _tf = None, None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await http.aclose()


app = FastAPI(title="myclaw", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def md() -> str:
    parts = []
    for n in MDS:
        try:
            fp = WS / n
            if fp.exists():
                parts.append(f"<!-- {n} -->\n{fp.read_text().strip()}")
        except Exception as e:
            logging.warning(f"Failed to read {n}: {e}")
    return "\n\n".join(parts)


def tools():
    global _t, _tf
    if _t is None:
        _t, _tf = load_tools(project_root=Path(__file__).parent, workspace=WS)
    return _t


def call_tool(n, a):
    global _tf
    if _tf is None:
        tools()
    if _tf and n in _tf:
        try:
            return _tf[n](**a)
        except Exception as e:
            return {"error": str(e), "success": False}
    return {"error": f"Tool {n} not found", "success": False}


def _auth(a):
    return KEY and a != f"Bearer {KEY}" and a != KEY


def _dedupe(client, server):
    seen = {(x.get("function") or {}).get("name") for x in client}
    return server + [
        t for t in client if (t.get("function") or {}).get("name") not in seen
    ]


@app.get("/health")
def _h():
    return {"status": "ok", "workspace": str(WS)}


@app.post("/_invalidate_cache")
async def _ic(a=Header(None)):
    if _auth(a):
        raise HTTPException(401)
    invalidate_cache()
    global _t, _tf
    _t = _tf = None
    return {"status": "cache invalidated"}


@app.get("/md/{f}")
async def _gf(f, a=Header(None)):
    if _auth(a) or f not in MDS:
        raise HTTPException(401 if _auth(a) else 404)
    return {"filename": f, "content": (WS / f).read_text() if (WS / f).exists() else ""}


@app.put("/md/{f}")
async def _pf(f, r: Request, a=Header(None)):
    if _auth(a) or f not in MDS:
        raise HTTPException(401 if _auth(a) else 404)
    b = await r.body()
    if len(b) > MAX_PAYLOAD_SIZE:
        return JSONResponse({"error": "File too large"}, status_code=413)
    WS.mkdir(parents=True, exist_ok=True)
    (WS / f).write_bytes(b)
    return {"status": "saved"}


@app.post("/v1/chat/completions")
async def chat(r: Request, a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")
    try:
        if CHECK_UPSTREAM:
            try:
                health_resp = await http.get(f"{UP.rstrip('/')}/api/tags", timeout=5)
                if health_resp.status_code >= 400:
                    return JSONResponse(
                        {"error": f"Upstream unhealthy: {health_resp.status_code}"}, 503
                    )
            except Exception as e:
                return JSONResponse({"error": f"Upstream unreachable: {e}"}, 503)

        p = await r.json()
        if "messages" not in p:
            return JSONResponse({"error": "messages required"}, 400)

        p["model"] = OLLAMA_MODEL or None
        b = md()
        p["messages"] = [
            {"role": "system", "content": SYSTEM_PROMPT + ("\n\n" + b if b else "")}
        ] + [
            {"role": x["role"], "content": x["content"]}
            for x in p.get("messages", [])
            if x.get("role") != "system"
        ]

        if t := tools():
            p["tools"] = _dedupe(p.get("tools", []), t)

        u, h = (
            f"{UP.rstrip('/')}/v1/chat/completions",
            {
                "Authorization": f"Bearer {KEY}" if KEY else "",
                "Content-Type": "application/json",
            },
        )

        if p.get("stream"):

            async def g():
                try:
                    async with http.stream("POST", u, json=p, headers=h) as x:
                        if x.status_code >= 400:
                            yield f'{{"error":"Upstream {x.status_code}"}}\n'
                            return
                        async for l in x.aiter_lines():
                            if l:
                                yield f"{l}\n"
                except Exception as e:
                    yield f'{{"error":"{e}"}}\n'

            return StreamingResponse(g(), media_type="text/event-stream")

        tc = 0
        while tc < MAX_TOOL_CALLS:
            x = await http.post(u, json=p, headers=h)
            if x.status_code >= 400:
                return JSONResponse({"error": f"Upstream {x.status_code}"}, 502)
            try:
                R = x.json()
            except:
                return JSONResponse({"error": "Invalid JSON from upstream"}, 502)
            if "choices" not in R:
                return R
            m, ts = (
                R["choices"][0]["message"],
                R["choices"][0]["message"].get("tool_calls", []),
            )
            if not ts:
                return R
            p["messages"].append(m)
            for t_ in ts:
                fn, ag = t_["function"]["name"], t_["function"]["arguments"]
                p["messages"].append(
                    {
                        "role": "tool",
                        "name": fn,
                        "content": str(
                            call_tool(fn, json.loads(ag) if isinstance(ag, str) else ag)
                        ),
                    }
                )
            tc += 1
        return JSONResponse({"error": f"Max tool calls ({MAX_TOOL_CALLS})"}, 400)
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, 400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)


if __name__ == "__main__":
    WS.mkdir(parents=True, exist_ok=True)
    for f in MDS:
        if not (WS / f).exists():
            (WS / f).write_text(f"# {f[:-3]}\n")
    print(f"workspace:{WS} upstream:{UP} listen:{MYCLAW_HOST}:{MYCLAW_PORT}")
    uvicorn.run(app, host=MYCLAW_HOST, port=MYCLAW_PORT)
