"""Agents router for MyClaw."""

from typing import Optional

import structlog
from fastapi import APIRouter, Request, Header, HTTPException

from config import settings
from agents.registry import AgentRegistry
from agents.models import Agent, AgentStatus, generate_agent_id

log = structlog.get_logger()

router = APIRouter(prefix="/agents", tags=["agents"])


def get_agent_registry(request: Request) -> AgentRegistry:
    """Get agent registry from app state."""
    return request.app.state.agent_registry


@router.get("/")
async def list_agents(a=Header(None)):
    """List all agents."""
    registry = get_agent_registry()
    agents = registry.list_agents()
    return {"agents": [agent.model_dump() for agent in agents]}


@router.get("/{agent_id}")
async def get_agent(agent_id: str, a=Header(None)):
    """Get agent details."""
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent.model_dump()


@router.delete("/{agent_id}")
async def terminate_agent(agent_id: str, a=Header(None)):
    """Terminate an agent."""
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    registry.terminate_agent(agent_id)
    return {"status": "terminated", "agent_id": agent_id}


@router.post("/{parent_id}/spawn")
async def spawn_agent(parent_id: str, request: Request, a=Header(None)):
    """Spawn a new agent."""
    registry = get_agent_registry()
    parent = registry.get_agent(parent_id)
    if not parent:
        raise HTTPException(404, "Parent agent not found")

    data = await request.json()
    name = data.get("name", f"agent-{generate_agent_id()[:8]}")

    agent = registry.create_agent(
        name=name,
        parent_id=parent_id,
        model=settings.model,
        status=AgentStatus.ACTIVE,
    )

    return agent.model_dump()


@router.get("/{agent_id}/messages")
async def get_agent_messages(agent_id: str, a=Header(None)):
    """Get agent messages."""
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return {"messages": agent.messages}


@router.get("/{agent_id}/events")
async def get_agent_events(agent_id: str):
    """Get agent events."""
    registry = get_agent_registry()
    agent = registry.get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return {"events": agent.events}
