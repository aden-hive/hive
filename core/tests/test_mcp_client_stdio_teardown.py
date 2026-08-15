"""Real STDIO round-trip: connect -> call -> disconnect must tear down cleanly.

Regression for the swarm hang. The old design entered the anyio-backed
``stdio_client`` / ``ClientSession`` contexts in one task (which then finished)
and exited them from a *different* task on disconnect, raising
"Attempted to exit cancel scope in a different task than it was entered in" and
leaking the MCP subprocess + sockets on every teardown. A single owner
coroutine now enters AND exits the contexts in the same task.

This drives a REAL FastMCP stdio server subprocess (real anyio cancel scopes),
unlike the mocked unit tests — so it actually exercises the fix.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
import time

import pytest

from framework.loader.mcp_client import MCPClient, MCPServerConfig

pytest.importorskip("mcp.server.fastmcp")

_ECHO_SERVER = textwrap.dedent(
    """
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("echo")

    @mcp.tool()
    def echo(text: str) -> str:
        return text

    mcp.run()
    """
)

# echo + slow. ``slow`` is ASYNC, like every gcu browser tool: the server's
# loop keeps answering echo/ping while it sleeps — same shape as the gcu
# server during a long browser_evaluate. (A blocking sync tool would freeze
# this FastMCP version's event loop and serialize everything server-side.)
_SLOW_SERVER = textwrap.dedent(
    """
    import anyio
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("slowsrv")

    @mcp.tool()
    def echo(text: str) -> str:
        return text

    @mcp.tool()
    async def slow(seconds: float) -> str:
        await anyio.sleep(seconds)
        return f"slept {seconds}"

    mcp.run()
    """
)


def _child_pids() -> set[str]:
    try:
        out = subprocess.run(["pgrep", "-P", str(os.getpid())], capture_output=True, text=True).stdout
        return set(out.split())
    except Exception:
        return set()


def test_windows_stdio_cwd_workaround_passes_dir_via_env(tmp_path) -> None:
    """On Windows, MCPClient discards cwd (the WinError 267 workaround) but
    must hand the directory to the child via HIVE_MCP_SERVER_CWD.

    Regression for agent-generated files landing in the project root:
    without this, any stdio server script that falls back to os.getcwd()
    for relative paths (e.g. files_server.py) silently inherits the
    *launching* Hive process's cwd instead of the directory this client was
    configured with.
    """
    if os.name != "nt":
        pytest.skip("exercises the Windows-only cwd=None workaround")

    srv_dir = tmp_path / "srv"
    srv_dir.mkdir()
    script = srv_dir / "env_probe_server.py"
    script.write_text(
        textwrap.dedent(
            """
            import os
            from mcp.server.fastmcp import FastMCP

            mcp = FastMCP("env-probe")

            @mcp.tool()
            def get_cwd_env() -> str:
                return os.environ.get("HIVE_MCP_SERVER_CWD", "<missing>")

            mcp.run()
            """
        )
    )

    client = MCPClient(
        MCPServerConfig(
            name="env-probe",
            transport="stdio",
            command=sys.executable,
            args=["env_probe_server.py"],  # relative — exercises the cwd-resolve branch
            cwd=str(srv_dir),
        )
    )
    client.connect()
    try:
        result = client.call_tool("get_cwd_env", {})
        assert str(srv_dir) in str(result)
    finally:
        client.disconnect()


def test_stdio_connect_call_disconnect_is_clean(tmp_path, caplog) -> None:
    script = tmp_path / "echo_server.py"
    script.write_text(_ECHO_SERVER)
    client = MCPClient(MCPServerConfig(name="echo", transport="stdio", command=sys.executable, args=[str(script)]))

    caplog.set_level(logging.DEBUG, logger="framework.loader.mcp_client")
    baseline = _child_pids()

    # Several connect/call/disconnect cycles, mimicking the per-call reconnect
    # churn that drove the leak in production.
    for i in range(3):
        client.connect()
        result = client.call_tool("echo", {"text": f"hi-{i}"})
        assert f"hi-{i}" in str(result)
        client.disconnect()

    # THE FIX: no cross-task anyio cancel-scope error during teardown.
    offending = [r.getMessage() for r in caplog.records if "cancel scope" in r.getMessage().lower() or "different task" in r.getMessage().lower()]
    assert not offending, f"cancel-scope teardown errors leaked: {offending}"

    # And no leaked MCP server subprocess after disconnect.
    time.sleep(0.3)
    leaked = _child_pids() - baseline
    assert not leaked, f"leaked child process(es) after disconnect: {leaked}"


_WEDGE_NEEDLES = ("different event loop", "cancel scope", "different task", "session not initialized")


def _assert_no_wedge_logs(caplog) -> None:
    offending = [r.getMessage() for r in caplog.records if any(n in r.getMessage().lower() for n in _WEDGE_NEEDLES)]
    assert not offending, f"cross-generation wedge errors leaked: {offending}"


def _slow_client(tmp_path) -> MCPClient:
    script = tmp_path / "slow_server.py"
    script.write_text(_SLOW_SERVER)
    return MCPClient(MCPServerConfig(name="slowsrv", transport="stdio", command=sys.executable, args=[str(script)]))


def test_reconnect_under_fire_yields_working_client(tmp_path, caplog) -> None:
    """disconnect()+connect() while a call is in flight must not wedge.

    Regression for the 2026-06-11 incident: a force-disconnect during a slow
    browser call left the shared client permanently broken ("Event is bound
    to a different event loop" / "STDIO session not initialized" on every
    call after the in-place reconnect).
    """
    import threading

    client = _slow_client(tmp_path)
    caplog.set_level(logging.DEBUG, logger="framework.loader.mcp_client")

    client.connect()
    outcome: dict = {}

    def _slow_call():
        try:
            outcome["result"] = client.call_tool("slow", {"seconds": 2.0})
        except Exception as exc:  # acceptable: the abandoned call may error
            outcome["error"] = exc

    t = threading.Thread(target=_slow_call)
    t.start()
    time.sleep(0.4)  # let the slow call get in flight

    # The force-disconnect + reconnect, mid-call.
    client.disconnect()
    client.connect()

    # THE FIX: the new generation must serve calls normally.
    result = client.call_tool("echo", {"text": "post-reconnect"})
    assert "post-reconnect" in str(result)

    t.join(timeout=15)
    assert not t.is_alive(), "in-flight call must not hang forever after reconnect"

    _assert_no_wedge_logs(caplog)
    client.disconnect()


def test_concurrent_disconnects_are_clean(tmp_path, caplog) -> None:
    """Two threads disconnecting at once → one teardown, reusable client."""
    import threading

    client = _slow_client(tmp_path)
    caplog.set_level(logging.DEBUG, logger="framework.loader.mcp_client")
    client.connect()

    threads = [threading.Thread(target=client.disconnect) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)
    assert all(not t.is_alive() for t in threads)

    # Client must be fully reusable afterwards.
    client.connect()
    assert "again" in str(client.call_tool("echo", {"text": "again"}))
    client.disconnect()

    _assert_no_wedge_logs(caplog)


def test_slow_call_does_not_convoy_concurrent_calls(tmp_path) -> None:
    """One slow call must not starve other calls on the shared client.

    The old per-client call lock serialized every stdio call, so one slow
    browser_evaluate made every other worker's call (even trivial status
    reads) time out — the 'browser alive but unreachable' root cause. MCP
    multiplexes requests over one session; concurrent calls must proceed.
    """
    if os.name == "nt":
        pytest.skip("Windows keeps stdio call serialization by design")
    import threading

    client = _slow_client(tmp_path)
    client.connect()

    started = threading.Event()

    def _slow_call():
        started.set()
        client.call_tool("slow", {"seconds": 2.5})

    t = threading.Thread(target=_slow_call, daemon=True)
    t.start()
    started.wait(2)
    time.sleep(0.3)  # ensure the slow request is on the wire

    t0 = time.monotonic()
    result = client.call_tool("echo", {"text": "not-convoyed"})
    elapsed = time.monotonic() - t0

    assert "not-convoyed" in str(result)
    assert elapsed < 1.5, f"echo waited {elapsed:.1f}s behind the slow call — convoy is back"

    # Liveness probe answers while the slow call is still running — this is
    # what stops the timeout handler from killing a busy-but-alive server.
    assert client.probe_liveness(timeout=5.0) is True

    t.join(timeout=10)
    client.disconnect()
