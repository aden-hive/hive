"""command_guard — browser kill/launch commands must be BLOCKED, not warned.

Every "incident" command below was actually run by a worker agent on
2026-06-11 (from ~/.config/Hive/logs/runtime.log) after its browser tools
hit a transport wedge: it killed the user's personal Chrome and relaunched
it on wrong profiles. The guard hard-blocks these across all three spawn
paths (terminal_exec, terminal_job_start, terminal_pty_run) while leaving
read-only process inspection untouched.
"""

from __future__ import annotations

import sys

import pytest

from terminal_tools.common.command_guard import check_command

INCIDENT_COMMANDS = [
    # 16:40:16 — scoped kill, then broad google-chrome kill
    'pkill -f "chrome.*silent-lime-narwhal" 2>/dev/null; pkill -f "google-chrome" 2>/dev/null; sleep 2; echo "done"',
    # 16:42:26 — SIGKILL everything matching chrome
    'pkill -9 -f chrome; sleep 3; echo "killed all chrome"',
    # 16:42:36 — kill by ps/grep pipeline (took the browser down)
    "kill $(ps aux | grep -v grep | grep -i chrome | awk '{print $2}') 2>/dev/null; sleep 2; echo \"done\"",
    # 16:44:07 — chromium variant
    'pkill -f "google-chrome"; echo "---"; pkill -f "chromium"; echo "---done"',
    # 16:44:28 — relaunch on the wrong profile
    "google-chrome --profile-directory=Default &",
    # 16:48:50 — relaunch, no-startup-window
    'google-chrome --no-startup-window 2>/dev/null &\ndisown\necho "started"',
    # 16:49:53 — nohup relaunch
    "nohup google-chrome --profile-directory=Default > /dev/null 2>&1 &",
    # 16:50:03 — invented CDP launch bypassing the bridge
    "google-chrome --remote-debugging-port=9222 --no-first-run --no-default-browser-check "
    "--user-data-dir=/home/timothy/.config/Hive/browser-profiles/keen-emerald-civet &>/dev/null &\necho $?",
]

ESCALATION_COMMANDS = [
    "ps aux | grep chrome | xargs kill -9",
    "ps aux | grep -i electron | awk '{print $2}' | xargs kill",
    "pkill -f bridge_host",
    "pkill -f gcu.server",
    "killall electron",
    "killall -9 chromium-browser",
    "setsid chromium --headless &",
    "/opt/google/chrome/chrome --profile-directory=Default",
]

BENIGN_COMMANDS = [
    # Read-only process inspection (workers legitimately did these too)
    "ps aux | grep -i chrome | head -5",
    "ps aux | grep -i chrome | grep -v grep | wc -l",
    'ps aux | grep -i "gcu\\|bridge" | grep -v grep',
    'which google-chrome google-chrome-stable chromium chromium-browser 2>/dev/null || echo "not found"',
    "pgrep -P 1234",
    # Generic kills not aimed at the browser/runtime
    "kill 5555",
    "kill -9 12345",
    "pkill -f my_python_script.py",
    "killall sleep",
    # Mentions of chrome that aren't kill/launch
    "grep -i chrome /tmp/page.html",
    'grep -n "reaction" /tmp/browser_interact_99.txt',
    "echo google-chrome is installed",
    "ls /opt/google/chrome/",
    "cat /home/x/chrome_notes.txt",
]


@pytest.mark.parametrize("cmd", INCIDENT_COMMANDS + ESCALATION_COMMANDS)
def test_kill_and_launch_commands_blocked(cmd):
    msg = check_command(cmd)
    assert msg is not None, f"guard MISSED: {cmd!r}"
    assert "BLOCKED" in msg
    # The message must teach the correct recovery, not just refuse.
    assert "hive-browser tab close" in msg and "report_to_parent" in msg


@pytest.mark.parametrize("cmd", BENIGN_COMMANDS)
def test_benign_commands_pass(cmd):
    assert check_command(cmd) is None, f"false positive: {cmd!r}"


def test_argv_list_form_blocked():
    assert check_command(["pkill", "-9", "-f", "chrome"]) is not None
    assert check_command(["google-chrome", "--profile-directory=Default"]) is not None
    assert check_command(["ls", "-la"]) is None


# --- integration: all three spawn paths refuse before spawning ---


@pytest.fixture
def exec_tool(mcp):
    from terminal_tools.exec import register_exec_tools

    register_exec_tools(mcp)
    return mcp._tool_manager._tools["terminal_exec"].fn


@pytest.fixture
def job_start_tool(mcp):
    from terminal_tools.jobs.tools import register_job_tools

    register_job_tools(mcp)
    return mcp._tool_manager._tools["terminal_job_start"].fn


@pytest.fixture
def pty_tools(mcp):
    from terminal_tools.pty.tools import register_pty_tools

    register_pty_tools(mcp)
    return mcp._tool_manager._tools


def test_terminal_exec_blocks_before_spawn(exec_tool):
    result = exec_tool(command="pkill -9 -f chrome")
    assert result.get("blocked") is True
    assert result["exit_code"] is None  # nothing was spawned
    assert result["pid"] is None
    assert "BLOCKED" in result["error"]


def test_terminal_exec_still_runs_benign(exec_tool):
    result = exec_tool(command="echo chrome status check")
    assert result.get("blocked") is None
    assert result["exit_code"] == 0


def test_terminal_job_start_blocks(job_start_tool):
    result = job_start_tool(command="nohup google-chrome --profile-directory=Default &", shell=True)
    assert result.get("blocked") is True
    assert "BLOCKED" in result["error"]
    assert "job_id" not in result


@pytest.mark.skipif(sys.platform == "win32", reason="PTY tools are POSIX-only (not supported on Windows)")
def test_terminal_pty_run_blocks_both_modes(pty_tools):
    open_fn = pty_tools["terminal_pty_open"].fn
    run_fn = pty_tools["terminal_pty_run"].fn
    close_fn = pty_tools["terminal_pty_close"].fn

    opened = open_fn()
    assert "session_id" in opened, f"pty open failed: {opened}"
    sid = opened["session_id"]
    try:
        blocked = run_fn(session_id=sid, command='pkill -f "google-chrome"')
        assert blocked.get("blocked") is True
        # raw_send types straight into live bash — must be guarded too
        blocked_raw = run_fn(session_id=sid, command="killall chrome\n", raw_send=True)
        assert blocked_raw.get("blocked") is True
        # benign still works
        ok = run_fn(session_id=sid, command="echo hi")
        assert "hi" in ok.get("output", "")
    finally:
        close_fn(session_id=sid, force=True)
