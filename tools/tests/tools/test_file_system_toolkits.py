"""Tests for file_system_toolkits tools (FastMCP)."""

import asyncio
import json
import os
from unittest.mock import patch

import pytest
from fastmcp import FastMCP


@pytest.fixture(autouse=True)
def _bypass_stale_edit_guard():
    """These tests exercise edit logic directly without a prior read_file,
    so the Gap 4 stale-edit guard would reject every call. Force
    check_fresh to always return FRESH here; the cache itself is
    covered by ``tools/tests/test_file_state_cache.py``.
    """
    from aden_tools.file_state_cache import FreshResult, Freshness
    with patch(
        "aden_tools.tools.file_system_toolkits.hashline_edit."
        "hashline_edit.check_fresh",
        return_value=FreshResult(Freshness.FRESH),
    ):
        yield


@pytest.fixture
def mcp():
    """Create a FastMCP instance."""
    return FastMCP("test-server")


@pytest.fixture
def mock_workspace():
    """Mock agent ID."""
    return {
        "agent_id": "test-agent",
    }


@pytest.fixture
def mock_secure_path(tmp_path):
    """Mock resolve_safe_path to return temp directory paths."""

    def _resolve_safe_path(path, *args, **kwargs):
        return os.path.join(tmp_path, path)

    with patch(
        "aden_tools.tools.file_system_toolkits.list_dir.list_dir.resolve_safe_path",
        side_effect=_resolve_safe_path,
    ):
        with patch(
            "aden_tools.tools.file_system_toolkits.replace_file_content.replace_file_content.resolve_safe_path",
            side_effect=_resolve_safe_path,
        ):
            with patch(
                "aden_tools.tools.file_system_toolkits.apply_diff.apply_diff.resolve_safe_path",
                side_effect=_resolve_safe_path,
            ):
                with patch(
                    "aden_tools.tools.file_system_toolkits.apply_patch.apply_patch.resolve_safe_path",
                    side_effect=_resolve_safe_path,
                ):
                    with patch(
                        "aden_tools.tools.file_system_toolkits.grep_search.grep_search.resolve_safe_path",
                        side_effect=_resolve_safe_path,
                    ):
                        with patch(
                            "aden_tools.tools.file_system_toolkits.execute_command_tool.execute_command_tool._resolve_cwd",
                            return_value=str(tmp_path),
                        ):
                            with patch(
                                "aden_tools.tools.file_system_toolkits.hashline_edit.hashline_edit.resolve_safe_path",
                                side_effect=_resolve_safe_path,
                            ):
                                yield


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
        (tmp_path / "file1.txt").write_text("content", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("content", encoding="utf-8")
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
        (tmp_path / "small.txt").write_text("hi", encoding="utf-8")
        (tmp_path / "larger.txt").write_text("hello world", encoding="utf-8")
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
        test_file.write_text("Hello World! Hello again!", encoding="utf-8")

        result = replace_file_content_fn(
            path="replace_test.txt", target="Hello", replacement="Hi", **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 2
        assert test_file.read_text(encoding="utf-8") == "Hi World! Hi again!"

    def test_replace_target_not_found(
        self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Replacing non-existent target returns error."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello World", encoding="utf-8")

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
        test_file.write_text("Hello World", encoding="utf-8")

        result = replace_file_content_fn(
            path="single.txt", target="Hello", replacement="Hi", **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 1
        assert test_file.read_text(encoding="utf-8") == "Hi World"

    def test_replace_multiline_content(
        self, replace_file_content_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Replacing content across multiple lines works correctly."""
        test_file = tmp_path / "multiline.txt"
        test_file.write_text("Line 1\nTODO: fix this\nLine 3\nTODO: add tests\n", encoding="utf-8")

        result = replace_file_content_fn(
            path="multiline.txt", target="TODO:", replacement="DONE:", **mock_workspace
        )

        assert result["success"] is True
        assert result["occurrences_replaced"] == 2
        expected = "Line 1\nDONE: fix this\nLine 3\nDONE: add tests\n"
        assert test_file.read_text(encoding="utf-8") == expected


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
        test_file.write_text("Line 1\nLine 2 with pattern\nLine 3", encoding="utf-8")

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
        test_file.write_text("Hello World", encoding="utf-8")

        result = grep_search_fn(path="test.txt", pattern="nonexistent", **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 0
        assert result["matches"] == []

    def test_grep_search_directory_non_recursive(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching directory non-recursively only searches immediate files."""
        # Create files in root
        (tmp_path / "file1.txt").write_text("pattern here", encoding="utf-8")
        (tmp_path / "file2.txt").write_text("no match here", encoding="utf-8")

        # Create nested directory with file
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("pattern in nested", encoding="utf-8")

        result = grep_search_fn(path=".", pattern="pattern", recursive=False, **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 1  # Only finds pattern in root, not in nested
        assert result["recursive"] is False

    def test_grep_search_directory_recursive(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching directory recursively finds matches in subdirectories."""
        # Create files in root
        (tmp_path / "file1.txt").write_text("pattern here", encoding="utf-8")

        # Create nested directory with file
        nested = tmp_path / "nested"
        nested.mkdir()
        (nested / "nested_file.txt").write_text("pattern in nested", encoding="utf-8")

        result = grep_search_fn(path=".", pattern="pattern", recursive=True, **mock_workspace)

        assert result["success"] is True
        assert result["total_matches"] == 2  # Finds pattern in both files
        assert result["recursive"] is True

    def test_grep_search_regex_pattern(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Searching with regex pattern finds complex matches."""
        test_file = tmp_path / "regex_test.txt"
        test_file.write_text("foo123bar\nfoo456bar\nbaz789baz\n", encoding="utf-8")

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
        test_file.write_text("hello hello hello\nworld\nhello again", encoding="utf-8")

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

    async def test_execute_simple_command(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """Executing a simple command returns output."""
        result = await execute_command_fn(command="echo 'Hello World'", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "Hello World" in result["stdout"]

    async def test_execute_failing_command(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """Executing a failing command returns non-zero exit code."""
        result = await execute_command_fn(command="exit 1", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 1

    async def test_execute_command_with_stderr(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """Executing a command that writes to stderr captures it."""
        result = await execute_command_fn(
            command="echo 'error message' >&2", **mock_workspace
        )

        assert result["success"] is True
        assert "error message" in result.get("stderr", "")

    async def test_execute_command_list_files(
        self, execute_command_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Executing ls command lists files."""
        # Create a test file
        (tmp_path / "testfile.txt").write_text("content", encoding="utf-8")

        result = await execute_command_fn(command=f"ls {tmp_path}", **mock_workspace)

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "testfile.txt" in result["stdout"]

    async def test_execute_command_with_pipe(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """Executing a command with pipe works correctly."""
        result = await execute_command_fn(
            command="echo 'hello world' | tr 'a-z' 'A-Z'", **mock_workspace
        )

        assert result["success"] is True
        assert result["return_code"] == 0
        assert "HELLO WORLD" in result["stdout"]

    # ── Gap 3: async, per-call timeout, background jobs ──────────────

    @pytest.fixture
    def bash_output_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.execute_command_tool import (
            register_tools,
        )

        register_tools(mcp)
        return mcp._tool_manager._tools["bash_output"].fn

    @pytest.fixture
    def bash_kill_fn(self, mcp):
        from aden_tools.tools.file_system_toolkits.execute_command_tool import (
            register_tools,
        )

        register_tools(mcp)
        return mcp._tool_manager._tools["bash_kill"].fn

    async def test_per_call_timeout_overrides_default(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """A per-call timeout under the default kills the command early."""
        import time

        start = time.monotonic()
        result = await execute_command_fn(
            command="sleep 10",
            timeout_seconds=1,
            **mock_workspace,
        )
        elapsed = time.monotonic() - start

        assert result.get("timed_out") is True
        assert "1 seconds" in result.get("error", "")
        # Must include the watchdog grace but stay well under 10s.
        assert elapsed < 5, f"timeout did not kill the command promptly ({elapsed:.2f}s)"

    async def test_timeout_is_clamped_upwards(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """A timeout above the 600s ceiling is silently clamped."""
        # We don't actually sleep 600s - we just run a quick command
        # with a nonsense timeout to prove the clamp doesn't raise.
        result = await execute_command_fn(
            command="echo fast",
            timeout_seconds=99999,
            **mock_workspace,
        )
        assert result["success"] is True
        assert "fast" in result["stdout"]

    async def test_event_loop_unblocked_while_command_runs(
        self, execute_command_fn, mock_workspace, mock_secure_path
    ):
        """The event loop keeps servicing other tasks while a bash
        command is running, unlike the old blocking subprocess.run."""
        ticks = 0

        async def ticker():
            nonlocal ticks
            for _ in range(20):
                await asyncio.sleep(0.05)
                ticks += 1

        ticker_task = asyncio.create_task(ticker())
        # A 0.5s command: if the event loop were blocked, ticks would
        # stay at 0 until it returned. We expect several ticks to land.
        result = await execute_command_fn(command="sleep 0.5", **mock_workspace)
        await ticker_task

        assert result["success"] is True
        assert ticks >= 5, (
            f"event loop looked blocked during subprocess "
            f"(only {ticks} ticks in 1s)"
        )

    async def test_background_job_start_poll_and_complete(
        self,
        execute_command_fn,
        bash_output_fn,
        mock_workspace,
        mock_secure_path,
    ):
        """A run_in_background job can be started, polled, and reports
        its exit status once the command finishes."""
        start_result = await execute_command_fn(
            command=(
                "python -c 'import time,sys;"
                "print(\"one\");sys.stdout.flush();time.sleep(0.1);"
                "print(\"two\");sys.stdout.flush();time.sleep(0.1);"
                "print(\"three\")'"
            ),
            run_in_background=True,
            **mock_workspace,
        )
        assert start_result["background"] is True
        job_id = start_result["id"]

        # Wait for the command to finish.
        deadline = asyncio.get_event_loop().time() + 5.0
        seen_text = ""
        while asyncio.get_event_loop().time() < deadline:
            poll = await bash_output_fn(id=job_id, **mock_workspace)
            seen_text += poll["stdout"]
            if poll["status"].startswith("exited"):
                break
            await asyncio.sleep(0.05)

        assert "one" in seen_text
        assert "two" in seen_text
        assert "three" in seen_text
        assert poll["status"] == "exited(0)"

    async def test_background_job_kill(
        self,
        execute_command_fn,
        bash_output_fn,
        bash_kill_fn,
        mock_workspace,
        mock_secure_path,
    ):
        """bash_kill terminates a long-running background job."""
        start_result = await execute_command_fn(
            command="sleep 30",
            run_in_background=True,
            **mock_workspace,
        )
        job_id = start_result["id"]

        kill_result = await bash_kill_fn(id=job_id, **mock_workspace)
        assert kill_result["id"] == job_id
        assert (
            "terminated" in kill_result["status"]
            or "killed" in kill_result["status"]
        )

        # Job id should be deregistered after kill.
        poll = await bash_output_fn(id=job_id, **mock_workspace)
        assert "no background job" in poll.get("error", "")

    async def test_bash_output_isolated_across_agents(
        self, execute_command_fn, bash_output_fn, mock_secure_path
    ):
        """Agent A's job id is not reachable from agent B."""
        start = await execute_command_fn(
            command="sleep 5",
            run_in_background=True,
            agent_id="agent-A",
        )
        poll_b = await bash_output_fn(id=start["id"], agent_id="agent-B")
        assert "no background job" in poll_b.get("error", "")

        # Clean up.
        from aden_tools.tools.file_system_toolkits.execute_command_tool import (
            background_jobs,
        )

        await background_jobs.clear_agent("agent-A")


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
        test_file.write_text("Hello World", encoding="utf-8")

        # Create a simple diff using diff_match_patch format
        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        patches = dmp.patch_make("Hello World", "Hello Universe")
        diff_text = dmp.patch_toText(patches)

        result = apply_diff_fn(path="diff_test.txt", diff_text=diff_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert result["patches_applied"] > 0
        assert test_file.read_text(encoding="utf-8") == "Hello Universe"

    def test_apply_diff_multiline(self, apply_diff_fn, mock_workspace, mock_secure_path, tmp_path):
        """Applying diff to multiline content works correctly."""
        test_file = tmp_path / "multiline.txt"
        original = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(original, encoding="utf-8")

        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        modified = "Line 1\nModified Line 2\nLine 3\n"
        patches = dmp.patch_make(original, modified)
        diff_text = dmp.patch_toText(patches)

        result = apply_diff_fn(path="multiline.txt", diff_text=diff_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text(encoding="utf-8") == modified

    def test_apply_diff_invalid_patch(
        self, apply_diff_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying an invalid diff handles gracefully."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content, encoding="utf-8")

        # Invalid diff text
        result = apply_diff_fn(path="test.txt", diff_text="invalid diff format", **mock_workspace)

        # Should either error or show no patches applied
        if "error" not in result:
            assert result.get("patches_applied", 0) == 0
        # File should remain unchanged
        assert test_file.read_text(encoding="utf-8") == original_content


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
        test_file.write_text("Hello World", encoding="utf-8")

        # Create a simple patch using diff_match_patch format
        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        patches = dmp.patch_make("Hello World", "Hello Python")
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(path="patch_test.txt", patch_text=patch_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert result["patches_applied"] > 0
        assert test_file.read_text(encoding="utf-8") == "Hello Python"

    def test_apply_patch_multiline(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying patch to multiline content works correctly."""
        test_file = tmp_path / "multiline.txt"
        original = "Line 1\nLine 2\nLine 3\n"
        test_file.write_text(original, encoding="utf-8")

        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        modified = "Line 1\nModified Line 2\nLine 3\n"
        patches = dmp.patch_make(original, modified)
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(path="multiline.txt", patch_text=patch_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text(encoding="utf-8") == modified

    def test_apply_patch_invalid_patch(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying an invalid patch handles gracefully."""
        test_file = tmp_path / "test.txt"
        original_content = "Original content"
        test_file.write_text(original_content, encoding="utf-8")

        # Invalid patch text
        result = apply_patch_fn(
            path="test.txt", patch_text="invalid patch format", **mock_workspace
        )

        # Should either error or show no patches applied
        if "error" not in result:
            assert result.get("patches_applied", 0) == 0
        # File should remain unchanged
        assert test_file.read_text(encoding="utf-8") == original_content

    def test_apply_patch_multiple_changes(
        self, apply_patch_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """Applying patch with multiple changes works correctly."""
        test_file = tmp_path / "complex.txt"
        original = "Function foo() {\n  return 42;\n}\n"
        test_file.write_text(original, encoding="utf-8")

        import diff_match_patch as dmp_module

        dmp = dmp_module.diff_match_patch()
        modified = "Function bar() {\n  return 100;\n}\n"
        patches = dmp.patch_make(original, modified)
        patch_text = dmp.patch_toText(patches)

        result = apply_patch_fn(path="complex.txt", patch_text=patch_text, **mock_workspace)

        assert result["success"] is True
        assert result["all_successful"] is True
        assert test_file.read_text(encoding="utf-8") == modified


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

    def test_hashline_skips_large_files_with_notice(
        self, grep_search_fn, mock_workspace, mock_secure_path, tmp_path
    ):
        """hashline=True skips files > 10MB and reports them in the response."""
        search_dir = tmp_path / "search_dir"
        search_dir.mkdir()

        small_file = search_dir / "small.txt"
        small_file.write_text("hello world\n")

        large_file = search_dir / "large.txt"
        # Write just over 10MB
        large_file.write_bytes(b"hello large\n" * (1024 * 1024))

        result = grep_search_fn(
            path="search_dir", pattern="hello", hashline=True, recursive=True, **mock_workspace
        )

        assert result["success"] is True
        assert "skipped_large_files" in result
        assert any("large.txt" in f for f in result["skipped_large_files"])
        # Small file should still have matches
        assert result["total_matches"] >= 1


class TestHashlineCrossToolConsistency:
    """Cross-tool consistency tests for hashline workflows."""

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
        grep_search_fn,
        hashline_edit_fn,
        mock_workspace,
        mock_secure_path,
        tmp_path,
    ):
        """Anchors from grep hashline mode should be consumable by hashline_edit."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("A\u2028B\nC\n", encoding="utf-8")

        # grep_search line iteration treats U+2028 as in-line content
        grep_res = grep_search_fn(path="test.txt", pattern="B", hashline=True, **mock_workspace)
        assert grep_res["success"] is True
        assert grep_res["total_matches"] == 1

        anchor = grep_res["matches"][0]["anchor"]
        edits = json.dumps([{"op": "set_line", "anchor": anchor, "content": "X"}])
        edit_res = hashline_edit_fn(path="test.txt", edits=edits, **mock_workspace)

        assert "error" not in edit_res, edit_res.get("error")
        assert edit_res["success"] is True
