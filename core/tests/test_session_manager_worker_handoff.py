from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.host.event_bus import EventBus, EventType
from framework.server.queen_orchestrator import install_worker_escalation_routing
from framework.server.session_manager import Session, SessionManager


def _make_session(event_bus: EventBus, session_id: str = "session_handoff") -> Session:
    return Session(id=session_id, event_bus=event_bus, llm=object(), loaded_at=0.0)


def _attach_queen(session: Session, queen_node) -> None:
    session.queen_executor = SimpleNamespace(node_registry={"queen": queen_node})


@pytest.mark.asyncio
async def test_worker_handoff_injects_addressed_request_into_queen() -> None:
    bus = EventBus()
    session = _make_session(bus)
    queen_node = SimpleNamespace(inject_event=AsyncMock())
    _attach_queen(session, queen_node)

    sub_id = install_worker_escalation_routing(session)
    assert sub_id is not None
    session.worker_handoff_sub = sub_id

    await bus.emit_escalation_requested(
        stream_id="worker:abc123",
        node_id="research_node",
        reason="Credential wall",
        context="HTTP 401 while calling external API",
        execution_id="exec_123",
        request_id="req-xyz",
    )

    queen_node.inject_event.assert_awaited_once()
    injected = queen_node.inject_event.await_args.args[0]
    kwargs = queen_node.inject_event.await_args.kwargs

    assert "[WORKER_ESCALATION]" in injected
    assert "request_id: req-xyz" in injected
    assert "worker_id: abc123" in injected
    assert "node_id: research_node" in injected
    assert "reason: Credential wall" in injected
    assert "HTTP 401 while calling external API" in injected
    assert kwargs["is_client_input"] is False
    # Entry recorded so reply_to_worker can address it later.
    assert "req-xyz" in session.pending_escalations
    entry = session.pending_escalations["req-xyz"]
    assert entry["worker_id"] == "abc123"
    assert entry["reason"] == "Credential wall"


@pytest.mark.asyncio
async def test_worker_handoff_ignores_queen_stream() -> None:
    bus = EventBus()
    session = _make_session(bus)
    queen_node = SimpleNamespace(inject_event=AsyncMock())
    _attach_queen(session, queen_node)

    install_worker_escalation_routing(session)

    await bus.emit_escalation_requested(
        stream_id="queen",
        node_id="queen",
        reason="should be ignored",
        request_id="req-ignored",
    )

    assert queen_node.inject_event.await_count == 0
    assert "req-ignored" not in session.pending_escalations


@pytest.mark.asyncio
async def test_worker_handoff_queen_dead_falls_back_to_client_input() -> None:
    """When the queen is not attached, the handoff should surface to the user."""
    bus = EventBus()
    session = _make_session(bus)
    # No queen_executor attached.

    captured = []

    async def _capture(event):
        captured.append(event)

    bus.subscribe(
        event_types=[EventType.CLIENT_INPUT_REQUESTED],
        handler=_capture,
    )
    install_worker_escalation_routing(session)

    await bus.emit_escalation_requested(
        stream_id="worker:w1",
        node_id="node_1",
        reason="stuck",
        request_id="req-dead",
    )

    assert any("[WORKER_ESCALATION]" in (e.data or {}).get("prompt", "") for e in captured)
    # Entry still recorded — queen may come back online and drain it.
    assert "req-dead" in session.pending_escalations


@pytest.mark.asyncio
async def test_stop_session_unsubscribes_worker_handoff() -> None:
    bus = EventBus()
    manager = SessionManager()
    session = _make_session(bus, session_id="session_stop")
    queen_node = SimpleNamespace(inject_event=AsyncMock())
    _attach_queen(session, queen_node)

    session.worker_handoff_sub = install_worker_escalation_routing(session)
    manager._sessions[session.id] = session

    await bus.emit_escalation_requested(
        stream_id="worker:main",
        node_id="node_1",
        reason="before stop",
        request_id="req-before",
    )
    assert queen_node.inject_event.await_count == 1

    stopped = await manager.stop_session(session.id)
    assert stopped is True
    assert session.worker_handoff_sub is None

    await bus.emit_escalation_requested(
        stream_id="worker:main",
        node_id="node_1",
        reason="after stop",
        request_id="req-after",
    )
    assert queen_node.inject_event.await_count == 1


@pytest.mark.asyncio
async def test_load_worker_core_defaults_to_session_llm_model(monkeypatch, tmp_path) -> None:
    bus = EventBus()
    manager = SessionManager(model="manager-default")
    session_llm = SimpleNamespace(model="queen-shared-model")
    session = Session(id="session_worker", event_bus=bus, llm=session_llm, loaded_at=0.0)

    runtime = SimpleNamespace(is_running=True)
    runner = SimpleNamespace(
        _llm=None,
        _agent_runtime=runtime,
        info=MagicMock(return_value={"id": "worker"}),
    )

    load_calls: list[dict[str, object]] = []

    def fake_load(agent_path, model=None, **kwargs):
        load_calls.append({"agent_path": agent_path, "model": model, "kwargs": kwargs})
        return runner

    monkeypatch.setattr("framework.loader.agent_loader.AgentLoader.load", fake_load)
    monkeypatch.setattr(manager, "_cleanup_stale_active_sessions", lambda *_args: None)
    monkeypatch.setattr(
        "framework.tools.queen_lifecycle_tools._read_agent_triggers_json",
        lambda *_args: [],
    )

    await manager._load_worker_core(session, tmp_path / "worker_agent")

    assert load_calls[0]["model"] == "queen-shared-model"
    assert session.runner is runner
    assert session.runner._llm is session_llm


@pytest.mark.asyncio
async def test_load_worker_core_keeps_explicit_worker_model_override(monkeypatch, tmp_path) -> None:
    bus = EventBus()
    manager = SessionManager(model="manager-default")
    session_llm = SimpleNamespace(model="queen-shared-model")
    session = Session(id="session_override", event_bus=bus, llm=session_llm, loaded_at=0.0)

    runtime = SimpleNamespace(is_running=True)
    runner = SimpleNamespace(
        _llm=None,
        _agent_runtime=runtime,
        info=MagicMock(return_value={"id": "worker"}),
    )

    load_calls: list[dict[str, object]] = []

    def fake_load(agent_path, model=None, **kwargs):
        load_calls.append({"agent_path": agent_path, "model": model, "kwargs": kwargs})
        return runner

    monkeypatch.setattr("framework.loader.agent_loader.AgentLoader.load", fake_load)
    monkeypatch.setattr(manager, "_cleanup_stale_active_sessions", lambda *_args: None)
    monkeypatch.setattr(
        "framework.tools.queen_lifecycle_tools._read_agent_triggers_json",
        lambda *_args: [],
    )

    await manager._load_worker_core(
        session,
        tmp_path / "worker_agent",
        model="explicit-worker-model",
    )

    assert load_calls[0]["model"] == "explicit-worker-model"
    assert session.runner is runner
    assert session.runner._llm is None

    assert session.worker_path == tmp_path / "worker_agent"
