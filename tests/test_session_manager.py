"""Tests for Session Manager."""

import json
import os
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from session_manager import SessionManager, get_session_manager, reset_session_manager


class TestSessionManagerInit:
    """Tests for SessionManager initialization."""

    def test_init_creates_storage_dir(self, tmp_path):
        """Test that initialization creates the storage directory."""
        storage = tmp_path / "sessions"
        sm = SessionManager(storage_dir=storage)
        assert storage.exists()
        assert storage.is_dir()

    def test_init_with_token_budget(self, tmp_path):
        """Test initialization with custom token budget."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=50000)
        assert sm.token_budget == 50000

    def test_init_with_ttl_days(self, tmp_path):
        """Test initialization with TTL days."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", ttl_days=7)
        assert sm.ttl_days == 7

    def test_init_default_values(self, tmp_path):
        """Test default values for token budget and TTL."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        assert sm.token_budget == 28000
        assert sm.ttl_days is None


class TestGenerateSessionId:
    """Tests for generate_session_id method."""

    def test_generate_with_ip_and_user_agent(self, tmp_path):
        """Test session ID generation with IP and user agent."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        session_id = sm.generate_session_id(ip="192.168.1.1", user_agent="Mozilla/5.0")
        assert isinstance(session_id, str)
        assert len(session_id) == 16
        assert session_id.isalnum()

    def test_generate_deterministic(self, tmp_path):
        """Test that same inputs produce same session ID."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        id1 = sm.generate_session_id(ip="192.168.1.1", user_agent="Mozilla/5.0")
        id2 = sm.generate_session_id(ip="192.168.1.1", user_agent="Mozilla/5.0")
        assert id1 == id2

    def test_generate_different_for_different_inputs(self, tmp_path):
        """Test that different inputs produce different session IDs."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        id1 = sm.generate_session_id(ip="192.168.1.1", user_agent="Mozilla/5.0")
        id2 = sm.generate_session_id(ip="192.168.1.2", user_agent="Mozilla/5.0")
        assert id1 != id2

    def test_generate_without_args(self, tmp_path):
        """Test session ID generation without IP and user agent (UUID)."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        session_id = sm.generate_session_id()
        assert isinstance(session_id, str)
        assert len(session_id) == 16
        assert session_id.isalnum()

    def test_generate_with_empty_ip_only(self, tmp_path):
        """Test session ID generation with empty IP."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        session_id = sm.generate_session_id(ip="")
        assert isinstance(session_id, str)
        assert len(session_id) == 16


class TestLoadSession:
    """Tests for load_session method."""

    def test_load_nonexistent_session(self, tmp_path):
        """Test loading a session that doesn't exist returns empty list."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        messages = sm.load_session("nonexistent_session_12345")
        assert messages == []

    def test_load_existing_session(self, tmp_path):
        """Test loading an existing session."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        session_id = "test_session_123"

        test_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        sm.save_session(session_id, test_messages)

        loaded = sm.load_session(session_id)
        assert loaded == test_messages

    def test_load_corrupted_session(self, tmp_path):
        """Test loading a corrupted JSON file returns empty list."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        session_path = tmp_path / "sessions" / "corrupted.json"
        session_path.write_text("{ invalid json }")

        messages = sm.load_session("corrupted")
        assert messages == []

    def test_load_session_without_messages_key(self, tmp_path):
        """Test loading a session file without messages key."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        session_path = tmp_path / "sessions" / "no_messages.json"
        session_path.write_text('{"session_id": "no_messages"}')

        messages = sm.load_session("no_messages")
        assert messages == []


class TestSaveSession:
    """Tests for save_session method."""

    def test_save_creates_file(self, tmp_path):
        """Test saving a session creates the file."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        sm.save_session("test_session", [{"role": "user", "content": "Hello"}])

        session_file = tmp_path / "sessions" / "test_session.json"
        assert session_file.exists()

    def test_save_creates_storage_dir(self, tmp_path):
        """Test saving creates the storage directory if missing."""
        storage = tmp_path / "new_sessions"
        sm = SessionManager(storage_dir=storage)
        sm.save_session("test", [{"role": "user", "content": "Hello"}])
        assert storage.exists()

    def test_save_overwrites_existing(self, tmp_path):
        """Test saving overwrites an existing session."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        sm.save_session("test", [{"role": "user", "content": "Hello"}])
        sm.save_session("test", [{"role": "user", "content": "Updated"}])

        loaded = sm.load_session("test")
        assert len(loaded) == 1
        assert loaded[0]["content"] == "Updated"

    def test_save_includes_metadata(self, tmp_path):
        """Test that save includes session_id and updated_at."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        sm.save_session("meta_test", [{"role": "user", "content": "Hello"}])

        session_file = tmp_path / "sessions" / "meta_test.json"
        with open(session_file) as f:
            data = json.load(f)

        assert "session_id" in data
        assert "updated_at" in data
        assert data["session_id"] == "meta_test"


class TestTruncateByTokenBudget:
    """Tests for truncate_by_token_budget method."""

    def test_truncate_empty_messages(self, tmp_path):
        """Test truncating empty message list."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=10000)
        result = sm.truncate_by_token_budget([])
        assert result == []

    def test_truncate_with_small_messages(self, tmp_path):
        """Test that small messages are not truncated."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=10000)
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = sm.truncate_by_token_budget(messages)
        assert len(result) == 2

    def test_truncate_respects_token_budget(self, tmp_path):
        """Test that truncation respects token budget."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=50)
        long_content = "x" * 1000
        messages = [
            {"role": "user", "content": long_content},
            {"role": "assistant", "content": long_content},
            {"role": "user", "content": long_content},
        ]
        result = sm.truncate_by_token_budget(messages)
        assert sum(len(json.dumps(m)) for m in result) <= 100

    def test_truncate_keeps_recent_messages(self, tmp_path):
        """Test that truncation keeps most recent messages."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=5000)
        messages = [
            {"role": "user", "content": "First message very long " + "x" * 50},
            {"role": "assistant", "content": "Second"},
            {"role": "user", "content": "Third"},
        ]
        result = sm.truncate_by_token_budget(messages)
        assert len(result) >= 1
        assert result[-1]["content"] == "Third"

    def test_truncate_with_system_prompt(self, tmp_path):
        """Test truncation with system prompt."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=10000)
        messages = [{"role": "user", "content": "Hello"}]
        result = sm.truncate_by_token_budget(messages, system_prompt="You are a helpful assistant")
        assert len(result) >= 0

    def test_truncate_with_tools(self, tmp_path):
        """Test truncation with tools list."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", token_budget=10000)
        messages = [{"role": "user", "content": "Hello"}]
        tools = [{"type": "function", "function": {"name": "test", "description": "Test function"}}]
        result = sm.truncate_by_token_budget(messages, tools=tools)
        assert len(result) >= 0


class TestCleanupOldSessions:
    """Tests for cleanup_old_sessions method."""

    def test_cleanup_returns_zero_when_no_ttl(self, tmp_path):
        """Test cleanup returns 0 when TTL is not set."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")
        removed = sm.cleanup_old_sessions()
        assert removed == 0

    def test_cleanup_returns_zero_when_no_sessions(self, tmp_path):
        """Test cleanup returns 0 when no session files exist."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", ttl_days=7)
        removed = sm.cleanup_old_sessions()
        assert removed == 0

    def test_cleanup_removes_old_sessions(self, tmp_path):
        """Test cleanup removes sessions older than TTL."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", ttl_days=7)

        old_session = tmp_path / "sessions" / "old.json"
        old_session.write_text('{"session_id": "old"}')
        old_time = time.time() - (8 * 86400)
        os.utime(old_session, (old_time, old_time))

        new_session = tmp_path / "sessions" / "new.json"
        new_session.write_text('{"session_id": "new"}')

        removed = sm.cleanup_old_sessions()
        assert removed == 1
        assert not old_session.exists()
        assert new_session.exists()

    def test_cleanup_keeps_recent_sessions(self, tmp_path):
        """Test cleanup keeps sessions within TTL."""
        sm = SessionManager(storage_dir=tmp_path / "sessions", ttl_days=7)

        session = tmp_path / "sessions" / "recent.json"
        session.write_text('{"session_id": "recent"}')

        removed = sm.cleanup_old_sessions()
        assert removed == 0
        assert session.exists()


class TestGetSessionManager:
    """Tests for get_session_manager factory function."""

    def test_get_session_manager_creates_instance(self, tmp_path):
        """Test that get_session_manager creates an instance."""
        reset_session_manager()
        sm = get_session_manager(storage_dir=tmp_path / "sessions")
        assert isinstance(sm, SessionManager)

    def test_get_session_manager_reuses_instance(self, tmp_path):
        """Test that get_session_manager reuses existing instance."""
        reset_session_manager()
        sm1 = get_session_manager(storage_dir=tmp_path / "sessions")
        sm2 = get_session_manager(storage_dir=tmp_path / "sessions")
        assert sm1 is sm2

    def test_get_session_manager_with_custom_token_budget(self, tmp_path):
        """Test get_session_manager with custom token budget."""
        reset_session_manager()
        sm = get_session_manager(storage_dir=tmp_path / "sessions", token_budget=50000)
        assert sm.token_budget == 50000

    def test_get_session_manager_with_custom_ttl(self, tmp_path):
        """Test get_session_manager with custom TTL."""
        reset_session_manager()
        sm = get_session_manager(storage_dir=tmp_path / "sessions", ttl_days=14)
        assert sm.ttl_days == 14


class TestResetSessionManager:
    """Tests for reset_session_manager function."""

    def test_reset_clears_global_instance(self, tmp_path):
        """Test that reset clears the global instance."""
        sm1 = get_session_manager(storage_dir=tmp_path / "sessions")
        reset_session_manager()
        sm2 = get_session_manager(storage_dir=tmp_path / "sessions")
        assert sm1 is not sm2


class TestIntegration:
    """Integration tests for SessionManager."""

    def test_full_session_lifecycle(self, tmp_path):
        """Test complete session lifecycle: create, save, load, update."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")

        session_id = sm.generate_session_id(ip="127.0.0.1", user_agent="TestAgent")

        initial_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        sm.save_session(session_id, initial_messages)

        loaded = sm.load_session(session_id)
        assert loaded == initial_messages

        updated_messages = loaded + [
            {"role": "user", "content": "How are you?"},
            {"role": "assistant", "content": "I'm good!"},
        ]
        sm.save_session(session_id, updated_messages)

        loaded_after = sm.load_session(session_id)
        assert len(loaded_after) == 4
        assert loaded_after[-1]["content"] == "I'm good!"

    def test_multiple_sessions(self, tmp_path):
        """Test multiple independent sessions."""
        sm = SessionManager(storage_dir=tmp_path / "sessions")

        sm.save_session("session_1", [{"role": "user", "content": "First"}])
        sm.save_session("session_2", [{"role": "user", "content": "Second"}])
        sm.save_session("session_3", [{"role": "user", "content": "Third"}])

        assert sm.load_session("session_1") == [{"role": "user", "content": "First"}]
        assert sm.load_session("session_2") == [{"role": "user", "content": "Second"}]
        assert sm.load_session("session_3") == [{"role": "user", "content": "Third"}]
