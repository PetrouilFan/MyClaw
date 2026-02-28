"""Tests for tool parser module."""

from tools.tool_parser import clean_content, extract_tool_calls


class TestExtractToolCalls:
    """Tests for extract_tool_calls function."""

    def test_standard_tool_calls(self):
        """Test standard OpenAI format tool_calls."""
        msg = {
            "tool_calls": [
                {
                    "id": "call_123",
                    "type": "function",
                    "function": {
                        "name": "get_time",
                        "arguments": "{}",
                    },
                }
            ]
        }
        result = extract_tool_calls(msg)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "get_time"

    def test_xml_tool_call_block(self):
        """Test XML-style <tool_call> blocks."""
        msg = {
            "content": 'I\'ll get the time for you.<tool_call>{"name": "get_time", "arguments": {}}</tool_call>'
        }
        result = extract_tool_calls(msg)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "get_time"

    def test_json_like_tool_call(self):
        """Test JSON-like tool call in content."""
        msg = {
            "content": 'Let me check this. {"name": "read_file", "arguments": {"filepath": "test.txt"}}'
        }
        result = extract_tool_calls(msg)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "read_file"

    def test_tool_call_in_reasoning(self):
        """Test tool call in reasoning field."""
        msg = {
            "reasoning": 'I should check the time first.<tool_call>{"name": "get_time", "arguments": {}}</tool_call>',
            "content": "I'll check that for you.",
        }
        result = extract_tool_calls(msg)
        assert len(result) == 1
        assert result[0]["function"]["name"] == "get_time"

    def test_multiple_tool_calls(self):
        """Test multiple tool calls in one message."""
        msg = {
            "content": '<tool_call>{"name": "get_time", "arguments": {}}</tool_call><tool_call>{"name": "read_file", "arguments": {"filepath": "a.txt"}}</tool_call>'
        }
        result = extract_tool_calls(msg)
        assert len(result) == 2

    def test_empty_message(self):
        """Test empty message returns empty list."""
        msg = {}
        result = extract_tool_calls(msg)
        assert result == []

    def test_no_tool_calls(self):
        """Test message without any tool calls."""
        msg = {"content": "Hello, how are you?"}
        result = extract_tool_calls(msg)
        assert result == []


class TestCleanContent:
    """Tests for clean_content function."""

    def test_simple_content(self):
        """Test simple text content passes through."""
        msg = {"content": "Hello, world!"}
        result = clean_content(msg)
        assert result == "Hello, world!"

    def test_removes_xml_tool_call_blocks(self):
        """Test XML tool call blocks are removed."""
        msg = {
            "content": 'Here you go.<tool_call>{"name": "test", "arguments": {}}</tool_call>Thanks!'
        }
        result = clean_content(msg)
        assert "<tool_call>" not in result
        assert "Thanks!" in result

    def test_removes_from_reasoning(self):
        """Test tool calls in reasoning are cleaned."""
        msg = {
            "reasoning": 'Thinking...<tool_call>{"name": "test"}</tool_call>',
            "content": "Done.",
        }
        result = clean_content(msg)
        assert "<tool_call>" not in result
        assert "Done." in result

    def test_returns_empty_for_invalid_tool_call(self):
        """Test returns empty for content that's only a tool call."""
        msg = {"content": '<tool_call>{"name": "test", "arguments": {}}'}
        result = clean_content(msg)
        assert result == ""

    def test_empty_message(self):
        """Test empty message returns empty string."""
        msg = {}
        result = clean_content(msg)
        assert result == ""

    def test_strips_trailing_tool_call_tags(self):
        """Test trailing </tool_call> tags are stripped."""
        msg = {"content": "Here is the result.</tool_call>"}
        result = clean_content(msg)
        assert "</tool_call>" not in result
        assert "Here is the result." in result

    def test_handles_nested_json_arguments(self):
        """Test nested JSON in arguments."""
        msg = {"content": '{"name": "test", "arguments": {"nested": {"key": "value"}}}'}
        result = extract_tool_calls(msg)
        assert len(result) == 1
        assert "nested" in result[0]["function"]["arguments"]

    def test_preserves_content_after_tool_call(self):
        """Test content after tool call is preserved."""
        msg = {
            "content": '<tool_call>{"name": "get_time", "arguments": {}}</tool_call>\n\nThe current time is 12:00 PM.'
        }
        result = clean_content(msg)
        assert "The current time is 12:00 PM." in result

    def test_handles_malformed_json(self):
        """Test malformed JSON is handled gracefully."""
        msg = {"content": '{"name": "test", "arguments": {invalid json here}'}
        result = extract_tool_calls(msg)
        assert isinstance(result, list)
