from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from framework.runtime.event_bus import EventBus
from framework.server.session_manager import Session, SessionManager


def _make_session(event_bus: EventBus, session_id: str = "session_handoff") -> Session:
    return Session(id=session_id, event_bus=event_bus, llm=object(), loaded_at=0.0)


def _make_executor(queen_node) -> SimpleNamespace:
    node_registry = {}
    if queen_node is not None:
        node_registry["queen"] = queen_node
    return SimpleNamespace(node_registry=node_registry)


@pytest.mark.asyncio
async def test_worker_handoff_injects_formatted_request_into_queen() -> None:
    bus = EventBus()
    manager = SessionManager()
    session = _make_session(bus)

    queen_node = SimpleNamespace(inject_event=AsyncMock())
    manager._subscribe_worker_handoffs(session, _make_executor(queen_node))

    await bus.emit_escalation_requested(
        stream_id="worker_a",
        node_id="research_node",
        reason="Credential wall",
        context="HTTP 401 while calling external API",
        execution_id="exec_123",
    )

    queen_node.inject_event.assert_awaited_once()
    injected = queen_node.inject_event.await_args.args[0]
    kwargs = queen_node.inject_event.await_args.kwargs

    assert "[WORKER_ESCALATION_REQUEST]" in injected
    assert "stream_id: worker_a" in injected
    assert "node_id: research_node" in injected
    assert "reason: Credential wall" in injected
    assert "context:\nHTTP 401 while calling external API" in injected
    assert kwargs["is_client_input"] is False


@pytest.mark.asyncio
async def test_worker_handoff_ignores_queen_stream() -> None:
    bus = EventBus()
    manager = SessionManager()
    session = _make_session(bus)

    queen_node = SimpleNamespace(inject_event=AsyncMock())
    manager._subscribe_worker_handoffs(session, _make_executor(queen_node))

    await bus.emit_escalation_requested(
        stream_id="queen",
        node_id="queen",
        reason="should be ignored",
    )

    assert queen_node.inject_event.await_count == 0


@pytest.mark.asyncio
async def test_worker_handoff_resubscribe_replaces_previous_subscription() -> None:
    bus = EventBus()
    manager = SessionManager()
    session = _make_session(bus)

    old_queen_node = SimpleNamespace(inject_event=AsyncMock())
    manager._subscribe_worker_handoffs(session, _make_executor(old_queen_node))
    first_sub = session.worker_handoff_sub
    assert first_sub is not None

    new_queen_node = SimpleNamespace(inject_event=AsyncMock())
    manager._subscribe_worker_handoffs(session, _make_executor(new_queen_node))
    second_sub = session.worker_handoff_sub

    assert second_sub is not None
    assert second_sub != first_sub
    assert first_sub not in bus._subscriptions

    await bus.emit_escalation_requested(
        stream_id="worker_b",
        node_id="planner",
        reason="stuck",
    )

    assert old_queen_node.inject_event.await_count == 0
    new_queen_node.inject_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_session_unsubscribes_worker_handoff() -> None:
    bus = EventBus()
    manager = SessionManager()
    session = _make_session(bus, session_id="session_stop")

    queen_node = SimpleNamespace(inject_event=AsyncMock())
    manager._subscribe_worker_handoffs(session, _make_executor(queen_node))
    manager._sessions[session.id] = session

    await bus.emit_escalation_requested(
        stream_id="worker_main",
        node_id="node_1",
        reason="before stop",
    )
    assert queen_node.inject_event.await_count == 1

    stopped = await manager.stop_session(session.id)
    assert stopped is True
    assert session.worker_handoff_sub is None

    await bus.emit_escalation_requested(
        stream_id="worker_main",
        node_id="node_1",
        reason="after stop",
    )
    assert queen_node.inject_event.await_count == 1
