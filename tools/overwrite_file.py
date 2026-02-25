from pathlib import Path

def overwrite_file(filepath: str, content: str):
    """Overwrite a file with new content."""
    p = Path(filepath)
    try:
        p.write_text(content, encoding="utf-8")
        return f"Successfully overwrote {filepath}."
    except Exception as e:
        return f"Error overwriting file {filepath}: {e}"
