"""Phase 1 browser-cleanup tests (P1 reliable close + P2 empty-group mitigation).

Covers:
- close_profile_context no longer reports a false "stopped" when the bridge is
  disconnected; it defers to the dead-letter queue and drain_dead_letter() later
  closes it (P1.1).
- The bridge-side forward orphan reaper closes only Hive-marked, unclaimed groups
  and only after a two-sweep debounce; user groups and pooled saved chips are
  never touched (P1.3).
- destroy_context records Chrome "Saved Tab Groups" chips and create_context
  recycles one instead of leaking a fresh chip (P2.1/P2.2).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import gcu.browser.tools.lifecycle as lc
from gcu.browser.bridge import HIVE_GROUP_MARKER, BeelineBridge, _Connection


class _FakeWS:
    """Minimal async WebSocket stand-in for bridge connection tests."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data) -> None:
        self.sent.append(data)

    async def close(self, *a, **k) -> None:
        self.closed = True


def _add_conn(bridge: BeelineBridge, label: str = "default", proto: int = 5) -> _Connection:
    """Register a fake extension connection so resolve_connection / per-conn
    protocol gating have a real connection to route to."""
    conn = _Connection(_FakeWS(), label=label)
    conn.protocol_version = proto
    conn.extension_id = f"ext-{label}"
    bridge._conns[label] = conn
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# P1.1 — close_profile_context honesty + dead-letter retry
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_defers_when_bridge_disconnected(monkeypatch):
    lc._contexts.clear()
    lc._DEAD_LETTER.clear()
    lc._contexts["w1"] = {"groupId": 7, "name": "w1", "tabs": set()}

    disconnected = MagicMock()
    disconnected.is_connected = False
    monkeypatch.setattr(lc, "get_bridge", lambda: disconnected)
    # Keep the reconnect-wait window tiny so the test is fast.
    monkeypatch.setattr(lc, "_REAP_RECONNECT_WAIT_S", 0.05)
    monkeypatch.setattr(lc, "_REAP_RECONNECT_POLL_S", 0.01)

    res = await lc.close_profile_context("w1", reason="worker_shutdown")

    # The old bug returned {ok:true, status:stopped, closedTabs:0} here.
    assert res["ok"] is False
    assert res["status"] == "deferred"
    assert res.get("retryable") is True
    assert any(e["groupId"] == 7 for e in lc._DEAD_LETTER)


@pytest.mark.asyncio
async def test_drain_dead_letter_closes_deferred(monkeypatch):
    lc._contexts.clear()
    lc._DEAD_LETTER.clear()
    lc._DEAD_LETTER.append({"profile": "w1", "groupId": 7, "name": "w1", "reason": "worker_shutdown"})

    connected = MagicMock()
    connected.is_connected = True
    connected.destroy_context = AsyncMock(return_value={"ok": True, "closedTabs": 1})
    monkeypatch.setattr(lc, "get_bridge", lambda: connected)

    closed = await lc.drain_dead_letter()

    assert closed == 1
    assert lc._DEAD_LETTER == []
    connected.destroy_context.assert_awaited_once_with(7, browser_profile=None)


@pytest.mark.asyncio
async def test_close_succeeds_when_connected(monkeypatch):
    lc._contexts.clear()
    lc._DEAD_LETTER.clear()
    lc._contexts["w2"] = {"groupId": 9, "name": "w2", "tabs": set()}

    connected = MagicMock()
    connected.is_connected = True
    connected.destroy_context = AsyncMock(return_value={"ok": True, "closedTabs": 2})
    monkeypatch.setattr(lc, "get_bridge", lambda: connected)

    res = await lc.close_profile_context("w2", reason="worker_shutdown")

    assert res["ok"] is True
    assert res["status"] == "stopped"
    assert res["closedTabs"] == 2
    assert lc._DEAD_LETTER == []


# ─────────────────────────────────────────────────────────────────────────────
# P1.3 — bridge-side forward orphan reaper
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_forward_reaper_closes_only_marked_orphans_after_debounce():
    bridge = BeelineBridge()
    sent: list[tuple[str, dict]] = []

    async def fake_send(type_, **params):
        sent.append((type_, params))
        return {"ok": True, "closedTabs": 0}

    bridge._send = fake_send  # type: ignore[assignment]
    # A live agent owns group 10.
    bridge._context_registry["agentA"] = {"groupId": 10, "name": "A", "registered_at_ms": 0.0}

    groups = [
        {"id": 10, "title": "A" + HIVE_GROUP_MARKER},  # owned -> never reaped
        {"id": 20, "title": "ghost" + HIVE_GROUP_MARKER},  # hive orphan -> reaped after 2 sweeps
        {"id": 30, "title": "my notes"},  # user group -> never reaped
    ]

    # Sweep 1: debounce only, nothing closed yet.
    await bridge._forward_reap_orphans(groups)
    assert not any(t == "context.destroy" for t, _ in sent)
    assert bridge._orphan_seen.get(20) == 1
    assert 30 not in bridge._orphan_seen  # user group never tracked

    # Sweep 2: the orphan crosses the debounce threshold and is closed.
    await bridge._forward_reap_orphans(groups)
    destroyed = [p["groupId"] for t, p in sent if t == "context.destroy"]
    assert destroyed == [20]


@pytest.mark.asyncio
async def test_forward_reaper_skips_pooled_saved_chips():
    bridge = BeelineBridge()
    bridge._send = AsyncMock(return_value={"ok": True})  # type: ignore[assignment]
    bridge._persisted_groups.add(20)

    groups = [{"id": 20, "title": "ghost" + HIVE_GROUP_MARKER}]
    await bridge._forward_reap_orphans(groups)
    await bridge._forward_reap_orphans(groups)

    bridge._send.assert_not_called()


@pytest.mark.asyncio
async def test_forward_reaper_resets_debounce_when_orphan_disappears():
    bridge = BeelineBridge()
    bridge._send = AsyncMock(return_value={"ok": True})  # type: ignore[assignment]

    marked = [{"id": 20, "title": "ghost" + HIVE_GROUP_MARKER}]
    await bridge._forward_reap_orphans(marked)
    assert bridge._orphan_seen.get(20) == 1
    # The group is gone next sweep (e.g. user reopened/closed it) -> counter resets.
    await bridge._forward_reap_orphans([])
    assert 20 not in bridge._orphan_seen


# ─────────────────────────────────────────────────────────────────────────────
# Renderer leak — ungrouped-orphan reaper (protocol 6)
# ─────────────────────────────────────────────────────────────────────────────


def _ungrouped_send(bridge, ids):
    """Patch bridge._send so tab.listUngrouped returns ``ids`` and capture
    every tab.close call. Returns the captured list."""
    closed: list[int] = []

    async def fake_send(type_, **params):
        if type_ == "tab.listUngrouped":
            return {"tabs": [{"id": i, "windowId": 1, "url": ""} for i in ids]}
        if type_ == "tab.close":
            closed.append(params.get("tabId"))
            return {"ok": True}
        return {"ok": True}

    bridge._send = fake_send  # type: ignore[assignment]
    return closed


@pytest.mark.asyncio
async def test_ungrouped_reaper_closes_tracked_escapee_after_debounce():
    bridge = BeelineBridge()
    closed = _ungrouped_send(bridge, ids=[50])
    # 50 was demonstrably ours and is no longer claimed by a live context.
    bridge._hive_tab_ids.add(50)

    # Sweep 1: debounce only.
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert closed == []
    assert bridge._ungrouped_seen.get(50) == 1

    # Sweep 2: crosses the threshold and is closed; tracking is dropped.
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert closed == [50]
    assert 50 not in bridge._hive_tab_ids
    assert 50 not in bridge._ungrouped_seen


@pytest.mark.asyncio
async def test_ungrouped_reaper_never_closes_untracked_user_tab():
    bridge = BeelineBridge()
    closed = _ungrouped_send(bridge, ids=[99])  # a user's loose tab
    bridge._hive_tab_ids.add(50)  # we track a DIFFERENT id

    await bridge._reap_ungrouped_orphans(browser_profile="default")
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert closed == []  # 99 is not ours — never a candidate


@pytest.mark.asyncio
async def test_ungrouped_reaper_skips_tab_owned_by_live_context():
    bridge = BeelineBridge()
    closed = _ungrouped_send(bridge, ids=[50])
    bridge._hive_tab_ids.add(50)
    bridge._tab_to_profile[50] = "agentA"  # a live agent still owns it

    await bridge._reap_ungrouped_orphans(browser_profile="default")
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert closed == []


@pytest.mark.asyncio
async def test_ungrouped_reaper_resets_debounce_when_regrouped():
    bridge = BeelineBridge()
    bridge._hive_tab_ids.add(50)

    # Sweep 1: candidate.
    _ungrouped_send(bridge, ids=[50])
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert bridge._ungrouped_seen.get(50) == 1

    # Sweep 2: Chrome re-grouped it (adoptEscapedTab / user drag) -> no longer
    # ungrouped -> debounce resets, never closed.
    closed = _ungrouped_send(bridge, ids=[])
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert 50 not in bridge._ungrouped_seen
    assert closed == []
    assert 50 in bridge._hive_tab_ids  # still tracked; it's healthy again


@pytest.mark.asyncio
async def test_ungrouped_reaper_noop_when_nothing_tracked():
    bridge = BeelineBridge()
    sent: list[str] = []

    async def fake_send(type_, **params):
        sent.append(type_)
        return {"tabs": []}

    bridge._send = fake_send  # type: ignore[assignment]
    # Empty _hive_tab_ids → must not even hit the extension.
    await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert sent == []


@pytest.mark.asyncio
async def test_sweep_gates_ungrouped_reaper_below_proto_6():
    bridge = BeelineBridge()
    _add_conn(bridge, "default", proto=5)  # no tab.listUngrouped support
    bridge._hive_tab_ids.add(50)
    bridge._connected = True

    sent: list[str] = []

    async def fake_send(type_, **params):
        sent.append(type_)
        if type_ == "tabGroup.list":
            return {"groups": []}
        return {"ok": True, "tabs": []}

    bridge._send = fake_send  # type: ignore[assignment]

    # Drive ONE sweep iteration's per-connection body by calling the reaper
    # path the loop guards. The loop itself sleeps 30s, so exercise the gate
    # directly: proto 5 must never send tab.listUngrouped.
    conn = bridge._conns["default"]
    if (conn.protocol_version or 0) >= 6:
        await bridge._reap_ungrouped_orphans(browser_profile="default")
    assert "tab.listUngrouped" not in sent


@pytest.mark.asyncio
async def test_hive_tab_ids_populated_by_create_tab_and_evicted_by_close():
    bridge = BeelineBridge()
    _add_conn(bridge, "default", proto=6)
    bridge._context_registry["agentA"] = {"groupId": 10, "name": "A", "browser_profile": "default", "registered_at_ms": 0.0}

    async def fake_send(type_, **params):
        if type_ == "tab.create":
            return {"tabId": 77}
        return {"ok": True}

    bridge._send = fake_send  # type: ignore[assignment]

    await bridge.create_tab(url="https://x.test", group_id=10)
    assert 77 in bridge._hive_tab_ids  # created inside a Hive group

    await bridge.close_tab(77)
    assert 77 not in bridge._hive_tab_ids  # evicted on close


def test_hive_tab_ids_updated_by_regrouped_event():
    bridge = BeelineBridge()
    bridge._context_registry["agentA"] = {"groupId": 10, "name": "A", "browser_profile": "default", "registered_at_ms": 0.0}

    # A page-spawned tab the extension adopted into our group.
    bridge._update_tab_profile_from_event({"event": "regrouped", "tabId": 88, "groupId": 10})
    assert bridge._tab_to_profile.get(88) == "agentA"
    assert 88 in bridge._hive_tab_ids

    # Removal evicts it from both maps.
    bridge._update_tab_profile_from_event({"event": "removed", "tabId": 88})
    assert 88 not in bridge._tab_to_profile
    assert 88 not in bridge._hive_tab_ids


# ─────────────────────────────────────────────────────────────────────────────
# Window affinity — every worker's group lands in ONE window per profile
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_context_pins_window_across_workers():
    """The bridge remembers the window a profile's groups live in and passes it
    to every later context.create — so a fresh worker doesn't land in whatever
    window the user currently has focused (durable across reaped peers)."""
    bridge = BeelineBridge()
    _add_conn(bridge, "default", proto=6)

    sent: list[dict] = []

    async def fake_send(type_, *, browser_profile=None, **params):
        sent.append(params)
        # The extension echoes the window the group actually landed in.
        return {"groupId": 100 + len(sent), "tabId": 200 + len(sent), "windowId": 7}

    bridge._send = fake_send  # type: ignore[assignment]

    # First worker: no window known yet → none sent; the response teaches it.
    await bridge.create_context("w1", "W1")
    assert "windowId" not in sent[0]
    assert bridge._hive_window_by_conn["default"] == 7

    # Second worker — even if w1's group was already reaped — reuses window 7.
    await bridge.create_context("w2", "W2")
    assert sent[1].get("windowId") == 7


@pytest.mark.asyncio
async def test_create_context_self_heals_when_window_changes():
    """If the remembered window was closed, the extension falls back and echoes
    the new window; the bridge updates its memory to match."""
    bridge = BeelineBridge()
    _add_conn(bridge, "default", proto=6)
    bridge._hive_window_by_conn["default"] = 7  # stale: user closed window 7

    async def fake_send(type_, *, browser_profile=None, **params):
        # Extension couldn't use window 7; landed in window 9 instead.
        return {"groupId": 101, "tabId": 201, "windowId": 9}

    bridge._send = fake_send  # type: ignore[assignment]

    await bridge.create_context("w3", "W3")
    assert bridge._hive_window_by_conn["default"] == 9


# ─────────────────────────────────────────────────────────────────────────────
# P2.1 / P2.2 — persisted saved-chip tracking + recycling
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_destroy_records_persisted_group_then_create_recycles_it():
    bridge = BeelineBridge()
    _add_conn(bridge, "default", proto=5)

    # context.destroy reports the saved chip survived.
    bridge._send = AsyncMock(return_value={"ok": True, "closedTabs": 1, "persistedGroup": True})  # type: ignore[assignment]
    await bridge.destroy_context(20)
    assert 20 in bridge._persisted_groups

    # The next create reuses that chip instead of minting a fresh one.
    calls: list[tuple[str, dict]] = []

    async def fake_send(type_, **params):
        calls.append((type_, params))
        return {"groupId": 20, "tabId": 200}

    bridge._send = fake_send  # type: ignore[assignment]
    await bridge.create_context("agentB", "B")

    create_params = next(p for t, p in calls if t == "context.create")
    assert create_params.get("recycleGroupId") == 20
    assert 20 not in bridge._persisted_groups  # consumed by the recycle


@pytest.mark.asyncio
async def test_destroy_non_persisted_group_not_pooled():
    bridge = BeelineBridge()
    bridge._persisted_groups.add(20)  # stale entry from a prior life
    bridge._send = AsyncMock(return_value={"ok": True, "closedTabs": 1, "persistedGroup": False})  # type: ignore[assignment]

    await bridge.destroy_context(20)
    assert 20 not in bridge._persisted_groups


@pytest.mark.asyncio
async def test_create_does_not_recycle_on_old_protocol():
    bridge = BeelineBridge()
    _add_conn(bridge, "default", proto=4)  # pre-recycling
    bridge._persisted_groups.add(20)

    calls: list[tuple[str, dict]] = []

    async def fake_send(type_, **params):
        calls.append((type_, params))
        return {"groupId": 99, "tabId": 200}

    bridge._send = fake_send  # type: ignore[assignment]
    await bridge.create_context("agentC", "C")

    create_params = next(p for t, p in calls if t == "context.create")
    assert "recycleGroupId" not in create_params  # gated off on proto < 5
