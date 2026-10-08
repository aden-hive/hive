"""bridge_host lifetime: dies with the durable runtime, debounced.

The worker's parent watch shuts the bridge down when HIVE_DESKTOP_PARENT_PID
(the desktop/runtime process) disappears — but only after
_PARENT_DEATH_CONFIRMATIONS consecutive "gone" reads, so a one-off probe glitch
can't tear a live bridge down. These exercise that logic without real processes.
"""

from __future__ import annotations

import asyncio

import pytest

import gcu.bridge_host as bh


@pytest.mark.asyncio
async def test_watch_parent_shuts_down_when_runtime_dies(monkeypatch):
    monkeypatch.setattr(bh, "_PARENT_CHECK_INTERVAL_S", 0.01)
    monkeypatch.setattr(bh, "_PARENT_DEATH_CONFIRMATIONS", 2)
    alive = {"v": True}
    monkeypatch.setattr(bh, "_pid_alive", lambda pid: alive["v"])

    stop = asyncio.Event()
    task = asyncio.create_task(bh._watch_parent(999999, stop))
    try:
        await asyncio.sleep(0.05)
        assert not stop.is_set()  # runtime alive → bridge stays up

        alive["v"] = False
        await asyncio.wait_for(stop.wait(), timeout=1.0)  # confirmed death → stop
        assert stop.is_set()
    finally:
        stop.set()
        await task


@pytest.mark.asyncio
async def test_watch_parent_debounces_a_transient_miss(monkeypatch):
    monkeypatch.setattr(bh, "_PARENT_CHECK_INTERVAL_S", 0.01)
    monkeypatch.setattr(bh, "_PARENT_DEATH_CONFIRMATIONS", 3)
    # One spurious "gone" read surrounded by "alive" — must NOT trigger shutdown.
    seq = [True, False, True, True, True]
    i = {"n": 0}

    def fake(_pid):
        n = i["n"]
        i["n"] += 1
        return seq[n] if n < len(seq) else True

    monkeypatch.setattr(bh, "_pid_alive", fake)

    stop = asyncio.Event()
    task = asyncio.create_task(bh._watch_parent(999999, stop))
    try:
        await asyncio.sleep(0.1)
        assert not stop.is_set()  # single transient miss < confirmations → alive
    finally:
        stop.set()
        await task
