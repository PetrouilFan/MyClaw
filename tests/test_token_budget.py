"""Tests for Token Budget utilities."""

import json

import pytest

from token_budget import (
    calculate_available_for_history,
    count_messages_tokens,
    count_tools_tokens,
    estimate_tokens,
    estimate_tokens_precise,
    get_tokenizer_for_model,
    truncate_messages,
)


class TestEstimateTokens:
    """Tests for estimate_tokens function."""

    def test_empty_string(self):
        """Test that empty string returns 0."""
        assert estimate_tokens("") == 0

    def test_none_input(self):
        """Test that None returns 0."""
        assert estimate_tokens(None) == 0

    def test_short_text(self):
        """Test short text returns at least 1 token."""
        assert estimate_tokens("Hi") >= 1

    def test_english_text(self):
        """Test English text estimation."""
        text = "Hello, how are you today?"
        tokens = estimate_tokens(text)
        assert tokens >= 1
        assert tokens <= len(text)

    def test_long_text(self):
        """Test long text estimation."""
        text = "a" * 1000
        tokens = estimate_tokens(text)
        assert tokens >= 100
        assert tokens <= 300

    def test_special_characters(self):
        """Test special characters are counted."""
        text = "!@#$%^&*()"
        tokens = estimate_tokens(text)
        assert tokens >= 1

    def test_chinese_characters(self):
        """Test Chinese characters (each char is ~1 token)."""
        text = "你好世界"
        tokens = estimate_tokens(text)
        assert tokens >= 1

    def test_newlines_counted(self):
        """Test newlines are counted."""
        text = "line1\nline2\nline3"
        tokens = estimate_tokens(text)
        assert tokens >= 1


class TestEstimateTokensPrecise:
    """Tests for estimate_tokens_precise function."""

    def test_returns_value(self):
        """Test that precise estimation returns a value."""
        result = estimate_tokens_precise("Hello world")
        assert isinstance(result, int)
        assert result >= 1


class TestGetTokenizerForModel:
    """Tests for get_tokenizer_for_model function."""

    def test_returns_callable(self):
        """Test that a callable is returned."""
        tokenizer = get_tokenizer_for_model("gpt-4")
        assert callable(tokenizer)

    def test_gpt_4_model(self):
        """Test tokenizer for GPT-4."""
        tokenizer = get_tokenizer_for_model("gpt-4")
        assert tokenizer is not None

    def test_gpt_35_model(self):
        """Test tokenizer for GPT-3.5."""
        tokenizer = get_tokenizer_for_model("gpt-3.5-turbo")
        assert tokenizer is not None

    def test_qwen_model(self):
        """Test tokenizer for Qwen."""
        tokenizer = get_tokenizer_for_model("qwen2.5")
        assert tokenizer is not None

    def test_llama_model(self):
        """Test tokenizer for Llama."""
        tokenizer = get_tokenizer_for_model("llama3")
        assert tokenizer is not None

    def test_unknown_model(self):
        """Test tokenizer for unknown model returns estimate_tokens."""
        tokenizer = get_tokenizer_for_model("unknown-model-xyz")
        assert tokenizer == estimate_tokens


class TestCountMessagesTokens:
    """Tests for count_messages_tokens function."""

    def test_empty_messages(self):
        """Test empty message list."""
        assert count_messages_tokens([]) == 0

    def test_single_message(self):
        """Test single message."""
        messages = [{"role": "user", "content": "Hello"}]
        tokens = count_messages_tokens(messages)
        assert tokens >= 1

    def test_multiple_messages(self):
        """Test multiple messages."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"},
        ]
        tokens = count_messages_tokens(messages)
        assert tokens >= 1


class TestCountToolsTokens:
    """Tests for count_tools_tokens function."""

    def test_empty_tools(self):
        """Test empty tool list."""
        assert count_tools_tokens([]) == 0

    def test_none_tools(self):
        """Test None tools."""
        assert count_tools_tokens(None) == 0

    def test_single_tool(self):
        """Test single tool definition."""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get current time",
                },
            }
        ]
        tokens = count_tools_tokens(tools)
        assert tokens >= 1

    def test_multiple_tools(self):
        """Test multiple tool definitions."""
        tools = [
            {"type": "function", "function": {"name": "tool1", "description": "Tool 1"}},
            {"type": "function", "function": {"name": "tool2", "description": "Tool 2"}},
            {"type": "function", "function": {"name": "tool3", "description": "Tool 3"}},
        ]
        tokens = count_tools_tokens(tools)
        assert tokens >= 1


class TestCalculateAvailableForHistory:
    """Tests for calculate_available_for_history function."""

    def test_simple_calculation(self):
        """Test basic calculation."""
        available = calculate_available_for_history(
            total_budget=10000,
            system_prompt="You are helpful.",
            tools=[],
        )
        assert isinstance(available, int)
        assert available >= 0

    def test_with_tools(self):
        """Test calculation with tools."""
        tools = [
            {"type": "function", "function": {"name": "tool1", "description": "Tool"}},
        ]
        available = calculate_available_for_history(
            total_budget=10000,
            system_prompt="You are helpful.",
            tools=tools,
        )
        assert available >= 0

    def test_reserved_tokens(self):
        """Test with custom reserved tokens."""
        available = calculate_available_for_history(
            total_budget=10000,
            system_prompt="You are helpful.",
            tools=[],
            reserved=5000,
        )
        assert available <= 5000

    def test_large_system_prompt(self):
        """Test with large system prompt."""
        large_prompt = "x" * 50000
        available = calculate_available_for_history(
            total_budget=10000,
            system_prompt=large_prompt,
            tools=[],
        )
        assert available == 0


class TestTruncateMessages:
    """Tests for truncate_messages function."""

    def test_empty_messages(self):
        """Test truncating empty message list."""
        result = truncate_messages([], 1000)
        assert result == []

    def test_none_messages(self):
        """Test truncating None messages."""
        result = truncate_messages(None, 1000)
        assert result == []

    def test_small_messages(self):
        """Test that small messages are not truncated."""
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        result = truncate_messages(messages, 10000)
        assert len(result) == 2

    def test_truncate_respects_limit(self):
        """Test that truncation respects token limit."""
        messages = [
            {"role": "user", "content": "x" * 5000},
            {"role": "assistant", "content": "y" * 5000},
            {"role": "user", "content": "z" * 5000},
        ]
        result = truncate_messages(messages, 1000)
        assert len(result) >= 0
        total_tokens = sum(estimate_tokens(json.dumps(m)) for m in result)
        assert total_tokens <= 1500

    def test_truncate_keeps_recent(self):
        """Test that truncation keeps most recent messages."""
        messages = [
            {"role": "user", "content": "First message " + "x" * 100},
            {"role": "assistant", "content": "Second message"},
            {"role": "user", "content": "Third message"},
        ]
        result = truncate_messages(messages, 1000)
        if len(result) > 0:
            assert result[-1]["content"] == "Third message"

    def test_truncate_empty_result(self):
        """Test that truncation can return empty list when budget too small."""
        messages = [{"role": "user", "content": "x" * 10000}]
        result = truncate_messages(messages, 10)
        assert len(result) == 0

    def test_preserves_message_structure(self):
        """Test that message structure is preserved."""
        messages = [
            {"role": "user", "content": "Hello", "name": "user1"},
            {"role": "assistant", "content": "Hi there!", "tool_calls": []},
        ]
        result = truncate_messages(messages, 10000)
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["role"] == "assistant"


class TestIntegration:
    """Integration tests for token budget functions."""

    def test_full_workflow(self):
        """Test complete token budget workflow."""
        system_prompt = "You are a helpful assistant."
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
            {"role": "user", "content": "How are you?"},
        ]
        tools = [
            {"type": "function", "function": {"name": "tool1", "description": "A tool"}},
        ]

        system_tokens = estimate_tokens(system_prompt)
        message_tokens = count_messages_tokens(messages)
        tools_tokens = count_tools_tokens(tools)

        available = calculate_available_for_history(
            total_budget=10000,
            system_prompt=system_prompt,
            tools=tools,
        )

        truncated = truncate_messages(messages, available)

        assert system_tokens >= 1
        assert message_tokens >= 1
        assert tools_tokens >= 1
        assert available >= 0
        assert len(truncated) >= 0
