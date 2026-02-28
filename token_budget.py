"""Token counting utilities for MyClaw.

Provides rough token estimation and optional tiktoken-based counting.
"""

import json
import re


def estimate_tokens(text: str) -> int:
    """Estimate token count using a simple heuristic.

    Average tokens is ~4 characters per token for English text.
    This is a rough approximation but fast and no dependencies.

    For more accurate counting, install tiktoken:
        pip install tiktoken
    """
    if not text:
        return 0

    chars = len(text)
    tokens = chars // 4

    tokens += len(re.findall(r"\S+", text)) // 2

    return max(1, tokens)


def estimate_tokens_precise(text: str) -> int:
    """Try to use tiktoken for precise counting, fall back to estimate.

    Requires: pip install tiktoken
    """
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except ImportError:
        return estimate_tokens(text)


def count_messages_tokens(messages: list[dict]) -> int:
    """Count total tokens in a list of messages."""
    total = 0
    for msg in messages:
        total += estimate_tokens(json.dumps(msg))
    return total


def count_tools_tokens(tools: list[dict]) -> int:
    """Count tokens for a list of tool definitions."""
    if not tools:
        return 0
    return estimate_tokens(json.dumps(tools))


def calculate_available_for_history(
    total_budget: int,
    system_prompt: str,
    tools: list[dict],
    reserved: int = 2000,
) -> int:
    """Calculate how many tokens are available for history.

    Args:
        total_budget: Total context window (e.g., 28000)
        system_prompt: System prompt content
        tools: List of tool definitions
        reserved: Tokens to reserve for response (default 2000)

    Returns:
        Available tokens for conversation history
    """
    used = estimate_tokens(system_prompt)
    used += count_tools_tokens(tools)
    used += reserved

    return max(0, total_budget - used)


def truncate_messages(
    messages: list[dict],
    max_tokens: int,
) -> list[dict]:
    """Truncate messages to fit within token budget.

    Keeps most recent messages, removes oldest first.
    """
    if not messages:
        return []

    result = []
    current_tokens = 0

    for msg in reversed(messages):
        msg_tokens = estimate_tokens(json.dumps(msg))
        if current_tokens + msg_tokens > max_tokens:
            break
        result.insert(0, msg)
        current_tokens += msg_tokens

    return result
