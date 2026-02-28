"""Tool loading module for MyClaw.

Handles dynamic loading of tools from Python modules.
"""

import importlib.util
from pathlib import Path
from typing import Any, Optional

_t: Optional[list[dict[str, Any]]] = None
_tf: Optional[dict[str, Any]] = None
_td: Optional[Path] = None


def load_tools(
    project_root: Optional[Path] = None,
    workspace: Optional[Path] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load tools from tools.py modules.

    Searches for tools.py in project_root and workspace directories.
    Uses caching to avoid reloading on every call.

    Args:
        project_root: Path to the project root directory.
        workspace: Path to the workspace directory.

    Returns:
        Tuple of (tools list, tool functions dict).
        Tools are schema definitions for LLM function calling.
        Functions are the actual callable implementations.
    """
    global _t, _tf, _td

    dirs = [d for d in (project_root, workspace) if d]
    for d in dirs:
        if d == _td and _t is not None:
            return _t, _tf

        tools_file = d / "tools.py"
        if tools_file.exists():
            try:
                module = importlib.util.module_from_spec(
                    spec := importlib.util.spec_from_file_location("t", tools_file)
                )
                spec.loader.exec_module(module)
                _tf, _t, _td = (
                    getattr(module, "TOOL_FUNCTIONS", {}),
                    getattr(module, "TOOLS", []),
                    d,
                )
                return _t, _tf
            except Exception:
                pass

    return [], {}


def invalidate_cache() -> None:
    """Invalidate the tool cache.

    Forces tools to be reloaded on the next call to load_tools().
    """
    global _t, _tf, _td
    _t = _tf = _td = None
