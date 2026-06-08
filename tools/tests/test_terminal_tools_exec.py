"""terminal_exec — envelope shape, semantic exits, warnings, auto-promotion."""

from __future__ import annotations

import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="terminal_tools is POSIX-only (uses resource module)")


@pytest.fixture
def exec_tool(mcp):
    from terminal_tools.exec import register_exec_tools

    register_exec_tools(mcp)
    return mcp._tool_manager._tools["terminal_exec"].fn


def test_envelope_shape_simple_echo(exec_tool):
    result = exec_tool(command="echo hello world")
    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "hello world"
    assert result["stderr"] == ""
    assert result["semantic_status"] == "ok"
    assert result["timed_out"] is False
    assert result["auto_backgrounded"] is False
    assert result["job_id"] is None
    assert result["warning"] is None
    assert result["pid"] is not None


def test_grep_no_matches_is_ok_not_error(exec_tool, tmp_path):
    f = tmp_path / "haystack.txt"
    f.write_text("apples\nbananas\n")
    result = exec_tool(command=f"grep zzz {f}")
    assert result["exit_code"] == 1
    assert result["semantic_status"] == "ok"
    assert "No matches found" in (result["semantic_message"] or "")


def test_diff_files_differ_is_ok_not_error(exec_tool, tmp_path):
    a = tmp_path / "a.txt"
    a.write_text("hi\n")
    b = tmp_path / "b.txt"
    b.write_text("bye\n")
    result = exec_tool(command=f"diff {a} {b}")
    assert result["exit_code"] == 1
    assert result["semantic_status"] == "ok"
    assert "differ" in (result["semantic_message"] or "")


def test_destructive_warning_for_rm_rf(exec_tool, tmp_path):
    # Don't actually delete anything — point at a missing path so the
    # command exits non-zero but the warning still fires from regex.
    target = tmp_path / "definitely_missing_dir"
    result = exec_tool(command=f"rm -rf {target}")
    assert result["warning"] is not None
    assert "force-remove" in result["warning"] or "recursively" in result["warning"]


def test_destructive_warning_drop_table(exec_tool):
    # Run `true` so the test doesn't depend on echo behavior; pass the
    # destructive text via stdin so the regex still matches the command.
    result = exec_tool(command="echo 'DROP TABLE users;'", shell=True)
    assert result["warning"] is not None
    assert "drop" in result["warning"].lower() or "truncate" in result["warning"].lower()


def test_command_not_found(exec_tool):
    result = exec_tool(command="this_command_does_not_exist_xyzzy")
    assert result["exit_code"] is None or result["exit_code"] != 0
    # Either pre-spawn FileNotFoundError or shell exit 127 — both are fine
    # as long as semantic_status reflects an error or the error field is set.
    assert (
        result["semantic_status"] == "error"
        or result.get("error")
        or "not found" in (result["semantic_message"] or "").lower()
    )


def test_zsh_refused(exec_tool):
    result = exec_tool(command="echo hi", shell=True)
    # shell=True (the bool) → /bin/bash → succeeds
    assert result["exit_code"] == 0


def test_zsh_string_refused():
    """Calling _resolve_shell with zsh path raises ZshRefused."""
    from terminal_tools.common.limits import ZshRefused, _resolve_shell

    with pytest.raises(ZshRefused):
        _resolve_shell("/bin/zsh")
    with pytest.raises(ZshRefused):
        _resolve_shell("/usr/local/bin/zsh")


def test_truncation_via_handle(exec_tool):
    """Generate >256 KB of output, verify output_handle is returned."""
    # Generate ~300 KB of output
    result = exec_tool(
        command="python3 -c 'import sys; sys.stdout.write(\"x\" * 300_000)'",
        shell=True,
        max_output_kb=128,  # smaller cap to force truncation
    )
    assert result["exit_code"] == 0
    assert result["stdout_truncated_bytes"] > 0
    assert result["output_handle"] is not None
    assert result["output_handle"].startswith("out_")


def test_output_handle_round_trip(exec_tool, mcp):
    from terminal_tools.output import register_output_tools

    register_output_tools(mcp)
    output_get = mcp._tool_manager._tools["terminal_output_get"].fn

    result = exec_tool(
        command="python3 -c 'import sys; sys.stdout.write(\"x\" * 300_000)'",
        shell=True,
        max_output_kb=64,
    )
    handle = result["output_handle"]
    assert handle is not None

    # First page
    page = output_get(output_handle=handle, since_offset=0, max_kb=64)
    assert page["expired"] is False
    assert len(page["data"]) > 0
    assert page["next_offset"] > 0

    # Bogus handle
    bogus = output_get(output_handle="out_doesnotexist", since_offset=0, max_kb=64)
    assert bogus["expired"] is True


def test_timed_out_marker(exec_tool):
    result = exec_tool(command="sleep 5", timeout_sec=1, auto_background_after_sec=0)
    assert result["timed_out"] is True


def test_auto_shell_for_pipelines(exec_tool):
    """Regression for the queen_technology session 152038 silent-mangling bug.

    The agent passed shell=False (default) with a pipeline command. The naive
    command.split() spawned the first program with the rest as junk argv —
    `ps aux | sort ...` produced "ps: error: garbage option", and `echo "..."
    && ps ...` produced fake-success output where echo printed the entire
    rest of the command verbatim. Fix: detect shell metacharacters and
    transparently route through bash -c.
    """
    # Case 1: pipeline. Was: ps spawned with "aux | sort ..." as argv → garbage option.
    result = exec_tool(command="ps aux | head -1")
    assert result["exit_code"] == 0, result
    assert result["auto_shell"] is True
    assert "USER" in result["stdout"] or "PID" in result["stdout"]
    assert "garbage option" not in (result.get("stderr") or "")

    # Case 2: && + pipe + awk. Was: echo printed the whole rest of the line.
    result = exec_tool(
        command="echo HEADER && echo line1 | head -1",
    )
    assert result["exit_code"] == 0, result
    assert result["auto_shell"] is True
    assert "HEADER" in result["stdout"]
    assert "line1" in result["stdout"]
    # The literal "&&" must NOT appear in stdout — that would mean echo
    # captured it as an argument again.
    assert "&&" not in result["stdout"]

    # Case 3: redirect + glob. Was: '*' passed as a literal arg to ls.
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        with open(os.path.join(tmp, "a.txt"), "w") as f:
            f.write("x")
        with open(os.path.join(tmp, "b.txt"), "w") as f:
            f.write("y")
        result = exec_tool(command=f"ls {tmp}/*.txt")
        assert result["exit_code"] == 0, result
        assert result["auto_shell"] is True
        assert "a.txt" in result["stdout"]
        assert "b.txt" in result["stdout"]


def test_no_auto_shell_for_argv_commands(exec_tool):
    """Plain argv commands (no metacharacters) should NOT auto-route to bash.
    Direct exec is faster and avoids quoting hazards."""
    result = exec_tool(command="echo hello")
    assert result["exit_code"] == 0
    assert result["auto_shell"] is False
    assert result["stdout"].strip() == "hello"


def test_explicit_shell_true_unchanged(exec_tool):
    """When the agent explicitly opts in via shell=True, auto_shell stays
    False — auto-detection only fires for shell=False."""
    result = exec_tool(command="echo a | tr a b", shell=True)
    assert result["exit_code"] == 0
    assert result["auto_shell"] is False
    assert result["stdout"].strip() == "b"


def test_auto_promotion(exec_tool, mcp):
    """Past auto_background_after_sec, the call returns auto_backgrounded=True."""
    from terminal_tools.jobs.tools import register_job_tools

    register_job_tools(mcp)
    # Use a 1s budget so the test runs quickly.
    start = time.monotonic()
    result = exec_tool(
        command="sleep 5",
        auto_background_after_sec=1,
        timeout_sec=10,
    )
    elapsed = time.monotonic() - start
    assert result["auto_backgrounded"] is True, result
    assert result["job_id"] is not None
    assert result["exit_code"] is None
    assert elapsed < 3, "auto-promotion should return quickly past the budget"

    # Take over via terminal_job_logs
    job_logs = mcp._tool_manager._tools["terminal_job_logs"].fn
    log_result = job_logs(job_id=result["job_id"], wait_until_exit=True, wait_timeout_sec=10)
    assert log_result["status"] == "exited"
    assert log_result["exit_code"] == 0
