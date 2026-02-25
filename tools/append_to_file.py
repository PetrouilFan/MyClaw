from pathlib import Path

def append_to_file(filepath: str, content: str):
    """Append content to a file."""
    p = Path(filepath)
    try:
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully appended to {filepath}."
    except Exception as e:
        return f"Error appending to file {filepath}: {e}"
