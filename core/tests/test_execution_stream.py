"""Tests for ExecutionStream retention behavior."""

import json

import pytest

from framework.graph import NodeSpec, Goal, SuccessCriterion
from framework.graph.edge import GraphSpec
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.runtime.event_bus import EventBus
from framework.runtime.execution_stream import ExecutionStream, EntryPointSpec
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage


class DummyLLMProvider(LLMProvider):
    """Deterministic LLM provider for execution stream tests."""

    def complete(
        self,
        messages: list[dict[str, object]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, object] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        return LLMResponse(content=json.dumps({"result": "ok"}), model="dummy")

    def complete_with_tools(
        self,
        messages: list[dict[str, object]],
        system: str,
        tools: list[Tool],
        tool_executor: callable,
        max_iterations: int = 10,
    ) -> LLMResponse:
        return LLMResponse(content=json.dumps({"result": "ok"}), model="dummy")


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
        node_type="llm_generate",
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
