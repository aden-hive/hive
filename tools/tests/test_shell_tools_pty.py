"""PTY sessions: bash-on-macOS, prompt sentinel, raw I/O, zsh refusal."""

from __future__ import annotations

import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="PTY is POSIX-only")


@pytest.fixture
def pty_tools(mcp):
    from shell_tools.pty.tools import register_pty_tools

    register_pty_tools(mcp)
    return {
        "open": mcp._tool_manager._tools["shell_pty_open"].fn,
        "run": mcp._tool_manager._tools["shell_pty_run"].fn,
        "close": mcp._tool_manager._tools["shell_pty_close"].fn,
    }


def test_open_close_basic(pty_tools):
    opened = pty_tools["open"]()
    assert "session_id" in opened
    assert opened["shell"] == "/bin/bash", "shell-tools must default to bash, not zsh"
    closed = pty_tools["close"](session_id=opened["session_id"])
    assert closed.get("already_closed") in (False, None)


def test_bash_on_darwin():
    """Even on macOS, the resolved shell is /bin/bash, not /bin/zsh."""
    from shell_tools.common.limits import _resolve_shell

    assert _resolve_shell(True) == "/bin/bash"


def test_pty_run_command(pty_tools):
    opened = pty_tools["open"]()
    sid = opened["session_id"]
    try:
        result = pty_tools["run"](session_id=sid, command="echo hello-pty", timeout_sec=5)
        assert result.get("timed_out") is False
        assert "hello-pty" in result["output"]
        assert result["prompt_after"] is True
    finally:
        pty_tools["close"](session_id=sid)


def test_pty_state_persists(pty_tools):
    opened = pty_tools["open"]()
    sid = opened["session_id"]
    try:
        pty_tools["run"](session_id=sid, command="MY_VAR=42")
        result = pty_tools["run"](session_id=sid, command="echo $MY_VAR", timeout_sec=3)
        assert "42" in result["output"]
    finally:
        pty_tools["close"](session_id=sid)


def test_raw_send_then_read_only(pty_tools):
    """Drive the python REPL via raw_send + read_only."""
    opened = pty_tools["open"]()
    sid = opened["session_id"]
    try:
        # Launch python with our own prompt regex
        pty_tools["run"](
            session_id=sid,
            command="python3 -q",
            expect=r">>>\s*$",
            timeout_sec=10,
        )
        pty_tools["run"](session_id=sid, command="x = 7\n", raw_send=True)
        pty_tools["run"](session_id=sid, command="print(x*x)\n", raw_send=True)
        time.sleep(0.5)
        drained = pty_tools["run"](session_id=sid, read_only=True, timeout_sec=2)
        assert "49" in drained["output"]
    finally:
        pty_tools["close"](session_id=sid, force=True)


def test_session_busy(pty_tools):
    """Concurrent run() calls on the same session return 'session busy'."""
    import threading

    opened = pty_tools["open"]()
    sid = opened["session_id"]
    try:
        results = []

        def run_long():
            results.append(pty_tools["run"](session_id=sid, command="sleep 2", timeout_sec=5))

        t = threading.Thread(target=run_long)
        t.start()
        time.sleep(0.2)
        # Concurrent call should fail
        result = pty_tools["run"](session_id=sid, command="echo nope", timeout_sec=1)
        assert "error" in result and "busy" in result["error"].lower()
        t.join(timeout=10)
    finally:
        pty_tools["close"](session_id=sid, force=True)


def test_unknown_session(pty_tools):
    result = pty_tools["run"](session_id="pty_doesnotexist", command="ls")
    assert "error" in result
