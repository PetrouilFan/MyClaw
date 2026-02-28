"""Multi-agent system for MyClaw.

Provides hierarchical agent spawning and inter-agent communication.
"""

from agents.models import Agent, AgentMessage, AgentEvent, AgentStatus
from agents.registry import AgentRegistry
from agents.queue import MessageQueue
from agents.events import EventManager
from agents.manager import AgentManager
from agents.service import AgentService

__all__ = [
    "Agent",
    "AgentMessage",
    "AgentEvent",
    "AgentStatus",
    "AgentRegistry",
    "MessageQueue",
    "EventManager",
    "AgentManager",
    "AgentService",
]
