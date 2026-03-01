"""Tests for Message Queue."""


from agents.queue import MessageQueue, get_message_queue, reset_message_queue
from agents.models import AgentMessage


class TestMessageQueue:
    """Tests for MessageQueue class."""

    def test_init(self, tmp_path):
        """Test MessageQueue initialization."""
        queue = MessageQueue(workspace=tmp_path)
        assert queue.storage_dir.exists()

    def test_publish(self, tmp_path):
        """Test publishing a message."""
        queue = MessageQueue(workspace=tmp_path)
        msg = AgentMessage(from_agent_id="agent1", to_agent_id="agent2", content="Hello")
        queue.publish(msg)

    def test_get_messages(self, tmp_path):
        """Test getting messages."""
        queue = MessageQueue(workspace=tmp_path)
        msg = AgentMessage(from_agent_id="agent1", to_agent_id="agent2", content="Hello")
        queue.publish(msg)
        messages = queue.get_messages("agent2")
        assert len(messages) >= 1

    def test_get_messages_empty(self, tmp_path):
        """Test getting messages when none exist."""
        queue = MessageQueue(workspace=tmp_path)
        messages = queue.get_messages("nonexistent")
        assert messages == []

    def test_get_unread_count(self, tmp_path):
        """Test getting unread count."""
        queue = MessageQueue(workspace=tmp_path)
        msg = AgentMessage(from_agent_id="agent1", to_agent_id="agent2", content="Hello")
        queue.publish(msg)
        count = queue.get_unread_count("agent2")
        assert count >= 0

    def test_clear_agent_messages(self, tmp_path):
        """Test clearing messages."""
        queue = MessageQueue(workspace=tmp_path)
        msg = AgentMessage(from_agent_id="agent1", to_agent_id="agent2", content="Hello")
        queue.publish(msg)
        queue.clear_agent_messages("agent2")
        messages = queue.get_messages("agent2")
        assert len(messages) == 0


class TestMessageQueueFactory:
    """Tests for message queue factory."""

    def test_get_message_queue(self, tmp_path):
        """Test getting message queue."""
        reset_message_queue()
        queue1 = get_message_queue(workspace=tmp_path)
        queue2 = get_message_queue(workspace=tmp_path)
        assert queue1 is queue2

    def test_reset_message_queue(self, tmp_path):
        """Test resetting message queue."""
        queue1 = get_message_queue(workspace=tmp_path)
        reset_message_queue()
        queue2 = get_message_queue(workspace=tmp_path)
        assert queue1 is not queue2
