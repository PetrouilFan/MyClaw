"""MyClaw tools package.

Provides unified tool loading and management for MyClaw.
"""

from pathlib import Path
from typing import Any

from tools._loader import invalidate_cache as _invalidate_cache
from tools._loader import load_tools as _load_tools

__all__ = [
    "load_tools",
    "invalidate_cache",
    "get_tool_functions",
    "get_tool_schemas",
]


def load_tools(
    project_root: Path | None = None,
    workspace: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load tools from the project root and/or workspace.

    Args:
        project_root: Path to the project root directory.
        workspace: Path to the workspace directory.

    Returns:
        Tuple of (tools list, tool functions dict).
    """
    return _load_tools(project_root=project_root, workspace=workspace)


def invalidate_cache() -> None:
    """Invalidate the tool cache, forcing a reload on next access."""
    _invalidate_cache()


def get_tool_functions(
    project_root: Path | None = None,
    workspace: Path | None = None,
) -> dict[str, Any]:
    """Get tool function callables.

    Args:
        project_root: Path to the project root directory.
        workspace: Path to the workspace directory.

    Returns:
        Dict mapping tool names to callables.
    """
    _, funcs = load_tools(project_root=project_root, workspace=workspace)
    return funcs


def get_tool_schemas(
    project_root: Path | None = None,
    workspace: Path | None = None,
) -> list[dict[str, Any]]:
    """Get tool schema definitions for LLM function calling.

    Args:
        project_root: Path to the project root directory.
        workspace: Path to the workspace directory.

    Returns:
        List of tool schema dicts.
    """
    tools, _ = load_tools(project_root=project_root, workspace=workspace)
    return tools
