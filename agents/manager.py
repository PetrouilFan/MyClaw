"""Agent manager - orchestrates agent lifecycle and execution."""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from agents.models import Agent, AgentMessage, AgentStatus, generate_agent_id
from agents.registry import get_agent_registry, AgentRegistry
from agents.queue import get_message_queue, MessageQueue
from agents.events import get_event_manager, EventManager
from agents.service import AgentService

logger = logging.getLogger("myclaw.agents.manager")


class AgentManager:
    """Manages agent lifecycle and coordinates between components.

    This is the main entry point for agent operations.
    """

    def __init__(
        self,
        registry: AgentRegistry,
        message_queue: MessageQueue,
        event_manager: EventManager,
        agent_service: AgentService,
    ):
        self.registry = registry
        self.message_queue = message_queue
        self.events = event_manager
        self.agent_service = agent_service
        self._running_tasks: Dict[str, asyncio.Task] = {}

    async def spawn_agent(
        self,
        name: str,
        parent_id: Optional[str],
        task: str,
        metadata: dict = None,
    ) -> Agent:
        """Spawn a new agent to handle a task.

        Args:
            name: Agent name
            parent_id: Parent agent ID (None for main)
            task: Initial task description
            metadata: Additional metadata

        Returns:
            Created agent

        Raises:
            ValueError: If cannot spawn
        """
        can_spawn, reason = self.registry.can_spawn(parent_id, (parent_id and 1) or 0)
        if not can_spawn:
            raise ValueError(reason)

        parent_depth = 0
        if parent_id:
            parent = self.registry.get_agent(parent_id)
            if parent:
                parent_depth = parent.depth

        agent = self.registry.create_agent(
            name=name,
            parent_id=parent_id,
            metadata=metadata,
        )

        agent.add_message("system", f"Task: {task}")
        self.registry.update_agent(agent)

        self.events.emit_spawn(agent.id, parent_id or "main", name)

        if parent_id:
            self.events.emit_status(
                parent_id,
                "child_spawned",
                f"Agent '{name}' spawned",
            )

        run_task = asyncio.create_task(
            self._run_agent(agent.id, task),
            name=f"agent-{agent.id}",
        )
        self._running_tasks[agent.id] = run_task

        logger.info(
            "agent_spawned",
            agent_id=agent.id,
            name=name,
            parent_id=parent_id,
        )

        return agent

    async def _run_agent(self, agent_id: str, initial_task: str) -> None:
        """Run an agent's task loop.

        Args:
            agent_id: Agent ID
            initial_task: Initial task description
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return

        try:
            agent.update_status(AgentStatus.RUNNING)
            self.registry.update_agent(agent)
            self.events.emit_status(agent_id, "running", "Agent started")

            result = await self.agent_service.run_task(
                agent_id=agent_id,
                initial_task=initial_task,
                parent_id=agent.parent_id,
            )

            agent.update_status(AgentStatus.COMPLETED)
            agent.metadata["result"] = str(result)
            self.registry.update_agent(agent)

            self.events.emit_complete(agent_id, result)

            if agent.parent_id:
                self.events.emit_status(
                    agent.parent_id,
                    "child_complete",
                    f"Agent '{agent.name}' completed",
                )

                self.send_message(
                    from_agent_id=agent_id,
                    to_agent_id=agent.parent_id,
                    content=f"Task completed: {str(result)[:200]}",
                )

            logger.info("agent_completed", agent_id=agent_id, result=str(result)[:100])

        except asyncio.CancelledError:
            agent.update_status(AgentStatus.TERMINATED)
            self.registry.update_agent(agent)
            self.events.emit_status(agent_id, "terminated", "Agent was terminated")
            raise

        except Exception as e:
            logger.exception("agent_error", agent_id=agent_id, error=str(e))
            agent.update_status(AgentStatus.ERROR)
            agent.metadata["error"] = str(e)
            self.registry.update_agent(agent)
            self.events.emit_error(agent_id, str(e))

        finally:
            if agent_id in self._running_tasks:
                del self._running_tasks[agent_id]

    def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        content: str,
    ) -> AgentMessage:
        """Send a message between agents.

        Args:
            from_agent_id: Sender agent ID
            to_agent_id: Recipient agent ID
            content: Message content

        Returns:
            Created message
        """
        message = AgentMessage(
            id=uuid.uuid4().hex[:12],
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            content=content,
        )

        self.message_queue.publish(message)

        self.events.emit_message(
            agent_id=to_agent_id,
            from_agent=from_agent_id,
            to_agent=to_agent_id,
            content=content,
        )

        logger.debug(
            "message_sent",
            from_=from_agent_id,
            to=to_agent_id,
            msg_id=message.id,
        )

        return message

    async def wait_for_message(
        self,
        agent_id: str,
        timeout: float = 60.0,
    ) -> Optional[AgentMessage]:
        """Wait for a message for an agent.

        Args:
            agent_id: Agent ID to wait for
            timeout: Timeout in seconds

        Returns:
            Message or None if timeout
        """
        return await self.message_queue.wait_for_message(agent_id, timeout)

    def get_messages(self, agent_id: str) -> list[AgentMessage]:
        """Get all messages for an agent.

        Args:
            agent_id: Agent ID

        Returns:
            List of messages
        """
        return self.message_queue.get_messages(agent_id)

    async def terminate_agent(self, agent_id: str) -> bool:
        """Terminate a running agent.

        Args:
            agent_id: Agent ID to terminate

        Returns:
            True if terminated
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return False

        if agent_id in self._running_tasks:
            task = self._running_tasks[agent_id]
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        for child_id in agent.children[:]:
            await self.terminate_agent(child_id)

        agent.update_status(AgentStatus.TERMINATED)
        self.registry.update_agent(agent)

        self.events.emit_status(agent_id, "terminated", "Agent terminated")

        logger.info("agent_terminated", agent_id=agent_id)

        return True

    def get_agent_status(self, agent_id: str) -> Optional[dict]:
        """Get agent status info.

        Args:
            agent_id: Agent ID

        Returns:
            Status dict or None
        """
        agent = self.registry.get_agent(agent_id)
        if not agent:
            return None

        unread = self.message_queue.get_unread_count(agent_id)

        return {
            "id": agent.id,
            "name": agent.name,
            "status": agent.status.value,
            "parent_id": agent.parent_id,
            "children": agent.children,
            "unread_messages": unread,
            "message_count": len(agent.messages),
            "created_at": agent.created_at.isoformat(),
            "updated_at": agent.updated_at.isoformat(),
        }


_manager: Optional[AgentManager] = None
_manager_lock = asyncio.Lock()


async def get_agent_manager() -> AgentManager:
    """Get or create the global agent manager."""
    global _manager

    if _manager is None:
        async with _manager_lock:
            if _manager is None:
                registry = get_agent_registry()
                message_queue = get_message_queue()
                event_manager = get_event_manager()
                agent_service = AgentService()

                _manager = AgentManager(
                    registry=registry,
                    message_queue=message_queue,
                    event_manager=event_manager,
                    agent_service=agent_service,
                )

    return _manager


async def reset_agent_manager() -> None:
    """Reset the agent manager (useful for testing)."""
    global _manager
    async with _manager_lock:
        _manager = None
