"""Tests for Agent System."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from agents.models import Agent, AgentMessage, AgentStatus, generate_agent_id
from agents.registry import AgentRegistry, get_agent_registry, reset_agent_registry


class TestAgentStatus:
    """Tests for AgentStatus enum."""

    def test_status_values(self):
        """Test all status values exist."""
        assert AgentStatus.IDLE.value == "idle"
        assert AgentStatus.RUNNING.value == "running"
        assert AgentStatus.WAITING.value == "waiting"
        assert AgentStatus.COMPLETED.value == "completed"
        assert AgentStatus.ERROR.value == "error"
        assert AgentStatus.TERMINATED.value == "terminated"


class TestGenerateAgentId:
    """Tests for generate_agent_id function."""

    def test_main_agent(self):
        """Test main agent ID generation."""
        agent_id = generate_agent_id(None, set())
        assert agent_id == "main"

    def test_sub_agent(self):
        """Test sub-agent ID generation."""
        agent_id = generate_agent_id("main", {"main"})
        assert agent_id == "sub"

    def test_nested_sub_agent(self):
        """Test nested sub-agent ID generation."""
        agent_id = generate_agent_id("sub", {"main", "sub"})
        assert "sub-" in agent_id

    def test_avoids_duplicate_names(self):
        """Test that duplicate names are avoided."""
        names = {"main", "sub", "sub-1"}
        agent_id = generate_agent_id("main", names)
        assert agent_id == "sub-2"


class TestAgentMessage:
    """Tests for AgentMessage model."""

    def test_create_message(self):
        """Test creating a message."""
        msg = AgentMessage(
            from_agent_id="agent1",
            to_agent_id="agent2",
            content="Hello!",
        )
        assert msg.from_agent_id == "agent1"
        assert msg.to_agent_id == "agent2"
        assert "Hello" in msg.content
        assert msg.id is not None

    def test_message_with_metadata(self):
        """Test message with metadata."""
        msg = AgentMessage(
            from_agent_id="agent1",
            to_agent_id="agent2",
            content="Hello!",
            metadata={"priority": "high"},
        )
        assert msg.metadata["priority"] == "high"


class TestAgent:
    """Tests for Agent model."""

    def test_create_agent(self):
        """Test creating an agent."""
        agent = Agent(name="test_agent")
        assert agent.name == "test_agent"
        assert agent.status == AgentStatus.IDLE
        assert agent.id is not None

    def test_add_message(self):
        """Test adding message to agent."""
        agent = Agent(name="test")
        agent.add_message("user", "Hello")
        assert len(agent.messages) == 1
        assert agent.messages[0]["role"] == "user"

    def test_add_child(self):
        """Test adding child to agent."""
        agent = Agent(name="parent")
        agent.add_child("child1")
        assert "child1" in agent.children
        agent.add_child("child1")
        assert len(agent.children) == 1

    def test_update_status(self):
        """Test updating agent status."""
        agent = Agent(name="test")
        agent.update_status(AgentStatus.RUNNING)
        assert agent.status == AgentStatus.RUNNING

    def test_to_summary(self):
        """Test agent summary conversion."""
        agent = Agent(name="test")
        summary = agent.to_summary()
        assert "id" in summary
        assert "name" in summary
        assert "status" in summary


class TestAgentRegistryInit:
    """Tests for AgentRegistry initialization."""

    def test_init_creates_storage_dir(self, tmp_path):
        """Test registry creates storage directory."""
        registry = AgentRegistry(workspace=tmp_path)
        assert registry.storage_dir.exists()

    def test_init_default_values(self, tmp_path):
        """Test default initialization values."""
        registry = AgentRegistry(workspace=tmp_path)
        assert registry.max_agents == 10
        assert registry.max_depth == 3

    def test_init_custom_values(self, tmp_path):
        """Test initialization with custom values."""
        registry = AgentRegistry(workspace=tmp_path, max_agents=5, max_depth=2)
        assert registry.max_agents == 5
        assert registry.max_depth == 2


class TestCreateAgent:
    """Tests for create_agent method."""

    def test_create_main_agent(self, tmp_path):
        """Test creating main agent."""
        registry = AgentRegistry(workspace=tmp_path / "reg1")
        agent = registry.create_agent(name="main_agent")
        assert agent.name == "main_agent"
        assert agent.parent_id is None
        assert agent.id == "main"

    def test_create_sub_agent(self, tmp_path):
        """Test creating sub-agent."""
        registry = AgentRegistry(workspace=tmp_path / "reg2")
        parent = registry.create_agent(name="parent")
        child = registry.create_agent(name="child", parent_id=parent.id)
        assert child.parent_id == parent.id
        assert child.depth == 1

    def test_create_agent_exceeds_max_depth(self, tmp_path):
        """Test that creating agent beyond max depth fails."""
        registry = AgentRegistry(workspace=tmp_path / "reg3", max_depth=0)
        can_spawn, reason = registry.can_spawn(None, 1)
        assert can_spawn is False
        assert "Max depth" in reason

    def test_create_agent_exceeds_max_active_agents(self, tmp_path):
        """Test that creating agent beyond max active agents fails."""
        registry = AgentRegistry(workspace=tmp_path / "reg4", max_agents=1)
        agent1 = registry.create_agent(name="agent1")
        agent1.update_status(AgentStatus.RUNNING)
        registry.update_agent(agent1)
        with pytest.raises(ValueError, match="Max agents"):
            registry.create_agent(name="agent2")

    def test_agent_has_children(self, tmp_path):
        """Test that parent agent tracks children."""
        registry = AgentRegistry(workspace=tmp_path / "reg5")
        parent = registry.create_agent(name="parent_agent")
        child = registry.create_agent(name="child_agent", parent_id=parent.id)
        assert child.id in parent.children


class TestGetAgent:
    """Tests for get_agent method."""

    def test_get_existing_agent(self, tmp_path):
        """Test getting existing agent."""
        registry = AgentRegistry(workspace=tmp_path / "reg6")
        created = registry.create_agent(name="test_get")
        retrieved = registry.get_agent(created.id)
        assert retrieved is not None
        assert retrieved.id == created.id

    def test_get_nonexistent_agent(self, tmp_path):
        """Test getting nonexistent agent returns None."""
        registry = AgentRegistry(workspace=tmp_path / "reg7")
        agent = registry.get_agent("nonexistent")
        assert agent is None


class TestUpdateAgent:
    """Tests for update_agent method."""

    def test_update_agent(self, tmp_path):
        """Test updating an agent."""
        registry = AgentRegistry(workspace=tmp_path / "reg8")
        agent = registry.create_agent(name="update_test")
        agent.update_status(AgentStatus.RUNNING)
        registry.update_agent(agent)
        retrieved = registry.get_agent(agent.id)
        assert retrieved.status == AgentStatus.RUNNING


class TestDeleteAgent:
    """Tests for delete_agent method."""

    def test_delete_existing_agent(self, tmp_path):
        """Test deleting existing agent."""
        registry = AgentRegistry(workspace=tmp_path / "reg9")
        agent = registry.create_agent(name="delete_test")
        result = registry.delete_agent(agent.id)
        assert result is True
        assert registry.get_agent(agent.id) is None

    def test_delete_nonexistent_agent(self, tmp_path):
        """Test deleting nonexistent agent returns False."""
        registry = AgentRegistry(workspace=tmp_path / "reg99")
        result = registry.delete_agent("nonexistent")
        assert result is False


class TestListAgents:
    """Tests for list_agents method."""

    def test_list_returns_agents(self, tmp_path):
        """Test listing returns agents."""
        registry = AgentRegistry(workspace=tmp_path / "reg10")
        registry.create_agent(name="list_agent1")
        agents = registry.list_agents()
        assert len(agents) >= 1

    def test_list_by_parent(self, tmp_path):
        """Test listing agents by parent."""
        registry = AgentRegistry(workspace=tmp_path / "reg11")
        parent = registry.create_agent(name="list_parent")
        registry.create_agent(name="list_child1", parent_id=parent.id)
        children = registry.list_agents(parent_id=parent.id)
        assert len(children) >= 1


class TestCountAgents:
    """Tests for count methods."""

    def test_count_agents(self, tmp_path):
        """Test counting agents."""
        registry = AgentRegistry(workspace=tmp_path / "reg12")
        registry.create_agent(name="count_agent1")
        assert registry.count_agents() >= 1

    def test_count_active_agents(self, tmp_path):
        """Test counting active agents."""
        registry = AgentRegistry(workspace=tmp_path / "reg13")
        agent = registry.create_agent(name="active_test")
        agent.update_status(AgentStatus.RUNNING)
        registry.update_agent(agent)
        assert registry.count_active_agents() == 1


class TestCanSpawn:
    """Tests for can_spawn method."""

    def test_can_spawn_at_limit(self, tmp_path):
        """Test can_spawn when at limit."""
        registry = AgentRegistry(workspace=tmp_path / "reg14", max_agents=1)
        agent = registry.create_agent(name="limit_agent1")
        agent.update_status(AgentStatus.RUNNING)
        registry.update_agent(agent)
        can_spawn, reason = registry.can_spawn(None, 0)
        assert can_spawn is False
        assert "Max agents" in reason

    def test_can_spawn_exceeds_depth(self, tmp_path):
        """Test can_spawn when depth exceeded."""
        registry = AgentRegistry(workspace=tmp_path / "reg15", max_depth=1)
        can_spawn, reason = registry.can_spawn(None, 2)
        assert can_spawn is False
        assert "Max depth" in reason


class TestConversation:
    """Tests for conversation methods."""

    def test_save_and_load_conversation(self, tmp_path):
        """Test saving and loading conversation."""
        registry = AgentRegistry(workspace=tmp_path / "conv1")
        agent = registry.create_agent(name="conv_test")
        registry.save_conversation(agent.id, [{"role": "user", "content": "Hello"}])
        messages = registry.load_conversation(agent.id)
        assert len(messages) == 1

    def test_append_to_conversation(self, tmp_path):
        """Test appending to conversation."""
        registry = AgentRegistry(workspace=tmp_path / "conv2")
        agent = registry.create_agent(name="append_test")
        registry.append_to_conversation(agent.id, "user", "Hello")
        registry.append_to_conversation(agent.id, "assistant", "Hi!")
        messages = registry.load_conversation(agent.id)
        assert len(messages) == 2


class TestGetAgentRegistry:
    """Tests for get_agent_registry factory."""

    def test_creates_instance(self, tmp_path):
        """Test factory creates instance."""
        reset_agent_registry()
        registry = get_agent_registry(workspace=tmp_path)
        assert isinstance(registry, AgentRegistry)

    def test_reuses_instance(self, tmp_path):
        """Test factory reuses instance."""
        reset_agent_registry()
        registry1 = get_agent_registry(workspace=tmp_path)
        registry2 = get_agent_registry(workspace=tmp_path)
        assert registry1 is registry2


class TestResetAgentRegistry:
    """Tests for reset_agent_registry function."""

    def test_reset_clears_global(self, tmp_path):
        """Test reset clears global instance."""
        registry1 = get_agent_registry(workspace=tmp_path)
        reset_agent_registry()
        registry2 = get_agent_registry(workspace=tmp_path)
        assert registry1 is not registry2
