"""Agent-related tools for LLM function calling."""

import asyncio
from typing import Optional


async def spawn_subagent(
    name: str,
    task: str,
    parent_agent_id: str = "main",
) -> dict:
    """Spawn a subagent to handle a task in parallel.

    The subagent will execute independently and can communicate back
    via messages. Use this for parallel task execution.

    Args:
        name: Name for the subagent (e.g., "researcher", "coder")
        task: Detailed task description for the subagent
        parent_agent_id: ID of the parent agent (default: "main")

    Returns:
        Dict with agent_id, status, and message
    """
    from agents.manager import get_agent_manager

    try:
        manager = await get_agent_manager()
        agent = await manager.spawn_agent(
            name=name,
            parent_id=parent_agent_id,
            task=task,
            metadata={"spawned_by": "tool"},
        )

        return {
            "success": True,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "status": agent.status.value,
            "message": f"Subagent '{name}' spawned with ID: {agent.id}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to spawn subagent: {str(e)}",
        }


async def send_message_to_agent(
    agent_id: str,
    message: str,
    from_agent_id: str = "main",
) -> dict:
    """Send a message to another agent.

    Use this to communicate with spawned subagents or other agents.

    Args:
        agent_id: ID of the agent to send message to
        message: Content of the message
        from_agent_id: ID of the sending agent (default: "main")

    Returns:
        Dict with success status and message
    """
    from agents.manager import get_agent_manager

    try:
        manager = await get_agent_manager()
        msg = manager.send_message(
            from_agent_id=from_agent_id,
            to_agent_id=agent_id,
            content=message,
        )

        return {
            "success": True,
            "message_id": msg.id,
            "message": f"Message sent to agent '{agent_id}'",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": f"Failed to send message: {str(e)}",
        }


async def get_agent_status(agent_id: str) -> dict:
    """Get the status of an agent.

    Args:
        agent_id: ID of the agent

    Returns:
        Dict with agent status information
    """
    from agents.manager import get_agent_manager

    try:
        manager = await get_agent_manager()
        status = manager.get_agent_status(agent_id)

        if status is None:
            return {
                "success": False,
                "error": f"Agent '{agent_id}' not found",
            }

        return {
            "success": True,
            "status": status,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def list_agents(
    parent_id: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """List all agents, optionally filtered by parent or status.

    Args:
        parent_id: Filter by parent agent ID
        status: Filter by status (idle, running, waiting, completed, error, terminated)

    Returns:
        Dict with list of agents
    """
    from agents.manager import get_agent_manager
    from agents.models import AgentStatus

    try:
        manager = await get_agent_manager()
        registry = manager.registry

        status_enum = AgentStatus(status) if status else None
        agents = registry.list_agents(parent_id=parent_id, status=status_enum)

        return {
            "success": True,
            "agents": [a.to_summary() for a in agents],
            "count": len(agents),
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def wait_for_agent_message(
    agent_id: str,
    timeout: float = 60.0,
) -> dict:
    """Wait for a message from another agent.

    Use this to receive messages from subagents or parent agents.

    Args:
        agent_id: ID of the agent waiting for messages
        timeout: Maximum time to wait in seconds (default: 60)

    Returns:
        Dict with message content or timeout info
    """
    from agents.manager import get_agent_manager

    try:
        manager = await get_agent_manager()

        message = await manager.wait_for_message(agent_id, timeout)

        if message:
            return {
                "success": True,
                "message": {
                    "id": message.id,
                    "from": message.from_agent_id,
                    "content": message.content,
                    "timestamp": message.timestamp.isoformat(),
                },
            }
        else:
            return {
                "success": True,
                "timeout": True,
                "message": "No message received within timeout",
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def get_agent_messages(agent_id: str) -> dict:
    """Get all messages for an agent.

    Args:
        agent_id: ID of the agent

    Returns:
        Dict with list of messages
    """
    from agents.manager import get_agent_manager

    try:
        manager = await get_agent_manager()
        messages = manager.get_messages(agent_id)

        return {
            "success": True,
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
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def terminate_agent(agent_id: str) -> dict:
    """Terminate a running agent.

    Args:
        agent_id: ID of the agent to terminate

    Returns:
        Dict with success status
    """
    from agents.manager import get_agent_manager

    try:
        manager = await get_agent_manager()
        result = await manager.terminate_agent(agent_id)

        return {
            "success": result,
            "message": f"Agent '{agent_id}' terminated"
            if result
            else f"Agent '{agent_id}' not found",
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def sync_spawn_subagent(name: str, task: str, parent_agent_id: str = "main") -> dict:
    """Synchronous wrapper for spawn_subagent."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(spawn_subagent(name, task, parent_agent_id))


def sync_send_message_to_agent(agent_id: str, message: str, from_agent_id: str = "main") -> dict:
    """Synchronous wrapper for send_message_to_agent."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(send_message_to_agent(agent_id, message, from_agent_id))


def sync_get_agent_status(agent_id: str) -> dict:
    """Synchronous wrapper for get_agent_status."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(get_agent_status(agent_id))


def sync_list_agents(parent_id: Optional[str] = None, status: Optional[str] = None) -> dict:
    """Synchronous wrapper for list_agents."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(list_agents(parent_id, status))


def sync_wait_for_agent_message(agent_id: str, timeout: float = 60.0) -> dict:
    """Synchronous wrapper for wait_for_agent_message."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(wait_for_agent_message(agent_id, timeout))


def sync_get_agent_messages(agent_id: str) -> dict:
    """Synchronous wrapper for get_agent_messages."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(get_agent_messages(agent_id))


def sync_terminate_agent(agent_id: str) -> dict:
    """Synchronous wrapper for terminate_agent."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(terminate_agent(agent_id))


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "spawn_subagent",
            "description": "Spawn a subagent to handle a task in parallel. The subagent will execute independently and can communicate results back. Use this for parallel task execution or delegating complex subtasks.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name for the subagent (e.g., 'researcher', 'coder', 'assistant')",
                    },
                    "task": {
                        "type": "string",
                        "description": "Detailed task description for the subagent to execute",
                    },
                    "parent_agent_id": {
                        "type": "string",
                        "description": "ID of the parent agent (default: 'main')",
                        "default": "main",
                    },
                },
                "required": ["name", "task"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message_to_agent",
            "description": "Send a message to another agent. Use this to communicate with spawned subagents or request information from other agents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent to send message to",
                    },
                    "message": {
                        "type": "string",
                        "description": "Content of the message",
                    },
                    "from_agent_id": {
                        "type": "string",
                        "description": "ID of the sending agent (default: 'main')",
                        "default": "main",
                    },
                },
                "required": ["agent_id", "message"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_status",
            "description": "Get the current status of an agent including whether it's running, waiting, or completed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent to check",
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_agents",
            "description": "List all agents, optionally filtered by parent agent or status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "parent_id": {
                        "type": "string",
                        "description": "Filter by parent agent ID",
                    },
                    "status": {
                        "type": "string",
                        "description": "Filter by status: idle, running, waiting, completed, error, terminated",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wait_for_agent_message",
            "description": "Wait for a message from another agent. Use this to receive results or updates from subagents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent waiting for messages",
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Maximum time to wait in seconds (default: 60)",
                        "default": 60,
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_agent_messages",
            "description": "Get all messages received by an agent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent",
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate_agent",
            "description": "Terminate a running agent. Use this to stop a misbehaving or unnecessary subagent.",
            "parameters": {
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": "ID of the agent to terminate",
                    },
                },
                "required": ["agent_id"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "spawn_subagent": sync_spawn_subagent,
    "send_message_to_agent": sync_send_message_to_agent,
    "get_agent_status": sync_get_agent_status,
    "list_agents": sync_list_agents,
    "wait_for_agent_message": sync_wait_for_agent_message,
    "get_agent_messages": sync_get_agent_messages,
    "terminate_agent": sync_terminate_agent,
}
