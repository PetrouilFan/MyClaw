"""Utility functions for MyClaw tools."""

from pathlib import Path


def _is_safe_path(path: Path, base: Path) -> bool:
    """Check if a path is safely within the base directory.

    Prevents directory traversal attacks.

    Args:
        path: The path to check.
        base: The base directory to restrict access to.

    Returns:
        True if path is within base, False otherwise.
    """
    try:
        resolved = path.resolve()
        return resolved.is_relative_to(base.resolve())
    except (ValueError, OSError):
        return False
