#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import json, logging, os, importlib.util
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
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

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY)

app = FastAPI(title="myclaw")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_t = _td = _tf = None
http = httpx.AsyncClient(timeout=300)
app.on_event("shutdown")(lambda: http.aclose())


def md() -> str:
    return "\n\n".join(
        f"<!-- {n} -->\n{(WS / n).read_text().strip()}"
        for n in MDS
        if (WS / n).exists()
    )


def tools():
    global _t, _td, _tf
    for d in [Path(__file__).parent, WS]:
        if d == _td and _t:
            return _t
        p = d / "tools.py"
        if p.exists():
            m = importlib.util.module_from_spec(
                s := importlib.util.spec_from_file_location("t", p)
            )
            s.loader.exec_module(m)
            _tf, _t, _td = getattr(m, "TOOL_FUNCTIONS", {}), getattr(m, "TOOLS", []), d
            return _t
    return []


def call_tool(n, a):
    global _tf
    _tf or tools()
    return _tf[n](**a) if _tf and n in _tf else f"Tool {n} not found"


def inject(messages, base_content):
    if not base_content:
        return list(messages) if messages else []
    return [{"role": "system", "content": base_content}] + [
        {"role": x["role"], "content": x["content"]}
        for x in (messages or [])
        if x.get("role") != "system"
    ]


def hdrs(r):
    return {
        "Authorization": f"Bearer {KEY}" if KEY else r.headers.get("authorization", ""),
        "Content-Type": "application/json",
    }


def _auth(a):
    return KEY and a != f"Bearer {KEY}" and a != KEY


def _dedupe(client_tools, server_tools):
    seen = {(x.get("function") or {}).get("name") for x in client_tools}
    return server_tools + [
        t for t in client_tools if (t.get("function") or {}).get("name") not in seen
    ]


@app.get("/health")
def _h():
    return {"status": "ok", "workspace": str(WS)}


@app.post("/_invalidate_cache")
async def _ic(a=Header(None)):
    global _t, _td, _tf
    _t = _td = _tf = None
    return {"status": "cache invalidated"} if not _auth(a) else HTTPException(401)


@app.get("/md/{f}")
async def _gf(f, r: Request, a=Header(None)):
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
        p = await r.json()
        if "messages" not in p:
            return JSONResponse({"error": "messages required"}, 400)
        p["model"] = OLLAMA_MODEL if OLLAMA_MODEL else None
        b = md()
        p["messages"] = inject(
            p.get("messages", []), SYSTEM_PROMPT + ("\n\n" + b if b else "")
        )
        if t := tools():
            p["tools"] = _dedupe(p.get("tools", []), t)
        u, h = f"{UP.rstrip('/')}/v1/chat/completions", hdrs(r)
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
            if "choices" in R:
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
                                call_tool(
                                    fn, json.loads(ag) if isinstance(ag, str) else ag
                                )
                            ),
                        }
                    )
                tc += 1
            else:
                return R
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
