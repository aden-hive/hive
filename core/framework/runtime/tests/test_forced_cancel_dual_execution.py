"""Regression tests for forced cancellation overlap in ExecutionStream."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.execution_manager import (
    EntryPointSpec,
    ExecutionAlreadyRunningError,
    ExecutionManager,
)
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.goal import Goal
from framework.orchestrator.orchestrator import ExecutionResult


def _build_stream(tmp_path, *, event_bus: EventBus | None = None) -> ExecutionManager:
    graph = GraphSpec(
        id="test-graph",
        goal_id="goal-1",
        version="1.0.0",
        entry_node="start",
        entry_points={"start": "start"},
        terminal_nodes=[],
        pause_nodes=[],
        nodes=[],
        edges=[],
    )
    goal = Goal(id="goal-1", name="goal-1", description="test goal")
    entry_spec = EntryPointSpec(
        id="webhook",
        name="Webhook",
        entry_node="start",
        trigger_type="webhook",
        isolation_level="shared",
        max_concurrent=1,
    )

    storage = SimpleNamespace(base_path=tmp_path)
    stream = ExecutionManager(
        stream_id="webhook",
        entry_spec=entry_spec,
        graph=graph,
        goal=goal,
        state_manager=MagicMock(),
        storage=storage,
        outcome_aggregator=MagicMock(),
        event_bus=event_bus,
    )
    stream._running = True
    return stream


def _install_blocking_executor(monkeypatch, release: asyncio.Event) -> None:
    class BlockingExecutor:
        def __init__(self, *args, **kwargs):
            self.node_registry = {}

        async def execute(self, *args, **kwargs):
            while True:
                try:
                    await release.wait()
                    break
                except asyncio.CancelledError:
                    continue
            return ExecutionResult(success=True, output={"ok": True})

    monkeypatch.setattr("framework.host.execution_manager.Orchestrator", BlockingExecutor)


@pytest.mark.asyncio
async def test_forced_cancel_timeout_keeps_stream_locked_until_task_exit(tmp_path, monkeypatch):
    event_bus = EventBus()
    stream = _build_stream(tmp_path, event_bus=event_bus)
    release = asyncio.Event()
    _install_blocking_executor(monkeypatch, release)

    started_events: list[AgentEvent] = []
    first_started = asyncio.Event()
    second_started = asyncio.Event()

    async def on_started(event: AgentEvent) -> None:
        started_events.append(event)
        if len(started_events) == 1:
            first_started.set()
        elif len(started_events) == 2:
            second_started.set()

    event_bus.subscribe(
        event_types=[EventType.EXECUTION_STARTED],
        handler=on_started,
        filter_stream="webhook",
    )

    async def immediate_timeout(_tasks, timeout=None):
        return set(), set(_tasks)

    execution_id = await stream.execute({}, session_state={"resume_session_id": "session-1"})
    await asyncio.wait_for(first_started.wait(), timeout=1)

    old_task = stream._execution_tasks[execution_id]
    monkeypatch.setattr("framework.host.execution_manager.asyncio.wait", immediate_timeout)

    try:
        cancelled = await stream.cancel_execution(execution_id, reason="forced timeout")

        assert cancelled == "cancelling"
        assert execution_id in stream._execution_tasks
        assert execution_id in stream._active_executions
        assert execution_id in stream._completion_events
        assert stream._active_executions[execution_id].status == "cancelling"
        assert not old_task.done()

        with pytest.raises(ExecutionAlreadyRunningError):
            await stream.execute({}, session_state={"resume_session_id": execution_id})

        assert len(started_events) == 1

        release.set()
        await asyncio.wait_for(old_task, timeout=1)

        restarted_id = await stream.execute({}, session_state={"resume_session_id": execution_id})
        assert restarted_id == execution_id
        await asyncio.wait_for(second_started.wait(), timeout=1)
    finally:
        release.set()
        await asyncio.gather(*stream._execution_tasks.values(), return_exceptions=True)


@pytest.mark.asyncio
async def test_repeated_forced_restarts_do_not_accumulate_parallel_tasks(tmp_path, monkeypatch):
    event_bus = EventBus()
    stream = _build_stream(tmp_path, event_bus=event_bus)
    release = asyncio.Event()
    _install_blocking_executor(monkeypatch, release)

    started_events: list[AgentEvent] = []
    first_started = asyncio.Event()

    async def on_started(event: AgentEvent) -> None:
        started_events.append(event)
        first_started.set()

    event_bus.subscribe(
        event_types=[EventType.EXECUTION_STARTED],
        handler=on_started,
        filter_stream="webhook",
    )

    async def immediate_timeout(_tasks, timeout=None):
        return set(), set(_tasks)

    monkeypatch.setattr("framework.host.execution_manager.asyncio.wait", immediate_timeout)

    execution_id = await stream.execute({}, session_state={"resume_session_id": "session-1"})
    await asyncio.wait_for(first_started.wait(), timeout=1)

    first_task = stream._execution_tasks[execution_id]

    try:
        assert await stream.cancel_execution(execution_id, reason="restart-1") == "cancelling"

        with pytest.raises(ExecutionAlreadyRunningError):
            await stream.execute({}, session_state={"resume_session_id": execution_id})

        with pytest.raises(ExecutionAlreadyRunningError):
            await stream.execute({}, session_state={"resume_session_id": execution_id})

        assert len(started_events) == 1
        assert list(stream._execution_tasks) == [execution_id]
        assert stream._execution_tasks[execution_id] is first_task
        assert not first_task.done()
    finally:
        release.set()
        await asyncio.wait_for(first_task, timeout=1)
