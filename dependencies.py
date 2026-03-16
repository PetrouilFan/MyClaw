"""Dependency injection for MyClaw.

Provides FastAPI dependency injectors for all services and managers.
"""

from pathlib import Path
from typing import Tuple

from fastapi import Request

from session_manager import SessionManager
from agents.registry import AgentRegistry


def get_settings(request: Request):
    """Get application settings."""
    return request.app.state.settings


def get_tools(request: Request) -> Tuple[list, dict]:
    """Get loaded tools and tool functions."""
    return request.app.state.tools, request.app.state.tool_funcs


def get_session_manager(request: Request) -> SessionManager:
    """Get session manager instance."""
    return request.app.state.session_mgr


def get_agent_registry(request: Request) -> AgentRegistry:
    """Get agent registry instance."""
    return request.app.state.agent_registry


def get_http_client(request: Request):
    """Get HTTP client instance."""
    return request.app.state.http_client


def get_project_root(request: Request) -> Path:
    """Get project root path."""
    return request.app.state.project_root
