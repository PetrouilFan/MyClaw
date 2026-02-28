"""Agent timeout handling for MyClaw.

Provides configurable timeouts, graceful shutdown, and auto-termination of stuck agents.
"""

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional

from agents.models import AgentStatus

logger = logging.getLogger("myclaw.agent_timeout")


@dataclass
class TimeoutConfig:
    """Configuration for agent timeouts."""

    default_timeout: int = 300
    warning_threshold: float = 0.8
    max_tool_call_duration: int = 60
    graceful_shutdown_timeout: int = 30


@dataclass
class AgentTimeoutInfo:
    """Information about an agent's timeout state."""

    agent_id: str
    started_at: float
    timeout: int
    last_activity: float = field(default_factory=time.time)
    is_stuck: bool = False
    warning_sent: bool = False


class AgentTimeoutManager:
    """Manages timeouts for agents."""

    def __init__(self, config: TimeoutConfig = None):
        self.config = config or TimeoutConfig()
        self._timeouts: dict[str, AgentTimeoutInfo] = {}
        self._lock = threading.RLock()
        self._callbacks: dict[str, list[Callable]] = {
            "timeout": [],
            "warning": [],
            "stuck": [],
        }
        self._monitor_task: Optional[threading.Thread] = None
        self._running = False

    def start_agent(self, agent_id: str, timeout: int = None) -> None:
        """Start tracking timeout for an agent."""
        with self._lock:
            self._timeouts[agent_id] = AgentTimeoutInfo(
                agent_id=agent_id,
                started_at=time.time(),
                timeout=timeout or self.config.default_timeout,
            )
            logger.debug("timeout_started", agent_id=agent_id, timeout=timeout)

    def update_activity(self, agent_id: str) -> None:
        """Update last activity time for an agent."""
        with self._lock:
            if agent_id in self._timeouts:
                self._timeouts[agent_id].last_activity = time.time()
                self._timeouts[agent_id].is_stuck = False

    def end_agent(self, agent_id: str) -> None:
        """Stop tracking timeout for an agent."""
        with self._lock:
            if agent_id in self._timeouts:
                del self._timeouts[agent_id]
                logger.debug("timeout_ended", agent_id=agent_id)

    def register_callback(
        self,
        event: str,
        callback: Callable[[str, dict], Any],
    ) -> None:
        """Register a callback for timeout events.

        Args:
            event: Event type ('timeout', 'warning', 'stuck')
            callback: Callback function(agent_id, details)
        """
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def get_time_remaining(self, agent_id: str) -> Optional[int]:
        """Get remaining time in seconds for an agent."""
        with self._lock:
            if agent_id not in self._timeouts:
                return None

            info = self._timeouts[agent_id]
            elapsed = time.time() - info.started_at
            remaining = info.timeout - elapsed
            return max(0, int(remaining))

    def is_timed_out(self, agent_id: str) -> bool:
        """Check if an agent has timed out."""
        return self.get_time_remaining(agent_id) == 0

    def _check_timeouts(self) -> None:
        """Check for timed out agents and trigger callbacks."""
        with self._lock:
            timed_out = []
            stuck = []
            warnings = []

            for agent_id, info in self._timeouts.items():
                elapsed = time.time() - info.started_at
                remaining = info.timeout - elapsed
                activity_gap = time.time() - info.last_activity

                if remaining <= 0:
                    timed_out.append(agent_id)
                elif (
                    not info.warning_sent
                    and elapsed >= info.timeout * self.config.warning_threshold
                ):
                    warnings.append(agent_id)
                    info.warning_sent = True
                elif activity_gap > self.config.max_tool_call_duration and not info.is_stuck:
                    stuck.append(agent_id)
                    info.is_stuck = True

            for agent_id in timed_out:
                for cb in self._callbacks["timeout"]:
                    try:
                        cb(
                            agent_id,
                            {"reason": "timeout", "timeout": self._timeouts[agent_id].timeout},
                        )
                    except Exception as e:
                        logger.error("timeout_callback_error", agent_id=agent_id, error=str(e))
                if agent_id in self._timeouts:
                    del self._timeouts[agent_id]

            for agent_id in warnings:
                for cb in self._callbacks["warning"]:
                    try:
                        cb(
                            agent_id,
                            {
                                "time_remaining": self.get_time_remaining(agent_id),
                                "timeout": self._timeouts.get(agent_id, {}).timeout
                                if agent_id in self._timeouts
                                else 0,
                            },
                        )
                    except Exception as e:
                        logger.error("warning_callback_error", agent_id=agent_id, error=str(e))

            for agent_id in stuck:
                for cb in self._callbacks["stuck"]:
                    try:
                        cb(agent_id, {"last_activity": self._timeouts[agent_id].last_activity})
                    except Exception as e:
                        logger.error("stuck_callback_error", agent_id=agent_id, error=str(e))

    def start_monitoring(self, interval: int = 5) -> None:
        """Start the timeout monitoring thread."""
        if self._running:
            return

        self._running = True
        self._monitor_task = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True
        )
        self._monitor_task.start()
        logger.info("timeout_monitoring_started", interval=interval)

    def stop_monitoring(self) -> None:
        """Stop the timeout monitoring thread."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.join(timeout=5)
        logger.info("timeout_monitoring_stopped")

    def _monitor_loop(self, interval: int) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                self._check_timeouts()
            except Exception as e:
                logger.error("monitoring_error", error=str(e))
            time.sleep(interval)

    def get_stats(self) -> dict:
        """Get timeout manager statistics."""
        with self._lock:
            total = len(self._timeouts)
            stuck = sum(1 for info in self._timeouts.values() if info.is_stuck)
            return {
                "tracked_agents": total,
                "stuck_agents": stuck,
                "default_timeout": self.config.default_timeout,
                "running": self._running,
            }


_timeout_manager: Optional[AgentTimeoutManager] = None


def get_timeout_manager(config: TimeoutConfig = None) -> AgentTimeoutManager:
    """Get or create the timeout manager."""
    global _timeout_manager

    if _timeout_manager is None:
        _timeout_manager = AgentTimeoutManager(config)

    return _timeout_manager


async def with_timeout(
    coro,
    timeout: int,
    on_timeout: Callable = None,
    on_warning: Callable = None,
):
    """Run a coroutine with timeout.

    Args:
        coro: Coroutine to run
        timeout: Timeout in seconds
        on_timeout: Callback when timeout occurs
        on_warning: Callback when warning threshold is reached

    Returns:
        Result of coroutine

    Raises:
        asyncio.TimeoutError: If timeout occurs
    """
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except asyncio.TimeoutError:
        if on_timeout:
            on_timeout()
        raise
