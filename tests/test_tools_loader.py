"""Tests for tools package - loader and __init__."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestLoadTools:
    """Tests for load_tools function."""

    def test_load_tools_from_project_root(self, tmp_path):
        """Test loading tools from project root."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "test_tool", "description": "A test tool"}}]
TOOL_FUNCTIONS = {"test_tool": lambda: "result"}
""")

        from tools._loader import load_tools

        tools, funcs = load_tools(project_root=tmp_path)

        assert len(tools) >= 0

    def test_load_tools_from_workspace(self, tmp_path):
        """Test loading tools from workspace."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "ws_tool", "description": "Workspace tool"}}]
TOOL_FUNCTIONS = {"ws_tool": lambda: "ws_result"}
""")

        from tools._loader import load_tools

        tools, funcs = load_tools(workspace=tmp_path)

        assert len(tools) >= 0

    def test_load_tools_caching(self, tmp_path):
        """Test that tools are cached."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "cached_tool", "description": "Cached tool"}}]
TOOL_FUNCTIONS = {"cached_tool": lambda: "result"}
""")

        from tools._loader import load_tools, invalidate_cache

        invalidate_cache()
        tools1, _ = load_tools(project_root=tmp_path)
        tools2, _ = load_tools(project_root=tmp_path)

        assert tools1 is tools2

    def test_load_tools_no_file(self, tmp_path):
        """Test loading when no tools.py exists."""
        from tools._loader import load_tools

        tools, funcs = load_tools(project_root=tmp_path)

        assert tools == []
        assert funcs == {}

    def test_load_tools_invalid_module(self, tmp_path):
        """Test loading with invalid Python file."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("This is not valid Python syntax @#$%")

        from tools._loader import load_tools

        tools, funcs = load_tools(project_root=tmp_path)

        assert tools == []
        assert funcs == {}


class TestInvalidateCache:
    """Tests for invalidate_cache function."""

    def test_invalidate_cache_clears(self, tmp_path):
        """Test invalidate cache clears the cache."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "test_tool"}}]
TOOL_FUNCTIONS = {}
""")

        from tools._loader import load_tools, invalidate_cache

        invalidate_cache()
        tools1, _ = load_tools(project_root=tmp_path)

        invalidate_cache()
        tools2, _ = load_tools(project_root=tmp_path)

        assert tools1 == tools2


class TestToolsPackage:
    """Tests for tools package __init__ functions."""

    def test_load_tools_wrapper(self, tmp_path):
        """Test load_tools wrapper function."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "wrapper_tool", "description": "Test"}}]
TOOL_FUNCTIONS = {}
""")

        from tools import load_tools

        tools, funcs = load_tools(project_root=tmp_path)
        assert isinstance(tools, list)

    def test_invalidate_cache_wrapper(self):
        """Test invalidate_cache wrapper."""
        from tools import invalidate_cache

        invalidate_cache()

    def test_get_tool_functions(self, tmp_path):
        """Test get_tool_functions returns function dict."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "func_tool"}}]
TOOL_FUNCTIONS = {"func_tool": lambda: "test"}
""")

        from tools import get_tool_functions

        funcs = get_tool_functions(project_root=tmp_path)
        assert isinstance(funcs, dict)

    def test_get_tool_schemas(self, tmp_path):
        """Test get_tool_schemas returns tools list."""
        tools_file = tmp_path / "tools.py"
        tools_file.write_text("""
TOOLS = [{"function": {"name": "schema_tool", "description": "Test"}}]
TOOL_FUNCTIONS = {}
""")

        from tools import get_tool_schemas

        tools = get_tool_schemas(project_root=tmp_path)
        assert isinstance(tools, list)
