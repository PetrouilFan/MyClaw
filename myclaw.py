#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

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
from config import settings
from api_models import ChatCompletionRequest, Message, ToolCall, FunctionCall
from dependencies import get_tools, get_session_manager, get_agent_registry, get_http_client
from services.tool_executor import ToolExecutor

from agent_loop import (
    add_planning_to_system_prompt,
    get_planning_agent,
    ErrorFormatter,
)
from tools._loader import invalidate_cache, load_tools
from tools.tool_parser import clean_content, extract_tool_calls

from session_manager import SessionManager, get_session_manager as get_global_session_manager
from context_builder import get_context_builder
from agents.registry import AgentRegistry

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

os.environ["MYCLAW_WORKSPACE"] = str(settings.workspace)

# Module-level cache for backward compatibility when app_state is not provided
_module_tools: Optional[list] = None
_module_tool_funcs: Optional[dict] = None


def _create_error_response(
    message: str, status_code: int, details: Optional[dict] = None
) -> JSONResponse:
    """Create a structured error response."""
    error_body = {"error": {"message": message, "code": status_code}}
    if details:
        error_body["error"]["details"] = details
    return JSONResponse(error_body, status_code=status_code)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI app."""
    # Initialize app state
    app.state.settings = settings
    app.state.http_client = httpx.AsyncClient(timeout=300)

    # Load tools
    project_root = Path(__file__).parent
    app.state.project_root = project_root
    app.state.tools, app.state.tool_funcs = load_tools(
        project_root=project_root, workspace=settings.workspace
    )

    # Initialize session manager
    app.state.session_mgr = SessionManager(
        storage_dir=settings.session_storage_path_resolved,
        token_budget=settings.session_token_budget,
        ttl_days=settings.session_ttl_days,
    )

    # Initialize agent registry
    app.state.agent_registry = AgentRegistry(
        workspace=settings.workspace,
        max_agents=settings.subagent_max_agents,
        max_depth=settings.subagent_max_depth,
    )

    # Startup security warnings
    if not settings.api_key and not settings.allowed_api_keys:
        log.warning("⚠️  NO API request.app.state.api_key CONFIGURED — all requests accepted")
    if "*" in settings.allowed_origins:
        log.warning("⚠️  CORS wildcard origin with credentials is insecure")

    yield

    # Cleanup
    await app.state.http_client.aclose()


def custom_openapi() -> dict:
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
            "description": "API key for authentication. Format: 'Bearer YOUR_API_request.app.state.api_key' or just 'YOUR_API_request.app.state.api_key'",
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
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

if "*" in settings.allowed_origins and len(settings.allowed_origins) == 1:
    structlog.get_logger().warning(
        "cors_credentials_with_wildcard",
        message="allow_credentials=True with allow_origins=['*'] is insecure",
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
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
    for n in settings.mds:
        try:
            fp = settings.workspace / n
            if fp.exists():
                parts.append(f"<!-- {n} -->\n{fp.read_text().strip()}")
        except Exception as e:
            log.warning("failed_to_read_md", filename=n, error=str(e))
    return "\n\n".join(parts)


def tools(app_state=None):
    global _module_tools, _module_tool_funcs
    
    if app_state is None:
        # Use module-level cache for backward compatibility
        if _module_tools is None:
            _module_tools, _module_tool_funcs = load_tools(
                project_root=Path(__file__).parent,
                workspace=settings.workspace
            )
            if _module_tools:
                metrics.tools_loaded.set(len(_module_tools))
        return _module_tools
    
    if app_state.tools is None:
        app_state.tools, app_state.tool_funcs = load_tools(
            project_root=Path(__file__).parent,
            workspace=settings.workspace
        )

        if settings.enable_agent_tools and AGENT_TOOLS_AVAILABLE:
            existing_names = {t.get("function", {}).get("name", "") for t in (app_state.tools or [])}
            for tool in AGENT_TOOLS:
                tool_name = tool.get("function", {}).get("name", "")
                if tool_name and tool_name not in existing_names:
                    app_state.tools = (app_state.tools or []) + [tool]

            for name, func in AGENT_TOOL_FUNCTIONS.items():
                if name not in (app_state.tool_funcs or {}):
                    app_state.tool_funcs = app_state.tool_funcs or {}
                    app_state.tool_funcs[name] = func

        if app_state.tools:
            metrics.tools_loaded.set(len(app_state.tools))
    return app_state.tools


def tool_functions(app_state=None):
    global _module_tool_funcs
    
    if app_state is None:
        # Use module-level cache for backward compatibility
        if _module_tool_funcs is None:
            tools()  # This will populate _module_tool_funcs
        return _module_tool_funcs or {}
    
    if app_state.tool_funcs is None:
        tools(app_state)
    return app_state.tool_funcs


async def call_tool(n, a, app_state=None):
    # For backward compatibility with tests that don't pass app_state
    if app_state is None:
        # Use module-level cache
        global _module_tool_funcs
        if _module_tool_funcs is None:
            tools()
        tool_funcs = _module_tool_funcs or {}
    else:
        if app_state.tool_funcs is None:
            tools(app_state)
        tool_funcs = app_state.tool_funcs
    
    if tool_funcs and n in tool_funcs:
        try:
            from tools.tool_validator import validate_tool_call

            validate_tool_call(n, a)
        except Exception as e:
            log.error("tool_validation_error", tool=n, error=str(e))
            return {"error": f"Validation failed: {str(e)}", "success": False, "tool": n}
        try:
            func = tool_funcs[n]
            import inspect
            if inspect.iscoroutinefunction(func):
                return await func(**a)
            return func(**a)
        except Exception as e:
            log.error("tool_execution_error", tool=n, error=str(e))
            return {"error": str(e), "success": False, "tool": n}
    return {"error": f"Tool {n} not found", "success": False}


def call_tool_sync(n, a):
    """Sync wrapper for call_tool (for use in tests)."""
    return asyncio.run(call_tool(n, a, None))


def _auth(a):
    api_key = settings.api_key
    if not api_key and not settings.allowed_api_keys:
        return False
    if settings.allowed_api_keys:
        key = a.replace("Bearer ", "") if a else ""
        return key not in settings.allowed_api_keys
    return a != f"Bearer {api_key}" and a != api_key


def _dedupe(client, server):
    seen = {(x.get("function") or {}).get("name") for x in client}
    return server + [t for t in client if (t.get("function") or {}).get("name") not in seen]


@app.get("/health")
def _h(request: Request):
    return {
        "status": "ok",
        "workspace": str(settings.workspace),
        "version": "0.1.0",
        "tools_loaded": len(tools(request.app.state)) if tools(request.app.state) else 0,
        "session_enabled": settings.session_enabled,
        "stateless_mode": settings.stateless_mode,
    }


@app.get("/sessions")
async def _list_sessions(a=Header(None)):
    if _auth(a):
        raise HTTPException(401, "Invalid API key")
    if not settings.session_enabled or settings.stateless_mode:
        raise HTTPException(404, "Session management not available")

    sm = get_global_session_manager(
        storage_dir=settings.session_storage_path_resolved,
        token_budget=settings.session_token_budget,
    )
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
    if not settings.session_enabled or settings.stateless_mode:
        raise HTTPException(404, "Session management not available")

    sm = get_global_session_manager(
        storage_dir=settings.session_storage_path_resolved,
        token_budget=settings.session_token_budget,
    )
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
        workspace=settings.workspace,
        max_agents=settings.subagent_max_agents,
        max_depth=settings.subagent_max_depth,
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

    manager = await get_agent_manager()  # type: ignore[possibly-undefined]  # type: ignore[possibly-undefined]
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

    manager = await get_agent_manager()  # type: ignore[possibly-undefined]
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
        manager = await get_agent_manager()  # type: ignore[possibly-undefined]
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

    manager = await get_agent_manager()  # type: ignore[possibly-undefined]
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

    event_manager = get_event_manager()  # type: ignore[possibly-undefined]

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
                {
                    "role": "system",
                    "content": settings.system_prompt + ("\n\n" + md() if md() else ""),
                }
            ] + messages

            request_data = ChatCompletionRequest(
                model=settings.model,
                messages=[Message(**m) for m in messages],
                stream=False,
            )

            if t := tools(request.app.state):
                request_data.tools = t

            u, h = (
                f"{request.app.state.upstream.rstrip('/')}/v1/chat/completions",
                {
                    "Authorization": f"Bearer {request.app.state.api_key}" if request.app.state.api_key else "",
                    "Content-Type": "application/json",
                },
            )

            try:
                x = await request.app.state.http_client.post(u, json=request_data.dict(), headers=h)
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
    if _auth(a) or f not in settings.mds:
        raise HTTPException(401 if _auth(a) else 404)
    return {
        "filename": f,
        "content": (settings.workspace / f).read_text()
        if (settings.workspace / f).exists()
        else "",
    }


@app.put("/md/{f}")
async def _pf(f, r: Request, a=Header(None)):
    if _auth(a) or f not in settings.mds:
        raise HTTPException(401 if _auth(a) else 404)
    b = await r.body()
    if len(b) > settings.max_payload_size:
        return _create_error_response(
            "File too large", 413, {"max_size": settings.max_payload_size}
        )
    settings.workspace.mkdir(parents=True, exist_ok=True)
    (settings.workspace / f).write_bytes(b)
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
        if request.app.state.check_upstream:
            try:
                health_resp = await request.app.state.http_client.get(f"{request.app.state.upstream.rstrip('/')}/api/tags", timeout=5)
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
            request_data_json = await request.json()
            request_data = ChatCompletionRequest(**request_data_json)
        except json.JSONDecodeError as e:
            return _create_error_response("Invalid JSON in request", 400, {"error": str(e)})
        except Exception as e:
            return _create_error_response(
                f"Invalid request format: {str(e)}", 400, {"error": str(e)}
            )

        session_history = []

        agent_mode = request.headers.get("X-Agent-Mode", "").lower()
        stateless_mode = agent_mode == "stateless" or settings.stateless_mode

        if settings.session_enabled and not stateless_mode:
            session_id = request.headers.get("X-Session-ID")
            if not session_id:
                client_ip = request.client.host if request.client else ""
                user_agent = request.headers.get("user-agent", "")
                sm = get_global_session_manager(
                    storage_dir=settings.session_storage_path_resolved,
                    token_budget=settings.session_token_budget,
                )
                session_id = sm.generate_session_id(ip=client_ip, user_agent=user_agent)

            sm = get_global_session_manager(
                storage_dir=settings.session_storage_path_resolved,
                token_budget=settings.session_token_budget,
            )
            session_history = sm.load_session(session_id)

        log.info("chat_request", model=settings.model, messages_count=len(request_data.messages))

        # Set the model from settings if not provided
        if not request_data.model:
            request_data.model = settings.model

        incoming_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in request_data.messages
            if msg.role != "system"
        ]

        user_message = ""
        if incoming_messages:
            last_msg = incoming_messages[-1]
            user_message = last_msg.get("content", "")

        cb = get_context_builder(workspace=settings.workspace)

        system_content = cb.build_system_prompt(
            base_prompt=settings.system_prompt,
            include_identity=True,
            include_personality=True,
            include_user=True,
            include_memories=settings.enable_selective_memory,
            query=user_message,
        )

        if session_history:
            available = settings.session_token_budget - 2000
            from token_budget import estimate_tokens, truncate_messages

            reserved = estimate_tokens(system_content)
            available_for_history = max(0, available - reserved)

            truncated_history = truncate_messages(session_history, available_for_history)

            request_data.messages = (
                [Message(role="system", content=system_content)]
                + [Message(**m) for m in truncated_history]
                + [Message(**m) for m in incoming_messages]
            )
        else:
            request_data.messages = [Message(role="system", content=system_content)] + [
                Message(**m) for m in incoming_messages
            ]

        all_tools = tools(request.app.state)
        if all_tools:
            if settings.enable_dynamic_tools:
                selected_tools = cb.select_tools(
                    all_tools=all_tools,
                    query=user_message,
                    conversation_history=session_history,
                    max_tools=settings.max_tools,
                )
                request_data.tools = _dedupe(request_data.tools or [], selected_tools)
            else:
                request_data.tools = _dedupe(request_data.tools or [], all_tools)

        u, h = (
            f"{request.app.state.upstream.rstrip('/')}/v1/chat/completions",
            {
                "Authorization": f"Bearer {request.app.state.api_key}" if request.app.state.api_key else "",
                "Content-Type": "application/json",
            },
        )

        if request_data.stream:

            async def g():
                try:
                    async with request.app.state.http_client.stream("POST", u, json=request_data.dict(), headers=h) as x:
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
            enable_planning=settings.enable_planning,
            enable_reflection=settings.enable_reflection,
        )
        error_formatter = ErrorFormatter()

        if settings.enable_planning:
            system_msg = request_data.messages[0]
            system_msg.content = add_planning_to_system_prompt(system_msg.content or "")

        tc = 0
        while tc < settings.max_tool_calls:
            x = await request.app.state.http_client.post(u, json=request_data.dict(), headers=h)
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

                if settings.session_enabled and not stateless_mode and session_id:
                    sm = get_global_session_manager(
                        storage_dir=settings.session_storage_path_resolved,
                        token_budget=settings.session_token_budget,
                    )
                    for msg in request_data.messages:
                        if msg.role not in ("system",):
                            session_history.append(msg.dict())
                    session_history.append({"role": "assistant", "content": content})
                    sm.save_session(session_id, session_history)

                return R
            request_data.messages.append(Message(**m))
            for t_ in ts:
                fn, ag = t_["function"]["name"], t_["function"]["arguments"]
                args = json.loads(ag) if isinstance(ag, str) else ag

                tool_result = None
                error_msg = None

                for attempt in range(settings.tool_max_retries + 1):
                    try:
                        tool_result = await call_tool(fn, args, request.app.state)

                        if isinstance(tool_result, dict) and tool_result.get("error"):
                            error_msg = tool_result.get("error", "Unknown error")
                            if attempt < settings.tool_max_retries:
                                log.warning("tool_retry", tool=fn, attempt=attempt, error=error_msg)
                                formatted_error = error_formatter.format_tool_error(
                                    fn, error_msg, args
                                )
                                request_data.messages.append(
                                    Message(role="tool", name=fn, content=formatted_error)
                                )
                                continue
                        else:
                            break
                    except Exception as e:
                        error_msg = str(e)
                        if attempt < settings.tool_max_retries:
                            log.warning(
                                "tool_error_retry", tool=fn, attempt=attempt, error=error_msg
                            )
                            formatted_error = error_formatter.format_tool_error(fn, error_msg, args)
                            request_data.messages.append(
                                {"role": "tool", "name": fn, "content": formatted_error}
                            )
                            continue
                        tool_result = {"error": error_msg, "success": False}
                        break

                result_str = str(tool_result) if tool_result else ""

                if settings.enable_reflection and planning_agent.should_reflect(result_str):
                    reflection = planning_agent.create_reflection(fn, args, result_str)
                    request_data.messages.append(Message(role="user", content=reflection))

                log.info("tool_call", tool=fn, arguments=ag)
                request_data.messages.append(Message(role="tool", name=fn, content=result_str))
                if settings.session_enabled and not settings.stateless_mode and session_id:
                    session_history.append(m)
                    session_history.append({"role": "tool", "name": fn, "content": result_str})
            tc += 1
        log.warning("max_tool_calls_reached", max_calls=settings.max_tool_calls)
        return _create_error_response(
            f"Max tool calls ({settings.max_tool_calls}) reached",
            400,
            {"max_calls": settings.max_tool_calls},
        )
    except json.JSONDecodeError as e:
        return _create_error_response("Invalid JSON in request", 400, {"error": str(e)})
    except Exception as e:
        log.error("chat_error", error=str(e), error_type=type(e).__name__)
        return _create_error_response(str(e), 500, {"error_type": type(e).__name__})


if __name__ == "__main__":
    settings.workspace.mkdir(parents=True, exist_ok=True)
    for f in settings.mds:
        if not (settings.workspace / f).exists():
            (settings.workspace / f).write_text(f"# {f[:-3]}\n")
    log.info(
        "myclaw_starting",
        workspace=str(settings.workspace),
        upstream=request.app.state.upstream,
        host=settings.host,
        port=settings.port,
    )
    uvicorn.run(app, host=settings.host, port=settings.port)
