import os
from pathlib import Path
from typing import Optional

from tools._utils import _is_safe_path

WS = Path(os.getenv("MYCLAW_WORKSPACE", Path(__file__).parent.parent / "workspace"))


def overwrite_file(filepath: str, content: str, base_dir: Optional[str] = None) -> str:
    """Overwrite a file with new content.

    Args:
        filepath: Path to the file to overwrite.
        content: New content to write.
        base_dir: Base directory for resolving relative paths.

    Returns:
        Success or error message.
    """
    base = Path(base_dir) if base_dir else WS
    p = (base / filepath).resolve()
    if not _is_safe_path(p, base):
        return f"Error: Access denied. Path must be within {base}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Successfully overwrote {p}."
    except Exception as e:
        return f"Error overwriting file {p}: {e}"
