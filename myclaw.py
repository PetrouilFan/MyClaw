#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import os, importlib.util
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
import uvicorn

WS = Path(os.getenv("MYCLAW_WORKSPACE", Path.home() / "myclaw"))
from settings import OLLAMA_MODEL, OLLAMA_URL, SYSTEM_PROMPT

UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", "")
MDS = ["SOUL.md", "PERSONALITY.md", "MEMORIES.md"]
app = FastAPI(title="myclaw")


def md() -> str:
    return "\n\n".join(
        f"<!-- {n} -->\n{(WS / n).read_text().strip()}"
        for n in MDS
        if (WS / n).exists()
    )


def tools() -> list:
    # Check current directory first, then WS
    for dir in [Path(__file__).parent, WS]:
        p = dir / "tools.py"
        if p.exists():
            m = importlib.util.module_from_spec(
                s := importlib.util.spec_from_file_location("t", p)
            )
            s.loader.exec_module(m)
            return getattr(m, "TOOLS", [])
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
async def get_md(f: str):
    if f not in MDS:
        raise HTTPException(404)
    return {"filename": f, "content": (WS / f).read_text() if (WS / f).exists() else ""}


@app.put("/md/{f}")
async def put_md(f: str, req: Request):
    if f not in MDS:
        raise HTTPException(404)
    WS.mkdir(parents=True, exist_ok=True)
    (WS / f).write_bytes(await req.body())
    return {"status": "saved"}


@app.post("/v1/chat/completions")
async def chat(req: Request):
    try:
        p = await req.json()
        p["model"] = OLLAMA_MODEL
        block = SYSTEM_PROMPT + "\n\n" + md() if md() else SYSTEM_PROMPT
        p["messages"] = inject(p.get("messages", []), block)
        if t := tools():
            p["tools"] = p.get("tools", []) + t
        url, h = f"{UP.rstrip('/')}/v1/chat/completions", hdrs(req)
        if p.get("stream"):
            c = httpx.AsyncClient(timeout=300)

            async def gen():
                try:
                    async with c.stream("POST", url, json=p, headers=h) as r:
                        async for line in r.aiter_lines():
                            if line:
                                yield f"{line}\n"
                        yield "data: [DONE]\n\n"
                finally:
                    await c.aclose()

            return StreamingResponse(gen(), media_type="text/event-stream")
        else:
            async with httpx.AsyncClient(timeout=300) as c:
                response = await c.post(url, json=p, headers=h)
                result = response.json()

                # Handle tool calls
                if "choices" in result:
                    choice = result["choices"][0]
                    msg = choice.get("message", {})
                    tool_calls = msg.get("tool_calls", [])

                    while tool_calls:
                        # Add assistant message with tool calls
                        p["messages"].append(msg)

                        # Execute each tool call
                        for tc in tool_calls:
                            func_name = tc.get("function", {}).get("name")
                            args = tc.get("function", {}).get("arguments", {})
                            if isinstance(args, str):
                                import json

                                args = json.loads(args)

                            tool_result = call_tool(func_name, args)

                            # Add tool result message
                            p["messages"].append(
                                {
                                    "role": "tool",
                                    "name": func_name,
                                    "content": str(tool_result),
                                }
                            )

                        # Get next response
                        response = await c.post(url, json=p, headers=h)
                        result = response.json()

                        if "choices" in result:
                            choice = result["choices"][0]
                            msg = choice.get("message", {})
                            tool_calls = msg.get("tool_calls", [])
                        else:
                            break

                return result
    except Exception as e:
        import traceback

        return {"error": str(e), "traceback": traceback.format_exc()}, 500


if __name__ == "__main__":
    WS.mkdir(parents=True, exist_ok=True)
    [
        ((WS / f).write_text(f"# {f.removesuffix('.md')}\n"))
        for f in MDS
        if not (WS / f).exists()
    ]
    print(
        f"workspace:{WS}  upstream:{UP}  listen:{UP}:{os.getenv('MYCLAW_PORT', '8080')}"
    )
    uvicorn.run(
        app,
        host=os.getenv("MYCLAW_HOST", "0.0.0.0"),
        port=int(os.getenv("MYCLAW_PORT", "8080")),
    )
