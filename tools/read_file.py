import os
from pathlib import Path
from typing import Optional

from tools._utils import _is_safe_path

WS = Path(os.getenv("MYCLAW_WORKSPACE", Path(__file__).parent.parent / "workspace"))


def read_file(filepath: str, base_dir: Optional[str] = None) -> str:
    """Read contents of a file.

    Args:
        filepath: Path to the file to read.
        base_dir: Base directory for resolving relative paths.

    Returns:
        File contents as string, or error message.
    """
    base = Path(base_dir) if base_dir else WS
    p = (base / filepath).resolve()
    if not _is_safe_path(p, base):
        return f"Error: Access denied. Path must be within {base}"
    if not p.exists():
        return f"File {p} not found."
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file {p}: {e}"
