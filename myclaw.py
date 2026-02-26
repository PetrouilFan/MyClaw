#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import json
import logging
import os
import traceback
import importlib.util
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
log = logging.getLogger(__name__)

UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY)
MDS = ["SOUL.md", "PERSONALITY.md", "MEMORIES.md"]
app = FastAPI(title="myclaw")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_tools_cache = None
_tools_dir_cache = None
_tool_funcs_cache = None


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
            global _tool_funcs_cache
            _tool_funcs_cache = getattr(m, "TOOL_FUNCTIONS", {})
            _tools_cache = getattr(m, "TOOLS", [])
            _tools_dir_cache = dir
            log.info(f"Loaded tools from {p}")
            return _tools_cache
    return []


def invalidate_tools_cache():
    global _tools_cache, _tools_dir_cache, _tool_funcs_cache
    _tools_cache = None
    _tools_dir_cache = None
    _tool_funcs_cache = None
    log.info("Tools cache invalidated")


def call_tool(name: str, arguments: dict) -> str:
    global _tool_funcs_cache
    if _tool_funcs_cache is None:
        tools()
    if _tool_funcs_cache and name in _tool_funcs_cache:
        try:
            result = _tool_funcs_cache[name](**arguments)
            log.info(f"Tool {name} executed successfully")
            return result
        except Exception as e:
            log.error(f"Tool {name} failed: {e}")
            return f"Error: {str(e)}"
    return f"Tool {name} not found"


def inject(msgs, block):
    if not block:
        return list(msgs) if msgs else []
    injected = list(msgs)
    filtered = [
        {"role": m["role"], "content": m["content"]}
        for m in injected
        if m.get("role") != "system"
    ]
    filtered = [{"role": "system", "content": block}] + filtered
    return filtered


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


@app.post("/_invalidate_cache")
async def invalidate_cache(authorization: str = Header(None)):
    if KEY and authorization != f"Bearer {KEY}" and authorization != KEY:
        raise HTTPException(401, "Invalid API key")
    invalidate_tools_cache()
    return {"status": "cache invalidated"}


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
    body = await req.body()
    if len(body) > MAX_PAYLOAD_SIZE:
        return JSONResponse({"error": "File too large"}, status_code=413)
    WS.mkdir(parents=True, exist_ok=True)
    (WS / f).write_bytes(body)
    log.info(f"Updated {f}")
    return {"status": "saved"}


def _dedupe_tools(client_tools: list, server_tools: list) -> list:
    client_names = {
        t.get("function", {}).get("name") for t in client_tools if t.get("function")
    }
    return server_tools + [
        t for t in client_tools if t.get("function", {}).get("name") not in client_names
    ]


http_client = httpx.AsyncClient(timeout=300)


@app.on_event("shutdown")
async def shutdown():
    await http_client.aclose()


@app.post("/v1/chat/completions")
async def chat(req: Request, authorization: str = Header(None)):
    if KEY and authorization != f"Bearer {KEY}" and authorization != KEY:
        raise HTTPException(401, "Invalid API key")
    try:
        content_length = req.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > MAX_PAYLOAD_SIZE:
                    return JSONResponse({"error": "Request too large"}, status_code=413)
            except ValueError:
                pass

        p = await req.json()
        if "messages" not in p:
            return JSONResponse({"error": "messages is required"}, status_code=400)

        if OLLAMA_MODEL:
            p["model"] = OLLAMA_MODEL

        block = md()
        full_block = SYSTEM_PROMPT + ("\n\n" + block if block else "")
        p["messages"] = inject(p.get("messages", []), full_block)

        server_tools = tools()
        if server_tools:
            p["tools"] = _dedupe_tools(p.get("tools", []), server_tools)

        url, h = f"{UP.rstrip('/')}/v1/chat/completions", hdrs(req)

        if p.get("stream"):

            async def gen():
                try:
                    async with http_client.stream("POST", url, json=p, headers=h) as r:
                        if r.status_code >= 400:
                            yield f'{{"error": "Upstream error: {r.status_code}"}}\n'
                            return
                        async for line in r.aiter_lines():
                            if line:
                                yield f"{line}\n"
                except Exception as e:
                    log.error(f"Streaming error: {e}")
                    yield f'{{"error": "{str(e)}"}}\n'

            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            tool_call_count = 0
            while tool_call_count < MAX_TOOL_CALLS:
                response = await http_client.post(url, json=p, headers=h)
                if response.status_code >= 400:
                    return JSONResponse(
                        {
                            "error": f"Upstream error: {response.status_code}",
                            "detail": response.text[:500],
                        },
                        status_code=502,
                    )
                try:
                    result = response.json()
                except json.JSONDecodeError:
                    return JSONResponse(
                        {"error": "Invalid JSON from upstream"},
                        status_code=502,
                    )

                if "choices" in result:
                    choice = result["choices"][0]
                    msg = choice.get("message", {})
                    tool_calls = msg.get("tool_calls", [])

                    if not tool_calls:
                        return result

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

                    tool_call_count += 1
                    log.info(f"Tool call {tool_call_count}/{MAX_TOOL_CALLS}")
                else:
                    return result

            return JSONResponse(
                {"error": f"Maximum tool call limit ({MAX_TOOL_CALLS}) reached"},
                status_code=400,
            )
    except json.JSONDecodeError:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)
    except Exception as e:
        log.error(f"Request error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


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
    log.info(f"Starting myclaw - workspace: {WS}, upstream: {UP}")
    uvicorn.run(app, host=host, port=port)
