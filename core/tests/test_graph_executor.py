"""
Tests for core GraphExecutor execution paths.
Focused on minimal success and failure scenarios.
"""

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult, NodeSpec


# ---- Dummy runtime (no real logging) ----
class DummyRuntime:
    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass


# ---- Fake node that always succeeds ----
class SuccessNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"result": 123},
            tokens_used=1,
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_executor_single_node_success():
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-1",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="test node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node="n1",
    )

    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"n1": SuccessNode()},
    )

    goal = Goal(
        id="g1",
        name="test-goal",
        description="simple test",
    )

    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
    assert result.path == ["n1"]
    assert result.steps_executed == 1


# ---- Fake node that always fails ----
class FailingNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=False,
            error="boom",
            output={},
            tokens_used=0,
            latency_ms=0,
        )


@pytest.mark.asyncio
async def test_executor_single_node_failure():
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-2",
        goal_id="g2",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="failing node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node="n1",
    )

    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"n1": FailingNode()},
    )

    goal = Goal(
        id="g2",
        name="fail-goal",
        description="failure test",
    )

    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is False
    assert result.error is not None
    assert result.path == ["n1"]
