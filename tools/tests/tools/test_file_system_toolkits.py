"""Tests for file_system_toolkits tools (FastMCP)."""

import json
import os
from unittest.mock import patch

import pytest
from fastmcp import FastMCP


@pytest.fixture
def mcp():
    """Create a FastMCP instance."""
    return FastMCP("test-server")


@pytest.fixture
def mock_workspace():
    """Mock workspace, agent, and session IDs."""
    return {
        "workspace_id": "test-workspace",
        "agent_id": "test-agent",
        "session_id": "test-session",
    }


@pytest.fixture
def mock_secure_path(tmp_path):
    """Mock get_secure_path to return temp directory paths."""

    def _get_secure_path(path, workspace_id, agent_id, session_id):
        return os.path.join(tmp_path, path)

    with patch(
        "aden_tools.tools.file_system_toolkits.view_file.view_file.get_secure_path",
        side_effect=_get_secure_path,
    ):
        with patch(
            "aden_tools.tools.file_system_toolkits.write_to_file.write_to_file.get_secure_path",
            side_effect=_get_secure_path,
        ):
            with patch(
                "aden_tools.tools.file_system_toolkits.list_dir.list_dir.get_secure_path",
                side_effect=_get_secure_path,
            ):
                with patch(
                    "aden_tools.tools.file_system_toolkits.replace_file_content.replace_file_content.get_secure_path",
                    side_effect=_get_secure_path,
                ):
                    with patch(
                        "aden_tools.tools.file_system_toolkits.apply_diff.apply_diff.get_secure_path",
                        side_effect=_get_secure_path,
                    ):
                        with patch(
                            "aden_tools.tools.file_system_toolkits.apply_patch.apply_patch.get_secure_path",
                            side_effect=_get_secure_path,
                        ):
                            with patch(
                                "aden_tools.tools.file_system_toolkits.grep_search.grep_search.get_secure_path",
                                side_effect=_get_secure_path,
                            ):
                                with patch(
                                    "aden_tools.tools.file_system_toolkits.grep_search.grep_search.WORKSPACES_DIR",
                                    str(tmp_path),
                                ):
                                    with patch(
                                        "aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool.get_secure_path",
                                        side_effect=_get_secure_path,
                                    ):
                                        with patch(
                                            "aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool.WORKSPACES_DIR",
                                            str(tmp_path),
                                        ):
                                            with patch(
                                                "aden_tools.tools.file_system_toolkits.hashline_edit.hashline_edit.get_secure_path",
                                                side_effect=_get_secure_path,
                                            ):
                                                yield


class TestViewFileTool:
    """Tests for view_file tool."""

    @pytest.fixture
    def view_file_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.view_file import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["view_file"].fn

    def test_view_existing_file(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Viewing an existing file returns content and metadata."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        result = view_file_fn(path="test.txt", **mock_workspace)

        assert result["success"] is True
        assert result["content"] == "Hello, World!"
        assert result["size_bytes"] == len(b"Hello, World!")
        assert result["lines"] == 1

    def test_view_nonexistent_file(self, view_file_fn, mock_workspace, mock_secure_path):
        """Viewing a non-existent file returns an error."""
        result = view_file_fn(path="nonexistent.txt", **mock_workspace)

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_view_multiline_file(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Viewing a multiline file returns correct line count."""
        test_file = tmp_path / "multiline.txt"
        content = "Line 1\nLine 2\nLine 3\nLine 4\n"
        test_file.write_text(content)

        result = view_file_fn(path="multiline.txt", **mock_workspace)

        assert result["success"] is True
        assert result["content"] == content
        assert result["lines"] == 4

    def test_view_empty_file(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Viewing an empty file returns empty content."""
        test_file = tmp_path / "empty.txt"
        test_file.write_text("")

        result = view_file_fn(path="empty.txt", **mock_workspace)

        assert result["success"] is True
        assert result["content"] == ""
        assert result["size_bytes"] == 0
        assert result["lines"] == 0

    def test_view_file_with_unicode(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Viewing a file with unicode characters works correctly."""
        test_file = tmp_path / "unicode.txt"
        content = "Hello 世界! 🌍 émoji"
        test_file.write_text(content, encoding="utf-8")

        result = view_file_fn(path="unicode.txt", **mock_workspace)

        assert result["success"] is True
        assert result["content"] == content
        assert result["size_bytes"] == len(content.encode("utf-8"))

    def test_view_nested_file(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Viewing a file in a nested directory works correctly."""
        nested = tmp_path / "nested" / "dir"
        nested.mkdir(parents=True)
        test_file = nested / "file.txt"
        test_file.write_text("nested content")

        result = view_file_fn(path="nested/dir/file.txt", **mock_workspace)

        assert result["success"] is True
        assert result["content"] == "nested content"

    def test_view_file_with_max_size_truncation(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Viewing a file with max_size truncates content when exceeding limit."""
        test_file = tmp_path / "large.txt"
        content = "x" * 1000
        test_file.write_text(content)

        result = view_file_fn(path="large.txt", max_size=100, **mock_workspace)

        assert result["success"] is True
        assert len(result["content"]) <= 100 + len(
            "\n\n[... Content truncated due to size limit ...]"
        )
        assert "[... Content truncated due to size limit ...]" in result["content"]

    def test_view_file_with_negative_max_size(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Viewing a file with negative max_size returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = view_file_fn(path="test.txt", max_size=-1, **mock_workspace)

        assert "error" in result
        assert "max_size must be non-negative" in result["error"]

    def test_view_file_with_custom_encoding(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Viewing a file with custom encoding works correctly."""
        test_file = tmp_path / "encoded.txt"
        content = "Hello 世界"
        test_file.write_text(content, encoding="utf-8")

        result = view_file_fn(path="encoded.txt", encoding="utf-8", **mock_workspace)

        assert result["success"] is True
        assert result["content"] == content

    def test_view_file_with_invalid_encoding(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Viewing a file with invalid encoding returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        result = view_file_fn(path="test.txt", encoding="invalid-encoding", **mock_workspace)

        assert "error" in result
        assert "Failed to read file" in result["error"]

    def test_offset_without_hashline_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Passing offset without hashline=True returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\nccc\n")

        result = view_file_fn(path="test.txt", offset=5, **mock_workspace)

        assert "error" in result
        assert "hashline=True" in result["error"]

    def test_limit_without_hashline_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Passing limit without hashline=True returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\nccc\n")

        result = view_file_fn(path="test.txt", limit=10, **mock_workspace)

        assert "error" in result
        assert "hashline=True" in result["error"]

    def test_offset_and_limit_without_hashline_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Passing both offset and limit without hashline=True returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\nccc\n")

        result = view_file_fn(path="test.txt", offset=2, limit=5, **mock_workspace)

        assert "error" in result
        assert "hashline=True" in result["error"]


class TestWriteToFileTool:
    """Tests for write_to_file tool."""

    @pytest.fixture
    def write_to_file_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.write_to_file import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["write_to_file"].fn

    def test_write_new_file(self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Writing to a new file creates it successfully."""
        result = write_to_file_fn(path="new_file.txt", content="Test content", **mock_workspace)

        assert result["success"] is True
        assert result["mode"] == "written"
        assert result["bytes_written"] > 0

        # Verify file was created
        created_file = tmp_path / "new_file.txt"
        assert created_file.exists()
        assert created_file.read_text() == "Test content"

    def test_write_append_mode(self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Writing with append=True appends to existing file."""
        test_file = tmp_path / "append_test.txt"
        test_file.write_text("Line 1\n")

        result = write_to_file_fn(
            path="append_test.txt", content="Line 2\n", append=True, **mock_workspace
        )

        assert result["success"] is True
        assert result["mode"] == "appended"
        assert test_file.read_text() == "Line 1\nLine 2\n"

    def test_write_overwrite_existing(
        self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Writing to existing file overwrites it by default."""
        test_file = tmp_path / "overwrite.txt"
        test_file.write_text("Original content")

        result = write_to_file_fn(path="overwrite.txt", content="New content", **mock_workspace)

        assert result["success"] is True
        assert result["mode"] == "written"
        assert test_file.read_text() == "New content"

    def test_write_creates_parent_directories(
        self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Writing creates parent directories if they don't exist."""
        result = write_to_file_fn(path="nested/dir/file.txt", content="Test", **mock_workspace)

        assert result["success"] is True
        created_file = tmp_path / "nested" / "dir" / "file.txt"
        assert created_file.exists()
        assert created_file.read_text() == "Test"

    def test_write_empty_content(
        self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Writing empty content creates empty file."""
        result = write_to_file_fn(path="empty.txt", content="", **mock_workspace)

        assert result["success"] is True
        assert result["bytes_written"] == 0
        created_file = tmp_path / "empty.txt"
        assert created_file.exists()
        assert created_file.read_text() == ""


class TestListDirTool:
    """Tests for list_dir tool."""

    @pytest.fixture
    def list_dir_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.list_dir import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["list_dir"].fn

    def test_list_directory(self, list_dir_fn, mock_workspace, mock_secure_path, tmp_path):
        """Listing a directory returns all entries."""
        # Create test files and directories
        (tmp_path / "file1.txt").write_text("content")
        (tmp_path / "file2.txt").write_text("content")
        (tmp_path / "subdir").mkdir()

        result = list_dir_fn(path=".", **mock_workspace)

        assert result["success"] is True
        assert result["total_count"] == 3
        assert len(result["entries"]) == 3

        # Check that entries have correct structure
        for entry in result["entries"]:
            assert "name" in entry
            assert "type" in entry
            assert entry["type"] in ["file", "directory"]

    def test_list_empty_directory(self, list_dir_fn, mock_workspace, mock_secure_path, tmp_path):
        """Listing an empty directory returns empty list."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = list_dir_fn(path="empty", **mock_workspace)

        assert result["success"] is True
        assert result["total_count"] == 0
        assert result["entries"] == []

    def test_list_nonexistent_directory(self, list_dir_fn, mock_workspace, mock_secure_path):
        """Listing a non-existent directory returns error."""
        result = list_dir_fn(path="nonexistent_dir", **mock_workspace)

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_list_directory_with_file_sizes(
        self, list_dir_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Listing a directory returns file sizes for files."""
        (tmp_path / "small.txt").write_text("hi")
        (tmp_path / "larger.txt").write_text("hello world")
        (tmp_path / "subdir").mkdir()

        result = list_dir_fn(path=".", **mock_workspace)

        assert result["success"] is True

        # Find entries by name
        entries_by_name = {e["name"]: e for e in result["entries"]}

        # Files should have size_bytes
        assert entries_by_name["small.txt"]["type"] == "file"
        assert entries_by_name["small.txt"]["size_bytes"] == 2

        assert entries_by_name["larger.txt"]["type"] == "file"
        assert entries_by_name["larger.txt"]["size_bytes"] == 11

        # Directories should have None for size_bytes
        assert entries_by_name["subdir"]["type"] == "directory"
        assert entries_by_name["subdir"]["size_bytes"] is None


class TestReplaceFileContentTool:
    """Tests for replace_file_content tool."""

    @pytest.fixture
    def replace_file_content_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.replace_file_content import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["replace_file_content"].fn

    def test_replace_content(
        self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Replacing content in a file works correctly."""
        test_file = tmp_path / "replace_test.txt"
        test_file.write_text("Hello World! Hello again!")

        result = replace_file_content_fn(
            path="replace_test.txt", target="Hello", replacement="Hi", **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 2
        assert test_file.read_text() == "Hi World! Hi again!"

    def test_replace_target_not_found(
        self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Replacing non-existent target returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = replace_file_content_fn(
            path="test.txt", target="nonexistent", replacement="new", **mock_workspace
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_replace_file_not_found(
        self, replace_file_content_fn, mock_workspace, mock_secure_path
    ):
        """Replacing content in non-existent file returns error."""
        result = replace_file_content_fn(
            path="nonexistent.txt", target="foo", replacement="bar", **mock_workspace
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_replace_single_occurrence(
        self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Replacing content with single occurrence works correctly."""
        test_file = tmp_path / "single.txt"
        test_file.write_text("Hello World")

        result = replace_file_content_fn(
            path="single.txt", target="Hello", replacement="Hi", **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 1
        assert test_file.read_text() == "Hi World"

    def test_replace_multiline_content(
        self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Replacing content across multiple lines works correctly."""
        test_file = tmp_path / "multiline.txt"
        test_file.write_text("Line 1\nTODO: fix this\nLine 3\nTODO: add tests\n")

        result = replace_file_content_fn(
            path="multiline.txt", target="TODO:", replacement="DONE:", **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 2
        assert test_file.read_text() == "Line 1\nDONE: fix this\nLine 3\nDONE: add tests\n"


class TestGrepSearchTool:
    """Tests for grep_search tool."""

    @pytest.fixture
    def grep_search_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.grep_search import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["grep_search"].fn

    def test_grep_search_single_file(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching a single file returns matches."""
        test_file = tmp_path / "search_test.txt"
        test_file.write_text("Line 1\nLine 2 with pattern\nLine 3")

        result = grep_search_fn(path="search_test.txt", pattern="pattern", **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["line_number"] == 2
        assert "pattern" in result["matches"][0]["line_content"]

    def test_grep_search_no_matches(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching with no matches returns empty list."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = grep_search_fn(path="test.txt", pattern="nonexistent", **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 0
        assert result["matches"] == []

    def test_grep_search_directory_non_recursive(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching directory non-recursively only searches immediate files."""
        # Create files in root
        (tmp_path / "file1.txt").write_text("pattern here")
        (tmp_path / "file2.txt").write_text("no match here")

        # Create nested directory with file
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("pattern in nested")

        result = grep_search_fn(path=".", pattern="pattern", recursive=False, **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 1  # Only finds pattern in root, not in nested
        assert result["recursive"] is False

    def test_grep_search_directory_recursive(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching directory recursively finds matches in subdirectories."""
        # Create files in root
        (tmp_path / "file1.txt").write_text("pattern here")

        # Create nested directory with file
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("pattern in nested")

        result = grep_search_fn(path=".", pattern="pattern", recursive=True, **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 2  # Finds pattern in both files
        assert result["recursive"] is True

    def test_grep_search_regex_pattern(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching with regex pattern finds complex matches."""
        test_file = tmp_path / "regex_test.txt"
        test_file.write_text("foo123bar\nfoo456bar\nbaz789baz\n")

        result = grep_search_fn(path="regex_test.txt", pattern=r"foo\d+bar", **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 2
        assert result["matches"][0]["line_number"] == 1
        assert result["matches"][1]["line_number"] == 2

    def test_grep_search_multiple_matches_per_line(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching returns one match per line even with multiple occurrences."""
        test_file = tmp_path / "multi_match.txt"
        test_file.write_text("hello hello hello\nworld\nhello again")

        result = grep_search_fn(path="multi_match.txt", pattern="hello", **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 2  # Line 1 and Line 3


class TestExecuteCommandTool:
    """Tests for execute_command_tool."""

    @pytest.fixture
    def execute_command_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.execute_command_tool import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["execute_command_tool"].fn

    def test_execute_simple_command(self, execute_command_fn, mock_workspace, mock_secure_path):
        """Executing a simple command returns output."""
        result = execute_command_fn(command="echo 'Hello World'", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "Hello World" in result["stdout"]

    def test_execute_failing_command(self, execute_command_fn, mock_workspace, mock_secure_path):
        """Executing a failing command returns non-zero exit code."""
        result = execute_command_fn(command="exit 1", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 1

    def test_execute_command_with_stderr(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """Executing a command that writes to stderr captures it."""
        result = execute_command_fn(command="echo 'error message' >&2", **mock_workspace)

        assert result["success"] is True
        assert "error message" in result.get("stderr", "")

    def test_execute_command_list_files(
        self, execute_command_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Executing ls command lists files."""
        # Create a test file
        (tmp_path / "testfile.txt").write_text("content")

        result = execute_command_fn(command=f"ls {tmp_path}", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "testfile.txt" in result["stdout"]

    def test_execute_command_with_pipe(self, execute_command_fn, mock_workspace, mock_secure_path):
        """Executing a command with pipe works correctly."""
        result = execute_command_fn(command="echo 'hello world' | tr 'a-z' 'A-Z'", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "HELLO WORLD" in result["stdout"]


class TestApplyDiffTool:
    """Tests for apply_diff tool."""

    @pytest.fixture
    def apply_diff_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.apply_diff import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["apply_diff"].fn

    def test_apply_diff_file_not_found(self, apply_diff_fn, mock_workspace, mock_secure_path):
        """Applying diff to non-existent file returns error."""
        result = apply_diff_fn(path="nonexistent.txt", diff_text="some diff", **mock_workspace)

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_apply_diff_successful(self, apply_diff_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying a valid diff successfully modifies the file."""
        test_file = tmp_path / "diff_test.txt"
        test_file.write_text("Hello World")

        # Create a simple diff using diff_match_patch format
        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        patches = dmp.patch_make("Hello World", "Hello Universe")
        diff_text = dmp.patch_toText(patches)

        result = apply_diff_fn(path="diff_test.txt", diff_text=diff_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert result["patches_applied"] > 0
        assert test_file.read_text() == "Hello Universe"

    def test_apply_diff_multiline(self, apply_diff_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying diff to multiline content works correctly."""
        test_file = tmp_path / "multiline.txt"
        original = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(original)

        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        modified = "Line 1\nModified Line 2\nLine 3\n"
        patches = dmp.patch_make(original, modified)
        diff_text = dmp.patch_toText(patches)

        result = apply_diff_fn(path="multiline.txt", diff_text=diff_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text() == modified

    def test_apply_diff_invalid_patch(
        self, apply_diff_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying an invalid diff handles gracefully."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        # Invalid diff text
        result = apply_diff_fn(path="test.txt", diff_text="invalid diff format", **mock_workspace)

        # Should either error or show no patches applied
        if "error" not in result:
            assert result.get("patches_applied", 0) == 0
        # File should remain unchanged
        assert test_file.read_text() == original_content


class TestApplyPatchTool:
    """Tests for apply_patch tool."""

    @pytest.fixture
    def apply_patch_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.apply_patch import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["apply_patch"].fn

    def test_apply_patch_file_not_found(self, apply_patch_fn, mock_workspace, mock_secure_path):
        """Applying patch to non-existent file returns error."""
        result = apply_patch_fn(path="nonexistent.txt", patch_text="some patch", **mock_workspace)

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_apply_patch_successful(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying a valid patch successfully modifies the file."""
        test_file = tmp_path / "patch_test.txt"
        test_file.write_text("Hello World")

        # Create a simple patch using diff_match_patch format
        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        patches = dmp.patch_make("Hello World", "Hello Python")
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(path="patch_test.txt", patch_text=patch_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert result["patches_applied"] > 0
        assert test_file.read_text() == "Hello Python"

    def test_apply_patch_multiline(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying patch to multiline content works correctly."""
        test_file = tmp_path / "multiline.txt"
        original = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(original)

        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        modified = "Line 1\nModified Line 2\nLine 3\n"
        patches = dmp.patch_make(original, modified)
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(path="multiline.txt", patch_text=patch_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text() == modified

    def test_apply_patch_invalid_patch(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying an invalid patch handles gracefully."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        # Invalid patch text
        result = apply_patch_fn(
            path="test.txt", patch_text="invalid patch format", **mock_workspace
        )

        # Should either error or show no patches applied
        if "error" not in result:
            assert result.get("patches_applied", 0) == 0
        # File should remain unchanged
        assert test_file.read_text() == original_content

    def test_apply_patch_multiple_changes(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying patch with multiple changes works correctly."""
        test_file = tmp_path / "complex.txt"
        original = "Function foo() {\n  return 42;\n}\n"
        test_file.write_text(original)

        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        modified = "Function bar() {\n  return 100;\n}\n"
        patches = dmp.patch_make(original, modified)
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(path="complex.txt", patch_text=patch_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text() == modified


class TestViewFileHashlineMode:
    """Tests for view_file hashline mode."""

    @pytest.fixture
    def view_file_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.view_file import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["view_file"].fn

    def test_hashline_format(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """hashline=True returns N:hhhh|content format."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello\nworld\n")

        result = view_file_fn(path="test.txt", hashline=True, **mock_workspace)

        assert result["success"] is True
        assert result["hashline"] is True
        lines = result["content"].split("\n")
        assert lines[0].startswith("1:")
        assert "|hello" in lines[0]
        assert lines[1].startswith("2:")
        assert "|world" in lines[1]

    def test_hashline_offset(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """hashline with offset skips initial lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\nccc\n")

        result = view_file_fn(path="test.txt", hashline=True, offset=2, **mock_workspace)

        assert result["success"] is True
        assert result["offset"] == 2
        lines = result["content"].split("\n")
        assert lines[0].startswith("2:")
        assert "|bbb" in lines[0]

    def test_hashline_limit(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """hashline with limit restricts number of lines."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\nccc\nddd\n")

        result = view_file_fn(path="test.txt", hashline=True, limit=2, **mock_workspace)

        assert result["success"] is True
        assert result["limit"] == 2
        assert result["shown_lines"] == 2
        assert result["total_lines"] == 4

    def test_hashline_total_and_shown_lines(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """total_lines and shown_lines are reported correctly."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("a\nb\nc\nd\ne\n")

        result = view_file_fn(path="test.txt", hashline=True, offset=2, limit=2, **mock_workspace)

        assert result["total_lines"] == 5
        assert result["shown_lines"] == 2

    def test_default_mode_unchanged(self, view_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Default mode (hashline=False) returns the same format as before."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello\n")

        result = view_file_fn(path="test.txt", **mock_workspace)

        assert result["success"] is True
        assert "hashline" not in result
        assert result["content"] == "hello\n"
        assert result["lines"] == 1

    def test_hashline_offset_zero_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline with offset=0 returns error (must be >= 1)."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\n")

        result = view_file_fn(path="test.txt", hashline=True, offset=0, **mock_workspace)

        assert "error" in result
        assert "offset" in result["error"].lower()

    def test_hashline_negative_offset_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline with negative offset returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\n")

        result = view_file_fn(path="test.txt", hashline=True, offset=-1, **mock_workspace)

        assert "error" in result
        assert "offset" in result["error"].lower()

    def test_hashline_negative_limit_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline with negative limit returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\n")

        result = view_file_fn(path="test.txt", hashline=True, limit=-1, **mock_workspace)

        assert "error" in result
        assert "limit" in result["error"].lower()

    def test_hashline_truncated_file_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Large file with hashline=True and no offset/limit returns error directing to paginate."""
        test_file = tmp_path / "large.txt"
        # Create a file larger than the max_size we'll pass
        content = "line\n" * 100  # 500 bytes
        test_file.write_text(content)

        result = view_file_fn(path="large.txt", hashline=True, max_size=50, **mock_workspace)

        assert "error" in result
        assert "too large" in result["error"].lower()
        assert "offset" in result["error"].lower()
        assert "limit" in result["error"].lower()

    def test_hashline_offset_beyond_end_returns_error(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline with offset beyond total lines returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("aaa\nbbb\n")

        result = view_file_fn(path="test.txt", hashline=True, offset=50, **mock_workspace)

        assert "error" in result
        assert "beyond" in result["error"].lower()
        assert "2 lines" in result["error"]

    def test_hashline_large_file_with_offset_limit_works(
        self, view_file_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Large file using offset/limit bypasses full-file size check."""
        test_file = tmp_path / "large.txt"
        lines = [f"line {i}" for i in range(1, 101)]
        test_file.write_text("\n".join(lines) + "\n")

        # File is large (> max_size=200), but offset/limit lets us page through it
        result = view_file_fn(
            path="large.txt", hashline=True, offset=10, limit=5, max_size=200, **mock_workspace
        )

        assert result["success"] is True
        assert result["shown_lines"] == 5
        assert result["total_lines"] == 100
        # First shown line should be line 10
        first_line = result["content"].split("\n")[0]
        assert first_line.startswith("10:")
        assert "|line 10" in first_line


class TestGrepSearchHashlineMode:
    """Tests for grep_search hashline mode."""

    @pytest.fixture
    def grep_search_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.grep_search import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["grep_search"].fn

    def test_hashline_anchor_present(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline=True includes anchor field in matches."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\ngoodbye world\n")

        result = grep_search_fn(path="test.txt", pattern="hello", hashline=True, **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 1
        match = result["matches"][0]
        assert "anchor" in match
        # Anchor format: N:hhhh (4-char hash)
        assert match["anchor"].startswith("1:")
        assert len(match["anchor"]) == 6  # "1:hhhh"

    def test_hashline_anchor_absent_by_default(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline=False (default) does not include anchor field."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("hello world\n")

        result = grep_search_fn(path="test.txt", pattern="hello", **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 1
        assert "anchor" not in result["matches"][0]

    def test_grep_hashline_preserves_indentation(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline=True preserves leading whitespace in line_content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("    hello world\n")

        result = grep_search_fn(path="test.txt", pattern="hello", hashline=True, **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 1
        assert result["matches"][0]["line_content"] == "    hello world"


class TestHashlineCrossToolConsistency:
    """Cross-tool consistency tests for hashline workflows."""

    @pytest.fixture
    def view_file_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.view_file import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["view_file"].fn

    @pytest.fixture
    def grep_search_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.grep_search import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["grep_search"].fn

    @pytest.fixture
    def hashline_edit_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.hashline_edit import register_tools

        register_tools(mcp)
        return mcp._tool_manager._tools["hashline_edit"].fn

    def test_unicode_line_separator_anchor_roundtrip(
        self,
        view_file_fn,
        grep_search_fn,
        hashline_edit_fn,
        mock_workspace,
        mock_secure_path,
        tmp_path,
    ):
        """Anchors from grep hashline mode should be consumable by hashline_edit."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("A\u2028B\nC\n", encoding="utf-8")

        # Hashline view sees U+2028 as a line boundary via splitlines()
        view_res = view_file_fn(path="test.txt", hashline=True, **mock_workspace)
        assert view_res["success"] is True
        assert view_res["total_lines"] == 3

        # grep_search line iteration treats U+2028 as in-line content
        grep_res = grep_search_fn(path="test.txt", pattern="B", hashline=True, **mock_workspace)
        assert grep_res["success"] is True
        assert grep_res["total_matches"] == 1

        anchor = grep_res["matches"][0]["anchor"]
        edits = json.dumps([{"op": "set_line", "anchor": anchor, "content": "X"}])
        edit_res = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" not in edit_res, edit_res.get("error")
        assert edit_res["success"] is True
