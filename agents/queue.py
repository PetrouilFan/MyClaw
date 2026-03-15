"""Message queue for inter-agent communication."""

import asyncio
import json
import logging
import threading
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from agents.models import AgentMessage

logger = logging.getLogger("myclaw.agents.queue")


class MessageQueue:
    """Async message queue for agent-to-agent communication.

    Supports both in-memory queuing and file-based persistence.
    """

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.storage_dir = self.workspace / "agents" / "messages"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._queues: Dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._lock = threading.RLock()
        self._all_messages: Dict[str, List[AgentMessage]] = defaultdict(list)

    def _get_agent_dir(self, agent_id: str) -> Path:
        """Get storage directory for an agent's messages."""
        agent_dir = self.storage_dir / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir

    def _load_messages(self, agent_id: str) -> List[AgentMessage]:
        """Load messages for an agent from disk."""
        messages_file = self._get_agent_dir(agent_id) / "inbox.json"
        if not messages_file.exists():
            return []

        try:
            with open(messages_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [AgentMessage(**msg) for msg in data]
        except Exception as e:
            logger.warning("failed_to_load_messages", agent_id=agent_id, error=str(e))
            return []

    def _save_messages(self, agent_id: str, messages: List[AgentMessage]) -> None:
        """Save messages for an agent to disk."""
        messages_file = self._get_agent_dir(agent_id) / "inbox.json"
        with open(messages_file, "w", encoding="utf-8") as f:
            json.dump([msg.model_dump(mode="json") for msg in messages], f, indent=2, default=str)

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        """Subscribe to messages for an agent."""
        with self._lock:
            if agent_id not in self._queues:
                self._queues[agent_id] = asyncio.Queue()
                self._all_messages[agent_id] = self._load_messages(agent_id)
            return self._queues[agent_id]

    def unsubscribe(self, agent_id: str) -> None:
        """Unsubscribe from messages."""
        with self._lock:
            if agent_id in self._queues:
                del self._queues[agent_id]

    def publish(self, message: AgentMessage) -> None:
        """Publish a message to the recipient's queue."""
        with self._lock:
            if message.to_agent_id in self._queues:
                try:
                    self._queues[message.to_agent_id].put_nowait(message)
                except asyncio.QueueFull:
                    logger.warning("queue_full", agent_id=message.to_agent_id)

            self._all_messages[message.to_agent_id].append(message)
            self._save_messages(message.to_agent_id, self._all_messages[message.to_agent_id])

            logger.debug(
                "message_published",
                msg_id=message.id,
                from_=message.from_agent_id,
                to=message.to_agent_id,
            )

    def get_messages(self, agent_id: str, since: Optional[datetime] = None) -> List[AgentMessage]:
        """Get all messages for an agent.

        Args:
            agent_id: Agent ID
            since: Optional datetime to get messages after

        Returns:
            List of messages
        """
        with self._lock:
            if agent_id not in self._all_messages:
                self._all_messages[agent_id] = self._load_messages(agent_id)

            messages = self._all_messages[agent_id]

            if since:
                messages = [m for m in messages if m.timestamp > since]

            return messages

    def get_unread_count(self, agent_id: str) -> int:
        """Get count of unread messages in queue."""
        with self._lock:
            queue = self._queues.get(agent_id)
            if queue:
                return queue.qsize()
            return 0

    async def wait_for_message(
        self,
        agent_id: str,
        timeout: Optional[float] = None,
    ) -> Optional[AgentMessage]:
        """Wait for a message for an agent.

        Args:
            agent_id: Agent ID
            timeout: Optional timeout in seconds

        Returns:
            Message or None if timeout
        """
        queue = self.subscribe(agent_id)

        try:
            if timeout:
                return await asyncio.wait_for(queue.get(), timeout=timeout)
            result = await queue.get()
            return result if isinstance(result, AgentMessage) else None
        except asyncio.TimeoutError:
            return None

    def clear_agent_messages(self, agent_id: str) -> None:
        """Clear messages for an agent."""
        with self._lock:
            if agent_id in self._all_messages:
                self._all_messages[agent_id] = []
                self._save_messages(agent_id, [])


_queue: Optional[MessageQueue] = None
_queue_lock = threading.Lock()


def get_message_queue(workspace: Optional[Path] = None) -> MessageQueue:
    """Get or create the global message queue."""
    global _queue

    if _queue is None:
        with _queue_lock:
            if _queue is None:
                if workspace is None:
                    from config import settings

                    workspace = settings.workspace

                _queue = MessageQueue(workspace=workspace)

    return _queue


def reset_message_queue() -> None:
    """Reset the message queue (useful for testing)."""
    global _queue
    with _queue_lock:
        _queue = None
