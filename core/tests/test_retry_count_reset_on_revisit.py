"""
Regression tests for GitHub issue #6605:
node_retry_counts never reset on node re-visits — nodes silently lose their
entire retry budget after the first failure cycle in feedback-loop graphs.

Fix: split retry tracking into two counters:
  - node_retry_counts: per-visit budget counter (reset on fresh visits)
  - node_retry_totals: cumulative retry metrics (never reset)
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


# ---------------------------------------------------------------------------
# Shared node implementations
# ---------------------------------------------------------------------------


class CallCountingFlakyNode(NodeProtocol):
    """Fails on the first `fail_times` calls, then succeeds.

    `attempt_count` is a shared counter across all visits so the test can
    assert exactly how many times the executor invoked the node.
    """

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Fail for the first ``fail_times`` calls, then succeed."""
        self.attempt_count += 1
        if self.attempt_count <= self.fail_times:
            return NodeResult(
                success=False,
                error=f"transient error (attempt {self.attempt_count})",
            )
        return NodeResult(
            success=True,
            output={"result": f"ok after {self.attempt_count} attempts"},
        )


class AlwaysSucceedsNode(NodeProtocol):
    """Stub node that always succeeds, used as the recovery target in feedback-loop graphs."""

    def __init__(self):
        self.execute_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Return a successful result and increment the call counter."""
        self.execute_count += 1
        return NodeResult(success=True, output={"recovered": True})


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Suppress exponential backoff delays."""
    monkeypatch.setattr("asyncio.sleep", AsyncMock())


@pytest.fixture
def runtime():
    """Provide a mock Runtime with all required methods stubbed."""
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="run_id")
    rt.decide = MagicMock(return_value="decision_id")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.set_node = MagicMock()
    return rt


@pytest.fixture
def goal():
    """Provide a minimal Goal for executor tests."""
    return Goal(id="g1", name="Retry Reset Test", description="Verifies retry budget resets")


# ---------------------------------------------------------------------------
# Test 1 — single failure cycle: visit 1 exhausts retries, visit 2 succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_budget_reset_on_revisit_via_on_failure(runtime, goal):
    """
    Graph: FlakyNode (max_retries=3) --ON_FAILURE--> RecoveryNode --> FlakyNode

    FlakyNode fails on calls 1-3, succeeds on call 4.

    Expected with fix:
        Visit 1 — calls 1, 2, 3 fail  → retry budget exhausted → ON_FAILURE → RecoveryNode
        Visit 2 — call 4 succeeds     → result.success = True

    Bug behaviour (without fix):
        Visit 2 — node_retry_counts["flaky"] is still 3, so 3 < 3 is False
        → immediately routes to ON_FAILURE again with 0 retries granted
        → infinite loop or hard termination, never succeeds
    """
    nodes = [
        NodeSpec(
            id="flaky",
            name="Flaky Node",
            node_type="event_loop",
            description="Fails then recovers",
            output_keys=["result"],
            max_retries=3,
        ),
        NodeSpec(
            id="recovery",
            name="Recovery Node",
            node_type="event_loop",
            description="Handles failure, loops back",
            output_keys=["recovered"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="flaky_on_failure",
            source="flaky",
            target="recovery",
            condition=EdgeCondition.ON_FAILURE,
        ),
        EdgeSpec(
            id="recovery_to_flaky",
            source="recovery",
            target="flaky",
            condition=EdgeCondition.ON_SUCCESS,
        ),
    ]

    graph = GraphSpec(
        id="retry_reset_graph",
        goal_id="g1",
        name="Retry Reset Graph",
        entry_node="flaky",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["flaky"],
        max_steps=20,
    )

    flaky = CallCountingFlakyNode(fail_times=3)
    recovery = AlwaysSucceedsNode()

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("flaky", flaky)
    executor.register_node("recovery", recovery)

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    # Visit 1: 3 failures (retried) + ON_FAILURE → recovery
    # Visit 2: 1 success
    assert flaky.attempt_count == 4, (
        f"Expected 4 total calls (3 failed + 1 success), got {flaky.attempt_count}. "
        "node_retry_counts may not be reset on re-visit."
    )
    assert recovery.execute_count == 1
    assert result.success is True

    # Cumulative metrics must reflect ALL retries, not just the last visit's
    assert result.total_retries == 3, (
        f"Expected 3 cumulative retries, got {result.total_retries}. "
        "node_retry_totals should never be reset."
    )
    assert result.retry_details == {"flaky": 3}


# ---------------------------------------------------------------------------
# Test 2 — two failure cycles: each visit independently gets full retry budget
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_budget_independent_per_visit(runtime, goal):
    """
    Graph: FlakyNode (max_retries=3) --ON_FAILURE--> RecoveryNode --> FlakyNode

    FlakyNode fails on calls 1-3 AND 4-6, succeeds on call 7.

    Expected with fix:
        Visit 1 — calls 1, 2, 3 fail → ON_FAILURE → RecoveryNode
        Visit 2 — calls 4, 5, 6 fail → ON_FAILURE → RecoveryNode
        Visit 3 — call 7 succeeds

    Verifies that each successive re-visit receives its own independent
    retry budget, not a permanently depleted one.
    """
    nodes = [
        NodeSpec(
            id="flaky",
            name="Flaky Node",
            node_type="event_loop",
            description="Fails twice across two visits then recovers",
            output_keys=["result"],
            max_retries=3,
        ),
        NodeSpec(
            id="recovery",
            name="Recovery Node",
            node_type="event_loop",
            description="Handles failure, loops back",
            output_keys=["recovered"],
        ),
    ]

    edges = [
        EdgeSpec(
            id="flaky_on_failure",
            source="flaky",
            target="recovery",
            condition=EdgeCondition.ON_FAILURE,
        ),
        EdgeSpec(
            id="recovery_to_flaky",
            source="recovery",
            target="flaky",
            condition=EdgeCondition.ON_SUCCESS,
        ),
    ]

    graph = GraphSpec(
        id="retry_reset_graph_2",
        goal_id="g1",
        name="Retry Reset Graph 2",
        entry_node="flaky",
        nodes=nodes,
        edges=edges,
        terminal_nodes=["flaky"],
        max_steps=30,
    )

    flaky = CallCountingFlakyNode(fail_times=6)
    recovery = AlwaysSucceedsNode()

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("flaky", flaky)
    executor.register_node("recovery", recovery)

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert flaky.attempt_count == 7, (
        f"Expected 7 total calls (6 failed across 2 visits + 1 success), "
        f"got {flaky.attempt_count}."
    )
    assert recovery.execute_count == 2
    assert result.success is True

    # Cumulative metrics must reflect retries from ALL visits (3 + 3 = 6)
    assert result.total_retries == 6, (
        f"Expected 6 cumulative retries, got {result.total_retries}. "
        "node_retry_totals should accumulate across visits."
    )
    assert result.retry_details == {"flaky": 6}


# ---------------------------------------------------------------------------
# Test 3 — linear graph: existing single-visit retry behavior unchanged
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_linear_graph_retry_unaffected(runtime, goal):
    """Verify that single-visit retry semantics are unchanged by the two-counter split.

    A node fails twice then succeeds in a linear graph (no feedback loop).

    Expected behavior:
        The node retries within its budget and succeeds — identical to pre-fix
        behaviour since no re-visit occurs.

    Bug behaviour (without fix):
        Not applicable — this test guards against regressions in the common
        single-visit path that the feedback-loop fix must leave untouched.
    """
    nodes = [
        NodeSpec(
            id="flaky",
            name="Flaky Node",
            node_type="event_loop",
            description="Fails twice then succeeds",
            output_keys=["result"],
            max_retries=3,
        ),
    ]

    graph = GraphSpec(
        id="linear_retry_graph",
        goal_id="g1",
        name="Linear Retry Graph",
        entry_node="flaky",
        nodes=nodes,
        edges=[],
        terminal_nodes=["flaky"],
        max_steps=10,
    )

    flaky = CallCountingFlakyNode(fail_times=2)

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("flaky", flaky)

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success is True
    assert flaky.attempt_count == 3, (
        f"Expected 3 calls (2 failed + 1 success), got {flaky.attempt_count}."
    )

    # Cumulative metrics for single-visit: 2 retries
    assert result.total_retries == 2
    assert result.retry_details == {"flaky": 2}
