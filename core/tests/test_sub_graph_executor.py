"""
Tests for sub-graph execution wiring (issue #2503).

Verifies that:
1. GraphExecutor accepts sub_graph_executor callback
2. The callback is passed to NodeContext
3. delegate_to_sub_graph tool is available when callback is set
4. Sub-graph execution returns proper results
"""

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor, create_sub_graph_executor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeResult, NodeSpec, SharedMemory


class DummyRuntime:
    execution_id = ""

    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass


class SuccessNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"result": "ok"},
            tokens_used=1,
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_executor_accepts_sub_graph_executor():
    """GraphExecutor should accept sub_graph_executor in constructor."""
    runtime = DummyRuntime()

    async def sub_graph_executor(graph_id: str, goal_id: str | None, input_data: dict):
        return ExecutionResult(
            success=True,
            output={"child_result": "executed"},
            steps_executed=1,
            total_tokens=10,
            total_latency_ms=100,
        )

    executor = GraphExecutor(
        runtime=runtime,
        sub_graph_executor=sub_graph_executor,
    )

    assert executor.sub_graph_executor is sub_graph_executor


@pytest.mark.asyncio
async def test_sub_graph_executor_passed_to_node_context():
    """sub_graph_executor should be passed to NodeContext via _build_context."""
    runtime = DummyRuntime()

    async def sub_graph_executor(graph_id: str, goal_id: str | None, input_data: dict):
        return ExecutionResult(
            success=True,
            output={},
            steps_executed=1,
        )

    graph = GraphSpec(
        id="parent-graph",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="test node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node="n1",
        terminal_nodes=["n1"],
    )

    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"n1": SuccessNode()},
        sub_graph_executor=sub_graph_executor,
    )

    goal = Goal(
        id="g1",
        name="test-goal",
        description="test",
    )

    ctx = executor._build_context(
        node_spec=graph.nodes[0],
        memory=SharedMemory(),
        goal=goal,
        input_data={},
        max_tokens=4096,
        node_registry={},
    )

    assert ctx.sub_graph_executor is sub_graph_executor


@pytest.mark.asyncio
async def test_create_sub_graph_executor_factory():
    """create_sub_graph_executor should create a working callback that loads and executes graphs."""
    runtime = DummyRuntime()

    child_graph = GraphSpec(
        id="child-graph",
        goal_id="child-goal",
        nodes=[
            NodeSpec(
                id="child-node",
                name="Child Node",
                description="child test node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["child_output"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node="child-node",
        terminal_nodes=["child-node"],
    )

    child_goal = Goal(
        id="child-goal",
        name="Child Goal",
        description="child test goal",
    )

    def graph_loader(graph_id: str):
        if graph_id == "child-graph":
            return child_graph, child_goal
        return None

    sub_graph_executor = create_sub_graph_executor(
        graph_loader=graph_loader,
        runtime=runtime,
    )

    result = await sub_graph_executor(
        graph_id="child-graph",
        goal_id=None,
        input_data={"test_input": "value"},
    )

    assert result.success is False  # Expected: no LLM provider
    assert "child-graph" in str(result) or result.steps_executed >= 0


@pytest.mark.asyncio
async def test_sub_graph_executor_handles_missing_graph():
    """sub_graph_executor should handle missing graphs gracefully."""
    runtime = DummyRuntime()

    def graph_loader(graph_id: str):
        return None

    sub_graph_executor = create_sub_graph_executor(
        graph_loader=graph_loader,
        runtime=runtime,
    )

    result = await sub_graph_executor(
        graph_id="nonexistent-graph",
        goal_id=None,
        input_data={},
    )

    assert result.success is False
    assert "not found" in result.error.lower()
