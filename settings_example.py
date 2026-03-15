"""Example settings for MyClaw.

Copy this file to settings.py and customize with your values.
DO NOT commit settings.py with real secrets - add it to .gitignore
"""

import os
from pathlib import Path

WS = Path(os.getenv("MYCLAW_WORKSPACE") or Path(__file__).parent / "workspace")
OLLAMA_MODEL = os.getenv("MYCLAW_MODEL", "hf.co/MaziyarPanahi/Qwen3-4B-Instruct-2507-GGUF:Q6_K")
OLLAMA_URL = os.getenv("MYCLAW_UPSTREAM", "http://localhost:11434")
MYCLAW_HOST = os.getenv("MYCLAW_HOST", "0.0.0.0")
MYCLAW_PORT = int(os.getenv("MYCLAW_PORT", "8080"))
MYCLAW_URL = f"http://127.0.0.1:{MYCLAW_PORT}"
MDS = ["SOUL.md", "PERSONALITY.md", "MEMORIES.md", "IDENTITY.md", "USER.md"]
SYSTEM_PROMPT = (
    """You are a helpful AI assistant. Use tools as needed to help the user efficiently."""
)
MYCLAW_API_KEY = os.getenv("MYCLAW_API_KEY", "")
MAX_TOOL_CALLS = int(os.getenv("MYCLAW_MAX_TOOL_CALLS", "100"))
MAX_PAYLOAD_SIZE = int(os.getenv("MYCLAW_MAX_PAYLOAD_SIZE", str(10 * 1024 * 1024)))
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHECK_UPSTREAM = os.getenv("MYCLAW_CHECK_UPSTREAM", "").lower() in ("1", "true", "yes")
MAX_COMMAND_DURATION = int(os.getenv("MYCLAW_MAX_COMMAND_DURATION", "60"))
ALLOWED_API_KEYS = (
    os.getenv("MYCLAW_ALLOWED_API_KEYS", "").split(",")
    if os.getenv("MYCLAW_ALLOWED_API_KEYS")
    else []
)
SESSION_ENABLED = os.getenv("MYCLAW_SESSION_ENABLED", "true").lower() in ("1", "true", "yes")
SESSION_STORAGE_PATH = (
    Path(os.getenv("MYCLAW_SESSION_STORAGE_PATH", ""))
    if os.getenv("MYCLAW_SESSION_STORAGE_PATH")
    else WS / "sessions"
)
SESSION_TOKEN_BUDGET = int(os.getenv("MYCLAW_SESSION_TOKEN_BUDGET", "100000"))
SESSION_TTL_DAYS = int(os.getenv("MYCLAW_SESSION_TTL_DAYS", "30"))
STATELESS_MODE = os.getenv("MYCLAW_STATELESS_MODE", "false").lower() in ("1", "true", "yes")
MAX_MEMORIES = int(os.getenv("MYCLAW_MAX_MEMORIES", "50"))
ENABLE_SELECTIVE_MEMORY = os.getenv("MYCLAW_ENABLE_SELECTIVE_MEMORY", "false").lower() in (
    "1",
    "true",
    "yes",
)
ENABLE_DYNAMIC_TOOLS = os.getenv("MYCLAW_ENABLE_DYNAMIC_TOOLS", "true").lower() in (
    "1",
    "true",
    "yes",
)
MAX_TOOLS = int(os.getenv("MYCLAW_MAX_TOOLS", "20"))
ENABLE_PLANNING = os.getenv("MYCLAW_ENABLE_PLANNING", "false").lower() in ("1", "true", "yes")
ENABLE_REFLECTION = os.getenv("MYCLAW_ENABLE_REFLECTION", "false").lower() in ("1", "true", "yes")
TOOL_MAX_RETRIES = int(os.getenv("MYCLAW_TOOL_MAX_RETRIES", "3"))
SUBAGENT_MAX_AGENTS = int(os.getenv("MYCLAW_SUBAGENT_MAX_AGENTS", "10"))
SUBAGENT_MAX_DEPTH = int(os.getenv("MYCLAW_SUBAGENT_MAX_DEPTH", "3"))
SUBAGENT_TIMEOUT = int(os.getenv("MYCLAW_SUBAGENT_TIMEOUT", "300"))
ENABLE_AGENT_TOOLS = os.getenv("MYCLAW_ENABLE_AGENT_TOOLS", "true").lower() in ("1", "true", "yes")
ALLOWED_ORIGINS = (
    os.getenv("MYCLAW_ALLOWED_ORIGINS", "*").split(",")
    if os.getenv("MYCLAW_ALLOWED_ORIGINS")
    else ["*"]
)

# OpenCode integration settings
OPENCODE_PORT = int(os.getenv("OPENCODE_PORT", "4096"))
OPENCODE_PROJECT_PATH = os.getenv("OPENCODE_PROJECT_PATH", "")
