"""
Tests for core GraphExecutor execution paths.
Focused on minimal success and failure scenarios.
"""

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Constraint, Goal
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


# ---- Hard constraint enforcement ----
class NodeOutputViolatingConstraint:
    """Node that writes output violating a no-competitor-names constraint."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"content": "Our product is better than CompetitorBrand!"},
            tokens_used=1,
            latency_ms=1,
        )


class NodeOutputSatisfyingConstraint:
    """Node that writes output satisfying a no-competitor-names constraint."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"content": "Our product is great for your needs."},
            tokens_used=1,
            latency_ms=1,
        )


@pytest.mark.asyncio
async def test_executor_hard_constraint_violated_returns_success_false():
    """When output violates a hard constraint, execution returns success=False."""
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-constraint",
        goal_id="g-constraint",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="output node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["content"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node="n1",
    )

    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"n1": NodeOutputViolatingConstraint()},
    )

    goal = Goal(
        id="g-constraint",
        name="constraint-goal",
        description="No competitor names in content",
        constraints=[
            Constraint(
                id="no-competitor-names",
                description="No competitor brand names",
                constraint_type="hard",
                check="'CompetitorBrand' not in str(result.get('content', ''))",
            )
        ],
    )

    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is False
    assert "Hard constraint violated" in (result.error or "")
    assert "no-competitor-names" in (result.error or "")
    assert result.output.get("content") == "Our product is better than CompetitorBrand!"


@pytest.mark.asyncio
async def test_executor_hard_constraint_satisfied_returns_success_true():
    """When output satisfies a hard constraint, execution returns success=True."""
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-constraint-ok",
        goal_id="g-constraint-ok",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="output node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["content"],
                max_retries=0,
            )
        ],
        edges=[],
        entry_node="n1",
    )

    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"n1": NodeOutputSatisfyingConstraint()},
    )

    goal = Goal(
        id="g-constraint-ok",
        name="constraint-goal",
        description="No competitor names in content",
        constraints=[
            Constraint(
                id="no-competitor-names",
                description="No competitor brand names",
                constraint_type="hard",
                check="'CompetitorBrand' not in str(result.get('content', ''))",
            )
        ],
    )

    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
    assert result.output.get("content") == "Our product is great for your needs."


@pytest.mark.asyncio
async def test_executor_constraint_empty_check_skipped():
    """Constraints with empty check are skipped; execution can still succeed."""
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-empty-check",
        goal_id="g-empty-check",
        nodes=[
            NodeSpec(
                id="n1",
                name="node1",
                description="output node",
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
        id="g-empty-check",
        name="goal-with-empty-check",
        description="Constraint with no programmatic check",
        constraints=[
            Constraint(
                id="no-check",
                description="No competitor names",
                constraint_type="hard",
                check="",  # empty -> skipped
            )
        ],
    )

    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
    assert result.path == ["n1"]
