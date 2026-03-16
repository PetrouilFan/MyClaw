"""Agents router for MyClaw."""

import structlog
from fastapi import APIRouter, Request, Header, HTTPException
from fastapi.responses import StreamingResponse
import asyncio

from config import settings

log = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("/")
async def list_agents(request: Request, a=Header(None)):
    """List all agents."""
    if not settings.enable_agent_tools:
        raise HTTPException(404, "Agent system not available")

    from agents.registry import AgentRegistry

    registry: AgentRegistry = request.app.state.agent_registry
    agents = registry.list_agents()
    return {"agents": [agent.model_dump() for agent in agents]}


@router.get("/{agent_id}")
async def get_agent(request: Request, agent_id: str, a=Header(None)):
    """Get agent status."""
    if not settings.enable_agent_tools:
        raise HTTPException(404, "Agent system not available")

    from agents.manager import get_agent_manager

    manager = await get_agent_manager()
    status = manager.get_agent_status(agent_id)

    if status is None:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    return status


@router.delete("/{agent_id}")
async def terminate_agent(request: Request, agent_id: str, a=Header(None)):
    """Terminate an agent."""
    if not settings.enable_agent_tools:
        raise HTTPException(404, "Agent system not available")

    from agents.manager import get_agent_manager

    manager = await get_agent_manager()
    result = await manager.terminate_agent(agent_id)

    if not result:
        raise HTTPException(404, f"Agent '{agent_id}' not found")

    return {"status": "terminated", "agent_id": agent_id}


@router.post("/{parent_id}/spawn")
async def spawn_agent(request: Request, parent_id: str, a=Header(None)):
    """Spawn a subagent."""
    if not settings.enable_agent_tools:
        raise HTTPException(404, "Agent system not available")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    name = body.get("name", f"agent-{body.get('task', '')[:20]}")
    task = body.get("task", "")

    if not task:
        raise HTTPException(400, "task is required")

    from agents.manager import get_agent_manager

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


@router.get("/{agent_id}/messages")
async def get_agent_messages(request: Request, agent_id: str, a=Header(None)):
    """Get messages for an agent."""
    if not settings.enable_agent_tools:
        raise HTTPException(404, "Agent system not available")

    from agents.manager import get_agent_manager

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


@router.get("/{agent_id}/events")
async def get_agent_events(request: Request, agent_id: str):
    """Server-Sent Events for agent updates."""
    if not settings.enable_agent_tools:
        raise HTTPException(404, "Agent system not available")

    from agents.events import get_event_manager

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
