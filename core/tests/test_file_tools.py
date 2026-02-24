"""Smoke tests for built-in file tools (framework.graph.file_tools)."""

import os
import tempfile

import pytest

from framework.graph.file_tools import (
    FILE_TOOL_NAMES,
    build_file_tools,
    execute_file_tool,
    is_file_tool,
)


class TestBuildFileTools:
    def test_returns_six_tools(self):
        tools = build_file_tools()
        assert len(tools) == 6

    def test_tool_names_match(self):
        tools = build_file_tools()
        names = {t.name for t in tools}
        assert names == FILE_TOOL_NAMES

    def test_all_tools_have_descriptions(self):
        for tool in build_file_tools():
            assert tool.description, f"{tool.name} missing description"

    def test_all_tools_have_parameters(self):
        for tool in build_file_tools():
            assert tool.parameters, f"{tool.name} missing parameters"
            assert tool.parameters.get("type") == "object"


class TestIsFileTool:
    def test_known_tools(self):
        for name in FILE_TOOL_NAMES:
            assert is_file_tool(name)

    def test_unknown_tool(self):
        assert not is_file_tool("web_search")
        assert not is_file_tool("set_output")
        assert not is_file_tool("load_data")


class TestReadFile:
    def test_read_temp_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("line1\nline2\nline3\n")
        result = execute_file_tool("read_file", {"path": str(f)})
        assert not result.is_error
        assert "line1" in result.content
        assert "line2" in result.content
        assert "line3" in result.content

    def test_read_with_offset(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\nd\ne\n")
        result = execute_file_tool("read_file", {"path": str(f), "offset": 3, "limit": 2})
        assert not result.is_error
        assert "c" in result.content
        assert "d" in result.content

    def test_read_missing_file(self):
        result = execute_file_tool("read_file", {"path": "/tmp/nonexistent_file_abc123.txt"})
        assert not result.is_error  # returns error text, not is_error flag
        assert "not found" in result.content.lower() or "error" in result.content.lower()

    def test_read_directory_lists_entries(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        result = execute_file_tool("read_file", {"path": str(tmp_path)})
        assert not result.is_error
        assert "a.txt" in result.content
        assert "b.txt" in result.content


class TestWriteFile:
    def test_write_new_file(self, tmp_path):
        f = tmp_path / "new.txt"
        result = execute_file_tool("write_file", {"path": str(f), "content": "hello world"})
        assert not result.is_error
        assert "Created" in result.content
        assert f.read_text() == "hello world"

    def test_overwrite_existing(self, tmp_path):
        f = tmp_path / "existing.txt"
        f.write_text("old")
        result = execute_file_tool("write_file", {"path": str(f), "content": "new"})
        assert not result.is_error
        assert "Updated" in result.content
        assert f.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path):
        f = tmp_path / "sub" / "dir" / "file.txt"
        result = execute_file_tool("write_file", {"path": str(f), "content": "deep"})
        assert not result.is_error
        assert f.read_text() == "deep"


class TestEditFile:
    def test_exact_match(self, tmp_path):
        f = tmp_path / "edit.txt"
        f.write_text("hello world\nfoo bar\n")
        result = execute_file_tool(
            "edit_file",
            {"path": str(f), "old_text": "foo bar", "new_text": "baz qux"},
        )
        assert not result.is_error
        assert "Replaced 1" in result.content
        assert "baz qux" in f.read_text()

    def test_fuzzy_whitespace_match(self, tmp_path):
        f = tmp_path / "edit2.txt"
        f.write_text("  hello  world  \n")
        result = execute_file_tool(
            "edit_file",
            {"path": str(f), "old_text": "hello world", "new_text": "goodbye"},
        )
        assert not result.is_error
        # Should match via fuzzy strategies

    def test_no_match_returns_error(self, tmp_path):
        f = tmp_path / "edit3.txt"
        f.write_text("hello world\n")
        result = execute_file_tool(
            "edit_file",
            {"path": str(f), "old_text": "xyz not present", "new_text": "replacement"},
        )
        assert not result.is_error  # error in content, not flag
        assert "could not find" in result.content.lower()


class TestListDirectory:
    def test_list_basic(self, tmp_path):
        (tmp_path / "file1.txt").write_text("a")
        (tmp_path / "file2.py").write_text("b")
        (tmp_path / "subdir").mkdir()
        result = execute_file_tool("list_directory", {"path": str(tmp_path)})
        assert not result.is_error
        assert "file1.txt" in result.content
        assert "file2.py" in result.content
        assert "subdir/" in result.content

    def test_list_recursive(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.txt").write_text("x")
        result = execute_file_tool(
            "list_directory", {"path": str(tmp_path), "recursive": True}
        )
        assert not result.is_error
        assert "deep.txt" in result.content

    def test_list_missing_dir(self):
        result = execute_file_tool(
            "list_directory", {"path": "/tmp/nonexistent_dir_abc123"}
        )
        assert not result.is_error
        assert "not found" in result.content.lower()


class TestSearchFiles:
    def test_search_basic(self, tmp_path):
        (tmp_path / "a.py").write_text("def hello():\n    pass\n")
        (tmp_path / "b.py").write_text("def world():\n    pass\n")
        result = execute_file_tool(
            "search_files", {"pattern": "def hello", "path": str(tmp_path)}
        )
        assert not result.is_error
        assert "hello" in result.content

    def test_search_with_include(self, tmp_path):
        (tmp_path / "a.py").write_text("target line\n")
        (tmp_path / "b.txt").write_text("target line\n")
        result = execute_file_tool(
            "search_files",
            {"pattern": "target", "path": str(tmp_path), "include": "*.py"},
        )
        assert not result.is_error
        assert "a.py" in result.content

    def test_search_no_matches(self, tmp_path):
        (tmp_path / "a.txt").write_text("nothing here\n")
        result = execute_file_tool(
            "search_files", {"pattern": "zzz_nonexistent", "path": str(tmp_path)}
        )
        assert not result.is_error
        assert "no matches" in result.content.lower()


class TestRunCommand:
    def test_basic_command(self):
        result = execute_file_tool("run_command", {"command": "echo hello"})
        assert not result.is_error
        assert "hello" in result.content
        assert "exit code: 0" in result.content

    def test_command_with_cwd(self, tmp_path):
        result = execute_file_tool(
            "run_command", {"command": "pwd", "cwd": str(tmp_path)}
        )
        assert not result.is_error
        assert str(tmp_path) in result.content

    def test_command_failure(self):
        result = execute_file_tool(
            "run_command", {"command": "exit 1"}
        )
        assert not result.is_error  # error in content, not flag
        assert "exit code: 1" in result.content

    def test_command_timeout(self):
        result = execute_file_tool(
            "run_command", {"command": "sleep 10", "timeout": 1}
        )
        assert not result.is_error
        assert "timed out" in result.content.lower()


class TestExecuteUnknownTool:
    def test_unknown_tool(self):
        result = execute_file_tool("nonexistent_tool", {})
        assert result.is_error
        assert "Unknown" in result.content
