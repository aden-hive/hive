"""Multi-connection bridge tests (P3 routing + P4 coexistence).

The bridge now accepts multiple simultaneous Chrome-extension connections —
one per Chrome profile — keyed by a user-assigned label, and routes each
command to the right connection. These tests drive a real ``BeelineBridge``
with fake websockets (no real sockets, no sleeps) and cover:

  * two labelled connections coexisting (no displacement);
  * resolve_connection's default / starred / ambiguous / missing rules;
  * _send routing by explicit profile and by tabId;
  * disconnect isolation — tearing down one connection leaves the other's
    connection + registry entry intact and only soft-prunes the dropped one.
"""

from __future__ import annotations

import asyncio
import json

import pytest

import gcu.browser.bridge as bridge_mod
from gcu.browser.bridge import BeelineBridge, BridgeError, _Connection


class FakeWS:
    """Minimal stand-in for a websockets server connection."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data) -> None:
        self.sent.append(data)

    async def close(self, *a, **k) -> None:
        self.closed = True


def _add_conn(bridge: BeelineBridge, label: str, *, protocol_version: int = 5) -> _Connection:
    """Register a fake connection on the bridge under ``label``."""
    conn = _Connection(FakeWS(), label=label)
    conn.extension_id = f"ext-{label}"
    conn.version = "1.0.0"
    conn.protocol_version = protocol_version
    bridge._conns[label] = conn
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Coexistence
# ─────────────────────────────────────────────────────────────────────────────


def test_two_connections_coexist():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    b = _add_conn(bridge, "B")

    assert len(bridge._conns) == 2
    assert bridge.is_connected is True
    assert bridge.resolve_connection("A") is a
    assert bridge.resolve_connection("B") is b
    assert a is not b


# ─────────────────────────────────────────────────────────────────────────────
# resolve_connection rules
# ─────────────────────────────────────────────────────────────────────────────


def test_resolve_default_single_connection():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    assert bridge.resolve_connection("default") is a
    # None is treated the same as the default label.
    assert bridge.resolve_connection(None) is a


def test_resolve_default_first_come_then_starred():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    a.connected_at_ms = 1.0
    b = _add_conn(bridge, "B")
    b.connected_at_ms = 2.0

    # First-come-claims-default: with no star, the earliest-connected (A) is the
    # default — no ambiguous failure.
    assert bridge.resolve_connection("default") is a
    # An explicit star overrides first-come.
    bridge._starred_default_label = "B"
    assert bridge.resolve_connection("default") is b


def test_resolve_default_zero_connections():
    bridge = BeelineBridge()
    with pytest.raises(BridgeError) as ei:
        bridge.resolve_connection("default")
    assert ei.value.code == "not_connected"
    assert ei.value.retryable is True


def test_resolve_unknown_label():
    bridge = BeelineBridge()
    _add_conn(bridge, "A")
    # Two connections make an unknown label genuinely ambiguous, so the bridge
    # fails fast. (With a SINGLE connection it now falls back to it, treating
    # the missing label as a stale id after an extension reinstall.)
    _add_conn(bridge, "B")
    with pytest.raises(BridgeError) as ei:
        bridge.resolve_connection("ghost")
    assert ei.value.code == "no_browser_profile"
    assert ei.value.retryable is False
    # The message names the missing label and lists what IS connected.
    assert "ghost" in str(ei.value)
    assert "A" in str(ei.value)


def test_effective_default_label():
    bridge = BeelineBridge()
    assert bridge._effective_default_label() is None  # zero conns → would raise
    a = _add_conn(bridge, "A")
    a.connected_at_ms = 1.0
    assert bridge._effective_default_label() == "A"  # sole conn
    b = _add_conn(bridge, "B")
    b.connected_at_ms = 2.0
    assert bridge._effective_default_label() == "A"  # first-come default = earliest connected
    bridge._starred_default_label = "B"
    assert bridge._effective_default_label() == "B"


# ─────────────────────────────────────────────────────────────────────────────
# _send routing
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_routes_to_explicit_profile():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    b = _add_conn(bridge, "B")

    # Fire the send; it will park on its future. Resolve that future by hand
    # so we can assert the frame landed on A's ws (and not B's).
    task = asyncio.create_task(bridge._send("cdp", browser_profile="A", method="X", timeout=1.0))
    await asyncio.sleep(0)  # let _send register its pending future and send

    assert len(a.ws.sent) == 1
    assert b.ws.sent == []
    assert len(a.pending) == 1
    assert b.pending == {}

    # Resolve the parked future so the task completes cleanly.
    msg_id = next(iter(a.pending))
    a.pending[msg_id].set_result({"ok": True})
    result = await task
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_send_routes_by_tab_id():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    b = _add_conn(bridge, "B")
    bridge._tab_to_conn[42] = "A"

    task = asyncio.create_task(bridge._send("cdp", tabId=42, method="X", timeout=1.0))
    await asyncio.sleep(0)

    assert len(a.ws.sent) == 1
    assert b.ws.sent == []

    msg_id = next(iter(a.pending))
    a.pending[msg_id].set_result({"ok": True})
    await task


@pytest.mark.asyncio
async def test_send_unknown_profile_raises_without_touching_sockets():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    # Multiple connections → an unknown profile is ambiguous and fails fast
    # before any socket is touched (a single connection would be used as the
    # stale-label fallback instead).
    _add_conn(bridge, "B")
    with pytest.raises(BridgeError) as ei:
        await bridge._send("cdp", browser_profile="ghost", method="X")
    assert ei.value.code == "no_browser_profile"
    assert a.ws.sent == []


# ─────────────────────────────────────────────────────────────────────────────
# Disconnect isolation
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ping_loop_runs_only_once_connection_is_registered(monkeypatch):
    # Regression: the ping loop must be started AFTER the connection is keyed
    # into self._conns under its label. Started earlier (label still None /
    # unregistered), its ownership guard is immediately false, the loop exits
    # without ever pinging, the extension never pongs, and last_pong_age_ms
    # grows == connection age → the desktop badge falsely shows "Extension stale".
    monkeypatch.setattr(bridge_mod, "_APP_PING_INTERVAL_S", 0.01)
    bridge = BeelineBridge()
    conn = _Connection(FakeWS(), label="A")

    # Unregistered → loop returns immediately, no ping sent.
    await asyncio.wait_for(bridge._ping_loop(conn), timeout=0.5)
    assert conn.ws.sent == []

    # Registered → loop actually pings; deregister to let it exit.
    bridge._conns["A"] = conn
    task = asyncio.create_task(bridge._ping_loop(conn))
    await asyncio.sleep(0.05)
    bridge._conns.pop("A", None)
    await asyncio.wait_for(task, timeout=0.5)
    assert any(json.loads(s).get("type") == "ping" for s in conn.ws.sent)


def test_disconnect_isolation_only_prunes_dropped_label():
    bridge = BeelineBridge()
    a = _add_conn(bridge, "A")
    b = _add_conn(bridge, "B")
    bridge._context_registry["agA"] = {
        "groupId": 1,
        "name": "a",
        "browser_profile": "A",
        "registered_at_ms": 0.0,
    }
    bridge._context_registry["agB"] = {
        "groupId": 2,
        "name": "b",
        "browser_profile": "B",
        "registered_at_ms": 0.0,
    }
    bridge._tab_to_conn[10] = "A"
    bridge._tab_to_conn[20] = "B"

    # Replicate the _handle_connection finally-block teardown scoping for A:
    # pop A, soft-prune only A's registry slice, drop A's tab routing.
    bridge._conns.pop("A", None)
    for meta in list(bridge._context_registry.values()):
        if meta.get("browser_profile") == "A":
            gid = meta.get("groupId")
            if gid is not None:
                bridge._prune_group(gid, soft=True)
    for tid in [t for t, lbl in bridge._tab_to_conn.items() if lbl == "A"]:
        bridge._tab_to_conn.pop(tid, None)

    # B's connection and registry entry survive untouched.
    assert "B" in bridge._conns
    assert bridge._conns["B"] is b
    assert bridge._context_registry["agB"]["groupId"] == 2
    assert bridge._tab_to_conn.get(20) == "B"

    # A is gone; its registry entry soft-pruned (kept, groupId cleared); its
    # tab routing dropped.
    assert "A" not in bridge._conns
    assert "agA" in bridge._context_registry  # soft prune keeps identity
    assert bridge._context_registry["agA"]["groupId"] is None
    assert 10 not in bridge._tab_to_conn
    # The dropped connection object is untouched by the survivor.
    assert a.label == "A"
