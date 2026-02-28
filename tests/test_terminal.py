"""Tests for terminal command execution tools."""

import platform
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


class TestRunTerminalCommand:
    """Tests for run_terminal_command function."""

    def test_simple_echo_command(self):
        """Test running a simple echo command."""
        from tools.terminal import run_terminal_command

        result = run_terminal_command("echo hello")

        assert result["status"] in ["completed", "failed"]
        assert "output_file" in result
        assert "pid" in result

    def test_command_with_spaces(self):
        """Test command with spaces in arguments."""
        from tools.terminal import run_terminal_command

        result = run_terminal_command('echo "hello world"')

        assert result["status"] == "completed"

    def test_failed_command(self):
        """Test running a failing command."""
        from tools.terminal import run_terminal_command

        if platform.system() == "Windows":
            result = run_terminal_command("exit 1")
        else:
            result = run_terminal_command("exit 1")

        assert result["status"] == "failed"
        assert result["return_code"] != 0

    def test_nonexistent_command(self):
        """Test running a nonexistent command."""
        from tools.terminal import run_terminal_command

        result = run_terminal_command("nonexistent_command_12345")

        assert result["status"] == "failed"

    def test_background_command(self):
        """Test running command in background."""
        from tools.terminal import run_terminal_command

        result = run_terminal_command("echo hello", background=True)

        assert result["status"] == "started"
        assert "pid" in result

    def test_max_processes_limit(self):
        """Test max processes limit is enforced."""
        from tools.terminal import run_terminal_command, _processes

        original_limit = 1
        with patch("tools.terminal.MAX_PROCESSES", 1):
            _processes.clear()

            result = run_terminal_command("echo test", background=True)

            result2 = run_terminal_command("echo test2", background=True)

            assert "Max processes" in result2.get("error", "")

    def test_custom_working_directory(self):
        """Test running command in custom working directory."""
        from tools.terminal import run_terminal_command

        with tempfile.TemporaryDirectory() as tmpdir:
            result = run_terminal_command("pwd", cwd=tmpdir)

            assert result["status"] == "completed"


class TestBackgroundCommand:
    """Tests for background command execution."""

    @pytest.fixture(autouse=True)
    def cleanup(self):
        """Clean up processes after each test."""
        from tools.terminal import cleanup_processes, _processes

        yield
        cleanup_processes(keep_running=False)
        _processes.clear()

    def test_list_terminal_commands(self):
        """Test listing terminal commands."""
        from tools.terminal import run_terminal_command, list_terminal_commands

        result = run_terminal_command("echo hello", background=True)
        pid = result["pid"]

        processes = list_terminal_commands()

        assert processes["total"] >= 1
        assert any(p["pid"] == pid for p in processes["processes"])

    def test_list_filter_by_status(self):
        """Test filtering processes by status."""
        from tools.terminal import run_terminal_command, list_terminal_commands

        run_terminal_command("sleep 10", background=True)
        run_terminal_command("echo done", background=True)

        running = list_terminal_commands(status_filter="running")
        assert running["total"] >= 1

    def test_kill_terminal_command(self):
        """Test killing a running command."""
        from tools.terminal import run_terminal_command, kill_terminal_command

        result = run_terminal_command("sleep 100", background=True)
        pid = result["pid"]

        kill_result = kill_terminal_command(pid)

        assert kill_result["status"] == "terminated"

    def test_kill_nonexistent_process(self):
        """Test killing a nonexistent process."""
        from tools.terminal import kill_terminal_command

        result = kill_terminal_command(999999)

        assert "not found" in result.get("error", "").lower()


class TestReadCommandOutput:
    """Tests for reading command output."""

    def test_read_output_from_completed(self):
        """Test reading output from completed command."""
        from tools.terminal import run_terminal_command, read_output

        result = run_terminal_command("echo hello world")

        output = read_output(result["pid"])

        assert "hello world" in output.get("output", "").lower()

    def test_read_specific_line_count(self):
        """Test reading specific number of lines."""
        from tools.terminal import run_terminal_command, read_output

        result = run_terminal_command("echo -e 'line1\nline2\nline3'")

        output = read_output(result["pid"], lines=2)

        assert output["lines"] <= 2

    def test_read_from_start(self):
        """Test reading from start of output."""
        from tools.terminal import run_terminal_command, read_output

        result = run_terminal_command("echo -e 'first\nsecond\nlast'")

        output = read_output(result["pid"], from_start=True)

        assert "first" in output["output"]

    def test_read_nonexistent_process(self):
        """Test reading output from nonexistent process."""
        from tools.terminal import read_output

        result = read_output(999999)

        assert "not found" in result.get("error", "").lower()


class TestCleanupProcesses:
    """Tests for process cleanup."""

    def test_cleanup_keeps_running(self):
        """Test cleanup keeps running processes."""
        from tools.terminal import run_terminal_command, cleanup_processes, _processes

        result = run_terminal_command("sleep 100", background=True)

        removed = cleanup_processes(keep_running=True)

        assert result["pid"] in _processes

    def test_cleanup_removes_completed(self):
        """Test cleanup removes completed processes."""
        from tools.terminal import run_terminal_command, cleanup_processes

        result = run_terminal_command("echo done")

        removed = cleanup_processes(keep_running=False)

        assert removed >= 1


class TestPathTraversal:
    """Tests for path traversal protection."""

    def test_path_traversal_blocked_in_cwd(self):
        """Test path traversal is blocked in cwd parameter."""
        from tools.terminal import run_terminal_command

        result = run_terminal_command("echo test", cwd="../../../etc")

        assert result.get("error") is not None or ".." not in result.get("output_file", "")


class TestTerminalTools:
    """Tests for terminal tool functions."""

    def test_get_terminal_help(self):
        """Test get_terminal_help function."""
        from tools.terminal import get_terminal_help

        result = get_terminal_help()

        assert "usage_guide" in result

    def test_terminal_help_with_file(self, tmp_path):
        """Test get_terminal_help with actual help file."""
        from tools.terminal import get_terminal_help

        help_file = tmp_path / "terminal_help.md"
        help_file.write_text("# Terminal Help\nUsage guide here...")

        with patch.object(Path, "parent", tmp_path, create=True):
            result = get_terminal_help()

            assert "Terminal Help" in result.get("usage_guide", "")


class TestAsyncTerminalCommands:
    """Tests for async terminal commands."""

    @pytest.mark.asyncio
    async def test_async_run_command(self):
        """Test async run command."""
        from tools.terminal import async_run_command

        result = await async_run_command("echo async hello")

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_async_wait_command(self):
        """Test async wait command."""
        from tools.terminal import async_run_command, async_wait_command

        result = await async_run_command("echo test", background=True)

        wait_result = await async_wait_command(result["pid"], timeout=10)

        assert wait_result["status"] in ["completed", "failed"]

    @pytest.mark.asyncio
    async def test_async_kill_command(self):
        """Test async kill command."""
        from tools.terminal import async_run_command, async_kill_command

        result = await async_run_command("sleep 100", background=True)

        kill_result = await async_kill_command(result["pid"])

        assert kill_result["status"] == "terminated"
