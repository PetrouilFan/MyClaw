"""Agent registry - manages all agents in the system."""

import json
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional

from agents.models import Agent, AgentStatus, generate_agent_id

logger = logging.getLogger("myclaw.agents.registry")


class AgentRegistry:
    """Thread-safe registry for all agents.

    Manages agent lifecycle and persistence.
    """

    def __init__(self, workspace: Path, max_agents: int = 10, max_depth: int = 3):
        self.workspace = workspace
        self.max_agents = max_agents
        self.max_depth = max_depth
        self._agents: Dict[str, Agent] = {}
        self._lock = threading.RLock()
        self._agent_names: set = set()

        self.storage_dir = self.workspace / "agents"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self._load_existing_agents()

    def _load_existing_agents(self) -> None:
        """Load existing agents from disk."""
        if not self.storage_dir.exists():
            return

        for agent_file in self.storage_dir.glob("*.json"):
            try:
                with open(agent_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                agent = Agent(**data)
                self._agents[agent.id] = agent
                self._agent_names.add(agent.name)
                logger.info("loaded_agent", agent_id=agent.id, name=agent.name)
            except Exception as e:
                logger.warning("failed_to_load_agent", file=str(agent_file), error=str(e))

    def _save_agent(self, agent: Agent) -> None:
        """Save agent to disk."""
        agent_file = self.storage_dir / f"{agent.id}.json"
        with open(agent_file, "w", encoding="utf-8") as f:
            json.dump(agent.model_dump(mode="json"), f, indent=2, default=str)

    def _delete_agent_file(self, agent_id: str) -> None:
        """Delete agent file from disk."""
        agent_file = self.storage_dir / f"{agent_id}.json"
        if agent_file.exists():
            agent_file.unlink()

    def count_agents(self) -> int:
        """Get total number of agents."""
        with self._lock:
            return len(self._agents)

    def count_active_agents(self) -> int:
        """Get number of running/waiting agents."""
        with self._lock:
            return sum(
                1
                for a in self._agents.values()
                if a.status in (AgentStatus.RUNNING, AgentStatus.WAITING)
            )

    def can_spawn(self, parent_id: Optional[str], depth: int) -> tuple[bool, str]:
        """Check if a new agent can be spawned.

        Returns:
            (can_spawn, reason)
        """
        with self._lock:
            if self.count_active_agents() >= self.max_agents:
                return False, f"Max agents ({self.max_agents}) reached"

            if depth > self.max_depth:
                return False, f"Max depth ({self.max_depth}) exceeded"

            if parent_id:
                parent = self._agents.get(parent_id)
                if not parent:
                    return False, f"Parent agent '{parent_id}' not found"

            return True, ""

    def create_agent(
        self,
        name: str,
        parent_id: Optional[str] = None,
        metadata: dict = None,
    ) -> Agent:
        """Create a new agent.

        Args:
            name: Agent name
            parent_id: Parent agent ID (None for main agent)
            metadata: Additional metadata

        Returns:
            Created Agent

        Raises:
            ValueError: If cannot spawn agent
        """
        with self._lock:
            depth = 0
            if parent_id:
                parent = self._agents.get(parent_id)
                if not parent:
                    raise ValueError(f"Parent agent '{parent_id}' not found")
                depth = parent.depth + 1

            can_spawn, reason = self.can_spawn(parent_id, depth)
            if not can_spawn:
                raise ValueError(reason)

            agent_id = generate_agent_id(parent_id, self._agent_names)

            agent = Agent(
                id=agent_id,
                name=name,
                parent_id=parent_id,
                depth=depth,
                metadata=metadata or {},
                status=AgentStatus.IDLE,
            )

            self._agents[agent_id] = agent
            self._agent_names.add(name)

            if parent_id:
                parent = self._agents[parent_id]
                parent.add_child(agent_id)
                self._save_agent(parent)

            self._save_agent(agent)
            logger.info("agent_created", agent_id=agent_id, name=name, parent_id=parent_id)

            return agent

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Get an agent by ID."""
        with self._lock:
            return self._agents.get(agent_id)

    def update_agent(self, agent: Agent) -> None:
        """Update an agent and persist to disk."""
        with self._lock:
            if agent.id in self._agents:
                self._agents[agent.id] = agent
                self._save_agent(agent)

    def delete_agent(self, agent_id: str) -> bool:
        """Delete an agent and its children.

        Returns:
            True if deleted, False if not found
        """
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return False

            for child_id in agent.children[:]:
                self.delete_agent(child_id)

            if agent.parent_id:
                parent = self._agents.get(agent.parent_id)
                if parent and agent_id in parent.children:
                    parent.children.remove(agent_id)
                    self._save_agent(parent)

            self._agent_names.discard(agent.name)
            del self._agents[agent_id]
            self._delete_agent_file(agent_id)

            logger.info("agent_deleted", agent_id=agent_id)
            return True

    def list_agents(
        self,
        parent_id: Optional[str] = None,
        status: Optional[AgentStatus] = None,
    ) -> List[Agent]:
        """List agents with optional filters."""
        with self._lock:
            agents = list(self._agents.values())

            if parent_id is not None:
                agents = [a for a in agents if a.parent_id == parent_id]

            if status:
                agents = [a for a in agents if a.status == status]

            return sorted(agents, key=lambda a: a.created_at)

    def get_children(self, agent_id: str) -> List[Agent]:
        """Get all child agents of an agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
            if not agent:
                return []
            return [self._agents[cid] for cid in agent.children if cid in self._agents]


_registry: Optional[AgentRegistry] = None
_registry_lock = threading.Lock()


def get_agent_registry(
    workspace: Path = None,
    max_agents: int = 10,
    max_depth: int = 3,
) -> AgentRegistry:
    """Get or create the global agent registry."""
    global _registry

    if _registry is None:
        with _registry_lock:
            if _registry is None:
                if workspace is None:
                    from settings import WS

                    workspace = WS

                _registry = AgentRegistry(
                    workspace=workspace,
                    max_agents=max_agents,
                    max_depth=max_depth,
                )

    return _registry


def reset_agent_registry() -> None:
    """Reset the registry (useful for testing)."""
    global _registry
    with _registry_lock:
        _registry = None
