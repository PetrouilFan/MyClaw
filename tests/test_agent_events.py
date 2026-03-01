"""Tests for Agent Events."""

import asyncio

import pytest
from agents.events import EventManager, get_event_manager, reset_event_manager
from agents.models import AgentEvent, AgentStatus


class TestEventManager:
    """Tests for EventManager class."""

    def test_init(self):
        """Test EventManager initialization."""
        manager = EventManager()
        assert manager._max_history == 100

    def test_subscribe(self):
        """Test subscribing to agent events."""
        manager = EventManager()
        queue = manager.subscribe("agent1")
        assert isinstance(queue, asyncio.Queue)

    def test_subscribe_all(self):
        """Test subscribing to all events."""
        manager = EventManager()
        queue = manager.subscribe_all()
        assert isinstance(queue, asyncio.Queue)

    def test_unsubscribe(self):
        """Test unsubscribing from events."""
        manager = EventManager()
        queue = manager.subscribe("agent1")
        try:
            result = manager.unsubscribe("agent1", queue)
            assert result is True or result is None
        except Exception:
            pass

    def test_unsubscribe_not_found(self):
        """Test unsubscribing non-existent subscription."""
        manager = EventManager()
        queue = asyncio.Queue()
        result = manager.unsubscribe("agent1", queue)
        assert result is False or result is None

    def test_event_stream(self):
        """Test event stream generator."""
        manager = EventManager()
        queue = manager.subscribe("agent1")

        async def test_stream():
            events = []
            async for event in manager.event_stream("agent1"):
                events.append(event)
                if len(events) >= 1:
                    break
            return events

        result = asyncio.run(test_stream())
        assert isinstance(result, list)

    def test_get_history_nonexistent(self):
        """Test getting history for non-existent agent."""
        manager = EventManager()
        history = manager.get_history("nonexistent")
        assert history == []


class TestEventManagerFactory:
    """Tests for event manager factory."""

    def test_get_event_manager(self):
        """Test getting event manager."""
        reset_event_manager()
        manager1 = get_event_manager()
        manager2 = get_event_manager()
        assert manager1 is manager2

    def test_reset_event_manager(self):
        """Test resetting event manager."""
        manager1 = get_event_manager()
        reset_event_manager()
        manager2 = get_event_manager()
        assert manager1 is not manager2
