"""Tests for file_write tool (FastMCP)."""
import pytest
from pathlib import Path

from fastmcp import FastMCP
from aden_tools.tools.file_write_tool import register_tools


@pytest.fixture
def file_write_fn(mcp: FastMCP):
    """Register and return the file_write tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["file_write"].fn


class TestFileWriteTool:
    """Tests for file_write tool."""

    def test_write_creates_new_file(self, file_write_fn, tmp_path: Path):
        """Writing to a new file creates it with content."""
        new_file = tmp_path / "new.txt"

        result = file_write_fn(file_path=str(new_file), content="Hello, World!")

        assert "error" not in result
        assert result["created"] is True
        assert result["name"] == "new.txt"
        assert new_file.read_text() == "Hello, World!"

    def test_write_overwrites_existing(self, file_write_fn, tmp_path: Path):
        """Writing to existing file overwrites by default."""
        existing = tmp_path / "existing.txt"
        existing.write_text("old content")

        result = file_write_fn(file_path=str(existing), content="new content")

        assert "error" not in result
        assert result["created"] is False
        assert result["previous_size"] is not None
        assert existing.read_text() == "new content"

    def test_write_appends_to_existing(self, file_write_fn, tmp_path: Path):
        """Writing with mode='append' adds to existing content."""
        existing = tmp_path / "existing.txt"
        existing.write_text("line1\n")

        result = file_write_fn(file_path=str(existing), content="line2\n", mode="append")

        assert "error" not in result
        assert result["mode"] == "append"
        assert existing.read_text() == "line1\nline2\n"

    def test_write_creates_parent_dirs(self, file_write_fn, tmp_path: Path):
        """Writing with create_dirs=True creates missing directories."""
        deep_path = tmp_path / "nested" / "dirs" / "file.txt"

        result = file_write_fn(file_path=str(deep_path), content="content", create_dirs=True)

        assert "error" not in result
        assert deep_path.exists()
        assert deep_path.read_text() == "content"

    def test_write_fails_without_parent_dir(self, file_write_fn, tmp_path: Path):
        """Writing with create_dirs=False fails if parent doesn't exist."""
        missing_dir = tmp_path / "missing" / "file.txt"

        result = file_write_fn(file_path=str(missing_dir), content="content", create_dirs=False)

        assert "error" in result
        assert "parent directory" in result["error"].lower()

    def test_write_invalid_mode(self, file_write_fn, tmp_path: Path):
        """Writing with invalid mode returns error."""
        result = file_write_fn(
            file_path=str(tmp_path / "test.txt"),
            content="content",
            mode="invalid"
        )

        assert "error" in result
        assert "invalid mode" in result["error"].lower()

    def test_write_returns_bytes_written(self, file_write_fn, tmp_path: Path):
        """Result includes accurate bytes_written count."""
        content = "Hello, World!"

        result = file_write_fn(file_path=str(tmp_path / "test.txt"), content=content)

        assert result["bytes_written"] == len(content.encode("utf-8"))

    def test_write_with_encoding(self, file_write_fn, tmp_path: Path):
        """Writing with specific encoding works."""
        file_path = tmp_path / "latin.txt"

        result = file_write_fn(file_path=str(file_path), content="café", encoding="latin-1")

        assert "error" not in result
        # Verify it was written with latin-1 encoding
        assert file_path.read_bytes() == "café".encode("latin-1")
