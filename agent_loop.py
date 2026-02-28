"""Agent loop improvements for MyClaw.

Adds planning, retry logic, and reflection for more reliable tool use.
"""

import json
from typing import Any


PLANNING_PROMPT = """## Agent Guidelines

Before executing tools, follow this reasoning process:

1. **Understand the Goal**: What is the user asking for?
2. **Plan**: What steps are needed? In what order?
3. **Execute**: Use the appropriate tools.
4. **Reflect**: Did the tool output make sense? If not, try a different approach.
5. **Confirm**: Provide a clear answer to the user.

### Tool Use Rules:
- Always validate tool arguments before calling
- If a tool fails, analyze the error and try an alternative approach
- For complex tasks, break them into smaller steps
- Check tool output before responding to the user

### Error Handling:
- Parse error messages carefully
- If a command fails, try to understand why
- Don't repeat the same failing command without modification
- Ask for clarification if needed

"""


PLANNING_XML_TEMPLATE = """<plan>
<goal>{goal}</goal>
<steps>
{steps}
</steps>
<reasoning>{reasoning}</reasoning>
</plan>"""

REFLECTION_PROMPT = """After each tool execution, consider:
1. Did the output match what I expected?
2. Do I need more information?
3. Should I try a different tool or approach?
4. Am I ready to answer the user's question?"""


class ToolRetry:
    """Manages retry logic for tool calls."""

    def __init__(self, max_retries: int = 2):
        self.max_retries = max_retries

    def should_retry(self, tool_name: str, attempt: int, error: str) -> bool:
        """Determine if a tool call should be retried."""
        if attempt >= self.max_retries:
            return False

        retryable_errors = [
            "timeout",
            "connection",
            "temporarily unavailable",
            "rate limit",
            "too many requests",
        ]

        error_lower = error.lower()
        return any(e in error_lower for e in retryable_errors)

    def get_retry_message(self, tool_name: str, attempt: int, error: str) -> str:
        """Generate a message about retrying."""
        return (
            f"Tool '{tool_name}' failed (attempt {attempt + 1}/{self.max_retries + 1}). "
            f"Error: {error}. "
            f"Consider trying a different approach or fixing the error."
        )


class ErrorFormatter:
    """Formats errors for the LLM to understand and respond to."""

    @staticmethod
    def format_tool_error(tool_name: str, error: str, args: dict = None) -> str:
        """Format a tool error for the LLM."""
        msg = f"Tool '{tool_name}' execution failed.\n"
        msg += f"Error: {error}\n"

        if args:
            msg += f"Arguments used: {json.dumps(args, indent=2)}\n"

        msg += "\nConsider:\n"
        msg += "- Checking if the arguments are correct\n"
        msg += "- Trying a different approach\n"
        msg += "- Using a different tool if this one isn't working\n"

        return msg

    @staticmethod
    def format_validation_error(tool_name: str, field: str, issue: str) -> str:
        """Format a validation error."""
        return (
            f"Validation error for tool '{tool_name}':\n"
            f"  Field: {field}\n"
            f"  Issue: {issue}\n"
            f"Please fix the arguments and try again."
        )

    @staticmethod
    def format_success(tool_name: str, result: Any, truncated: bool = False) -> str:
        """Format successful tool execution."""
        result_str = str(result)

        if truncated:
            result_str = result_str[:2000] + "\n[Output truncated...]"

        return f"Tool '{tool_name}' executed successfully:\n{result_str}"


class PlanningAgent:
    """Manages the planning and reflection process."""

    def __init__(self, enable_planning: bool = True, enable_reflection: bool = True):
        self.enable_planning = enable_planning
        self.enable_reflection = enable_reflection
        self.tool_retry = ToolRetry(max_retries=2)

    def create_plan(self, user_message: str, available_tools: list = None) -> str:
        """Create a plan based on user message."""
        if not self.enable_planning:
            return ""

        tools_desc = ""
        if available_tools:
            tool_names = [(t.get("function") or {}).get("name", "unknown") for t in available_tools]
            tools_desc = f"\nAvailable tools: {', '.join(tool_names)}"

        prompt = f"""Analyze this user request and create a plan:

User request: {user_message}
{tools_desc}

Respond with:
<plan>
<goal>What the user wants</goal>
<steps>
1. First step
2. Second step
3. etc.
</steps>
<reasoning>Your reasoning about how to approach this</reasoning>
</plan>

If no tools are needed, just respond normally."""

        return prompt

    def should_reflect(self, tool_result: str) -> bool:
        """Determine if reflection is needed based on tool result."""
        if not self.enable_reflection:
            return False

        reflection_triggers = [
            "error",
            "failed",
            "not found",
            "permission denied",
            "no such file",
            "command not found",
            "unexpected",
        ]

        result_lower = tool_result.lower()
        return any(t in result_lower for t in reflection_triggers)

    def create_reflection(self, tool_name: str, tool_args: dict, result: str) -> str:
        """Create a reflection prompt after tool execution."""
        prompt = f"""Tool '{tool_name}' was executed with arguments: {json.dumps(tool_args)}

Result: {result[:500]}

{REFLECTION_PROMPT}

Respond with your analysis and next steps, or provide the final answer to the user."""
        return prompt

    def format_final_error(self, error: str, attempts: int) -> str:
        """Format a final error after all retries exhausted."""
        return (
            f"After {attempts} attempts, the operation failed.\n"
            f"Final error: {error}\n\n"
            "I wasn't able to complete this task. "
            "You may need to:\n"
            "- Check the parameters\n"
            "- Try a different approach\n"
            "- Provide more information"
        )


def get_planning_agent(
    enable_planning: bool = True,
    enable_reflection: bool = True,
    max_retries: int = 2,
) -> PlanningAgent:
    """Get a planning agent instance."""
    return PlanningAgent(
        enable_planning=enable_planning,
        enable_reflection=enable_reflection,
    )


def add_planning_to_system_prompt(system_prompt: str) -> str:
    """Add planning instructions to system prompt."""
    if PLANNING_PROMPT.strip() in system_prompt:
        return system_prompt

    return system_prompt + "\n\n" + PLANNING_PROMPT
