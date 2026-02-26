from pathlib import Path
from tools._utils import _is_safe_path


def read_file(filepath: str, base_dir: str = None):
    base = Path(base_dir) if base_dir else Path.cwd()
    p = (base / filepath).resolve()
    if not _is_safe_path(p, base):
        return f"Error: Access denied. Path must be within {base}"
    if not p.exists():
        return f"File {p} not found."
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file {p}: {e}"
