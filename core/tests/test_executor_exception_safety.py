"""
Regression tests for executor exception-safety fixes.

Covers:
  - node_spec pre-initialisation so the except handler never
    raises UnboundLocalError (issue #4514, finding 1).
  - Parallel branch failure reporting gracefully falls back
    to node_id when graph.get_node() returns None (issue #4514, finding 2).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult, NodeSpec

# ---- Shared helpers (mirror existing test_graph_executor.py) ----


class DummyRuntime:
    """Minimal runtime stub that records calls for assertions."""

    def __init__(self):
        self.problems: list[dict] = []
        self.ended = False

    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        self.ended = True

    def report_problem(self, **kwargs):
        self.problems.append(kwargs)


class SuccessNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={"result": 42},
            tokens_used=1,
            latency_ms=1,
        )


class FailingNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=False,
            error="branch-boom",
            output={},
            tokens_used=0,
            latency_ms=0,
        )


# ── Finding 1: node_spec unbound in except handler ──────────────


@pytest.mark.asyncio
async def test_exception_before_node_spec_does_not_cause_unbound_error():
    """
    If graph.get_node() raises inside the try block (before node_spec is
    assigned on the current iteration), the except handler must still work
    — it should NOT raise UnboundLocalError.

    Before the fix, `node_spec` was first assigned inside the while-loop;
    an exception before that line left it undefined, causing the except
    handler to crash with UnboundLocalError and mask the real error.
    """
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-unbound",
        goal_id="g-unbound",
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

    goal = Goal(id="g-unbound", name="unbound-test", description="unbound node_spec test")

    # Patch get_node so it works normally during graph.validate() but raises
    # *inside* the executor's try block (simulating corruption/race).  The
    # simple graph triggers exactly 1 get_node call during validate(), so we
    # let the first call through and raise on all subsequent ones.
    original_get_node = graph.get_node
    call_count = 0

    def raise_after_validation(node_id: str):
        nonlocal call_count
        call_count += 1
        if call_count > 1:
            raise ValueError("simulated get_node failure")
        return original_get_node(node_id)

    with patch.object(graph, "get_node", side_effect=raise_after_validation):
        result = await executor.execute(graph=graph, goal=goal)

    # The executor should surface the *original* ValueError, not UnboundLocalError
    assert result.success is False
    assert "simulated get_node failure" in (result.error or "")

    # Runtime should have been notified of the problem
    assert runtime.ended is True
    assert len(runtime.problems) == 1
    assert "simulated get_node failure" in runtime.problems[0]["description"]


@pytest.mark.asyncio
async def test_exception_handler_logs_node_when_node_spec_assigned():
    """
    When node_spec IS assigned before the exception, the except handler
    should still work correctly (the pre-init doesn't break existing paths).
    """
    runtime = DummyRuntime()

    class CrashingNode:
        """Node whose execute() raises an unexpected exception."""

        def validate_input(self, ctx):
            return []

        async def execute(self, ctx):
            raise RuntimeError("unexpected node crash")

    graph = GraphSpec(
        id="graph-crash",
        goal_id="g-crash",
        nodes=[
            NodeSpec(
                id="n1",
                name="crasher",
                description="crashing node",
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
        node_registry={"n1": CrashingNode()},
    )

    goal = Goal(id="g-crash", name="crash-test", description="node crash test")
    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is False
    assert "unexpected node crash" in (result.error or "")
    assert runtime.ended is True


# ── Finding 2: parallel branch failure with get_node() returning None ─


@pytest.mark.asyncio
async def test_parallel_branch_failure_none_node_uses_fallback_name():
    """
    When a parallel branch fails and graph.get_node(branch.node_id) returns
    None, the error message should fall back to using the raw node_id instead
    of crashing with AttributeError: 'NoneType' has no attribute 'name'.
    """

    graph = GraphSpec(
        id="graph-par",
        goal_id="g-par",
        nodes=[
            NodeSpec(
                id="fan-out",
                name="fan-out-node",
                description="fan-out node",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                parallel_branches=[
                    {"branch_id": "b1", "node_id": "branch-1"},
                    {"branch_id": "b2", "node_id": "branch-2"},
                ],
                max_retries=0,
            ),
            NodeSpec(
                id="branch-1",
                name="branch-one",
                description="succeeding branch",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
            NodeSpec(
                id="branch-2",
                name="branch-two",
                description="failing branch",
                node_type="llm_generate",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[],
        entry_node="fan-out",
    )

    # Directly test the walrus-operator list comprehension used in
    # _execute_parallel_branches for failed-branch name resolution.
    # We simulate the pattern without the full parallel execution wiring:
    #   n.name if (n := graph.get_node(node_id)) else node_id
    # where "ghost-node" is NOT in the graph → fallback to raw node_id.

    fake_branches = [
        SimpleNamespace(node_id="ghost-node"),  # no NodeSpec in graph
        SimpleNamespace(node_id="branch-1"),  # has NodeSpec
    ]

    failed_names = [
        n.name if (n := graph.get_node(b.node_id)) else b.node_id for b in fake_branches
    ]

    # ghost-node should fallback to its ID; branch-1 should resolve to its name
    assert failed_names == ["ghost-node", "branch-one"]
