"""Chat router for MyClaw."""

from typing import Optional

import structlog
from fastapi import APIRouter, WebSocket, Request, Header, HTTPException
from fastapi.responses import StreamingResponse

from config import settings
from api_models import ChatCompletionRequest, Message, ToolCall, FunctionCall
from dependencies import get_tools, get_session_manager, get_http_client
from session_manager import SessionManager
from services.tool_executor import ToolExecutor
from tools._loader import load_tools
from tools.tool_parser import clean_content, extract_tool_calls

log = structlog.get_logger()

router = APIRouter(prefix="/v1", tags=["chat"])


def md() -> str:
    """Get markdown content for system prompt."""
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
    """Get loaded tools."""
    from myclaw import _module_tools, _module_tool_funcs
    
    if app_state is None:
        if _module_tools is None:
            _module_tools, _module_tool_funcs = load_tools(
                project_root=settings.workspace.parent,
                workspace=settings.workspace
            )
        return _module_tools
    
    if app_state.tools is None:
        app_state.tools, app_state.tool_funcs = load_tools(
            project_root=settings.workspace.parent,
            workspace=settings.workspace
        )
    return app_state.tools


def tool_functions(app_state=None):
    """Get tool functions."""
    from myclaw import _module_tool_funcs
    
    if app_state is None:
        if _module_tool_funcs is None:
            tools()
        return _module_tool_funcs or {}
    
    if app_state.tool_funcs is None:
        tools(app_state)
    return app_state.tool_funcs


@router.websocket("/chat")
async def websocket_chat(websocket: WebSocket):
    """WebSocket endpoint for chat."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            messages = data.get("messages", [])

            if not messages:
                await websocket.send_json({"error": "messages required"})
                continue

            messages = [
                {"role": "system", "content": settings.system_prompt + ("\n\n" + md() if md() else "")}
            ] + messages

            request_data = ChatCompletionRequest(
                model=settings.model,
                messages=[Message(**m) for m in messages],
                stream=False,
            )

            if t := tools(websocket.app.state):
                request_data.tools = t

            upstream = websocket.app.state.upstream
            api_key = websocket.app.state.api_key
            http_client = websocket.app.state.http_client

            u, h = (
                f"{upstream.rstrip('/')}/v1/chat/completions",
                {
                    "Authorization": f"Bearer {api_key}" if api_key else "",
                    "Content-Type": "application/json",
                },
            )

            try:
                x = await http_client.post(u, json=request_data.dict(), headers=h)
                if x.status_code >= 400:
                    await websocket.send_json({"error": f"Upstream error: {x.status_code}"})
                    continue
                response = x.json()
                await websocket.send_json(response)
            except Exception as e:
                log.error("websocket_error", error=str(e))
    except Exception:
        pass


@router.post("/chat/completions")
async def chat(request: Request, a=Header(None)):
    """Main chat completions endpoint."""
    # Authentication check
    if not settings.api_key and not settings.allowed_api_keys:
        # No auth configured
        pass
    elif settings.allowed_api_keys:
        key = a.replace("Bearer ", "") if a else ""
        if key not in settings.allowed_api_keys:
            raise HTTPException(401, "Invalid API key")
    elif settings.api_key:
        if a != f"Bearer {settings.api_key}" and a != settings.api_key:
            raise HTTPException(401, "Invalid API key")

    client_ip = request.client.host if request.client else "unknown"
    session_id = request.headers.get("X-Session-ID")

    # Parse request
    try:
        request_data_json = await request.json()
        request_data = ChatCompletionRequest(**request_data_json)
    except Exception as e:
        return {"error": {"message": f"Invalid request: {str(e)}", "code": 400}}

    session_history = []

    agent_mode = request.headers.get("X-Agent-Mode", "").lower()
    stateless_mode = agent_mode == "stateless" or settings.stateless_mode

    # Session management
    if settings.session_enabled and not stateless_mode:
        if not session_id:
            client_ip = request.client.host if request.client else ""
            user_agent = request.headers.get("user-agent", "")
            sm = get_session_manager(
                storage_dir=settings.session_storage_path_resolved,
                token_budget=settings.session_token_budget,
            )
            session_id = sm.generate_session_id(ip=client_ip, user_agent=user_agent)

        sm = get_session_manager(
            storage_dir=settings.session_storage_path_resolved,
            token_budget=settings.session_token_budget,
        )
        session_history = sm.load_session(session_id)

    log.info("chat_request", model=settings.model, messages_count=len(request_data.messages))

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
        request_data.messages = [
            Message(role="system", content=system_content)
        ] + [Message(**m) for m in incoming_messages]

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

    # Streaming response
    if request_data.stream:
        async def g():
            try:
                async with request.app.state.http_client.stream(
                    "POST",
                    f"{request.app.state.upstream.rstrip('/')}/v1/chat/completions",
                    json=request_data.dict(),
                    headers={
                        "Authorization": f"Bearer {request.app.state.api_key}" if request.app.state.api_key else "",
                        "Content-Type": "application/json",
                    }
                ) as x:
                    if x.status_code >= 400:
                        yield f'{{"error":"Upstream {x.status_code}"}}\\n'
                        return
                    async for line in x.aiter_lines():
                        if line:
                            yield f"{line}\\n"
            except Exception as e:
                log.error("stream_error", error=str(e))
                yield f'{{"error":"{e}"}}\\n'

        return StreamingResponse(g(), media_type="text/event-stream")

    # Non-streaming response with tool execution
    # Initialize session manager if needed
    sm = None
    if settings.session_enabled and not stateless_mode and session_id:
        sm = get_session_manager(
            storage_dir=settings.session_storage_path_resolved,
            token_budget=settings.session_token_budget,
        )

    # Create tool executor
    executor = ToolExecutor(
        http_client=request.app.state.http_client,
        upstream_url=request.app.state.upstream,
        api_key=request.app.state.api_key,
        session_manager=sm,
        session_id=session_id if settings.session_enabled and not stateless_mode else None,
        session_history=session_history,
    )

    # Get tool functions
    tool_funcs = tool_functions(request.app.state) or {}

    # Execute the tool execution loop
    return await executor.execute_loop(request_data, tool_funcs)


def _dedupe(client, server):
    """Deduplicate tools."""
    seen = {(x.get("function") or {}).get("name") for x in client}
    return server + [t for t in client if (t.get("function") or {}).get("name") not in seen]
