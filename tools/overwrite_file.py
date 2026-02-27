import os
from pathlib import Path
from tools._utils import _is_safe_path

WS = Path(os.getenv("MYCLAW_WORKSPACE", Path(__file__).parent.parent / "workspace"))


def overwrite_file(filepath: str, content: str, base_dir: str = None):
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
