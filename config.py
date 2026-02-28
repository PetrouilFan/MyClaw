"""Configuration management for MyClaw.

Uses Pydantic for environment variable validation and settings management.
"""

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class MyClawSettings(BaseSettings):
    """MyClaw application settings.

    All settings can be overridden via environment variables.
    """

    model_config = SettingsConfigDict(
        env_prefix="MYCLAW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    workspace: Path = Field(
        default=Path(__file__).parent / "workspace",
        description="Workspace directory for MyClaw files",
    )

    model: str = Field(
        default="hf.co/MaziyarPanahi/Qwen3-4B-Instruct-2507-GGUF:Q6_K",
        description="Ollama model to use",
    )

    upstream: str = Field(
        default="http://100.92.128.50:11434",
        description="Upstream Ollama API URL",
    )

    api_key: str = Field(
        default="",
        description="API key for authentication",
    )

    host: str = Field(
        default="0.0.0.0",
        description="Host to bind the server to",
    )

    port: int = Field(
        default=8080,
        description="Port to bind the server to",
    )

    max_tool_calls: int = Field(
        default=100,
        ge=1,
        le=1000,
        description="Maximum number of tool calls per request",
    )

    max_payload_size: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        description="Maximum payload size in bytes",
    )

    check_upstream: bool = Field(
        default=False,
        description="Check upstream health on each request",
    )

    telegram_bot_token: Optional[str] = Field(
        default=None,
        description="Telegram bot token (optional)",
    )

    max_history_length: int = Field(
        default=100,
        ge=10,
        le=1000,
        description="Maximum chat history length",
    )

    max_output_lines: int = Field(
        default=2000,
        ge=100,
        description="Maximum lines in terminal output",
    )

    max_processes: int = Field(
        default=1000,
        ge=1,
        description="Maximum concurrent processes",
    )

    allowed_commands: list[str] = Field(
        default_factory=lambda: [
            "git",
            "python",
            "npm",
            "node",
            "ls",
            "cat",
            "grep",
            "echo",
            "pwd",
            "cd",
            "mkdir",
            "rm",
            "cp",
            "mv",
            "find",
            "head",
            "tail",
            "wc",
            "curl",
            "wget",
            "tar",
            "zip",
            "unzip",
        ],
        description="Allowed terminal commands (whitelist)",
    )

    blocked_patterns: list[str] = Field(
        default_factory=lambda: [
            "rm -rf /",
            "curl | sh",
            "wget | sh",
            "; rm ",
            "&& rm ",
            "|| rm ",
            "> /etc/passwd",
            "> /etc/shadow",
            "chmod 777",
            "chown -R",
            "mkfs",
            "dd if=",
            ":(){:|:&};:",
        ],
        description="Blocked command patterns (security)",
    )

    max_command_duration: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Maximum command execution duration in seconds",
    )

    rate_limit_per_minute: int = Field(
        default=60,
        ge=1,
        description="Rate limit per minute for API endpoints",
    )

    allowed_api_keys: set[str] = Field(
        default_factory=set,
        description="Allowed API keys for authentication (comma-separated)",
    )


settings = MyClawSettings()
