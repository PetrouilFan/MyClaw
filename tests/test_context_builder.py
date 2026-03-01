"""Tests for Context Builder."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from context_builder import ContextBuilder, get_context_builder, reset_context_builder


class TestContextBuilderInit:
    """Tests for ContextBuilder initialization."""

    def test_init_default_values(self, tmp_path):
        """Test default values for token budget and max memories."""
        cb = ContextBuilder(workspace=tmp_path)
        assert cb.token_budget == 28000
        assert cb.max_memories == 5

    def test_init_custom_values(self, tmp_path):
        """Test initialization with custom values."""
        cb = ContextBuilder(workspace=tmp_path, token_budget=50000, max_memories=10)
        assert cb.token_budget == 50000
        assert cb.max_memories == 10


class TestLoadMdFile:
    """Tests for load_md_file method."""

    def test_load_existing_file(self, tmp_path):
        """Test loading an existing markdown file."""
        (tmp_path / "SOUL.md").write_text("# My Soul\nI am helpful.")
        cb = ContextBuilder(workspace=tmp_path)
        content = cb.load_md_file("SOUL.md")
        assert content == "# My Soul\nI am helpful."

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading a non-existent file returns None."""
        cb = ContextBuilder(workspace=tmp_path)
        content = cb.load_md_file("NONEXISTENT.md")
        assert content is None

    def test_load_empty_file(self, tmp_path):
        """Test loading an empty file."""
        (tmp_path / "EMPTY.md").write_text("")
        cb = ContextBuilder(workspace=tmp_path)
        content = cb.load_md_file("EMPTY.md")
        assert content == ""

    def test_load_file_with_whitespace(self, tmp_path):
        """Test that whitespace is stripped."""
        (tmp_path / "TEST.md").write_text("  \n  Content  \n  ")
        cb = ContextBuilder(workspace=tmp_path)
        content = cb.load_md_file("TEST.md")
        assert content == "Content"


class TestGetIdentity:
    """Tests for get_identity method."""

    def test_get_identity_with_file(self, tmp_path):
        """Test getting identity when SOUL.md exists."""
        (tmp_path / "SOUL.md").write_text("# Identity\nI am a helpful assistant.")
        cb = ContextBuilder(workspace=tmp_path)
        identity = cb.get_identity()
        assert "I am a helpful assistant" in identity

    def test_get_identity_without_file(self, tmp_path):
        """Test getting identity when SOUL.md doesn't exist."""
        cb = ContextBuilder(workspace=tmp_path)
        identity = cb.get_identity()
        assert identity == ""


class TestGetPersonality:
    """Tests for get_personality method."""

    def test_get_personality_with_file(self, tmp_path):
        """Test getting personality when PERSONALITY.md exists."""
        (tmp_path / "PERSONALITY.md").write_text("# Personality\nI am friendly and concise.")
        cb = ContextBuilder(workspace=tmp_path)
        personality = cb.get_personality()
        assert "I am friendly" in personality

    def test_get_personality_without_file(self, tmp_path):
        """Test getting personality when PERSONALITY.md doesn't exist."""
        cb = ContextBuilder(workspace=tmp_path)
        personality = cb.get_personality()
        assert personality == ""


class TestGetUserContext:
    """Tests for get_user_context method."""

    def test_get_user_context_with_file(self, tmp_path):
        """Test getting user context when USER.md exists."""
        (tmp_path / "USER.md").write_text("# User Context\nUser prefers Python.")
        cb = ContextBuilder(workspace=tmp_path)
        user_ctx = cb.get_user_context()
        assert "prefers Python" in user_ctx

    def test_get_user_context_without_file(self, tmp_path):
        """Test getting user context when USER.md doesn't exist."""
        cb = ContextBuilder(workspace=tmp_path)
        user_ctx = cb.get_user_context()
        assert user_ctx == ""


class TestGetMemories:
    """Tests for get_memories method."""

    def test_get_memories_no_file(self, tmp_path):
        """Test getting memories when MEMORIES.md doesn't exist."""
        cb = ContextBuilder(workspace=tmp_path)
        memories = cb.get_memories()
        assert memories == ""

    def test_get_memories_with_query_matching(self, tmp_path):
        """Test getting memories with matching query."""
        content = """# Memories
Remember to buy milk
User likes coffee
Python is great
"""
        (tmp_path / "MEMORIES.md").write_text(content)
        cb = ContextBuilder(workspace=tmp_path)
        memories = cb.get_memories(query="coffee")
        assert "coffee" in memories.lower()

    def test_get_memories_with_query_no_match(self, tmp_path):
        """Test getting memories with no matching query falls back to recent."""
        content = """# Memories
Remember to buy milk
Python is great
"""
        (tmp_path / "MEMORIES.md").write_text(content)
        cb = ContextBuilder(workspace=tmp_path)
        memories = cb.get_memories(query="xyz123", max_tokens=50)
        assert "buy milk" in memories.lower() or "python" in memories.lower()

    def test_get_memories_fallback_to_recent(self, tmp_path):
        """Test fallback to recent memories when no query match."""
        content = """# Memories
Line one
Line two
Line three
Line four
Line five
Line six
"""
        (tmp_path / "MEMORIES.md").write_text(content)
        cb = ContextBuilder(workspace=tmp_path, max_memories=3)
        memories = cb.get_memories()
        assert "Line four" in memories
        assert "Line one" not in memories

    def test_get_memories_with_max_tokens(self, tmp_path):
        """Test getting memories respects max_tokens."""
        content = """# Memories
""" + "\n".join([f"Memory {i}: " + "x" * 100 for i in range(10)])
        (tmp_path / "MEMORIES.md").write_text(content)
        cb = ContextBuilder(workspace=tmp_path, max_memories=5)
        memories = cb.get_memories(max_tokens=200)
        from token_budget import estimate_tokens

        assert estimate_tokens(memories) <= 250


class TestExtractKeywords:
    """Tests for _extract_keywords method."""

    def test_extract_keywords_basic(self):
        """Test basic keyword extraction."""
        cb = ContextBuilder(workspace=Path("/tmp"))
        keywords = cb._extract_keywords("I want to run a terminal command")
        assert "terminal" in keywords
        assert "command" in keywords

    def test_extract_keywords_filters_stop_words(self):
        """Test that stop words are filtered."""
        cb = ContextBuilder(workspace=Path("/tmp"))
        keywords = cb._extract_keywords("the and for are but not you")
        assert len(keywords) == 0

    def test_extract_keywords_minimum_length(self):
        """Test that words shorter than 3 chars are filtered."""
        cb = ContextBuilder(workspace=Path("/tmp"))
        keywords = cb._extract_keywords("I am ok")
        assert "am" not in keywords
        assert "ok" not in keywords


class TestCompressMd:
    """Tests for _compress_md method."""

    def test_compress_empty(self):
        """Test compressing empty content."""
        cb = ContextBuilder(workspace=Path("/tmp"))
        result = cb._compress_md("")
        assert result == ""

    def test_compress_under_limit(self):
        """Test that content under limit is not truncated."""
        cb = ContextBuilder(workspace=Path("/tmp"))
        content = "Short content"
        result = cb._compress_md(content, max_tokens=100)
        assert result == content

    def test_compress_over_limit(self):
        """Test that content over limit is truncated."""
        cb = ContextBuilder(workspace=Path("/tmp"))
        long_content = "\n".join([f"Line {i}: " + "x" * 50 for i in range(20)])
        result = cb._compress_md(long_content, max_tokens=100)
        from token_budget import estimate_tokens

        assert estimate_tokens(result) <= 120


class TestBuildSystemPrompt:
    """Tests for build_system_prompt method."""

    def test_build_minimal_prompt(self, tmp_path):
        """Test building minimal system prompt."""
        cb = ContextBuilder(workspace=tmp_path)
        prompt = cb.build_system_prompt(
            base_prompt="You are a helpful assistant.",
            include_identity=False,
            include_personality=False,
            include_user=False,
            include_memories=False,
        )
        assert prompt == "You are a helpful assistant."

    def test_build_with_identity(self, tmp_path):
        """Test building prompt with identity."""
        (tmp_path / "SOUL.md").write_text("# Identity\nI am AI.")
        cb = ContextBuilder(workspace=tmp_path)
        prompt = cb.build_system_prompt(
            include_identity=True,
            include_personality=False,
            include_user=False,
            include_memories=False,
        )
        assert "Identity" in prompt
        assert "I am AI" in prompt

    def test_build_with_personality(self, tmp_path):
        """Test building prompt with personality."""
        (tmp_path / "PERSONALITY.md").write_text("# Personality\nI am friendly.")
        cb = ContextBuilder(workspace=tmp_path)
        prompt = cb.build_system_prompt(
            include_identity=False,
            include_personality=True,
            include_user=False,
            include_memories=False,
        )
        assert "Personality" in prompt

    def test_build_with_user_context(self, tmp_path):
        """Test building prompt with user context."""
        (tmp_path / "USER.md").write_text("# User Context\nUser likes Python.")
        cb = ContextBuilder(workspace=tmp_path)
        prompt = cb.build_system_prompt(
            include_identity=False,
            include_personality=False,
            include_user=True,
            include_memories=False,
        )
        assert "User Context" in prompt

    def test_build_with_memories(self, tmp_path):
        """Test building prompt with memories."""
        (tmp_path / "MEMORIES.md").write_text("# Memories\nRemember: buy milk")
        cb = ContextBuilder(workspace=tmp_path)
        prompt = cb.build_system_prompt(
            include_identity=False,
            include_personality=False,
            include_user=False,
            include_memories=True,
            query="milk",
        )
        assert "Memories" in prompt

    def test_build_respects_token_limit(self, tmp_path):
        """Test that build respects 2000 token limit."""
        (tmp_path / "SOUL.md").write_text("# Identity\n" + "x" * 10000)
        cb = ContextBuilder(workspace=tmp_path)
        prompt = cb.build_system_prompt(
            include_identity=True,
            include_personality=False,
            include_user=False,
            include_memories=False,
        )
        from token_budget import estimate_tokens

        assert estimate_tokens(prompt) <= 2100


class TestSelectTools:
    """Tests for select_tools method."""

    def test_select_tools_empty(self, tmp_path):
        """Test selecting from empty tool list."""
        cb = ContextBuilder(workspace=tmp_path)
        selected = cb.select_tools([])
        assert selected == []

    def test_select_tools_no_query(self, tmp_path):
        """Test selecting tools without query returns all (limited)."""
        cb = ContextBuilder(workspace=tmp_path)
        tools = [
            {"type": "function", "function": {"name": "tool1", "description": "Tool 1"}},
            {"type": "function", "function": {"name": "tool2", "description": "Tool 2"}},
        ]
        selected = cb.select_tools(tools, max_tools=2)
        assert len(selected) == 2

    def test_select_tools_with_terminal_query(self, tmp_path):
        """Test selecting tools with terminal-related query."""
        cb = ContextBuilder(workspace=tmp_path)
        tools = [
            {
                "type": "function",
                "function": {"name": "run_terminal_command", "description": "Run terminal"},
            },
            {"type": "function", "function": {"name": "read_file", "description": "Read file"}},
            {"type": "function", "function": {"name": "get_time", "description": "Get time"}},
        ]
        selected = cb.select_tools(tools, query="run a shell command", max_tools=2)
        tool_names = [t["function"]["name"] for t in selected]
        assert "run_terminal_command" in tool_names

    def test_select_tools_max_limit(self, tmp_path):
        """Test that max_tools limit is respected."""
        cb = ContextBuilder(workspace=tmp_path)
        tools = [
            {"type": "function", "function": {"name": f"tool{i}", "description": f"Tool {i}"}}
            for i in range(20)
        ]
        selected = cb.select_tools(tools, max_tools=5)
        assert len(selected) == 5

    def test_select_tools_with_conversation_history(self, tmp_path):
        """Test selecting tools based on conversation history."""
        cb = ContextBuilder(workspace=tmp_path)
        tools = [
            {
                "type": "function",
                "function": {"name": "run_terminal_command", "description": "Run terminal"},
            },
            {"type": "function", "function": {"name": "read_file", "description": "Read file"}},
        ]
        history = [{"role": "user", "content": "Please read the file"}]
        selected = cb.select_tools(tools, conversation_history=history)
        tool_names = [t["function"]["name"] for t in selected]
        assert "read_file" in tool_names


class TestGetContextBuilder:
    """Tests for get_context_builder factory."""

    def test_get_context_builder_creates_instance(self, tmp_path):
        """Test that get_context_builder creates an instance."""
        reset_context_builder()
        cb = get_context_builder(workspace=tmp_path)
        assert isinstance(cb, ContextBuilder)

    def test_get_context_builder_reuses_instance(self, tmp_path):
        """Test that get_context_builder reuses existing instance."""
        reset_context_builder()
        cb1 = get_context_builder(workspace=tmp_path)
        cb2 = get_context_builder(workspace=tmp_path)
        assert cb1 is cb2


class TestResetContextBuilder:
    """Tests for reset_context_builder function."""

    def test_reset_clears_global(self, tmp_path):
        """Test that reset clears global instance."""
        cb1 = get_context_builder(workspace=tmp_path)
        reset_context_builder()
        cb2 = get_context_builder(workspace=tmp_path)
        assert cb1 is not cb2
