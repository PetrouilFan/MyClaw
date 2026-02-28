"""Tests for tool functions."""

import os
import tempfile
from pathlib import Path

from tools.get_time import get_time
from tools.read_file import read_file
from tools.append_to_file import append_to_file
from tools.overwrite_file import overwrite_file
from tools.search_memories import search_memories


class TestGetTime:
    """Tests for get_time function."""

    def test_returns_string(self):
        """Test get_time returns a string."""
        result = get_time()
        assert isinstance(result, str)

    def test_returns_iso_format(self):
        """Test result is in ISO format."""
        result = get_time()
        assert "T" in result


class TestReadFile:
    """Tests for read_file function."""

    def test_read_nonexistent_file(self):
        """Test reading non-existent file returns error."""
        result = read_file("nonexistent_file_12345.txt")
        assert "not found" in result.lower() or "error" in result.lower()

    def test_read_existing_file(self):
        """Test reading existing file."""
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            f.write("Hello, World!")
            temp_path = f.name

        try:
            result = read_file(temp_path, base_dir=os.path.dirname(temp_path))
            assert "Hello, World!" in result
        finally:
            os.unlink(temp_path)

    def test_path_traversal_blocked(self):
        """Test path traversal is blocked."""
        result = read_file("../../../etc/passwd")
        assert "Access denied" in result


class TestAppendToFile:
    """Tests for append_to_file function."""

    def test_append_creates_file(self):
        """Test appending creates new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_append.txt")
            result = append_to_file(filepath, "Hello", base_dir=tmpdir)
            assert "success" in result.lower()

    def test_append_adds_content(self):
        """Test appending actually adds content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_append.txt")
            append_to_file(filepath, "Hello", base_dir=tmpdir)
            append_to_file(filepath, " World!", base_dir=tmpdir)

            with open(filepath) as f:
                content = f.read()

            assert "Hello World!" == content

    def test_path_traversal_blocked(self):
        """Test path traversal is blocked."""
        result = append_to_file("../../../etc/passwd", "malicious")
        assert "Access denied" in result


class TestOverwriteFile:
    """Tests for overwrite_file function."""

    def test_overwrite_creates_file(self):
        """Test overwriting creates new file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_overwrite.txt")
            result = overwrite_file(filepath, "Hello", base_dir=tmpdir)
            assert "success" in result.lower()

    def test_overwrite_replaces_content(self):
        """Test overwriting replaces content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = os.path.join(tmpdir, "test_overwrite.txt")
            overwrite_file(filepath, "Hello", base_dir=tmpdir)
            overwrite_file(filepath, "World", base_dir=tmpdir)

            with open(filepath) as f:
                content = f.read()

            assert content == "World"

    def test_path_traversal_blocked(self):
        """Test path traversal is blocked."""
        result = overwrite_file("../../../etc/passwd", "malicious")
        assert "Access denied" in result


class TestSearchMemories:
    """Tests for search_memories function."""

    def test_no_memories_file(self):
        """Test when MEMORIES.md doesn't exist."""
        original_workspace = os.environ.get("MYCLAW_WORKSPACE")
        os.environ["MYCLAW_WORKSPACE"] = "/nonexistent/path"

        result = search_memories("test")

        if original_workspace:
            os.environ["MYCLAW_WORKSPACE"] = original_workspace
        else:
            os.environ.pop("MYCLAW_WORKSPACE", None)

        assert "not found" in result.lower()

    def test_no_matches(self):
        """Test search with no matches."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_file = Path(tmpdir) / "MEMORIES.md"
            mem_file.write_text("Some content without the search term")

            original_workspace = os.environ.get("MYCLAW_WORKSPACE")
            os.environ["MYCLAW_WORKSPACE"] = tmpdir

            result = search_memories("xyz123")

            if original_workspace:
                os.environ["MYCLAW_WORKSPACE"] = original_workspace
            else:
                os.environ.pop("MYCLAW_WORKSPACE", None)

            assert "no match" in result.lower()

    def test_finds_match(self):
        """Test search finds matching content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mem_file = Path(tmpdir) / "MEMORIES.md"
            mem_file.write_text("Important: remember to buy milk")

            original_workspace = os.environ.get("MYCLAW_WORKSPACE")
            os.environ["MYCLAW_WORKSPACE"] = tmpdir

            result = search_memories("milk")

            if original_workspace:
                os.environ["MYCLAW_WORKSPACE"] = original_workspace
            else:
                os.environ.pop("MYCLAW_WORKSPACE", None)

            assert "milk" in result.lower()
