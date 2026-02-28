"""Pytest configuration and shared fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    old_workspace = os.environ.get("MYCLAW_WORKSPACE")
    os.environ["MYCLAW_WORKSPACE"] = str(workspace)

    yield workspace

    if old_workspace:
        os.environ["MYCLAW_WORKSPACE"] = old_workspace
    else:
        os.environ.pop("MYCLAW_WORKSPACE", None)


@pytest.fixture
def mock_settings():
    """Mock settings for testing."""
    from unittest.mock import patch

    with patch("settings.WS", Path(tempfile.mkdtemp())):
        with patch("settings.OLLAMA_MODEL", "test-model"):
            with patch("settings.OLLAMA_URL", "http://localhost:11434"):
                with patch("settings.MYCLAW_API_KEY", "test-key"):
                    with patch("settings.MAX_TOOL_CALLS", 10):
                        with patch("settings.MAX_PAYLOAD_SIZE", 10 * 1024 * 1024):
                            yield
