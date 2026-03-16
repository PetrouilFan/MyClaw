#!/usr/bin/env python3
"""myclaw — minimal OpenClaw-like LLM middleware."""

import asyncio
import os
from pathlib import Path
from typing import Optional

import httpx
import structlog
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from config import settings

# Import routers
from routers.chat import router as chat_router
from routers.agents import router as agents_router
from routers.admin import router as admin_router

from tools._loader import load_tools
from session_manager import SessionManager
from agents.registry import AgentRegistry

import metrics

RATE_LIMIT_PER_MINUTE = 60

try:
    from agents.tools import TOOLS as AGENT_TOOLS, TOOL_FUNCTIONS as AGENT_TOOL_FUNCTIONS

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


def tools(app_state=None):
    global _module_tools, _module_tool_funcs

    if app_state is None:
        # Use module-level cache for backward compatibility
        if _module_tools is None:
            _module_tools, _module_tool_funcs = load_tools(
                project_root=Path(__file__).parent, workspace=settings.workspace
            )
            if _module_tools:
                metrics.tools_loaded.set(len(_module_tools))
        return _module_tools

    if app_state.tools is None:
        app_state.tools, app_state.tool_funcs = load_tools(
            project_root=Path(__file__).parent, workspace=settings.workspace
        )

        if settings.enable_agent_tools and AGENT_TOOLS_AVAILABLE:
            existing_names = {
                t.get("function", {}).get("name", "") for t in (app_state.tools or [])
            }
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


def _metrics():
    from starlette.responses import Response
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Include routers
app.include_router(admin_router)
app.include_router(agents_router)
app.include_router(chat_router)
