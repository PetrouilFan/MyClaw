import os
from pathlib import Path
from tools._utils import _is_safe_path

WS = Path(os.getenv("MYCLAW_WORKSPACE", Path(__file__).parent.parent / "workspace"))


def append_to_file(filepath: str, content: str, base_dir: str = None):
    base = Path(base_dir) if base_dir else WS
    p = (base / filepath).resolve()
    if not _is_safe_path(p, base):
        return f"Error: Access denied. Path must be within {base}"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully appended to {p}."
    except Exception as e:
        return f"Error appending to file {p}: {e}"
