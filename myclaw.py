#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import json
import os
from pathlib import Path

import httpx
import uvicorn
import structlog
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi import WebSocket
from settings import (
    MAX_PAYLOAD_SIZE,
    MAX_TOOL_CALLS,
    MDS,
    MYCLAW_API_KEY,
    MYCLAW_HOST,
    MYCLAW_PORT,
    OLLAMA_MODEL,
    OLLAMA_URL,
    SYSTEM_PROMPT,
    WS,
    ALLOWED_API_KEYS,
)

limiter = Limiter(key_func=get_remote_address)

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ]
)
log = structlog.get_logger()

os.environ["MYCLAW_WORKSPACE"] = str(WS)
from tools._loader import invalidate_cache, load_tools
from tools.tool_parser import clean_content, extract_tool_calls

UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY)
CHECK_UPSTREAM = os.getenv("MYCLAW_CHECK_UPSTREAM", "").lower() in ("1", "true", "yes")

import metrics

http = httpx.AsyncClient(timeout=300)
_t, _tf = None, None


def _create_error_response(message: str, status_code: int, details: dict = None) -> JSONResponse:
    """Create a structured error response."""
    error_body = {"error": {"message": message, "code": status_code}}
    if details:
        error_body["error"]["details"] = details
    return JSONResponse(error_body, status_code=status_code)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await http.aclose()


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    from fastapi.openapi.utils import get_openapi

    openapi_schema = get_openapi(
        title="MyClaw API",
        description="OpenClaw-inspired LLM middleware with tool execution and terminal command support.",
        version="0.1.0",
        routes=app.routes,
    )
    openapi_schema["info"]["contact"] = {
        "name": "MyClaw",
        "description": "LLM Middleware with Tools",
    }
    openapi_schema["components"]["securitySchemes"] = {
        "ApiKeyAuth": {
            "type": "apiKey",
            "in": "header",
            "name": "Authorization",
            "description": "API key for authentication. Format: 'Bearer YOUR_API_KEY' or just 'YOUR_API_KEY'",
        }
    }
    for path in openapi_schema["paths"].values():
        for method in path.values():
            if method.get("tags") and "internal" not in method["tags"]:
                method["security"] = [{"ApiKeyAuth": []}]
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app = FastAPI(
    title="MyClaw API",
    description="OpenClaw-inspired LLM middleware with tool execution and terminal command support.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)
app.openapi = custom_openapi

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(httpx.TimeoutException)
async def timeout_exception_handler(request: Request, exc: httpx.TimeoutException):
    """Handle upstream timeout errors."""
    log.error("upstream_timeout", path=str(request.url))
    return _create_error_response("Upstream timeout", 504, {"retry_after": 30})


@app.exception_handler(httpx.ConnectError)
async def connection_exception_handler(request: Request, exc: httpx.ConnectError):
    """Handle upstream connection errors."""
    log.error("upstream_connection_error", path=str(request.url), error=str(exc))
    return _create_error_response("Upstream unreachable", 503, {"error": str(exc)})


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions."""
    return _create_error_response(exc.detail, exc.status_code)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle general exceptions."""
    log.error(
        "unhandled_error", path=str(request.url), error=str(exc), error_type=type(exc).__name__
    )
    return _create_error_response("Internal server error", 500, {"error_type": type(exc).__name__})


def md() -> str:
    parts = []
    for n in MDS:
        try:
            fp = WS / n
            if fp.exists():
                parts.append(f"<!-- {n} -->\n{fp.read_text().strip()}")
        except Exception as e:
            log.warning("failed_to_read_md", filename=n, error=str(e))
    return "\n\n".join(parts)


def tools():
    global _t, _tf
    if _t is None:
        _t, _tf = load_tools(project_root=Path(__file__).parent, workspace=WS)
        if _t:
            metrics.tools_loaded.set(len(_t))
    return _t


def call_tool(n, a):
    global _tf
    if _tf is None:
        tools()
    if _tf and n in _tf:
        try:
            return _tf[n](**a)
        except Exception as e:
            log.error("tool_execution_error", tool=n, error=str(e))
            return {"error": str(e), "success": False, "tool": n}
    return {"error": f"Tool {n} not found", "success": False}


def _auth(a):
    if not KEY and not ALLOWED_API_KEYS:
        return False
    if ALLOWED_API_KEYS:
        key = a.replace("Bearer ", "") if a else ""
        return key not in ALLOWED_API_KEYS
    return a != f"Bearer {KEY}" and a != KEY


def _dedupe(client, server):
    seen = {(x.get("function") or {}).get("name") for x in client}
    return server + [t for t in client if (t.get("function") or {}).get("name") not in seen]


@app.get("/health")
def _h():
    return {
        "status": "ok",
        "workspace": str(WS),
        "version": "0.1.0",
        "tools_loaded": len(tools()) if tools() else 0,
    }


@app.get("/metrics")
def _metrics():
    from starlette.responses import Response
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            messages = data.get("messages", [])

            if not messages:
                await websocket.send_json({"error": "messages required"})
                continue

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT + ("\n\n" + md() if md() else "")}
            ] + messages

            p = {
                "model": OLLAMA_MODEL,
                "messages": messages,
                "stream": False,
            }

            if t := tools():
                p["tools"] = t

            u, h = (
                f"{UP.rstrip('/')}/v1/chat/completions",
                {
                    "Authorization": f"Bearer {KEY}" if KEY else "",
                    "Content-Type": "application/json",
                },
            )

            try:
                x = await http.post(u, json=p, headers=h)
                if x.status_code >= 400:
                    await websocket.send_json({"error": f"Upstream error: {x.status_code}"})
                    continue
                response = x.json()
                await websocket.send_json(response)
            except Exception as e:
                log.error("websocket_error", error=str(e))
                await websocket.send_json({"error": str(e)})

    except Exception:
        pass
    finally:
        await websocket.close()


@app.post("/_invalidate_cache")
async def _ic(a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")
    invalidate_cache()
    global _t, _tf
    _t = _tf = None
    log.info("cache_invalidated")
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
        return _create_error_response("File too large", 413, {"max_size": MAX_PAYLOAD_SIZE})
    WS.mkdir(parents=True, exist_ok=True)
    (WS / f).write_bytes(b)
    return {"status": "saved"}


@app.post("/v1/chat/completions")
@limiter.limit("60/minute")
async def chat(r: Request, a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")
    try:
        if CHECK_UPSTREAM:
            try:
                health_resp = await http.get(f"{UP.rstrip('/')}/api/tags", timeout=5)
                if health_resp.status_code >= 400:
                    return _create_error_response(
                        "Upstream unhealthy", 503, {"upstream_status": health_resp.status_code}
                    )
            except httpx.TimeoutException:
                return _create_error_response("Upstream timeout", 504)
            except httpx.ConnectError as e:
                log.error("upstream_unreachable", error=str(e))
                return _create_error_response("Upstream unreachable", 503, {"error": str(e)})

        try:
            p = await r.json()
        except json.JSONDecodeError as e:
            return _create_error_response("Invalid JSON in request", 400, {"error": str(e)})

        if "messages" not in p:
            return _create_error_response("messages required", 400)

        log.info("chat_request", model=OLLAMA_MODEL, messages_count=len(p.get("messages", [])))

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
                    log.error("stream_error", error=str(e))
                    yield f'{{"error":"{e}"}}\n'

            return StreamingResponse(g(), media_type="text/event-stream")

        tc = 0
        while tc < MAX_TOOL_CALLS:
            x = await http.post(u, json=p, headers=h)
            if x.status_code >= 400:
                log.error("upstream_error", status_code=x.status_code)
                return _create_error_response(
                    f"Upstream error: {x.status_code}", 502, {"status_code": x.status_code}
                )
            try:
                R = x.json()
            except:
                return _create_error_response("Invalid JSON from upstream", 502)
            if "choices" not in R:
                return R
            m = R["choices"][0]["message"]
            ts = extract_tool_calls(m)
            log.debug("tool_calls_extracted", count=len(ts))
            if not ts:
                content = clean_content(m)
                R["choices"][0]["message"]["content"] = content
                log.info("chat_response", tool_calls=0)
                return R
            p["messages"].append(m)
            for t_ in ts:
                fn, ag = t_["function"]["name"], t_["function"]["arguments"]
                log.info("tool_call", tool=fn, arguments=ag)
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
        log.warning("max_tool_calls_reached", max_calls=MAX_TOOL_CALLS)
        return _create_error_response(
            f"Max tool calls ({MAX_TOOL_CALLS}) reached", 400, {"max_calls": MAX_TOOL_CALLS}
        )
    except json.JSONDecodeError as e:
        return _create_error_response("Invalid JSON in request", 400, {"error": str(e)})
    except Exception as e:
        log.error("chat_error", error=str(e), error_type=type(e).__name__)
        return _create_error_response(str(e), 500, {"error_type": type(e).__name__})


if __name__ == "__main__":
    WS.mkdir(parents=True, exist_ok=True)
    for f in MDS:
        if not (WS / f).exists():
            (WS / f).write_text(f"# {f[:-3]}\n")
    log.info("myclaw_starting", workspace=str(WS), upstream=UP, host=MYCLAW_HOST, port=MYCLAW_PORT)
    uvicorn.run(app, host=MYCLAW_HOST, port=MYCLAW_PORT)
