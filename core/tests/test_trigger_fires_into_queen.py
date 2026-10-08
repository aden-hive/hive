"""Tests for queen-level trigger system.

Verifies that:
- Timer triggers fire inject_trigger() on the queen node
- Webhook triggers fire inject_trigger() via EventBus WEBHOOK_RECEIVED
- Queen node unavailable → trigger skipped silently
- colony_id=None → trigger discarded (gating)
- remove_trigger cleans up webhook subscription
- run_agent_with_input is in _QUEEN_RUNNING_TOOLS
- System prompts reference run_agent_with_input, not start_graph()
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.host.event_bus import EventBus
from framework.host.triggers import TriggerDefinition
from framework.server.session_manager import Session


def _make_session(event_bus: EventBus, session_id: str = "session_trigger_test") -> Session:
    return Session(id=session_id, event_bus=event_bus, llm=object(), loaded_at=0.0)


def _make_executor(queen_node) -> SimpleNamespace:
    return SimpleNamespace(node_registry={"queen": queen_node})


@pytest.mark.asyncio
async def test_interval_timer_fires_inject_trigger_on_queen_node() -> None:
    """Timer with interval_minutes fires inject_trigger() on the queen node."""
    from framework.agent_loop.agent_loop import TriggerEvent
    from framework.tools.queen_lifecycle_tools import _start_trigger_timer

    bus = EventBus()
    session = _make_session(bus)
    session.colony_id = "test_colony"  # colony is bound

    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    session.queen_executor = _make_executor(queen_node)

    tdef = TriggerDefinition(
        id="test-timer",
        trigger_type="timer",
        trigger_config={"interval_minutes": 0.001},  # ~60ms
        task="run it",
    )

    await _start_trigger_timer(session, "test-timer", tdef)

    # Let the timer fire at least once
    await asyncio.sleep(0.15)

    # Cancel the background task
    task = session.active_timer_tasks.get("test-timer")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert queen_node.inject_trigger.await_count >= 1

    # Inspect the TriggerEvent passed to inject_trigger
    call_args = queen_node.inject_trigger.await_args_list[0]
    trigger: TriggerEvent = call_args.args[0]
    assert trigger.trigger_type == "timer"
    assert trigger.source_id == "test-timer"
    assert trigger.payload.get("task") == "run it"


@pytest.mark.asyncio
async def test_timer_fire_persists_last_and_next_due(tmp_path) -> None:
    """After firing, last_fired_at + next_due_at must be stamped on the
    TriggerDefinition and written to triggers.json. The activation-missed
    handshake reads these from disk on the next activation."""
    from framework.tools.queen_lifecycle_tools import (
        _read_agent_triggers_json,
        _start_trigger_timer,
    )

    bus = EventBus()
    session = _make_session(bus)
    session.colony_id = "test_colony"
    session.worker_path = tmp_path  # _save_trigger_to_agent writes here

    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    session.queen_executor = _make_executor(queen_node)

    tdef = TriggerDefinition(
        id="persist-timer",
        trigger_type="timer",
        trigger_config={"interval_minutes": 0.001},
        task="persist it",
    )

    await _start_trigger_timer(session, "persist-timer", tdef)
    await asyncio.sleep(0.15)

    task = session.active_timer_tasks.get("persist-timer")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # In-memory: TriggerDefinition was stamped.
    assert tdef.last_fired_at is not None
    assert tdef.next_due_at is not None

    # On-disk: triggers.json carries the same fields. This is the
    # signal the missed-handshake reads from on next activation.
    raw = _read_agent_triggers_json(tmp_path)
    persisted = next(t for t in raw if t["id"] == "persist-timer")
    assert persisted["last_fired_at"] == tdef.last_fired_at
    assert persisted["next_due_at"] == tdef.next_due_at


@pytest.mark.asyncio
async def test_timer_skipped_when_queen_node_unavailable() -> None:
    """No inject_trigger call and no exception when queen executor is not set."""
    from framework.tools.queen_lifecycle_tools import _start_trigger_timer

    bus = EventBus()
    session = _make_session(bus)
    session.colony_id = "test_colony"
    session.queen_executor = None  # queen not ready

    tdef = TriggerDefinition(
        id="no-queen-timer",
        trigger_type="timer",
        trigger_config={"interval_minutes": 0.001},
        task="should not fire",
    )

    await _start_trigger_timer(session, "no-queen-timer", tdef)
    await asyncio.sleep(0.15)

    task = session.active_timer_tasks.get("no-queen-timer")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # No exception raised, nothing to assert beyond completion


@pytest.mark.asyncio
async def test_webhook_trigger_fires_inject_trigger() -> None:
    """WEBHOOK_RECEIVED on EventBus → inject_trigger() on the queen node."""
    from framework.agent_loop.agent_loop import TriggerEvent
    from framework.tools.queen_lifecycle_tools import _start_trigger_webhook

    bus = EventBus()
    session = _make_session(bus)
    session.colony_id = "test_colony"

    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    session.queen_executor = _make_executor(queen_node)

    tdef = TriggerDefinition(
        id="test-webhook",
        trigger_type="webhook",
        trigger_config={"path": "/hooks/test", "methods": ["POST"]},
        task="process it",
    )

    # Patch WebhookServer to avoid binding a real port
    mock_server = MagicMock()
    mock_server.is_running = False
    mock_server.add_route = MagicMock()
    mock_server.start = AsyncMock()
    with patch("framework.host.webhook_server.WebhookServer", return_value=mock_server):
        with patch("framework.host.webhook_server.WebhookServerConfig"):
            await _start_trigger_webhook(session, "test-webhook", tdef)

    # Simulate an incoming webhook event on the EventBus
    await bus.emit_webhook_received(
        source_id="test-webhook",
        path="/hooks/test",
        method="POST",
        headers={},
        payload={"event": "push"},
    )
    await asyncio.sleep(0.05)  # let handler run

    assert queen_node.inject_trigger.await_count == 1
    trigger: TriggerEvent = queen_node.inject_trigger.await_args_list[0].args[0]
    assert trigger.trigger_type == "webhook"
    assert trigger.source_id == "test-webhook"
    assert trigger.payload["method"] == "POST"
    assert trigger.payload["path"] == "/hooks/test"
    assert trigger.payload["task"] == "process it"
    assert trigger.payload["payload"] == {"event": "push"}


@pytest.mark.asyncio
async def test_webhook_trigger_discarded_when_no_worker() -> None:
    """inject_trigger is NOT called when no worker is loaded."""
    from framework.tools.queen_lifecycle_tools import _start_trigger_webhook

    bus = EventBus()
    session = _make_session(bus)
    session.colony_id = None  # no colony bound

    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    session.queen_executor = _make_executor(queen_node)

    tdef = TriggerDefinition(
        id="no-worker-webhook",
        trigger_type="webhook",
        trigger_config={"path": "/hooks/noop", "methods": ["POST"]},
        task="should not fire",
    )

    mock_server = MagicMock()
    mock_server.is_running = False
    mock_server.add_route = MagicMock()
    mock_server.start = AsyncMock()
    with patch("framework.host.webhook_server.WebhookServer", return_value=mock_server):
        with patch("framework.host.webhook_server.WebhookServerConfig"):
            await _start_trigger_webhook(session, "no-worker-webhook", tdef)

    await bus.emit_webhook_received(
        source_id="no-worker-webhook",
        path="/hooks/noop",
        method="POST",
        headers={},
        payload={},
    )
    await asyncio.sleep(0.05)

    assert queen_node.inject_trigger.await_count == 0


@pytest.mark.asyncio
async def test_remove_trigger_cleans_up_webhook_subscription() -> None:
    """After remove_trigger(), WEBHOOK_RECEIVED no longer calls inject_trigger."""
    from framework.tools.queen_lifecycle_tools import _start_trigger_webhook

    bus = EventBus()
    session = _make_session(bus)
    session.colony_id = "test_colony"

    queen_node = SimpleNamespace(inject_trigger=AsyncMock())
    session.queen_executor = _make_executor(queen_node)

    tdef = TriggerDefinition(
        id="removable-webhook",
        trigger_type="webhook",
        trigger_config={"path": "/hooks/removable", "methods": ["POST"]},
        task="run it",
    )

    mock_server = MagicMock()
    mock_server.is_running = False
    mock_server.add_route = MagicMock()
    mock_server.start = AsyncMock()
    with patch("framework.host.webhook_server.WebhookServer", return_value=mock_server):
        with patch("framework.host.webhook_server.WebhookServerConfig"):
            await _start_trigger_webhook(session, "removable-webhook", tdef)

    # Manually unsubscribe (mirrors what remove_trigger does)
    sub_id = session.active_webhook_subs.pop("removable-webhook", None)
    assert sub_id is not None
    bus.unsubscribe(sub_id)

    # Now fire — should NOT reach queen
    await bus.emit_webhook_received(
        source_id="removable-webhook",
        path="/hooks/removable",
        method="POST",
        headers={},
        payload={},
    )
    await asyncio.sleep(0.05)

    assert queen_node.inject_trigger.await_count == 0
    assert "removable-webhook" not in session.active_webhook_subs


def test_run_worker_in_colony_tools() -> None:
    """run_worker must be available to the queen in COLONY phase."""
    from framework.agents.queen.nodes import _QUEEN_COLONY_TOOLS

    assert "run_worker" in _QUEEN_COLONY_TOOLS


def test_colony_tools_include_monitoring_and_review() -> None:
    """COLONY-phase queen must be able to monitor live workers AND review finished ones."""
    from framework.agents.queen.nodes import _QUEEN_COLONY_TOOLS

    for required in (
        # Live-worker controls
        "get_worker_status",
        "inject_message",
        "stop_worker",
        # Post-run review / scheduling
        "set_trigger",
        "remove_trigger",
        "list_triggers",
    ):
        assert required in _QUEEN_COLONY_TOOLS, f"{required} missing from colony tools"


def test_colony_tools_include_tracker_for_parallel_workers() -> None:
    """COLONY prompt requires tracker setup, so the callable tool list must expose it."""
    from framework.agents.queen.nodes import _QUEEN_COLONY_TOOLS

    for required in (
        "tracker_sql",
        "tracker_register_writable",
        "tracker_upsert",
        "tracker_query",
    ):
        assert required in _QUEEN_COLONY_TOOLS, f"{required} missing from colony tools"
