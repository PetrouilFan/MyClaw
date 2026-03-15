"""Additional tests for terminal command execution tools."""

import tempfile
from pathlib import Path
from unittest.mock import patch



class TestTerminalValidation:
    """Tests for terminal command validation."""

    def test_is_command_allowed_no_restrictions(self):
        """Test command allowed when no restrictions."""
        with patch("tools.terminal.ALLOWED_COMMANDS", []):
            from tools.terminal import _is_command_allowed

            result, reason = _is_command_allowed("echo hello")
            assert result is True

    def test_is_command_allowed_with_list(self):
        """Test command allowed when in allowed list."""
        with patch("tools.terminal.ALLOWED_COMMANDS", ["echo", "ls", "pwd"]):
            from tools.terminal import _is_command_allowed

            result, reason = _is_command_allowed("echo hello")
            assert result is True

    def test_is_command_not_in_allowed_list(self):
        """Test command not allowed when not in list."""
        with patch("tools.terminal.ALLOWED_COMMANDS", ["ls", "pwd"]):
            from tools.terminal import _is_command_allowed

            result, reason = _is_command_allowed("echo hello")
            assert result is False

    def test_is_pattern_blocked_default(self):
        """Test default blocked patterns."""
        with patch("tools.terminal.BLOCKED_PATTERNS", ["rm -rf", "del /f"]):
            from tools.terminal import _is_pattern_blocked

            result, reason = _is_pattern_blocked("rm -rf /")
            assert result is True
            assert "rm -rf" in reason

    def test_is_pattern_blocked_clean(self):
        """Test clean command not blocked."""
        with patch("tools.terminal.BLOCKED_PATTERNS", ["rm -rf", "del /f"]):
            from tools.terminal import _is_pattern_blocked

            result, reason = _is_pattern_blocked("echo hello")
            assert result is False

    def test_validate_command_invalid(self):
        """Test validation rejects invalid commands."""
        with patch("tools.terminal.BLOCKED_PATTERNS", ["rm -rf"]):
            with patch("tools.terminal.ALLOWED_COMMANDS", []):
                from tools.terminal import _validate_command

                result, reason = _validate_command("rm -rf /")
                assert result is False


class TestTerminalOutput:
    """Tests for terminal output handling."""

    def test_cleanup_output_files(self):
        """Test cleanup output files."""
        from tools.terminal import cleanup_output_files

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test_output.txt"
            test_file.write_text("test content")

            with patch("tools.terminal.OUTPUT_DIR", Path(tmpdir)):
                removed = cleanup_output_files(max_age_hours=0)
                assert removed >= 0


class TestTerminalConstants:
    """Tests for terminal constants."""

    def test_max_processes_default(self):
        """Test default max processes."""
        from tools.terminal import MAX_PROCESSES

        assert MAX_PROCESSES == 1000

    def test_max_output_lines_default(self):
        """Test default max output lines."""
        from tools.terminal import MAX_OUTPUT_LINES

        assert MAX_OUTPUT_LINES == 2000


class TestTerminalHelp:
    """Tests for terminal help."""

    def test_get_terminal_help_content(self):
        """Test terminal help returns content."""
        from tools.terminal import get_terminal_help

        result = get_terminal_help()
        assert "usage_guide" in result


class TestTerminalWait:
    """Tests for wait terminal command."""

    def test_wait_nonexistent_process(self):
        """Test waiting for nonexistent process."""
        from tools.terminal import wait_terminal_command_sync as wait_terminal_command

        result = wait_terminal_command(999999)
        assert "error" in result or "not found" in result.get("error", "").lower()


class TestTerminalKill:
    """Tests for kill terminal command."""

    def test_kill_invalid_pid(self):
        """Test killing with invalid PID."""
        from tools.terminal import kill_terminal_command_sync as kill_terminal_command

        result = kill_terminal_command(0)
        assert "error" in result or "not found" in result.get("error", "").lower()
