"""Event manager for Server-Sent Events (SSE) updates."""

import asyncio
import json
import logging
import threading
from collections import defaultdict
from typing import Any, AsyncIterator, Dict, List, Optional

from agents.models import AgentEvent

logger = logging.getLogger("myclaw.agents.events")


class EventManager:
    """Manages Server-Sent Events (SSE) for real-time agent updates.

    Allows clients to subscribe to events from specific agents.
    """

    def __init__(self):
        self._subscribers: Dict[str, List[asyncio.Queue]] = defaultdict(list)
        self._global_subscribers: List[asyncio.Queue] = []
        self._lock = threading.RLock()
        self._event_history: Dict[str, List[AgentEvent]] = defaultdict(list)
        self._max_history = 100

    def subscribe(self, agent_id: str) -> asyncio.Queue:
        """Subscribe to events for a specific agent.

        Args:
            agent_id: Agent ID to subscribe to

        Returns:
            Queue that will receive events
        """
        with self._lock:
            queue = asyncio.Queue(maxsize=100)
            self._subscribers[agent_id].append(queue)

            for event in self._event_history.get(agent_id, [])[-10:]:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

            return queue

    def subscribe_all(self) -> asyncio.Queue:
        """Subscribe to all events.

        Returns:
            Queue that will receive all events
        """
        with self._lock:
            queue = asyncio.Queue(maxsize=100)
            self._global_subscribers.append(queue)
            return queue

    def unsubscribe(self, agent_id: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from agent events.

        Args:
            agent_id: Agent ID
            queue: Queue to remove
        """
        with self._lock:
            if agent_id in self._subscribers:
                try:
                    self._subscribers[agent_id].remove(queue)
                    if not self._subscribers[agent_id]:
                        del self._subscribers[agent_id]
                except ValueError:
                    pass

    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from all events.

        Args:
            queue: Queue to remove
        """
        with self._lock:
            try:
                self._global_subscribers.remove(queue)
            except ValueError:
                pass

    def emit(self, event: AgentEvent) -> None:
        """Emit an event to all subscribers.

        Args:
            event: Event to emit
        """
        with self._lock:
            self._event_history[event.agent_id].append(event)
            if len(self._event_history[event.agent_id]) > self._max_history:
                self._event_history[event.agent_id] = self._event_history[event.agent_id][
                    -self._max_history :
                ]

            queues = list(self._subscribers.get(event.agent_id, []))
            queues.extend(self._global_subscribers)

            for queue in queues:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    logger.warning("event_queue_full", agent_id=event.agent_id)

    def emit_spawn(self, agent_id: str, parent_id: str, name: str) -> None:
        """Emit a spawn event."""
        self.emit(
            AgentEvent(
                type=AgentEvent.SPAWN,
                agent_id=parent_id,
                data={
                    "child_id": agent_id,
                    "child_name": name,
                },
            )
        )

    def emit_message(
        self,
        agent_id: str,
        from_agent: str,
        to_agent: str,
        content: str,
    ) -> None:
        """Emit a message event."""
        self.emit(
            AgentEvent(
                type=AgentEvent.MESSAGE,
                agent_id=to_agent,
                data={
                    "from": from_agent,
                    "content": content[:200],
                },
            )
        )

    def emit_status(self, agent_id: str, status: str, message: str = "") -> None:
        """Emit a status change event."""
        self.emit(
            AgentEvent(
                type=AgentEvent.STATUS,
                agent_id=agent_id,
                data={
                    "status": status,
                    "message": message,
                },
            )
        )

    def emit_complete(self, agent_id: str, result: Any = None) -> None:
        """Emit a completion event."""
        self.emit(
            AgentEvent(
                type=AgentEvent.COMPLETE,
                agent_id=agent_id,
                data={"result": str(result) if result else None},
            )
        )

    def emit_error(self, agent_id: str, error: str) -> None:
        """Emit an error event."""
        self.emit(
            AgentEvent(
                type=AgentEvent.ERROR,
                agent_id=agent_id,
                data={"error": error},
            )
        )

    def get_history(self, agent_id: str, limit: int = 10) -> List[AgentEvent]:
        """Get event history for an agent.

        Args:
            agent_id: Agent ID
            limit: Maximum number of events to return

        Returns:
            List of recent events
        """
        with self._lock:
            events = self._event_history.get(agent_id, [])
            return events[-limit:]

    async def event_stream(
        self,
        agent_id: Optional[str] = None,
        timeout: float = 30.0,
    ) -> AsyncIterator[str]:
        """Create an SSE event stream.

        Args:
            agent_id: Specific agent ID (None for all events)
            timeout: Timeout for waiting on queue

        Yields:
            SSE-formatted event strings
        """
        if agent_id:
            queue = self.subscribe(agent_id)
        else:
            queue = self.subscribe_all()

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=timeout)
                    yield f"data: {json.dumps(event.model_dump(mode='json'), default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield f": heartbeat\n\n"
        finally:
            if agent_id:
                self.unsubscribe(agent_id, queue)
            else:
                self.unsubscribe_all(queue)


_event_manager: Optional[EventManager] = None
_event_manager_lock = threading.Lock()


def get_event_manager() -> EventManager:
    """Get or create the global event manager."""
    global _event_manager

    if _event_manager is None:
        with _event_manager_lock:
            if _event_manager is None:
                _event_manager = EventManager()

    return _event_manager


def reset_event_manager() -> None:
    """Reset the event manager (useful for testing)."""
    global _event_manager
    with _event_manager_lock:
        _event_manager = None
