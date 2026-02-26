#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import json
import os
import importlib.util
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, JSONResponse
import uvicorn

from settings import (
    WS,
    OLLAMA_MODEL,
    OLLAMA_URL,
    SYSTEM_PROMPT,
    MYCLAW_API_KEY,
)

UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY)
MDS = ["SOUL.md", "PERSONALITY.md", "MEMORIES.md"]
app = FastAPI(title="myclaw")

_tools_cache = None
_tools_dir_cache = None


def _auth(authorization: str = Header(None)):
    if KEY and authorization != f"Bearer {KEY}" and authorization != KEY:
        raise HTTPException(401, "Invalid API key")


def md() -> str:
    return "\n\n".join(
        f"<!-- {n} -->\n{(WS / n).read_text().strip()}"
        for n in MDS
        if (WS / n).exists()
    )


def tools() -> list:
    global _tools_cache, _tools_dir_cache
    for dir in [Path(__file__).parent, WS]:
        if dir == _tools_dir_cache and _tools_cache is not None:
            return _tools_cache
        p = dir / "tools.py"
        if p.exists():
            m = importlib.util.module_from_spec(
                s := importlib.util.spec_from_file_location("t", p)
            )
            s.loader.exec_module(m)
            _tools_cache = getattr(m, "TOOLS", [])
            _tools_dir_cache = dir
            return _tools_cache
    return []


def call_tool(name: str, arguments: dict) -> str:
    for dir in [Path(__file__).parent, WS]:
        p = dir / "tools.py"
        if p.exists():
            m = importlib.util.module_from_spec(
                s := importlib.util.spec_from_file_location("t", p)
            )
            s.loader.exec_module(m)
            tool_funcs = getattr(m, "TOOL_FUNCTIONS", {})
            if name in tool_funcs:
                try:
                    return tool_funcs[name](**arguments)
                except Exception as e:
                    return f"Error: {str(e)}"
    return f"Tool {name} not found"


def inject(msgs, block):
    if not block:
        return msgs
    if msgs and msgs[0]["role"] == "system":
        msgs[0]["content"] = block + "\n\n" + msgs[0]["content"]
    else:
        msgs = [{"role": "system", "content": block}] + msgs
    return msgs


def hdrs(req):
    auth = req.headers.get("authorization", "")
    if auth and KEY:
        return {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
    elif auth:
        return {"Authorization": auth, "Content-Type": "application/json"}
    return {"Content-Type": "application/json"}


@app.get("/health")
async def health():
    return {"status": "ok", "workspace": str(WS)}


@app.get("/md/{f}")
async def get_md(f: str, authorization: str = Header(None)):
    if KEY and authorization != f"Bearer {KEY}" and authorization != KEY:
        raise HTTPException(401, "Invalid API key")
    if f not in MDS:
        raise HTTPException(404)
    return {"filename": f, "content": (WS / f).read_text() if (WS / f).exists() else ""}


@app.put("/md/{f}")
async def put_md(f: str, req: Request, authorization: str = Header(None)):
    if KEY and authorization != f"Bearer {KEY}" and authorization != KEY:
        raise HTTPException(401, "Invalid API key")
    if f not in MDS:
        raise HTTPException(404)
    WS.mkdir(parents=True, exist_ok=True)
    (WS / f).write_bytes(await req.body())
    return {"status": "saved"}


def _dedupe_tools(client_tools: list, server_tools: list) -> list:
    client_names = {
        t.get("function", {}).get("name") for t in client_tools if t.get("function")
    }
    return server_tools + [
        t for t in client_tools if t.get("function", {}).get("name") not in client_names
    ]


@app.post("/v1/chat/completions")
async def chat(req: Request, authorization: str = Header(None)):
    if KEY and authorization != f"Bearer {KEY}" and authorization != KEY:
        raise HTTPException(401, "Invalid API key")
    try:
        p = await req.json()
        if "messages" not in p:
            return JSONResponse({"error": "messages is required"}, status_code=400)

        if OLLAMA_MODEL and OLLAMA_MODEL != "llama3.2":
            p["model"] = OLLAMA_MODEL

        block = md()
        full_block = SYSTEM_PROMPT + ("\n\n" + block if block else "")
        p["messages"] = inject(p.get("messages", []), full_block)

        server_tools = tools()
        if server_tools:
            p["tools"] = _dedupe_tools(p.get("tools", []), server_tools)

        url, h = f"{UP.rstrip('/')}/v1/chat/completions", hdrs(req)

        if p.get("stream"):
            c = httpx.AsyncClient(timeout=300)

            async def gen():
                try:
                    async with c.stream("POST", url, json=p, headers=h) as r:
                        async for line in r.aiter_lines():
                            if line:
                                yield f"{line}\n"
                finally:
                    await c.aclose()

            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            async with httpx.AsyncClient(timeout=300) as c:
                response = await c.post(url, json=p, headers=h)
                result = response.json()

                if "choices" in result:
                    choice = result["choices"][0]
                    msg = choice.get("message", {})
                    tool_calls = msg.get("tool_calls", [])

                    while tool_calls:
                        p["messages"].append(msg)

                        for tc in tool_calls:
                            func_name = tc.get("function", {}).get("name")
                            args = tc.get("function", {}).get("arguments", {})
                            if isinstance(args, str):
                                args = json.loads(args)

                            tool_result = call_tool(func_name, args)

                            p["messages"].append(
                                {
                                    "role": "tool",
                                    "name": func_name,
                                    "content": str(tool_result),
                                }
                            )

                        response = await c.post(url, json=p, headers=h)
                        result = response.json()

                        if "choices" in result:
                            choice = result["choices"][0]
                            msg = choice.get("message", {})
                            tool_calls = msg.get("tool_calls", [])
                        else:
                            break

                return result
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    except Exception as e:
        import traceback

        return JSONResponse(
            {"error": str(e), "traceback": traceback.format_exc()}, status_code=500
        )


if __name__ == "__main__":
    WS.mkdir(parents=True, exist_ok=True)
    [
        ((WS / f).write_text(f"# {f.removesuffix('.md')}\n"))
        for f in MDS
        if not (WS / f).exists()
    ]
    host = os.getenv("MYCLAW_HOST", "0.0.0.0")
    port = int(os.getenv("MYCLAW_PORT", "8080"))
    print(f"workspace:{WS}  upstream:{UP}  listen:{host}:{port}")
    uvicorn.run(app, host=host, port=port)
