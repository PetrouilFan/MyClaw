"""Context builder for MyClaw.

Handles selective memory injection, dynamic tool selection, and context optimization.
"""

import re
from pathlib import Path
from typing import Optional

from token_budget import estimate_tokens


class ContextBuilder:
    """Builds optimized context for LLM requests."""

    def __init__(
        self,
        workspace: Path,
        token_budget: int = 28000,
        max_memories: int = 5,
    ):
        self.workspace = workspace
        self.token_budget = token_budget
        self.max_memories = max_memories

    def load_md_file(self, filename: str) -> Optional[str]:
        """Load a markdown file from workspace."""
        path = self.workspace / filename
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except Exception:
                pass
        return None

    def get_identity(self) -> str:
        """Get identity (SOUL.md)."""
        content = self.load_md_file("SOUL.md")
        if content:
            return self._compress_md(content, max_tokens=300)
        return ""

    def get_personality(self) -> str:
        """Get personality (PERSONALITY.md)."""
        content = self.load_md_file("PERSONALITY.md")
        if content:
            return self._compress_md(content, max_tokens=500)
        return ""

    def get_user_context(self) -> str:
        """Get user context (USER.md)."""
        content = self.load_md_file("USER.md")
        if content:
            return self._compress_md(content, max_tokens=300)
        return ""

    def get_memories(self, query: str = "", max_tokens: int = 500) -> str:
        """Get relevant memories based on query.

        Uses keyword matching to find relevant memories.
        Falls back to recent memories if no query match.
        """
        content = self.load_md_file("MEMORIES.md")
        if not content:
            return ""

        lines = content.split("\n")

        if query:
            keywords = self._extract_keywords(query)
            relevant_lines = []

            for i, line in enumerate(lines):
                line_lower = line.lower()
                if any(kw in line_lower for kw in keywords):
                    relevant_lines.append((i, line))

            if relevant_lines:
                result = "\n".join(line for _, line in relevant_lines[: self.max_memories])
                if estimate_tokens(result) <= max_tokens:
                    return result

        recent = [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        if recent:
            result = "\n".join(recent[-self.max_memories :])
            if estimate_tokens(result) <= max_tokens:
                return result

        return ""

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract keywords from text for memory matching."""
        words = re.findall(r"\b\w{3,}\b", text.lower())
        stop_words = {
            "the",
            "and",
            "for",
            "are",
            "but",
            "not",
            "you",
            "all",
            "can",
            "had",
            "her",
            "was",
            "one",
            "our",
            "out",
            "day",
            "get",
            "has",
            "him",
            "his",
            "how",
            "its",
            "may",
            "now",
            "old",
            "see",
            "than",
            "that",
            "this",
            "with",
            "have",
            "from",
            "they",
            "will",
            "would",
            "there",
            "their",
            "what",
            "about",
            "which",
            "when",
            "make",
            "like",
            "just",
            "know",
            "take",
            "into",
            "year",
            "your",
            "some",
            "could",
            "them",
            "other",
            "then",
            "look",
            "only",
            "come",
            "over",
            "such",
            "also",
            "back",
            "after",
            "use",
            "two",
            "how",
            "our",
            "first",
            "been",
            "call",
            "what",
            "system",
            "assistant",
            "user",
            "message",
            "hello",
            "hi",
        }
        return [w for w in words if w not in stop_words]

    def _compress_md(self, content: str, max_tokens: int = 500) -> str:
        """Compress markdown content to fit token budget."""
        if not content:
            return ""

        tokens = estimate_tokens(content)
        if tokens <= max_tokens:
            return content

        lines = content.split("\n")
        result = []
        current_tokens = 0

        for line in lines:
            line_tokens = estimate_tokens(line)
            if current_tokens + line_tokens > max_tokens:
                break
            result.append(line)
            current_tokens += line_tokens

        return "\n".join(result)

    def build_system_prompt(
        self,
        base_prompt: str = "You are a helpful AI assistant.",
        include_identity: bool = True,
        include_personality: bool = True,
        include_user: bool = True,
        include_memories: bool = True,
        query: str = "",
    ) -> str:
        """Build optimized system prompt with selective context."""
        parts = [base_prompt]

        if include_identity:
            identity = self.get_identity()
            if identity:
                parts.append(f"\n## Identity\n{identity}")

        if include_personality:
            personality = self.get_personality()
            if personality:
                parts.append(f"\n## Personality\n{personality}")

        if include_user:
            user_ctx = self.get_user_context()
            if user_ctx:
                parts.append(f"\n## User Context\n{user_ctx}")

        if include_memories:
            memories = self.get_memories(query=query, max_tokens=400)
            if memories:
                parts.append(f"\n## Relevant Memories\n{memories}")

        result = "\n".join(parts)

        if estimate_tokens(result) > 2000:
            result = self._compress_md(result, max_tokens=2000)

        return result

    def select_tools(
        self,
        all_tools: list[dict],
        query: str = "",
        conversation_history: list[dict] = None,
        max_tools: int = 10,
    ) -> list[dict]:
        """Select relevant tools based on query and conversation context."""
        if not all_tools:
            return []

        if not query and not conversation_history:
            return all_tools[:max_tools]

        conversation_history = conversation_history or []

        recent_messages = " ".join(m.get("content", "") for m in conversation_history[-5:])
        context = f"{query} {recent_messages}".lower()

        tool_keywords = {
            "terminal": ["run", "command", "execute", "shell", "bash", "terminal", "cmd"],
            "file_read": ["read", "file", "content", "view", "show", "cat", "open"],
            "file_write": ["write", "save", "create", "file", "append", "overwrite"],
            "time": ["time", "date", "clock", "now"],
            "memory": ["remember", "memory", "past", "previous", "earlier"],
        }

        scores = {}
        for tool in all_tools:
            tool_name = (tool.get("function") or {}).get("name", "").lower()
            scores[tool_name] = 0

            for category, keywords in tool_keywords.items():
                if category in tool_name:
                    for kw in keywords:
                        if kw in context:
                            scores[tool_name] += 2

        if conversation_history:
            for tool in all_tools:
                tool_name = (tool.get("function") or {}).get("name", "").lower()
                for msg in conversation_history[-3:]:
                    msg_content = msg.get("content", "").lower()
                    if tool_name.replace("_", " ") in msg_content:
                        scores[tool_name] = scores.get(tool_name, 0) + 1

        sorted_tools = sorted(
            all_tools,
            key=lambda t: scores.get((t.get("function") or {}).get("name", "").lower(), 0),
            reverse=True,
        )

        selected = []
        for tool in sorted_tools:
            tool_name = (tool.get("function") or {}).get("name", "").lower()
            if scores.get(tool_name, 0) > 0 or len(selected) < 3:
                selected.append(tool)
            if len(selected) >= max_tools:
                break

        if not selected:
            selected = all_tools[:max_tools]

        return selected


_context_builder: Optional[ContextBuilder] = None


def get_context_builder(
    workspace: Path = None,
    token_budget: int = 28000,
) -> ContextBuilder:
    """Get or create the global context builder instance."""
    global _context_builder

    if _context_builder is None:
        if workspace is None:
            from settings import WS

            workspace = WS

        _context_builder = ContextBuilder(
            workspace=workspace,
            token_budget=token_budget,
        )

    return _context_builder


def reset_context_builder() -> None:
    """Reset the context builder (useful for testing)."""
    global _context_builder
    _context_builder = None
