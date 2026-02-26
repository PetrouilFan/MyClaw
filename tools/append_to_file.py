from pathlib import Path


def _is_safe_path(path: Path, base: Path) -> bool:
    try:
        resolved = path.resolve()
        return resolved.is_relative_to(base.resolve())
    except (ValueError, OSError):
        return False


def append_to_file(filepath: str, content: str, base_dir: str = None):
    """Append content to a file."""
    base = Path(base_dir) if base_dir else Path.cwd()
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
