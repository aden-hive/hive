"""Tests for ExecutionStream retention behavior."""

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from framework.graph import Goal, NodeSpec, SuccessCriterion
from framework.graph.edge import GraphSpec
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import FinishEvent, StreamEvent, TextDeltaEvent, ToolCallEvent
from framework.runtime.event_bus import EventBus
from framework.runtime.execution_stream import EntryPointSpec, ExecutionStream
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage


class DummyLLMProvider(LLMProvider):
    """Deterministic LLM provider for execution stream tests.

    Uses set_output tool call to properly set outputs, avoiding stall detection.
    """

    def __init__(self):
        self._call_count = 0

    def complete(
        self,
        messages: list[dict[str, object]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, object] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        return LLMResponse(content="Summary for compaction.", model="dummy")

    def complete_with_tools(
        self,
        messages: list[dict[str, object]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable,
        max_iterations: int = 10,
    ) -> LLMResponse:
        return LLMResponse(content="Summary for compaction.", model="dummy")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        self._call_count += 1

        if self._call_count == 1:
            # First call: set the output via tool call
            yield ToolCallEvent(
                tool_use_id=f"tc_{self._call_count}",
                tool_name="set_output",
                tool_input={"key": "result", "value": "ok"},
            )
            yield FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=10)
        else:
            # Subsequent calls: just finish with text
            yield TextDeltaEvent(content="Done.", snapshot="Done.")
            yield FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5)


@pytest.mark.asyncio
async def test_execution_stream_retention(tmp_path):
    goal = Goal(
        id="test-goal",
        name="Test Goal",
        description="Retention test",
        success_criteria=[
            SuccessCriterion(
                id="result",
                description="Result present",
                metric="output_contains",
                target="result",
            )
        ],
        constraints=[],
    )

    node = NodeSpec(
        id="hello",
        name="Hello",
        description="Return a result",
        node_type="event_loop",
        input_keys=["user_name"],
        output_keys=["result"],
        system_prompt='Return JSON: {"result": "ok"}',
    )

    graph = GraphSpec(
        id="test-graph",
        goal_id=goal.id,
        version="1.0.0",
        entry_node="hello",
        entry_points={"start": "hello"},
        terminal_nodes=["hello"],
        pause_nodes=[],
        nodes=[node],
        edges=[],
        default_model="dummy",
        max_tokens=10,
    )

    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    stream = ExecutionStream(
        stream_id="start",
        entry_spec=EntryPointSpec(
            id="start",
            name="Start",
            entry_node="hello",
            trigger_type="manual",
            isolation_level="shared",
        ),
        graph=graph,
        goal=goal,
        state_manager=SharedStateManager(),
        storage=storage,
        outcome_aggregator=OutcomeAggregator(goal, EventBus()),
        event_bus=None,
        llm=DummyLLMProvider(),
        tools=[],
        tool_executor=None,
        result_retention_max=3,
        result_retention_ttl_seconds=None,
    )

    await stream.start()

    for i in range(5):
        execution_id = await stream.execute({"user_name": f"user-{i}"})
        result = await stream.wait_for_completion(execution_id, timeout=5)
        assert result is not None
        assert execution_id not in stream._active_executions
        assert execution_id not in stream._completion_events
        assert execution_id not in stream._execution_tasks

    assert len(stream._execution_results) <= 3

    await stream.stop()
    await storage.stop()


@pytest.mark.asyncio
async def test_shared_session_reuses_directory_and_memory(tmp_path):
    """When an async entry point uses resume_session_id, it should:
    1. Run in the same session directory as the primary execution
    2. Have access to the primary session's memory
    3. NOT overwrite the primary session's state.json
    """
    goal = Goal(
        id="test-goal",
        name="Test",
        description="Shared session test",
        success_criteria=[
            SuccessCriterion(
                id="result",
                description="Result present",
                metric="output_contains",
                target="result",
            )
        ],
        constraints=[],
    )

    node = NodeSpec(
        id="hello",
        name="Hello",
        description="Return a result",
        node_type="event_loop",
        input_keys=["user_name"],
        output_keys=["result"],
        system_prompt='Return JSON: {"result": "ok"}',
    )

    graph = GraphSpec(
        id="test-graph",
        goal_id=goal.id,
        version="1.0.0",
        entry_node="hello",
        entry_points={"start": "hello"},
        terminal_nodes=["hello"],
        pause_nodes=[],
        nodes=[node],
        edges=[],
        default_model="dummy",
        max_tokens=10,
    )

    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    from framework.storage.session_store import SessionStore

    session_store = SessionStore(tmp_path)

    # Primary stream
    primary_stream = ExecutionStream(
        stream_id="primary",
        entry_spec=EntryPointSpec(
            id="primary",
            name="Primary",
            entry_node="hello",
            trigger_type="manual",
            isolation_level="shared",
        ),
        graph=graph,
        goal=goal,
        state_manager=SharedStateManager(),
        storage=storage,
        outcome_aggregator=OutcomeAggregator(goal, EventBus()),
        event_bus=None,
        llm=DummyLLMProvider(),
        tools=[],
        tool_executor=None,
        session_store=session_store,
    )

    await primary_stream.start()

    # Run primary execution — creates session directory and state.json
    primary_exec_id = await primary_stream.execute({"user_name": "alice"})
    primary_result = await primary_stream.wait_for_completion(primary_exec_id, timeout=5)
    assert primary_result is not None
    assert primary_result.success

    # Verify primary session's state.json exists and has the primary entry_point
    primary_state_path = tmp_path / "sessions" / primary_exec_id / "state.json"
    assert primary_state_path.exists()
    primary_state = json.loads(primary_state_path.read_text())
    assert primary_state["entry_point"] == "primary"

    # Async stream — simulates a webhook entry point sharing the session
    async_stream = ExecutionStream(
        stream_id="webhook",
        entry_spec=EntryPointSpec(
            id="webhook",
            name="Webhook",
            entry_node="hello",
            trigger_type="event",
            isolation_level="shared",
        ),
        graph=graph,
        goal=goal,
        state_manager=SharedStateManager(),
        storage=storage,
        outcome_aggregator=OutcomeAggregator(goal, EventBus()),
        event_bus=None,
        llm=DummyLLMProvider(),
        tools=[],
        tool_executor=None,
        session_store=session_store,
    )

    await async_stream.start()

    # Run async execution with resume_session_id pointing to primary session
    session_state = {
        "resume_session_id": primary_exec_id,
        "memory": {"rules": "star important emails"},
    }
    async_exec_id = await async_stream.execute({"event": "new_email"}, session_state=session_state)

    # Should reuse the primary session ID
    assert async_exec_id == primary_exec_id

    async_result = await async_stream.wait_for_completion(async_exec_id, timeout=5)
    assert async_result is not None
    assert async_result.success

    # State.json should NOT have been overwritten by the async execution
    # (it should still show the primary entry point)
    final_state = json.loads(primary_state_path.read_text())
    assert final_state["entry_point"] == "primary"

    # Verify only ONE session directory exists (not two)
    sessions_dir = tmp_path / "sessions"
    session_dirs = [d for d in sessions_dir.iterdir() if d.is_dir()]
    assert len(session_dirs) == 1
    assert session_dirs[0].name == primary_exec_id

    await primary_stream.stop()
    await async_stream.stop()
    await storage.stop()
