"""Exercise real process ownership, deadlines and retrieval on Windows/POSIX."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from terminal_tools.common.limits import ShellSpec
from terminal_tools.exec import register_exec_tools
from terminal_tools.jobs.manager import JobManager
from terminal_tools.jobs.tools import register_job_tools


@pytest.fixture
def terminal(mcp, monkeypatch):
    manager = JobManager()
    monkeypatch.setattr("terminal_tools.jobs.manager._MANAGER", manager)
    # Exercise real child processes without depending on a particular shell.
    monkeypatch.setattr("terminal_tools.exec.resolve_shell_spec", lambda _: ShellSpec(sys.executable, ("-c",), "direct"))
    register_exec_tools(mcp)
    register_job_tools(mcp)
    yield {name: tool.fn for name, tool in mcp._tool_manager._tools.items()}
    manager.shutdown_all(grace_sec=0)


def _run(terminal, script, **kwargs):
    return terminal["terminal_exec"](command=script, shell=True, **kwargs)


def _logs(terminal, result):
    return terminal["terminal_job_logs"](job_id=result["job_id"], wait_until_exit=True, wait_timeout_sec=5)


def test_finishes_before_deadline(terminal):
    result = _run(terminal, "print('complete')", timeout_sec=5, auto_background_after_sec=0)
    assert result["exit_code"] == 0, result
    assert result["stdout"].strip() == "complete"
    assert not result["timed_out"]


@pytest.mark.parametrize("promotion", [0, 0.5, 2])
def test_deadline_before_or_at_promotion_kills_inline(terminal, promotion):
    result = _run(terminal, "import time; print('before', flush=True); time.sleep(30)", timeout_sec=0.5, auto_background_after_sec=promotion)
    assert result["timed_out"], result
    assert not result["auto_backgrounded"]
    assert result["job_id"] is None
    assert "before" in result["stdout"]


def test_promotion_preserves_deadline_output_and_start_time(terminal):
    started = time.monotonic()
    result = _run(terminal, "import time; print('before', flush=True); time.sleep(30)", timeout_sec=0.8, auto_background_after_sec=0.2)
    assert result["auto_backgrounded"], result
    final = _logs(terminal, result)
    assert final["status"] == "exited"
    assert final["timed_out"]
    assert final["exit_code"] != 0
    assert "before" in final["data"]
    assert final["runtime_ms"] >= 750
    assert time.monotonic() - started < 5
    summary = terminal["terminal_job_manage"](action="list")["jobs"][0]
    assert summary["timed_out"]


def test_unlimited_command_promotes_and_finishes(terminal):
    result = _run(terminal, "import time; time.sleep(0.3); print('complete')", timeout_sec=0, auto_background_after_sec=0.1)
    final = _logs(terminal, result)
    assert final["exit_code"] == 0
    assert not final["timed_out"]
    assert final["data"].strip() == "complete"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows process-control contract")
@pytest.mark.parametrize("stop_action", ["signal_term", "signal_kill"])
def test_windows_interrupt_is_rejected_and_supported_stop_exits(terminal, stop_action):
    result = _run(terminal, "import time; print('ready', flush=True); time.sleep(30)", timeout_sec=0, auto_background_after_sec=0.1)
    manage = terminal["terminal_job_manage"]
    rejected = manage(action="signal_int", job_id=result["job_id"])
    assert rejected["code"] == "unsupported_action"
    assert rejected["capabilities"] == manage(action="capabilities")
    current = terminal["terminal_job_logs"](job_id=result["job_id"])
    assert current["status"] == "running"
    stopped = manage(action=stop_action, job_id=result["job_id"])
    assert stopped["ok"]
    assert "Forcefully" in stopped["semantics"]
    assert _logs(terminal, result)["status"] == "exited"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"timeout_sec": 0, "auto_background_after_sec": 0},
        {"timeout_sec": 221, "auto_background_after_sec": 0},
        {"timeout_sec": -1},
        {"auto_background_after_sec": -1},
        {"timeout_sec": float("inf")},
        {"auto_background_after_sec": float("nan")},
    ],
)
def test_invalid_budgets_do_not_spawn(terminal, kwargs, monkeypatch):
    def forbidden(*args, **kw):
        pytest.fail("invalid budget spawned a process")

    monkeypatch.setattr("terminal_tools.exec.spawn_process", forbidden)
    result = _run(terminal, "print('unexpected')", **kwargs)
    assert result["error"]


@pytest.mark.parametrize("env", [None, {}])
def test_sanitizes_inherited_env(terminal, monkeypatch, env):
    monkeypatch.setenv("ZSH_HIVE_TEST", "strip")
    monkeypatch.setenv("HIVE_TEST_KEEP", "keep")
    result = _run(terminal, "import os; print(os.getenv('ZSH_HIVE_TEST')); print(os.getenv('HIVE_TEST_KEEP'))", env=env)
    assert result["stdout"].splitlines() == ["None", "keep"]


def test_preserves_overrides_and_framework_identity(terminal):
    result = _run(
        terminal,
        "import os; print(os.getenv('HIVE_TEST_KEEP')); print(os.getenv('HIVE_CRM_PRINCIPAL'))",
        env={"HIVE_TEST_KEEP": "override"},
        crm_principal="audit",
    )
    assert result["stdout"].splitlines() == ["override", "audit"]


@pytest.mark.parametrize("env", [None, {}])
def test_explicit_jobs_sanitize_environment(terminal, monkeypatch, env):
    from terminal_tools.jobs.manager import get_manager

    monkeypatch.setenv("ZSH_HIVE_TEST", "strip")
    monkeypatch.setenv("HIVE_TEST_KEEP", "keep")
    # Direct argv execution isolates environment behavior from shell quoting.
    monkeypatch.setattr("terminal_tools.common.limits.resolve_shell_spec", lambda _: ShellSpec(None, (), "direct"))
    manager = get_manager()
    spawn = manager.start

    def start(command, **kwargs):
        return spawn([sys.executable, "-c", "import os; print(os.getenv('ZSH_HIVE_TEST')); print(os.getenv('HIVE_TEST_KEEP'))"], **kwargs)

    monkeypatch.setattr(manager, "start", start)
    result = terminal["terminal_job_start"](command="audit", env=env)
    final = _logs(terminal, result)
    assert final["data"].splitlines() == ["None", "keep"]


def _is_running(pid):
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes as W

        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.OpenProcess.argtypes, api.OpenProcess.restype = [W.DWORD, W.BOOL, W.DWORD], W.HANDLE
        api.GetExitCodeProcess.argtypes = [W.HANDLE, ctypes.POINTER(W.DWORD)]
        api.CloseHandle.argtypes = [W.HANDLE]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = W.DWORD()
            assert api.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = Path(f"/proc/{pid}/stat")
    return not (stat.exists() and stat.read_text().split(") ", 1)[1].startswith("Z"))


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_or_cancel_stops_descendants_only(terminal, cancel):
    sibling = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        result = _run(
            terminal,
            "import subprocess,sys,time; child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "print(child.pid,flush=True); time.sleep(30)",
            timeout_sec=2,
            auto_background_after_sec=0.1,
        )
        if cancel:
            # Let the parent publish the child PID before cancellation.
            end = time.monotonic() + 1.5
            while time.monotonic() < end:
                if terminal["terminal_job_logs"](job_id=result["job_id"])["data"].strip():
                    break
                time.sleep(0.01)
            assert terminal["terminal_job_manage"](action="signal_term", job_id=result["job_id"])["ok"]
        final = _logs(terminal, result)
        assert final["status"] == "exited"
        assert final["timed_out"] is not cancel
        child_pid = int(final["data"].strip())
        end = time.monotonic() + 2
        while _is_running(child_pid) and time.monotonic() < end:
            time.sleep(0.01)
        assert not _is_running(child_pid)
        assert sibling.poll() is None
    finally:
        sibling.terminate()
        sibling.wait(timeout=5)


def test_blocked_stdin_still_times_out(terminal):
    result = _run(terminal, "import time; time.sleep(30)", stdin="x" * 2_000_000, timeout_sec=0.5, auto_background_after_sec=0)
    assert result["timed_out"]
