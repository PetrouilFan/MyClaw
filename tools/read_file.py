from pathlib import Path

def read_file(filepath: str):
    """Read content from a file."""
    p = Path(filepath)
    if not p.exists():
        return f"File {filepath} not found."
    
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading file {filepath}: {e}"
