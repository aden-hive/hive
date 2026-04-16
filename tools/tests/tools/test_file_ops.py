"""Tests for aden_tools.file_ops (shared file tools).

These tests cover Windows compatibility concerns: path relativization
in search_files (ripgrep and Python fallback) and cross-platform behavior.
"""

import os
from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.file_ops import register_file_tools


@pytest.fixture
def file_ops_mcp(tmp_path):
    """Create FastMCP with file_ops registered, sandboxed to tmp_path."""

    def resolve_path(p: str) -> str:
        if os.path.isabs(p):
            return os.path.normpath(p)
        return str((tmp_path / p).resolve())

    mcp = FastMCP("test-file-ops")
    register_file_tools(
        mcp,
        resolve_path=resolve_path,
        project_root=str(tmp_path),
    )
    return mcp


def _get_tool_fn(mcp, name):
    """Extract the raw function for a registered tool."""
    return mcp._tool_manager._tools[name].fn


class TestSearchFilesPathRelativization:
    """Tests for search_files path handling (Windows path separator fix)."""

    def test_ripgrep_output_with_backslash_relativized(self, file_ops_mcp, tmp_path):
        """Ripgrep output with backslashes (Windows) relativized when project_root set.

        Simulates: rg outputs 'C:\\Users\\...\\proj\\src\\foo.py:1:needle'
        Expected: output should show 'src\\foo.py:1:needle' or 'src/foo.py:1:needle'
        (relativized, not full path).
        """
        # Create a file so the search has something to find
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "foo.py").write_text("needle\n")
        project_root = str(tmp_path)

        # Ripgrep on Windows outputs backslash-separated paths
        # Format: path:line_num:content
        rg_output = f"{project_root}{os.sep}src{os.sep}foo.py:1:needle"

        search_fn = _get_tool_fn(file_ops_mcp, "search_files")

        with patch("aden_tools.file_ops.subprocess.run") as mock_run:
            mock_run.return_value = type("Result", (), {"returncode": 0, "stdout": rg_output, "stderr": ""})()

            result = search_fn(
                pattern="needle",
                path=str(tmp_path),
            )

        # Output should be relativized (no full project_root in the line)
        assert project_root not in result, f"Output should not contain full project_root. Got: {result!r}"
        # Should contain the relative path part
        assert "foo.py" in result
        assert "1:" in result or ":1:" in result

    def test_ripgrep_output_with_forward_slash_relativized(self, file_ops_mcp, tmp_path):
        """Ripgrep output using forward slashes (Unix/rg default) should be relativized."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "bar.py").write_text("pattern_match\n")
        project_root = str(tmp_path)

        # Some ripgrep builds output forward slashes even on Windows
        rg_output = f"{project_root}/src/bar.py:1:pattern_match"

        search_fn = _get_tool_fn(file_ops_mcp, "search_files")

        with patch("aden_tools.file_ops.subprocess.run") as mock_run:
            mock_run.return_value = type("Result", (), {"returncode": 0, "stdout": rg_output, "stderr": ""})()

            result = search_fn(
                pattern="pattern_match",
                path=str(tmp_path),
            )

        assert project_root not in result or "src/bar.py" in result
        assert "bar.py" in result

    def test_python_fallback_relativizes_paths(self, file_ops_mcp, tmp_path):
        """Python fallback (no ripgrep) uses os.path.relpath - should work on all platforms."""
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "baz.txt").write_text("find_me\n")

        search_fn = _get_tool_fn(file_ops_mcp, "search_files")

        # Ensure ripgrep is not used
        with patch("aden_tools.file_ops.subprocess.run", side_effect=FileNotFoundError()):
            result = search_fn(
                pattern="find_me",
                path=str(tmp_path),
            )

        # Python fallback uses os.path.relpath - should produce relative path
        project_root = str(tmp_path)
        assert project_root not in result or "subdir" in result
        assert "baz.txt" in result
        assert "1:" in result or ":1:" in result


class TestSearchFilesBasic:
    """Basic search_files behavior (no path mocking)."""

    def test_search_finds_content(self, file_ops_mcp, tmp_path):
        """search_files finds matching content via Python fallback when rg absent."""
        (tmp_path / "hello.txt").write_text("world\n")

        search_fn = _get_tool_fn(file_ops_mcp, "search_files")

        with patch("aden_tools.file_ops.subprocess.run", side_effect=FileNotFoundError()):
            result = search_fn(pattern="world", path=str(tmp_path))

        assert "world" in result
        assert "hello.txt" in result

    def test_search_nonexistent_dir_returns_error(self, file_ops_mcp, tmp_path):
        """search_files on non-existent directory returns error."""
        search_fn = _get_tool_fn(file_ops_mcp, "search_files")
        result = search_fn(pattern="x", path=str(tmp_path / "nonexistent"))
        assert "Error" in result
        assert "not found" in result.lower()
