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
        if d == _td and _t is not None and _tf is not None:
            return _t, _tf

        tools_file = d / "tools.py"
        if tools_file.exists():
            try:
                spec = importlib.util.spec_from_file_location("t", tools_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                _tf_val = getattr(module, "TOOL_FUNCTIONS", None)
                _t_val = getattr(module, "TOOLS", None)
                # Ensure values are not None
                if _tf_val is None:
                    _tf_val = {}
                if _t_val is None:
                    _t_val = []
                # Explicitly assert non-None for mypy
                assert _tf_val is not None
                assert _t_val is not None
                _tf = _tf_val
                _t = _t_val
                _td = d
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
