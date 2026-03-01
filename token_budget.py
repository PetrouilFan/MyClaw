"""Token counting utilities for MyClaw.

Provides rough token estimation and tiktoken-based counting.
"""

import json
import re
from typing import Optional

_tiktoken_encoder: Optional[object] = None


def _get_tiktoken_encoder() -> Optional[object]:
    """Get or initialize tiktoken encoder."""
    global _tiktoken_encoder

    if _tiktoken_encoder is None:
        try:
            import tiktoken

            _tiktoken_encoder = tiktoken.get_encoding("cl100k_base")
        except ImportError:
            pass

    return _tiktoken_encoder


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
    """Use tiktoken for precise counting, fall back to estimate.

    Requires: pip install tiktoken
    """
    enc = _get_tiktoken_encoder()
    if enc is not None:
        return len(enc.encode(text))
    return estimate_tokens(text)


def get_tokenizer_for_model(model: str):
    """Get appropriate tokenizer for a specific model.

    Args:
        model: Model name (e.g., 'gpt-4', 'qwen', 'llama')

    Returns:
        Tokenizer function
    """
    enc = _get_tiktoken_encoder()

    if enc is not None:
        model_lower = model.lower()
        try:
            import tiktoken

            if "qwen" in model_lower:
                try:
                    return tiktoken.get_encoding("cl100k_base")
                except ImportError:
                    pass

            if "gpt" in model_lower:
                if "4" in model_lower:
                    return tiktoken.get_encoding("cl100k_base")
                return tiktoken.get_encoding("p50k_base")

            if "llama" in model_lower or "mistral" in model_lower:
                try:
                    return tiktoken.get_encoding("cc100")
                except ImportError:
                    pass
        except ImportError:
            pass

    return estimate_tokens


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
