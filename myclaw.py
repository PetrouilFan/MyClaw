#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import asyncio
import json
import os
import time
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
    ALLOWED_ORIGINS,
    SESSION_ENABLED,
    SESSION_STORAGE_PATH,
    SESSION_TOKEN_BUDGET,
    STATELESS_MODE,
    ENABLE_SELECTIVE_MEMORY,
    ENABLE_DYNAMIC_TOOLS,
    MAX_TOOLS,
    ENABLE_PLANNING,
    ENABLE_REFLECTION,
    TOOL_MAX_RETRIES,
    ENABLE_AGENT_TOOLS,
    SUBAGENT_MAX_AGENTS,
    SUBAGENT_MAX_DEPTH,
)

from agent_loop import (
    add_planning_to_system_prompt,
    get_planning_agent,
    ErrorFormatter,
)
from tools._loader import invalidate_cache, load_tools
from tools.tool_parser import clean_content, extract_tool_calls

from session_manager import get_session_manager
from context_builder import get_context_builder

import metrics

RATE_LIMIT_PER_MINUTE = 60

try:
    from agents.tools import TOOLS as AGENT_TOOLS, TOOL_FUNCTIONS as AGENT_TOOL_FUNCTIONS
    from agents.manager import get_agent_manager
    from agents.events import get_event_manager

    AGENT_TOOLS_AVAILABLE = True
except ImportError:
    AGENT_TOOLS_AVAILABLE = False
    AGENT_TOOLS = []
    AGENT_TOOL_FUNCTIONS = {}

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

UP = os.getenv("MYCLAW_UPSTREAM", OLLAMA_URL)
KEY = os.getenv("MYCLAW_API_KEY", MYCLAW_API_KEY)
CHECK_UPSTREAM = os.getenv("MYCLAW_CHECK_UPSTREAM", "").lower() in ("1", "true", "yes")

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

if "*" in ALLOWED_ORIGINS and len(ALLOWED_ORIGINS) == 1:
    structlog.get_logger().warning(
        "cors_credentials_with_wildcard",
        message="allow_credentials=True with allow_origins=['*'] is insecure",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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

        if ENABLE_AGENT_TOOLS and AGENT_TOOLS_AVAILABLE:
            existing_names = {t.get("function", {}).get("name", "") for t in (_t or [])}
            for tool in AGENT_TOOLS:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name and tool_name not in existing_names:
                    _t = (_t or []) + [tool]

            for name, func in AGENT_TOOL_FUNCTIONS.items():
                if name not in (_tf or {}):
                    _tf = _tf or {}
                    _tf[name] = func

        if _t:
            metrics.tools_loaded.set(len(_t))
    return _t


def tool_functions():
    global _tf
    if _tf is None:
        tools()
    return _tf


def call_tool(n, a):
    global _tf
    if _tf is None:
        tools()
    if _tf and n in _tf:
        try:
            from tools.tool_validator import validate_tool_call

            validate_tool_call(n, a)
        except Exception as e:
            log.error("tool_validation_error", tool=n, error=str(e))
            return {"error": f"Validation failed: {str(e)}", "success": False, "tool": n}
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
        "session_enabled": SESSION_ENABLED,
        "stateless_mode": STATELESS_MODE,
    }


@app.get("/sessions")
async def _list_sessions(a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")
    if not SESSION_ENABLED or STATELESS_MODE:
        raise HTTPException(404, "Session management not available")

    sm = get_session_manager(storage_dir=SESSION_STORAGE_PATH, token_budget=SESSION_TOKEN_BUDGET)
    sessions = []
    for path in sm.storage_dir.glob("*.json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            sessions.append(
                {
                    "session_id": data.get("session_id"),
                    "updated_at": data.get("updated_at"),
                    "message_count": len(data.get("messages", [])),
                }
            )
        except (json.JSONDecodeError, IOError):
            pass
    return {"sessions": sessions, "total": len(sessions)}


@app.delete("/sessions/{session_id}")
async def _delete_session(session_id, a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")
    if not SESSION_ENABLED or STATELESS_MODE:
        raise HTTPException(404, "Session management not available")

    sm = get_session_manager(storage_dir=SESSION_STORAGE_PATH, token_budget=SESSION_TOKEN_BUDGET)
    path = sm._get_session_path(session_id)
    if path.exists():
        path.unlink()
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(404, "Session not found")


@app.get("/agents")
async def _list_agents(a=Header(None)):
    """List all agents."""
    if _auth(a):
        raise HTTPException(401, "Invalid API key")

    if not AGENT_TOOLS_AVAILABLE:
        raise HTTPException(404, "Agent system not available")

    from agents.registry import get_agent_registry

    registry = get_agent_registry(
        workspace=WS,
        max_agents=SUBAGENT_MAX_AGENTS,
        max_depth=SUBAGENT_MAX_DEPTH,
    )

    parent_id = None

    agents = registry.list_agents(parent_id=parent_id)
    return {
        "agents": [a.to_summary() for a in agents],
        "total": len(agents),
    }


@app.get("/agents/{agent_id}")
async def _get_agent(agent_id: str, a=Header(None)):
    """Get agent status."""
    if _auth(a):
        raise HTTPException(401, "Invalid API key")

    if not AGENT_TOOLS_AVAILABLE:
        raise HTTPException(404, "Agent system not available")

    manager = await get_agent_manager()
    status = manager.get_agent_status(agent_id)

    if status is None:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    return status


@app.delete("/agents/{agent_id}")
async def _terminate_agent(agent_id: str, a=Header(None)):
    """Terminate an agent."""
    if _auth(a):
        raise HTTPException(401, "Invalid API key")

    if not AGENT_TOOLS_AVAILABLE:
        raise HTTPException(404, "Agent system not available")

    manager = await get_agent_manager()
    result = await manager.terminate_agent(agent_id)

    if not result:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    return {"status": "terminated", "agent_id": agent_id}


@app.post("/agents/{parent_id}/spawn")
async def _spawn_agent(parent_id: str, request: Request, a=Header(None)):
    """Spawn a subagent."""
    if _auth(a):
        raise HTTPException(401, "Invalid API key")

    if not AGENT_TOOLS_AVAILABLE:
        raise HTTPException(404, "Agent system not available")

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _create_error_response("Invalid JSON", 400)

    name = body.get("name", f"agent-{body.get('task', '')[:20]}")
    task = body.get("task", "")

    if not task:
        return _create_error_response("task is required", 400)

    try:
        manager = await get_agent_manager()
        agent = await manager.spawn_agent(
            name=name,
            parent_id=parent_id,
            task=task,
            metadata=body.get("metadata", {}),
        )
        return {
            "agent_id": agent.id,
            "name": agent.name,
            "status": agent.status.value,
            "message": f"Agent '{name}' spawned successfully",
        }
    except ValueError as e:
        return _create_error_response(str(e), 400)
    except Exception as e:
        log.error("spawn_agent_error", error=str(e))
        return _create_error_response(str(e), 500)


@app.get("/agents/{agent_id}/messages")
async def _get_agent_messages(agent_id: str, a=Header(None)):
    """Get messages for an agent."""
    if _auth(a):
        raise HTTPException(401, "Invalid API key")

    if not AGENT_TOOLS_AVAILABLE:
        raise HTTPException(404, "Agent system not available")

    manager = await get_agent_manager()
    messages = manager.get_messages(agent_id)

    return {
        "messages": [
            {
                "id": m.id,
                "from": m.from_agent_id,
                "to": m.to_agent_id,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in messages
        ],
        "count": len(messages),
    }


@app.get("/agents/{agent_id}/events")
async def _agent_events(agent_id: str):
    """Server-Sent Events for agent updates."""
    if not AGENT_TOOLS_AVAILABLE:
        raise HTTPException(404, "Agent system not available")

    event_manager = get_event_manager()

    async def event_generator():
        try:
            async for event in event_manager.event_stream(agent_id):
                yield event
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


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
async def chat(request: Request, a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")

    client_ip = request.client.host if request.client else "unknown"
    session_id = request.headers.get("X-Session-ID")

    from rate_limiter import get_rate_limiter

    rl = get_rate_limiter(requests_per_minute=RATE_LIMIT_PER_MINUTE)

    ip_allowed, ip_info = rl.check_ip(client_ip)
    if not ip_allowed:
        raise HTTPException(
            429,
            "Rate limit exceeded",
            headers={
                "X-RateLimit-Limit": str(ip_info.limit),
                "X-RateLimit-Remaining": str(ip_info.remaining),
                "X-RateLimit-Reset": str(ip_info.reset),
                "Retry-After": str(ip_info.reset - int(time.time())),
            },
        )

    if session_id:
        session_allowed, session_info = rl.check_session(session_id)
        if not session_allowed:
            raise HTTPException(
                429,
                "Session rate limit exceeded",
                headers={
                    "X-RateLimit-Session-Limit": str(session_info.limit),
                    "X-RateLimit-Session-Remaining": str(session_info.remaining),
                    "X-RateLimit-Session-Reset": str(session_info.reset),
                    "Retry-After": str(session_info.reset - int(time.time())),
                },
            )

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
            p = await request.json()
        except json.JSONDecodeError as e:
            return _create_error_response("Invalid JSON in request", 400, {"error": str(e)})

        if "messages" not in p:
            return _create_error_response("messages required", 400)

        session_history = []

        agent_mode = request.headers.get("X-Agent-Mode", "").lower()
        stateless_mode = agent_mode == "stateless" or STATELESS_MODE

        if SESSION_ENABLED and not stateless_mode:
            session_id = request.headers.get("X-Session-ID")
            if not session_id:
                client_ip = request.client.host if request.client else ""
                user_agent = request.headers.get("user-agent", "")
                sm = get_session_manager(
                    storage_dir=SESSION_STORAGE_PATH,
                    token_budget=SESSION_TOKEN_BUDGET,
                )
                session_id = sm.generate_session_id(ip=client_ip, user_agent=user_agent)

            sm = get_session_manager(
                storage_dir=SESSION_STORAGE_PATH,
                token_budget=SESSION_TOKEN_BUDGET,
            )
            session_history = sm.load_session(session_id)

        log.info("chat_request", model=OLLAMA_MODEL, messages_count=len(p.get("messages", [])))

        p["model"] = OLLAMA_MODEL or None

        incoming_messages = [
            {"role": x["role"], "content": x["content"]}
            for x in p.get("messages", [])
            if x.get("role") != "system"
        ]

        user_message = ""
        if incoming_messages:
            last_msg = incoming_messages[-1]
            user_message = last_msg.get("content", "")

        cb = get_context_builder(workspace=WS)

        system_content = cb.build_system_prompt(
            base_prompt=SYSTEM_PROMPT,
            include_identity=True,
            include_personality=True,
            include_user=True,
            include_memories=ENABLE_SELECTIVE_MEMORY,
            query=user_message,
        )

        if session_history:
            available = SESSION_TOKEN_BUDGET - 2000
            from token_budget import estimate_tokens, truncate_messages

            reserved = estimate_tokens(system_content)
            available_for_history = max(0, available - reserved)

            truncated_history = truncate_messages(session_history, available_for_history)

            p["messages"] = (
                [{"role": "system", "content": system_content}]
                + truncated_history
                + incoming_messages
            )
        else:
            p["messages"] = [{"role": "system", "content": system_content}] + incoming_messages

        all_tools = tools()
        if all_tools:
            if ENABLE_DYNAMIC_TOOLS:
                selected_tools = cb.select_tools(
                    all_tools=all_tools,
                    query=user_message,
                    conversation_history=session_history,
                    max_tools=MAX_TOOLS,
                )
                p["tools"] = _dedupe(p.get("tools", []), selected_tools)
            else:
                p["tools"] = _dedupe(p.get("tools", []), all_tools)

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
                        async for line in x.aiter_lines():
                            if line:
                                yield f"{line}\n"
                except Exception as e:
                    log.error("stream_error", error=str(e))
                    yield f'{{"error":"{e}"}}\n'

            return StreamingResponse(g(), media_type="text/event-stream")

        planning_agent = get_planning_agent(
            enable_planning=ENABLE_PLANNING,
            enable_reflection=ENABLE_REFLECTION,
        )
        error_formatter = ErrorFormatter()

        if ENABLE_PLANNING:
            system_msg = p["messages"][0]
            system_msg["content"] = add_planning_to_system_prompt(system_msg.get("content", ""))

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
            except Exception:
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

                if SESSION_ENABLED and not stateless_mode and session_id:
                    sm = get_session_manager(
                        storage_dir=SESSION_STORAGE_PATH,
                        token_budget=SESSION_TOKEN_BUDGET,
                    )
                    for msg in p["messages"]:
                        if msg.get("role") not in ("system",):
                            session_history.append(msg)
                    session_history.append({"role": "assistant", "content": content})
                    sm.save_session(session_id, session_history)

                return R
            p["messages"].append(m)
            for t_ in ts:
                fn, ag = t_["function"]["name"], t_["function"]["arguments"]
                args = json.loads(ag) if isinstance(ag, str) else ag

                tool_result = None
                error_msg = None

                for attempt in range(TOOL_MAX_RETRIES + 1):
                    try:
                        tool_result = call_tool(fn, args)

                        if isinstance(tool_result, dict) and tool_result.get("error"):
                            error_msg = tool_result.get("error", "Unknown error")
                            if attempt < TOOL_MAX_RETRIES:
                                log.warning("tool_retry", tool=fn, attempt=attempt, error=error_msg)
                                formatted_error = error_formatter.format_tool_error(
                                    fn, error_msg, args
                                )
                                p["messages"].append(
                                    {"role": "tool", "name": fn, "content": formatted_error}
                                )
                                continue
                        else:
                            break
                    except Exception as e:
                        error_msg = str(e)
                        if attempt < TOOL_MAX_RETRIES:
                            log.warning(
                                "tool_error_retry", tool=fn, attempt=attempt, error=error_msg
                            )
                            formatted_error = error_formatter.format_tool_error(fn, error_msg, args)
                            p["messages"].append(
                                {"role": "tool", "name": fn, "content": formatted_error}
                            )
                            continue
                        tool_result = {"error": error_msg, "success": False}
                        break

                result_str = str(tool_result) if tool_result else ""

                if ENABLE_REFLECTION and planning_agent.should_reflect(result_str):
                    reflection = planning_agent.create_reflection(fn, args, result_str)
                    p["messages"].append({"role": "user", "content": reflection})

                log.info("tool_call", tool=fn, arguments=ag)
                p["messages"].append({"role": "tool", "name": fn, "content": result_str})
                if SESSION_ENABLED and not STATELESS_MODE and session_id:
                    session_history.append(m)
                    session_history.append({"role": "tool", "name": fn, "content": result_str})
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
