"""Tests for file_read tool (FastMCP)."""
import pytest
from pathlib import Path

from fastmcp import FastMCP
from aden_tools.tools.file_read_tool import register_tools


@pytest.fixture
def file_read_fn(mcp: FastMCP):
    """Register and return the file_read tool function."""
    register_tools(mcp)
    # Access the registered tool's function directly
    return mcp._tool_manager._tools["file_read"].fn


class TestFileReadTool:
    """Tests for file_read tool."""

    def test_read_existing_file(self, file_read_fn, sample_text_file: Path):
        """Reading an existing file returns content and metadata."""
        result = file_read_fn(file_path=str(sample_text_file))

        assert "error" not in result
        assert result["content"] == "Hello, World!\nLine 2\nLine 3"
        assert result["name"] == "test.txt"
        assert result["encoding"] == "utf-8"
        assert "size" in result

    def test_read_file_not_found(self, file_read_fn, tmp_path: Path):
        """Reading a non-existent file returns an error dict."""
        missing_file = tmp_path / "does_not_exist.txt"

        result = file_read_fn(file_path=str(missing_file))

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_read_directory_returns_error(self, file_read_fn, tmp_path: Path):
        """Reading a directory (not a file) returns an error."""
        result = file_read_fn(file_path=str(tmp_path))

        assert "error" in result
        assert "not a file" in result["error"].lower()

    def test_read_file_too_large(self, file_read_fn, tmp_path: Path):
        """Reading a file exceeding max_size returns an error."""
        large_file = tmp_path / "large.txt"
        large_file.write_text("x" * 1000)

        result = file_read_fn(file_path=str(large_file), max_size=100)

        assert "error" in result
        assert "too large" in result["error"].lower()
        assert "file_size" in result

    def test_read_with_no_size_limit(self, file_read_fn, tmp_path: Path):
        """Reading with max_size=0 allows any file size."""
        large_file = tmp_path / "large.txt"
        content = "x" * 100_000
        large_file.write_text(content)

        # max_size=0 means no limit in the implementation
        result = file_read_fn(file_path=str(large_file), max_size=0)

        assert "error" not in result
        assert result["content"] == content

    def test_read_with_different_encoding(self, file_read_fn, tmp_path: Path):
        """Reading with a specific encoding works."""
        latin_file = tmp_path / "latin.txt"
        # Write bytes directly with latin-1 encoding
        latin_file.write_bytes("café".encode("latin-1"))

        result = file_read_fn(file_path=str(latin_file), encoding="latin-1")

        assert "error" not in result
        assert result["content"] == "café"
        assert result["encoding"] == "latin-1"

    def test_read_with_wrong_encoding_returns_error(self, file_read_fn, tmp_path: Path):
        """Reading with wrong encoding returns helpful error."""
        # Create a file with bytes that aren't valid UTF-8
        binary_file = tmp_path / "binary.txt"
        binary_file.write_bytes(b"\xff\xfe")

        result = file_read_fn(file_path=str(binary_file), encoding="utf-8")

        assert "error" in result
        assert "suggestion" in result

    def test_returns_absolute_path(self, file_read_fn, sample_text_file: Path):
        """Result includes the absolute path."""
        result = file_read_fn(file_path=str(sample_text_file))

        assert result["path"] == str(sample_text_file.resolve())
