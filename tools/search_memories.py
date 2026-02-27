import os
import re
from pathlib import Path


def search_memories(query: str):
    """Search MEMORIES.md for a term."""
    ws = Path(os.getenv("MYCLAW_WORKSPACE", Path(__file__).parent.parent / "workspace"))
    mem_file = ws / "MEMORIES.md"
    if not mem_file.exists():
        return "MEMORIES.md not found."

    try:
        content = mem_file.read_text(encoding="utf-8")
        pattern = re.compile(f"(?i){re.escape(query)}", re.MULTILINE)
        matches = pattern.findall(content)
        if matches:
            lines = content.splitlines()
            result_lines = []
            for i, line in enumerate(lines):
                if re.search(f"(?i){re.escape(query)}", line):
                    result_lines.append(line)
            return "\n".join(result_lines) if result_lines else "\n".join(matches[:10])
        return f"No matches found for '{query}'."
    except Exception as e:
        return f"Error reading MEMORIES.md: {e}"
