"""Session management for MyClaw.

Handles conversation history with file-based storage.
"""

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from token_budget import estimate_tokens


class SessionManager:
    """Manages conversation history with file-based storage."""

    def __init__(
        self,
        storage_dir: Path,
        token_budget: int = 28000,
        ttl_days: Optional[int] = None,
    ):
        self.storage_dir = storage_dir
        self.token_budget = token_budget
        self.ttl_days = ttl_days
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, session_id: str) -> Path:
        """Get the file path for a session."""
        return self.storage_dir / f"{session_id}.json"

    def generate_session_id(self, ip: str = "", user_agent: str = "") -> str:
        """Generate a session ID from IP and user agent, or create new UUID."""
        if ip or user_agent:
            data = f"{ip}:{user_agent}".encode()
            return hashlib.sha256(data).hexdigest()[:16]
        return uuid.uuid4().hex[:16]

    def load_session(self, session_id: str) -> list[dict]:
        """Load conversation history for a session.

        Returns empty list if session doesn't exist.
        """
        path = self._get_session_path(session_id)
        if not path.exists():
            return []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("messages", [])
        except (json.JSONDecodeError, IOError):
            return []

    def save_session(self, session_id: str, messages: list[dict]) -> None:
        """Save conversation history for a session."""
        path = self._get_session_path(session_id)
        data = {
            "session_id": session_id,
            "updated_at": datetime.now().isoformat(),
            "messages": messages,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def truncate_by_token_budget(
        self,
        messages: list[dict],
        system_prompt: str = "",
        tools: list = None,
    ) -> list[dict]:
        """Truncate messages to fit within token budget.

        Keeps most recent messages, removes oldest until under budget.
        """
        tools = tools or []

        reserved = estimate_tokens(system_prompt)
        reserved += sum(estimate_tokens(json.dumps(t)) for t in tools)
        reserved += 2000  # Reserve for response

        available = self.token_budget - reserved
        if available < 500:
            return []

        result = []
        current_tokens = 0

        for msg in reversed(messages):
            msg_tokens = estimate_tokens(json.dumps(msg))
            if current_tokens + msg_tokens > available:
                break
            result.insert(0, msg)
            current_tokens += msg_tokens

        return result

    def cleanup_old_sessions(self) -> int:
        """Remove sessions older than TTL (if configured)."""
        if not self.ttl_days:
            return 0

        removed = 0
        cutoff = datetime.now().timestamp() - (self.ttl_days * 86400)

        for path in self.storage_dir.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                pass

        return removed


_session_manager: Optional[SessionManager] = None


def get_session_manager(
    storage_dir: Path = None,
    token_budget: int = 28000,
    ttl_days: Optional[int] = None,
) -> SessionManager:
    """Get or create the global session manager instance."""
    global _session_manager

    if _session_manager is None:
        if storage_dir is None:
            from settings import WS

            storage_dir = WS / "sessions"

        _session_manager = SessionManager(
            storage_dir=storage_dir,
            token_budget=token_budget,
            ttl_days=ttl_days,
        )

    return _session_manager


def reset_session_manager() -> None:
    """Reset the session manager (useful for testing)."""
    global _session_manager
    _session_manager = None
