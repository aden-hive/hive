"""A wedged MCP call must not block its worker thread forever.

Regression for the swarm hang: `_run_async` ran the STDIO coroutine via
`run_coroutine_threadsafe(...).result()` with NO timeout, so a hung browser
call whose force-disconnect also failed (anyio teardown bug) leaked one
tool-pool thread per call until the pool was exhausted. It now bounds the wait
and raises a dead-session error so the thread is reclaimed and the caller
reconnects.

Also covers the reconnect policy added after the 2026-06-11 incident:
- concurrent `_reconnect()` calls collapse (one teardown, not N),
- a worker that failed on generation N must not tear down generation N+1,
- a failed reconnect arms a fail-fast cooldown (no connect storms).
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from framework.loader.mcp_client import MCPClient, MCPServerConfig, _StdioConnection


def _running_loop_in_thread():
    loop = asyncio.new_event_loop()
    started = threading.Event()

    def _run():
        asyncio.set_event_loop(loop)
        loop.call_soon(started.set)
        loop.run_forever()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    started.wait(2)
    return loop, t


def test_run_async_reclaims_thread_on_wedged_call(monkeypatch) -> None:
    client = MCPClient(MCPServerConfig(name="wedged", transport="stdio", command="true"))
    loop, t = _running_loop_in_thread()
    client._conn = _StdioConnection(generation=1, loop=loop, loop_thread=t)
    client._connected = True
    # Shrink the last-resort backstop so the test is fast.
    monkeypatch.setattr(MCPClient, "_CALL_RESULT_TIMEOUT", 0.3)

    async def _never():
        await asyncio.Event().wait()  # never completes — the wedged call

    t0 = time.monotonic()
    try:
        client._run_async(_never())
        raised = None
    except RuntimeError as exc:
        raised = exc
    elapsed = time.monotonic() - t0

    assert raised is not None, "wedged call should raise, not hang"
    assert "transport closed" in str(raised).lower()
    # Must be classified as a dead session so _call_tool_with_retry reconnects.
    assert client._is_stdio_dead_session_error(raised)
    assert client._connected is False
    # Returned promptly (~0.3s) instead of blocking the thread forever.
    assert elapsed < 2.0

    # The abandoned-call message must steer the LLM away from process
    # killing (the incident failure mode), not just report a timeout.
    assert "do not kill" in str(raised).lower()

    # In-flight accounting must drain back to zero after the abandon.
    assert client.inflight_calls == 0

    # Let the scheduled cancellation of the wedged task settle before tearing
    # the loop down (avoids a noisy "Task was destroyed but pending" warning).
    time.sleep(0.1)
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)
    loop.close()


def test_reconnect_collapses_for_stale_generation(monkeypatch) -> None:
    """A worker that failed on gen N must no-op when gen N+1 already exists."""
    client = MCPClient(MCPServerConfig(name="c", transport="stdio", command="true"))
    client._conn = _StdioConnection(generation=2)  # fresh generation, healthy
    client._connected = True
    # This thread's last call ran on the OLD generation.
    client._thread_call_gen.gen = 1

    calls = {"disconnect": 0, "connect": 0}
    monkeypatch.setattr(client, "disconnect", lambda: calls.__setitem__("disconnect", calls["disconnect"] + 1))
    monkeypatch.setattr(client, "connect", lambda: calls.__setitem__("connect", calls["connect"] + 1))

    client._reconnect()

    assert calls == {"disconnect": 0, "connect": 0}, "stale-generation reconnect must collapse to a no-op"


def test_reconnect_proceeds_for_current_generation(monkeypatch) -> None:
    client = MCPClient(MCPServerConfig(name="c", transport="stdio", command="true"))
    client._conn = _StdioConnection(generation=3)
    client._connected = True
    client._thread_call_gen.gen = 3  # failed on the CURRENT generation

    calls = {"disconnect": 0, "connect": 0}
    monkeypatch.setattr(client, "disconnect", lambda: calls.__setitem__("disconnect", calls["disconnect"] + 1))
    monkeypatch.setattr(client, "connect", lambda: calls.__setitem__("connect", calls["connect"] + 1))

    client._reconnect()

    assert calls == {"disconnect": 1, "connect": 1}


def test_reconnect_cooldown_fails_fast(monkeypatch) -> None:
    """After a failed connect, further reconnects raise immediately."""
    client = MCPClient(MCPServerConfig(name="c", transport="stdio", command="true"))
    client._connected = False

    def _boom():
        raise RuntimeError("server is gone")

    monkeypatch.setattr(client, "disconnect", lambda: None)
    monkeypatch.setattr(client, "connect", _boom)

    with pytest.raises(RuntimeError, match="server is gone"):
        client._reconnect()

    # Cooldown armed: the next attempt fails fast WITHOUT calling connect.
    monkeypatch.setattr(client, "connect", lambda: pytest.fail("connect must not run during cooldown"))
    t0 = time.monotonic()
    with pytest.raises(RuntimeError, match="cooldown"):
        client._reconnect()
    assert time.monotonic() - t0 < 0.5
    # Cooldown error is still classified for the retry path.
    try:
        client._reconnect()
    except RuntimeError as exc:
        assert client._is_stdio_dead_session_error(exc)


def test_concurrent_reconnects_collapse(monkeypatch) -> None:
    """N workers racing into _reconnect produce ONE teardown+connect."""
    client = MCPClient(MCPServerConfig(name="c", transport="stdio", command="true"))
    client._generation = 1
    client._conn = _StdioConnection(generation=1)
    client._connected = True

    calls = {"disconnect": 0, "connect": 0}
    lock = threading.Lock()

    def _slow_disconnect():
        with lock:
            calls["disconnect"] += 1
        time.sleep(0.2)
        client._conn = None
        client._connected = False

    def _connect():
        with lock:
            calls["connect"] += 1
        client._generation += 1
        client._conn = _StdioConnection(generation=client._generation)
        client._connected = True

    monkeypatch.setattr(client, "disconnect", _slow_disconnect)
    monkeypatch.setattr(client, "connect", _connect)

    def _worker():
        client._thread_call_gen.gen = 1  # everyone failed on gen 1
        client._reconnect()

    threads = [threading.Thread(target=_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)

    assert calls["disconnect"] == 1, f"expected one teardown, got {calls['disconnect']}"
    assert calls["connect"] == 1, f"expected one connect, got {calls['connect']}"
    assert client._conn is not None and client._conn.generation == 2
