import importlib.util
from pathlib import Path
from typing import Optional

_t: Optional[list] = None
_tf: Optional[dict] = None
_td: Optional[Path] = None


def load_tools(project_root: Optional[Path] = None, workspace: Optional[Path] = None):
    global _t, _tf, _td
    dirs = [d for d in (project_root, workspace) if d]
    for d in dirs:
        if d == _td and _t is not None:
            return _t, _tf
        p = d / "tools.py"
        if p.exists():
            try:
                m = importlib.util.module_from_spec(
                    s := importlib.util.spec_from_file_location("t", p)
                )
                s.loader.exec_module(m)
                _tf, _t, _td = (
                    getattr(m, "TOOL_FUNCTIONS", {}),
                    getattr(m, "TOOLS", []),
                    d,
                )
                return _t, _tf
            except Exception:
                pass
    return [], {}


def invalidate_cache():
    global _t, _tf, _td
    _t = _tf = _td = None
