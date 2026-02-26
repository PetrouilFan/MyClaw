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
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
log, UP, KEY, MDS = (
    logging.getLogger(__name__),
    os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL),
    os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY),
    ["SOUL.md", "PERSONALITY.md", "MEMORIES.md"],
)
app = FastAPI(title="myclaw")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
_t = _td = _tf = None

md = lambda: "\n\n".join(
    f"<!-- {n} -->\n{(WS / n).read_text().strip()}" for n in MDS if (WS / n).exists()
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


inject = lambda m, b: (
    [{"role": "system", "content": b}]
    + [
        {"role": x["role"], "content": x["content"]}
        for x in (m or [])
        if x.get("role") != "system"
    ]
    if b
    else list(m)
    if m
    else []
)
hdrs = lambda r: {
    "Authorization": (f"Bearer {KEY}" if KEY else r.headers.get("authorization", "")),
    "Content-Type": "application/json",
}
_auth = lambda a: KEY and a != f"Bearer {KEY}" and a != KEY
_dedupe = lambda c, s: (
    s
    + [
        t
        for t in c
        if (t.get("function") or {}).get("name")
        not in {(x.get("function") or {}).get("name") for x in c}
    ]
)

http = httpx.AsyncClient(timeout=300)
app.on_event("shutdown")(lambda: http.aclose())


@app.get("/health")
def _h():
    return {"status": "ok", "workspace": str(WS)}


@app.post("/_invalidate_cache")
async def _ic(a=Header(None)):
    global _t, _td, _tf
    _t = _td = _tf = None
    return {"status": "cache invalidated"} if not _auth(a) else HTTPException(401)


@app.get("/md/{f}")
async def _gf(f, a=Header(None), r=Request()):
    if _auth(a) or f not in MDS:
        raise HTTPException(401 if _auth(a) else 404)
    return {"filename": f, "content": (WS / f).read_text() if (WS / f).exists() else ""}


@app.put("/md/{f}")
async def _pf(f, a=Header(None), r=Request()):
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
        if c := r.headers.get("content-length"):
            try:
                int(c) > MAX_PAYLOAD_SIZE
            except ValueError:
                pass
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
    [(WS / f).write_text(f"# {f[:-3]}\n") for f in MDS if not (WS / f).exists()]
    h, p = os.getenv("MYCLAW_HOST", "0.0.0.0"), int(os.getenv("MYCLAW_PORT", "8080"))
    print(f"workspace:{WS} upstream:{UP} listen:{h}:{p}")
    uvicorn.run(app, host=h, port=p)
