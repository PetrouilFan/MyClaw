"""Data models for the multi-agent system."""

import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field
from typing import ClassVar


class AgentStatus(str, Enum):
    """Agent lifecycle status."""

    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    ERROR = "error"
    TERMINATED = "terminated"


class AgentMessage(BaseModel):
    """Message between agents."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    from_agent_id: str
    to_agent_id: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)
    metadata: dict = Field(default_factory=dict)


class AgentEvent(BaseModel):
    """Event emitted by agents."""

    type: str
    agent_id: str
    data: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)

    SPAWN: ClassVar = "spawn"
    MESSAGE: ClassVar = "message"
    STATUS: ClassVar = "status"
    COMPLETE: ClassVar = "complete"
    ERROR: ClassVar = "error"
    TERMINATE: ClassVar = "terminate"
    CHILD_SPAWNED: ClassVar = "child_spawned"
    CHILD_COMPLETE: ClassVar = "child_complete"


class Agent(BaseModel):
    """Represents an agent in the system."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str
    parent_id: Optional[str] = None
    status: AgentStatus = AgentStatus.IDLE
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    messages: list[dict] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)
    depth: int = 0

    def add_message(self, role: str, content: str) -> None:
        """Add a message to the agent's history."""
        self.messages.append(
            {
                "role": role,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            }
        )
        self.updated_at = datetime.now()

    def add_child(self, child_id: str) -> None:
        """Add a child agent ID."""
        if child_id not in self.children:
            self.children.append(child_id)
            self.updated_at = datetime.now()

    def update_status(self, status: AgentStatus) -> None:
        """Update agent status."""
        self.status = status
        self.updated_at = datetime.now()

    def get_storage_path(self, workspace: Path) -> Path:
        """Get the file storage path for this agent."""
        return workspace / "agents" / self.id

    def to_summary(self) -> dict:
        """Return a summary dict for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "parent_id": self.parent_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "children": self.children,
            "message_count": len(self.messages),
            "depth": self.depth,
        }


def generate_agent_id(parent_id: Optional[str], existing_names: set) -> str:
    """Generate a unique agent ID based on parent.

    Args:
        parent_id: Parent agent ID (None for main agent)
        existing_names: Set of existing agent names to avoid collisions

    Returns:
        Generated agent ID (e.g., 'main', 'sub-1', 'sub-1-1')
    """
    if parent_id is None:
        base = "main"
    elif parent_id == "main":
        base = "sub"
    else:
        base = f"sub-{parent_id}"

    if base not in existing_names:
        return base

    counter = 1
    while f"{base}-{counter}" in existing_names:
        counter += 1

    return f"{base}-{counter}"
