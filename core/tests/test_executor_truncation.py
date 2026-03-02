"""
Tests for executor max_steps exhaustion detection.

Validates that GraphExecutor correctly reports execution_quality="truncated"
when the step budget is exhausted without reaching a terminal node,
and "clean" when a terminal node is properly reached.
"""

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult, NodeSpec


# ---- Minimal runtime stub (matches test_graph_executor.py pattern) ----
class DummyRuntime:
    execution_id = ""

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
            output={"result": "done"},
            tokens_used=1,
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_terminal_node_reached_is_clean():
    """When the executor reaches a terminal node, quality should be 'clean'."""
    graph = GraphSpec(
        id="graph-term",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="start",
                name="start",
                description="entry",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
            NodeSpec(
                id="end",
                name="end",
                description="terminal",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[
            EdgeSpec(
                id="e1",
                source="start",
                target="end",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        entry_node="start",
        terminal_nodes=["end"],
        max_steps=10,
    )

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"start": SuccessNode(), "end": SuccessNode()},
    )

    goal = Goal(id="g1", name="test", description="test")
    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
    assert result.execution_quality == "clean"
    assert "end" in result.path


@pytest.mark.asyncio
async def test_no_edges_ends_cleanly():
    """A single node with no outgoing edges should end with 'clean'."""
    graph = GraphSpec(
        id="graph-single",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="only",
                name="only",
                description="sole node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[],
        entry_node="only",
        max_steps=10,
    )

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"only": SuccessNode()},
    )

    goal = Goal(id="g1", name="test", description="test")
    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
    assert result.execution_quality == "clean"


@pytest.mark.asyncio
async def test_max_steps_exhaustion_is_truncated():
    """Exhausting max_steps in a self-loop should report 'truncated'."""
    graph = GraphSpec(
        id="graph-loop",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="loop_node",
                name="loop_node",
                description="loops forever",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[
            EdgeSpec(
                id="self_loop",
                source="loop_node",
                target="loop_node",
                condition=EdgeCondition.ALWAYS,
            ),
        ],
        entry_node="loop_node",
        terminal_nodes=[],  # No terminal nodes — loop never ends
        max_steps=3,  # Small step budget
    )

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"loop_node": SuccessNode()},
    )

    goal = Goal(id="g1", name="test", description="test")
    result = await executor.execute(graph=graph, goal=goal)

    # Should still return partial output (not crash)
    assert result.success is True
    # But quality should indicate truncation, NOT clean
    assert result.execution_quality == "truncated"
    assert result.steps_executed == 3
