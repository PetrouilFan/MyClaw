"""OpenCode tool for MyClaw agents.

Allows LLM agents to invoke OpenCode for coding tasks with full session management.
"""

import os
import subprocess
import time
import httpx
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("myclaw.opencode")

OPENCODE_PORT = int(os.getenv("OPENCODE_PORT", "4096"))
OPENCODE_PROJECT = os.getenv("OPENCODE_PROJECT_PATH", "")

_server_process: Optional[subprocess.Popen] = None
_server_url: Optional[str] = None


class _ServerManager:
    """Manages opencode serve lifecycle."""

    @staticmethod
    def is_running() -> bool:
        """Check if server is running."""
        global _server_process
        if _server_process is None:
            return False
        return _server_process.poll() is None

    @staticmethod
    def start(port: int = OPENCODE_PORT) -> str:
        """Start opencode serve and return URL."""
        global _server_process, _server_url

        if _ServerManager.is_running():
            return _server_url

        cmd = ["opencode", "serve", "--port", str(port)]
        logger.info("opencode_starting", port=port, cmd=" ".join(cmd))

        _server_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        _server_url = f"http://localhost:{port}"
        time.sleep(3)

        logger.info("opencode_started", url=_server_url)
        return _server_url

    @staticmethod
    def stop():
        """Stop opencode serve."""
        global _server_process, _server_url
        if _server_process:
            logger.info("opencode_stopping")
            _server_process.terminate()
            _server_process.wait(timeout=5)
            _server_process = None
            _server_url = None


class _OpenCodeClient:
    """HTTP client for opencode serve API."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(timeout=300)

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        resp = self._http.request(method, url, **kwargs)
        if resp.status_code >= 400:
            raise Exception(f"OpenCode API error: {resp.status_code} - {resp.text}")
        return resp.json() if resp.content else {}

    def list_sessions(self) -> list:
        """GET /session"""
        return self._request("GET", "/session") or []

    def create_session(self, project_path: str = None, title: str = None) -> dict:
        """POST /session"""
        body = {}
        if project_path:
            body["projectPath"] = project_path
        if title:
            body["title"] = title
        return self._request("POST", "/session", json=body)

    def send_prompt(self, session_id: str, query: str, model: str = None) -> dict:
        """POST /session/{id}/prompt"""
        body = {"query": query}
        if model:
            body["model"] = {"providerID": "openai", "modelID": model}
        return self._request("POST", f"/session/{session_id}/prompt", json=body)

    def get_session(self, session_id: str) -> dict:
        """GET /session/{id}"""
        return self._request("GET", f"/session/{session_id}")

    def end_session(self, session_id: str) -> dict:
        """DELETE /session/{id}"""
        return self._request("DELETE", f"/session/{session_id}")

    def close(self):
        self._http.close()


def opencode_chat(
    prompt: str,
    session_id: Optional[str] = None,
    project_path: Optional[str] = None,
) -> dict:
    """Send a prompt to OpenCode.

    Creates a new session if session_id is not provided.
    Continues existing session if session_id is given.
    """
    try:
        url = _ServerManager.start()
        client = _OpenCodeClient(url)

        if not project_path:
            from settings import WS

            project_path = str(WS)

        if not session_id:
            result = client.create_session(project_path=project_path)
            session_id = result.get("session", {}).get("id")
            if not session_id:
                return {"success": False, "error": "Failed to create session"}

        result = client.send_prompt(session_id, prompt)
        response = result.get("response", {}).get("content", "")

        return {
            "success": True,
            "response": response,
            "session_id": session_id,
            "status": "completed",
        }
    except Exception as e:
        logger.error("opencode_chat_error", error=str(e))
        return {"success": False, "error": str(e)}
    finally:
        client.close()


def opencode_list() -> dict:
    """List all OpenCode sessions."""
    try:
        url = _ServerManager.start()
        client = _OpenCodeClient(url)
        sessions = client.list_sessions()
        return {"success": True, "sessions": sessions}
    except Exception as e:
        logger.error("opencode_list_error", error=str(e))
        return {"success": False, "error": str(e)}


def opencode_end(session_id: str) -> dict:
    """End/terminate an OpenCode session."""
    try:
        url = _ServerManager.start()
        client = _OpenCodeClient(url)
        client.end_session(session_id)
        return {"success": True, "session_id": session_id, "status": "terminated"}
    except Exception as e:
        logger.error("opencode_end_error", error=str(e))
        return {"success": False, "error": str(e)}


def opencode_status() -> dict:
    """Get OpenCode server and session status."""
    running = _ServerManager.is_running()
    return {
        "server_running": running,
        "server_url": _server_url,
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "opencode_chat",
            "description": "Send a prompt to OpenCode AI coding agent. Creates a new session if no session_id provided, otherwise continues existing session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Prompt/query for OpenCode"},
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to continue (optional)",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "Project path (defaults to MyClaw workspace)",
                    },
                },
                "required": ["prompt"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencode_list",
            "description": "List all OpenCode sessions.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencode_end",
            "description": "End/terminate an OpenCode session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID to terminate"},
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "opencode_status",
            "description": "Get OpenCode server and session status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_FUNCTIONS = {
    "opencode_chat": opencode_chat,
    "opencode_list": opencode_list,
    "opencode_end": opencode_end,
    "opencode_status": opencode_status,
}
