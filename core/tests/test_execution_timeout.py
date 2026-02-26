"""
Tests for GraphExecutor execution timeout enforcement.

Verifies that:
1. execution_timeout_seconds stops runaway executions at node boundaries
2. Timeout results include saved state for potential resumption
3. No timeout is enforced when execution_timeout_seconds is None (default)
"""

import asyncio

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult, NodeSpec


class DummyRuntime:
    """Minimal runtime stub for testing."""

    execution_id = ""

    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass


class SlowNode:
    """A node that sleeps to simulate long-running work."""

    def __init__(self, delay: float = 0.3):
        self._delay = delay

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        await asyncio.sleep(self._delay)
        return NodeResult(
            success=True,
            output={"result": "done"},
            tokens_used=1,
            latency_ms=int(self._delay * 1000),
        )


class InstantNode:
    """A node that completes immediately."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"result": "instant"},
            tokens_used=1,
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_execution_timeout_stops_at_node_boundary():
    """Execution should stop when wall-clock time exceeds the configured timeout."""
    # Create a chain of 3 slow nodes (each takes ~0.3s, total ~0.9s)
    # Set a timeout of 0.5s — should stop before completing all 3
    graph = GraphSpec(
        id="timeout-test",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="n1",
                name="slow-1",
                description="First slow node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
            ),
            NodeSpec(
                id="n2",
                name="slow-2",
                description="Second slow node",
                node_type="event_loop",
                input_keys=["result"],
                output_keys=["result"],
            ),
            NodeSpec(
                id="n3",
                name="slow-3",
                description="Third slow node",
                node_type="event_loop",
                input_keys=["result"],
                output_keys=["result"],
            ),
        ],
        edges=[
            {"id": "e1", "source": "n1", "target": "n2", "condition": "on_success"},
            {"id": "e2", "source": "n2", "target": "n3", "condition": "on_success"},
        ],
        entry_node="n1",
        execution_timeout_seconds=0.5,
    )

    slow = SlowNode(delay=0.3)
    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": slow, "n2": slow, "n3": slow},
    )

    goal = Goal(id="g1", name="timeout-test", description="Test timeout")
    result = await executor.execute(graph=graph, goal=goal)

    # Should have timed out (not all 3 nodes completed)
    assert result.success is False
    assert "timed out" in result.error.lower()
    assert result.execution_quality == "failed"
    # Should have executed at least 1 node but not all 3
    assert 0 < result.steps_executed < 3
    # Session state should be saved for potential resume
    assert "memory" in result.session_state
    assert "execution_path" in result.session_state


@pytest.mark.asyncio
async def test_no_timeout_when_none():
    """When execution_timeout_seconds is None (default), no timeout applies."""
    graph = GraphSpec(
        id="no-timeout-test",
        goal_id="g1",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="Test node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
            ),
        ],
        edges=[],
        entry_node="n1",
        # execution_timeout_seconds is None by default
    )

    assert graph.execution_timeout_seconds is None

    executor = GraphExecutor(
        runtime=DummyRuntime(),
        node_registry={"n1": InstantNode()},
    )

    goal = Goal(id="g1", name="no-timeout", description="No timeout test")
    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True


@pytest.mark.asyncio
async def test_timeout_field_on_graph_spec():
    """execution_timeout_seconds should be configurable on GraphSpec."""
    # Test default
    graph_default = GraphSpec(
        id="default",
        goal_id="g1",
        nodes=[],
        edges=[],
        entry_node="n1",
    )
    assert graph_default.execution_timeout_seconds is None

    # Test explicit value
    graph_with_timeout = GraphSpec(
        id="with-timeout",
        goal_id="g1",
        nodes=[],
        edges=[],
        entry_node="n1",
        execution_timeout_seconds=300.0,
    )
    assert graph_with_timeout.execution_timeout_seconds == 300.0

    # Test zero (should be valid - means immediate timeout)
    graph_zero = GraphSpec(
        id="zero-timeout",
        goal_id="g1",
        nodes=[],
        edges=[],
        entry_node="n1",
        execution_timeout_seconds=0,
    )
    assert graph_zero.execution_timeout_seconds == 0
