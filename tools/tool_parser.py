import json
import re
from typing import Any


def extract_tool_calls(message: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool calls from an LLM response message.

    Handles multiple formats:
    - Standard OpenAI tool_calls format
    - <tool_call>...</tool_call> XML blocks
    - JSON-like {name: ..., arguments: ...} blocks

    Args:
        message: The message dict from the LLM response, containing
                 content, reasoning, and/or tool_calls fields.

    Returns:
        List of tool call dicts in standardized format:
        [{"function": {"name": "...", "arguments": {...}}}, ...]
    """
    tool_calls = message.get("tool_calls", [])
    if tool_calls:
        return tool_calls

    combined = (
        (message.get("reasoning", "") or "") + "\n" + (message.get("content", "") or "")
    )
    matches: list[str] = []

    xml_matches = re.findall(r"<tool_call>(.*?)</tool_call>", combined, re.DOTALL)
    for m in xml_matches:
        if m not in matches:
            matches.append(m)

    trailing_matches = re.findall(r"(.*?)\s*</tool_call>", combined, re.DOTALL)
    for m in trailing_matches:
        if m not in matches:
            matches.append(m)

    json_like = re.findall(
        r'\{[^}]*"name"\s*:\s*"[^"]+"[^}]*"arguments"\s*:\s*\{.*\}', combined
    )
    for m in json_like:
        if m not in matches:
            matches.append(m)

    for raw in matches:
        parsed = _try_parse_tool_call(raw)
        if parsed:
            tool_calls.append(parsed)

    return tool_calls


def _try_parse_tool_call(raw: str) -> dict[str, Any] | None:
    """Attempt to parse a raw string as a tool call.

    Tries multiple parsing strategies and returns the first successful match.
    """
    stripped = raw.strip()

    try:
        parsed = json.loads(stripped)
        name = parsed.get("name", "")
        args = parsed.get("arguments", {})
        if name:
            return {"function": {"name": name, "arguments": args}}
    except (json.JSONDecodeError, TypeError):
        pass

    fixed = stripped.replace("'", '"')
    try:
        parsed = json.loads(fixed)
        name = parsed.get("name", "")
        args = parsed.get("arguments", {})
        if name:
            return {"function": {"name": name, "arguments": args}}
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        if fixed.count("}") > fixed.count("{"):
            fixed = "{" + fixed.rsplit("}", 1)[0] + "}"
        fixed = re.sub(r",[^}]*$", "", fixed)
        parsed = json.loads(fixed)
        name = parsed.get("name", "")
        args = parsed.get("arguments", {})
        if name:
            return {"function": {"name": name, "arguments": args}}
    except (json.JSONDecodeError, TypeError):
        pass

    return None


def clean_content(message: dict[str, Any]) -> str:
    """Extract and clean final content from an LLM response.

    Removes tool_call blocks from reasoning/content and returns
    the final text response.
    """
    content = message.get("content", "") or ""
    reasoning = message.get("reasoning", "") or ""
    combined = reasoning + "\n" + content

    if not combined:
        return ""

    cleaned = re.sub(
        r"<tool_call>.*?</tool_call>",
        "",
        combined.strip(),
        flags=re.DOTALL,
    )
    cleaned = re.sub(r"</tool_call>\s*$", "", cleaned).strip()

    if cleaned.startswith("<tool_call>") or (
        cleaned.startswith("{")
        and '"name":' in cleaned[:60]
        and '"arguments"' in cleaned
    ):
        return ""

    return cleaned
