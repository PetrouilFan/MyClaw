"""Tests for configuration module."""

import os

import pytest


class TestConfig:
    """Tests for Pydantic configuration."""

    def test_default_values(self):
        """Test default configuration values."""
        from config import MyClawSettings

        settings = MyClawSettings()
        assert settings.workspace.name == "workspace"
        assert settings.port == 8080
        assert settings.max_tool_calls == 100

    def test_env_override(self):
        """Test environment variable overrides."""
        os.environ["MYCLAW_PORT"] = "9000"
        os.environ["MYCLAW_MAX_TOOL_CALLS"] = "50"

        from config import MyClawSettings

        settings = MyClawSettings()

        assert settings.port == 9000
        assert settings.max_tool_calls == 50

        os.environ.pop("MYCLAW_PORT", None)
        os.environ.pop("MYCLAW_MAX_TOOL_CALLS", None)

    def test_workspace_from_env(self):
        """Test workspace can be set via env var."""
        os.environ["MYCLAW_WORKSPACE"] = "/custom/workspace"

        from config import MyClawSettings

        settings = MyClawSettings()

        assert "custom" in str(settings.workspace)

        os.environ.pop("MYCLAW_WORKSPACE", None)

    def test_validation_limits(self):
        """Test that validation works for constrained values."""
        from config import MyClawSettings

        with pytest.raises(ValueError):
            MyClawSettings(max_tool_calls=0)

        with pytest.raises(ValueError):
            MyClawSettings(max_tool_calls=2000)

    def test_settings_singleton(self):
        """Test settings singleton works."""
        from config import settings

        assert settings is not None
        assert settings.port > 0
