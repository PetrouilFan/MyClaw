from pathlib import Path


def _is_safe_path(path: Path, base: Path) -> bool:
    try:
        resolved = path.resolve()
        return resolved.is_relative_to(base.resolve())
    except (ValueError, OSError):
        return False
