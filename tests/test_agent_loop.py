"""Tests for Agent Loop - planning, retry logic, and reflection."""

from agent_loop import (
    ToolRetry,
    ErrorFormatter,
    PlanningAgent,
    get_planning_agent,
    add_planning_to_system_prompt,
)


class TestToolRetry:
    """Tests for ToolRetry class."""

    def test_should_retry_timeout_error(self):
        """Test retry returns True for timeout errors."""
        retry = ToolRetry(max_retries=2)
        result = retry.should_retry("tool1", 0, "Request timeout")
        assert result is True

    def test_should_retry_connection_error(self):
        """Test retry returns True for connection errors."""
        retry = ToolRetry(max_retries=2)
        result = retry.should_retry("tool1", 0, "Connection refused")
        assert result is True

    def test_should_retry_rate_limit(self):
        """Test retry returns True for rate limit errors."""
        retry = ToolRetry(max_retries=2)
        result = retry.should_retry("tool1", 0, "Rate limit exceeded")
        assert result is True

    def test_should_retry_non_retryable(self):
        """Test retry returns False for non-retryable errors."""
        retry = ToolRetry(max_retries=2)
        result = retry.should_retry("tool1", 0, "File not found")
        assert result is False

    def test_should_retry_max_attempts(self):
        """Test retry returns False when max attempts reached."""
        retry = ToolRetry(max_retries=2)
        result = retry.should_retry("tool1", 2, "timeout")
        assert result is False

    def test_get_retry_message_format(self):
        """Test retry message is formatted correctly."""
        retry = ToolRetry(max_retries=2)
        msg = retry.get_retry_message("tool1", 0, "Timeout error")
        assert "tool1" in msg
        assert "attempt 1" in msg
        assert "Timeout error" in msg


class TestErrorFormatter:
    """Tests for ErrorFormatter class."""

    def test_format_tool_error_with_args(self):
        """Test tool error formatting with arguments."""
        formatter = ErrorFormatter()
        result = formatter.format_tool_error("read_file", "File not found", {"path": "/test"})
        assert "read_file" in result
        assert "File not found" in result
        assert "/test" in result

    def test_format_tool_error_no_args(self):
        """Test tool error formatting without arguments."""
        formatter = ErrorFormatter()
        result = formatter.format_tool_error("tool1", "Error message")
        assert "tool1" in result
        assert "Error message" in result

    def test_format_validation_error(self):
        """Test validation error formatting."""
        formatter = ErrorFormatter()
        result = formatter.format_validation_error("tool1", "path", "must be string")
        assert "tool1" in result
        assert "path" in result
        assert "must be string" in result

    def test_format_success_no_truncation(self):
        """Test success formatting without truncation."""
        formatter = ErrorFormatter()
        result = formatter.format_success("tool1", "Success!")
        assert "tool1" in result
        assert "Success!" in result
        assert "truncated" not in result.lower()

    def test_format_success_truncated(self):
        """Test success formatting with truncation."""
        formatter = ErrorFormatter()
        long_result = "x" * 3000
        result = formatter.format_success("tool1", long_result, truncated=True)
        assert "truncated" in result.lower()


class TestPlanningAgent:
    """Tests for PlanningAgent class."""

    def test_create_plan_disabled(self):
        """Test create_plan returns empty when disabled."""
        agent = PlanningAgent(enable_planning=False, enable_reflection=False)
        result = agent.create_plan("Test task")
        assert result == ""

    def test_create_plan_enabled(self):
        """Test create_plan generates plan when enabled."""
        agent = PlanningAgent(enable_planning=True, enable_reflection=False)
        result = agent.create_plan("Test task")
        assert "Test task" in result
        assert "plan" in result.lower()

    def test_create_plan_with_tools(self):
        """Test create_plan includes available tools."""
        agent = PlanningAgent(enable_planning=True, enable_reflection=False)
        tools = [
            {"function": {"name": "tool1"}},
            {"function": {"name": "tool2"}},
        ]
        result = agent.create_plan("Test task", available_tools=tools)
        assert "tool1" in result
        assert "tool2" in result

    def test_should_reflect_disabled(self):
        """Test should_reflect returns False when disabled."""
        agent = PlanningAgent(enable_planning=False, enable_reflection=False)
        result = agent.should_reflect("error message")
        assert result is False

    def test_should_reflect_triggers_error(self):
        """Test should_reflect detects error trigger."""
        agent = PlanningAgent(enable_planning=False, enable_reflection=True)
        result = agent.should_reflect("Error: something failed")
        assert result is True

    def test_should_reflect_triggers_not_found(self):
        """Test should_reflect detects not found trigger."""
        agent = PlanningAgent(enable_planning=False, enable_reflection=True)
        result = agent.should_reflect("File not found")
        assert result is True

    def test_should_reflect_no_trigger(self):
        """Test should_reflect returns False when no trigger."""
        agent = PlanningAgent(enable_planning=False, enable_reflection=True)
        result = agent.should_reflect("Successfully completed task")
        assert result is False

    def test_create_reflection(self):
        """Test create_reflection generates reflection prompt."""
        agent = PlanningAgent(enable_planning=False, enable_reflection=True)
        result = agent.create_reflection("tool1", {"arg": "value"}, "result content")
        assert "tool1" in result
        assert "result content" in result

    def test_planning_agent_format_final_error(self):
        """Test PlanningAgent format_final_error formats correctly."""
        agent = PlanningAgent(enable_planning=True, enable_reflection=True)
        result = agent.format_final_error("Final error", 3)
        assert "3" in result
        assert "Final error" in result


class TestModuleFunctions:
    """Tests for module-level functions."""

    def test_get_planning_agent_defaults(self):
        """Test get_planning_agent with defaults."""
        agent = get_planning_agent()
        assert agent.enable_planning is True
        assert agent.enable_reflection is True

    def test_get_planning_agent_custom(self):
        """Test get_planning_agent with custom values."""
        agent = get_planning_agent(enable_planning=False, enable_reflection=False)
        assert agent.enable_planning is False
        assert agent.enable_reflection is False

    def test_add_planning_to_prompt(self):
        """Test add_planning adds planning to prompt."""
        result = add_planning_to_system_prompt("Base prompt")
        assert "Base prompt" in result
        assert "Agent Guidelines" in result

    def test_add_planning_duplicate_check(self):
        """Test add_planning doesn't add when full prompt already present."""
        from agent_loop import PLANNING_PROMPT

        prompt = "Base prompt\n\n" + PLANNING_PROMPT.strip()
        result = add_planning_to_system_prompt(prompt)
        assert result == prompt

    def test_add_planning_empty_prompt(self):
        """Test add_planning with empty prompt."""
        result = add_planning_to_system_prompt("")
        assert "Agent Guidelines" in result

    def test_add_planning_with_prompt_already_has_it(self):
        """Test add_planning doesn't duplicate when full prompt exists."""
        from agent_loop import PLANNING_PROMPT

        prompt_with_planning = "Base prompt\n\n" + PLANNING_PROMPT.strip()
        result = add_planning_to_system_prompt(prompt_with_planning)
        assert result == prompt_with_planning
