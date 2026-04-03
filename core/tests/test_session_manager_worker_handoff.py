from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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

    monkeypatch.setattr("framework.runner.AgentRunner.load", fake_load)
    monkeypatch.setattr(manager, "_cleanup_stale_active_sessions", lambda *_args: None)
    monkeypatch.setattr(manager, "_subscribe_worker_digest", lambda *_args: None)
    monkeypatch.setattr(manager, "_subscribe_worker_colony_memory", AsyncMock())
    monkeypatch.setattr(
        "framework.tools.queen_lifecycle_tools._read_agent_triggers_json",
        lambda *_args: [],
    )

    await manager._load_worker_core(session, tmp_path / "worker_agent")

    assert load_calls[0]["model"] == "queen-shared-model"
    assert session.runner is runner
    assert session.runner._llm is session_llm
    assert runtime._dynamic_memory_provider_factory is not None


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

    monkeypatch.setattr("framework.runner.AgentRunner.load", fake_load)
    monkeypatch.setattr(manager, "_cleanup_stale_active_sessions", lambda *_args: None)
    monkeypatch.setattr(manager, "_subscribe_worker_digest", lambda *_args: None)
    monkeypatch.setattr(manager, "_subscribe_worker_colony_memory", AsyncMock())
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


@pytest.mark.asyncio
async def test_load_worker_core_continues_when_colony_memory_subscription_fails(
    monkeypatch, tmp_path
) -> None:
    bus = EventBus()
    manager = SessionManager(model="manager-default")
    session_llm = SimpleNamespace(model="queen-shared-model")
    session = Session(id="session_memory_warning", event_bus=bus, llm=session_llm, loaded_at=0.0)

    runtime = SimpleNamespace(is_running=True)
    runner = SimpleNamespace(
        _llm=None,
        _agent_runtime=runtime,
        info=MagicMock(return_value={"id": "worker"}),
    )

    monkeypatch.setattr("framework.runner.AgentRunner.load", lambda *args, **kwargs: runner)
    monkeypatch.setattr(manager, "_cleanup_stale_active_sessions", lambda *_args: None)
    monkeypatch.setattr(manager, "_subscribe_worker_digest", lambda *_args: None)
    monkeypatch.setattr(
        manager,
        "_subscribe_worker_colony_memory",
        AsyncMock(side_effect=ImportError("optional memory hook unavailable")),
    )
    monkeypatch.setattr(
        "framework.tools.queen_lifecycle_tools._read_agent_triggers_json",
        lambda *_args: [],
    )

    await manager._load_worker_core(session, tmp_path / "worker_agent")

    assert session.runner is runner
    assert session.graph_runtime is runtime
    assert session.worker_path == tmp_path / "worker_agent"
