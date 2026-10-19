"""Worker browser pre-flight: a worker bound to a Chrome browser profile that
isn't connected must fail fast ("should not even be attempted") — it must NOT
run the agent loop and burn the whole timeout retrying a browser that can't
route.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import framework.host.worker as worker_mod
from framework.host.worker import Worker


@pytest.mark.asyncio
async def test_worker_not_attempted_when_bound_profile_disconnected(monkeypatch):
    # Bridge reports only "alpha" connected; the worker is bound to "ghost".
    async def fake_labels():
        return {"alpha"}

    monkeypatch.setattr(worker_mod, "_connected_browser_labels", fake_labels)

    agent_loop = MagicMock()
    agent_loop.execute = AsyncMock()  # must never be called

    w = Worker(
        worker_id="w-ghost",
        task="open the browser",
        agent_loop=agent_loop,
        context=MagicMock(),
        browser_profile="ghost",
    )
    w._emit_terminal_events = AsyncMock()  # don't need a real event bus

    result = await w.run()

    agent_loop.execute.assert_not_called()  # not attempted
    assert result.status == "failed"
    assert "ghost" in (result.summary or "")
    assert w._emit_terminal_events.await_count == 1


@pytest.mark.asyncio
async def test_worker_not_blocked_when_bridge_unreachable(monkeypatch):
    # Probe returns None ("unknown") → do NOT pre-fail; let the worker proceed
    # (the tool layer's instant fail-fast still applies if needed).
    async def fake_labels():
        return None

    monkeypatch.setattr(worker_mod, "_connected_browser_labels", fake_labels)

    agent_loop = MagicMock()
    res = MagicMock()
    res.success = True
    agent_loop.execute = AsyncMock(return_value=res)

    w = Worker(
        worker_id="w-unknown",
        task="open the browser",
        agent_loop=agent_loop,
        context=MagicMock(),
        browser_profile="ghost",
    )
    w._emit_terminal_events = AsyncMock()
    w._build_result = MagicMock(return_value=MagicMock(status="success"))

    await w.run()

    agent_loop.execute.assert_awaited_once()  # proceeded; not pre-failed
