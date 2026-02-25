import os
from pathlib import Path

def search_memories(query: str):
    """Search MEMORIES.md for a term."""
    ws = Path(os.getenv("MYCLAW_WORKSPACE", Path.home()/"myclaw"))
    mem_file = ws / "MEMORIES.md"
    if not mem_file.exists():
        return "MEMORIES.md not found."
    
    try:
        lines = mem_file.read_text(encoding="utf-8").splitlines()
        matches = [line for line in lines if query.lower() in line.lower()]
        if matches:
            return "\n".join(matches)
        return f"No matches found for '{query}'."
    except Exception as e:
        return f"Error reading MEMORIES.md: {e}"
