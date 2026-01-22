"""Tests for file_system_toolkits tools (FastMCP)."""
import os
import pytest
from pathlib import Path
from unittest.mock import Mock, patch

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
        "session_id": "test-session"
    }


@pytest.fixture
def mock_secure_path(tmp_path):
    """Mock get_secure_path to return temp directory paths."""
    def _get_secure_path(path, workspace_id, agent_id, session_id):
        return os.path.join(tmp_path, path)
    
    with patch("aden_tools.tools.file_system_toolkits.view_file.view_file.get_secure_path", side_effect=_get_secure_path):
        with patch("aden_tools.tools.file_system_toolkits.write_to_file.write_to_file.get_secure_path", side_effect=_get_secure_path):
            with patch("aden_tools.tools.file_system_toolkits.list_dir.list_dir.get_secure_path", side_effect=_get_secure_path):
                with patch("aden_tools.tools.file_system_toolkits.replace_file_content.replace_file_content.get_secure_path", side_effect=_get_secure_path):
                    with patch("aden_tools.tools.file_system_toolkits.apply_diff.apply_diff.get_secure_path", side_effect=_get_secure_path):
                        with patch("aden_tools.tools.file_system_toolkits.apply_patch.apply_patch.get_secure_path", side_effect=_get_secure_path):
                            with patch("aden_tools.tools.file_system_toolkits.grep_search.grep_search.get_secure_path", side_effect=_get_secure_path):
                                with patch("aden_tools.tools.file_system_toolkits.grep_search.grep_search.WORKSPACES_DIR", str(tmp_path)):
                                    with patch("aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool.get_secure_path", side_effect=_get_secure_path):
                                        with patch("aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool.WORKSPACES_DIR", str(tmp_path)):
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
        assert result["size_bytes"] == len("Hello, World!".encode("utf-8"))
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


class TestWriteToFileTool:
    """Tests for write_to_file tool."""

    @pytest.fixture
    def write_to_file_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.write_to_file import register_tools
        register_tools(mcp)
        return mcp._tool_manager._tools["write_to_file"].fn

    def test_write_new_file(self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Writing to a new file creates it successfully."""
        result = write_to_file_fn(
            path="new_file.txt",
            content="Test content",
            **mock_workspace
        )

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
            path="append_test.txt",
            content="Line 2\n",
            append=True,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["mode"] == "appended"
        assert test_file.read_text() == "Line 1\nLine 2\n"

    def test_write_overwrite_existing(self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Writing to existing file overwrites it by default."""
        test_file = tmp_path / "overwrite.txt"
        test_file.write_text("Original content")

        result = write_to_file_fn(
            path="overwrite.txt",
            content="New content",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["mode"] == "written"
        assert test_file.read_text() == "New content"

    def test_write_creates_parent_directories(self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Writing creates parent directories if they don't exist."""
        result = write_to_file_fn(
            path="nested/dir/file.txt",
            content="Test",
            **mock_workspace
        )

        assert result["success"] is True
        created_file = tmp_path / "nested" / "dir" / "file.txt"
        assert created_file.exists()
        assert created_file.read_text() == "Test"

    def test_write_empty_content(self, write_to_file_fn, mock_workspace, mock_secure_path, tmp_path):
        """Writing empty content creates empty file."""
        result = write_to_file_fn(
            path="empty.txt",
            content="",
            **mock_workspace
        )

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

    def test_list_directory_with_file_sizes(self, list_dir_fn, mock_workspace, mock_secure_path, tmp_path):
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

    def test_replace_content(self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path):
        """Replacing content in a file works correctly."""
        test_file = tmp_path / "replace_test.txt"
        test_file.write_text("Hello World! Hello again!")

        result = replace_file_content_fn(
            path="replace_test.txt",
            target="Hello",
            replacement="Hi",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 2
        assert test_file.read_text() == "Hi World! Hi again!"

    def test_replace_target_not_found(self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path):
        """Replacing non-existent target returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = replace_file_content_fn(
            path="test.txt",
            target="nonexistent",
            replacement="new",
            **mock_workspace
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_replace_file_not_found(self, replace_file_content_fn, mock_workspace, mock_secure_path):
        """Replacing content in non-existent file returns error."""
        result = replace_file_content_fn(
            path="nonexistent.txt",
            target="foo",
            replacement="bar",
            **mock_workspace
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_replace_single_occurrence(self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path):
        """Replacing content with single occurrence works correctly."""
        test_file = tmp_path / "single.txt"
        test_file.write_text("Hello World")

        result = replace_file_content_fn(
            path="single.txt",
            target="Hello",
            replacement="Hi",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 1
        assert test_file.read_text() == "Hi World"

    def test_replace_multiline_content(self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path):
        """Replacing content across multiple lines works correctly."""
        test_file = tmp_path / "multiline.txt"
        test_file.write_text("Line 1\nTODO: fix this\nLine 3\nTODO: add tests\n")

        result = replace_file_content_fn(
            path="multiline.txt",
            target="TODO:",
            replacement="DONE:",
            **mock_workspace
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

    def test_grep_search_single_file(self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path):
        """Searching a single file returns matches."""
        test_file = tmp_path / "search_test.txt"
        test_file.write_text("Line 1\nLine 2 with pattern\nLine 3")

        result = grep_search_fn(
            path="search_test.txt",
            pattern="pattern",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["total_matches"] == 1
        assert len(result["matches"]) == 1
        assert result["matches"][0]["line_number"] == 2
        assert "pattern" in result["matches"][0]["line_content"]

    def test_grep_search_no_matches(self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path):
        """Searching with no matches returns empty list."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World")

        result = grep_search_fn(
            path="test.txt",
            pattern="nonexistent",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["total_matches"] == 0
        assert result["matches"] == []

    def test_grep_search_directory_non_recursive(self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path):
        """Searching directory non-recursively only searches immediate files."""
        # Create files in root
        (tmp_path / "file1.txt").write_text("pattern here")
        (tmp_path / "file2.txt").write_text("no match here")

        # Create nested directory with file
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("pattern in nested")

        result = grep_search_fn(
            path=".",
            pattern="pattern",
            recursive=False,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["total_matches"] == 1  # Only finds pattern in root, not in nested
        assert result["recursive"] is False

    def test_grep_search_directory_recursive(self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path):
        """Searching directory recursively finds matches in subdirectories."""
        # Create files in root
        (tmp_path / "file1.txt").write_text("pattern here")

        # Create nested directory with file
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("pattern in nested")

        result = grep_search_fn(
            path=".",
            pattern="pattern",
            recursive=True,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["total_matches"] == 2  # Finds pattern in both files
        assert result["recursive"] is True

    def test_grep_search_regex_pattern(self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path):
        """Searching with regex pattern finds complex matches."""
        test_file = tmp_path / "regex_test.txt"
        test_file.write_text("foo123bar\nfoo456bar\nbaz789baz\n")

        result = grep_search_fn(
            path="regex_test.txt",
            pattern=r"foo\d+bar",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["total_matches"] == 2
        assert result["matches"][0]["line_number"] == 1
        assert result["matches"][1]["line_number"] == 2

    def test_grep_search_multiple_matches_per_line(self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path):
        """Searching returns one match per line even with multiple occurrences."""
        test_file = tmp_path / "multi_match.txt"
        test_file.write_text("hello hello hello\nworld\nhello again")

        result = grep_search_fn(
            path="multi_match.txt",
            pattern="hello",
            **mock_workspace
        )

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
        result = execute_command_fn(
            command="echo 'Hello World'",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "Hello World" in result["stdout"]

    def test_execute_failing_command(self, execute_command_fn, mock_workspace, mock_secure_path):
        """Executing a failing command returns non-zero exit code."""
        result = execute_command_fn(
            command="exit 1",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["return_code"] == 1

    def test_execute_command_with_stderr(self, execute_command_fn, mock_workspace, mock_secure_path):
        """Executing a command that writes to stderr captures it."""
        result = execute_command_fn(
            command="echo 'error message' >&2",
            **mock_workspace
        )

        assert result["success"] is True
        assert "error message" in result.get("stderr", "")

    def test_execute_command_list_files(self, execute_command_fn, mock_workspace, mock_secure_path, tmp_path):
        """Executing ls command lists files."""
        # Create a test file
        (tmp_path / "testfile.txt").write_text("content")

        result = execute_command_fn(
            command=f"ls {tmp_path}",
            **mock_workspace
        )

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "testfile.txt" in result["stdout"]

    def test_execute_command_with_pipe(self, execute_command_fn, mock_workspace, mock_secure_path):
        """Executing a command with pipe works correctly."""
        result = execute_command_fn(
            command="echo 'hello world' | tr 'a-z' 'A-Z'",
            **mock_workspace
        )

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
        result = apply_diff_fn(
            path="nonexistent.txt",
            diff_text="some diff",
            **mock_workspace
        )

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

        result = apply_diff_fn(
            path="diff_test.txt",
            diff_text=diff_text,
            **mock_workspace
        )

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

        result = apply_diff_fn(
            path="multiline.txt",
            diff_text=diff_text,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text() == modified

    def test_apply_diff_invalid_patch(self, apply_diff_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying an invalid diff handles gracefully."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        # Invalid diff text
        result = apply_diff_fn(
            path="test.txt",
            diff_text="invalid diff format",
            **mock_workspace
        )

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
        result = apply_patch_fn(
            path="nonexistent.txt",
            patch_text="some patch",
            **mock_workspace
        )

        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_apply_patch_successful(self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying a valid patch successfully modifies the file."""
        test_file = tmp_path / "patch_test.txt"
        test_file.write_text("Hello World")

        # Create a simple patch using diff_match_patch format
        import diff_match_patch as dmp_module
        dmp = dmp_module.diff_match_patch()
        patches = dmp.patch_make("Hello World", "Hello Python")
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(
            path="patch_test.txt",
            patch_text=patch_text,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["all_successful"] is True
        assert result["patches_applied"] > 0
        assert test_file.read_text() == "Hello Python"

    def test_apply_patch_multiline(self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying patch to multiline content works correctly."""
        test_file = tmp_path / "multiline.txt"
        original = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(original)

        import diff_match_patch as dmp_module
        dmp = dmp_module.diff_match_patch()
        modified = "Line 1\nModified Line 2\nLine 3\n"
        patches = dmp.patch_make(original, modified)
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(
            path="multiline.txt",
            patch_text=patch_text,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text() == modified

    def test_apply_patch_invalid_patch(self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying an invalid patch handles gracefully."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content)

        # Invalid patch text
        result = apply_patch_fn(
            path="test.txt",
            patch_text="invalid patch format",
            **mock_workspace
        )

        # Should either error or show no patches applied
        if "error" not in result:
            assert result.get("patches_applied", 0) == 0
        # File should remain unchanged
        assert test_file.read_text() == original_content

    def test_apply_patch_multiple_changes(self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying patch with multiple changes works correctly."""
        test_file = tmp_path / "complex.txt"
        original = "Function foo() {\n  return 42;\n}\n"
        test_file.write_text(original)

        import diff_match_patch as dmp_module
        dmp = dmp_module.diff_match_patch()
        modified = "Function bar() {\n  return 100;\n}\n"
        patches = dmp.patch_make(original, modified)
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(
            path="complex.txt",
            patch_text=patch_text,
            **mock_workspace
        )

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text() == modified
