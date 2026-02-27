"""
Tests for feedback/callback edges and max_node_visits in GraphExecutor.

Covers:
- NodeSpec.max_node_visits default value
- Visit limit enforcement (skip on exceed)
- Multiple visits allowed when max_node_visits > 1
- Unlimited visits with max_node_visits=0
- Conditional feedback edges (backward traversal)
- Conditional edge NOT firing (forward path taken)
- node_visit_counts populated in ExecutionResult
"""

from unittest.mock import MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec

# ---------------------------------------------------------------------------
# Mock node implementations
# ---------------------------------------------------------------------------


class SuccessNode(NodeProtocol):
    """Always succeeds with configurable output."""

    def __init__(self, output: dict | None = None):
        self._output = output or {"result": "ok"}
        self.execute_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.execute_count += 1
        return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)


class StatefulNode(NodeProtocol):
    """Returns different outputs on successive executions."""

    def __init__(self, outputs: list[dict]):
        self._outputs = outputs
        self.execute_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        output = self._outputs[min(self.execute_count, len(self._outputs) - 1)]
        self.execute_count += 1
        return NodeResult(success=True, output=output, tokens_used=10, latency_ms=5)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime():
    from framework.runtime.core import Runtime

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
    return Goal(id="g1", name="Test", description="Feedback edge tests")


# ---------------------------------------------------------------------------
# 1. NodeSpec default
# ---------------------------------------------------------------------------


def test_max_node_visits_default():
    """NodeSpec.max_node_visits should default to 0 (unbounded, for forever-alive agents)."""
    spec = NodeSpec(
        id="n", name="N", description="test", node_type="event_loop", output_keys=["out"]
    )
    assert spec.max_node_visits == 0


# ---------------------------------------------------------------------------
# 2. Visit limit skips node
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visit_limit_skips_node(runtime, goal):
    """A→B→A cycle with A.max_visits=1: second visit to A should be skipped.

    Neither node is terminal — max_steps is the guard. After A is skipped,
    the skip-redirect loop (A skip→B→A skip→B...) burns through max_steps.
    """
    node_a = NodeSpec(
        id="a",
        name="A",
        description="entry with visit limit",
        node_type="event_loop",
        output_keys=["a_out"],
        max_node_visits=1,
    )
    node_b = NodeSpec(
        id="b",
        name="B",
        description="middle node",
        node_type="event_loop",
        output_keys=["b_out"],
        max_node_visits=0,  # unlimited — let max_steps guard
    )

    graph = GraphSpec(
        id="cycle_graph",
        goal_id="g1",
        name="Cycle Graph",
        entry_node="a",
        nodes=[node_a, node_b],
        edges=[
            EdgeSpec(id="a_to_b", source="a", target="b", condition=EdgeCondition.ON_SUCCESS),
            EdgeSpec(id="b_to_a", source="b", target="a", condition=EdgeCondition.ON_SUCCESS),
        ],
        terminal_nodes=[],  # No terminal — max_steps is the guard
        max_steps=10,
    )

    a_impl = SuccessNode({"a_out": "from_a"})
    b_impl = SuccessNode({"b_out": "from_b"})

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("a", a_impl)
    executor.register_node("b", b_impl)

    result = await executor.execute(graph, goal, {})

    # A should only execute once (all subsequent visits are skipped)
    assert a_impl.execute_count == 1
    # Path should contain "a" exactly once (skipped visits aren't appended)
    assert result.path.count("a") == 1
    # Visit count tracks ALL visits (including skipped ones)
    assert result.node_visit_counts["a"] >= 2
    # B executes multiple times (no visit limit)
    assert b_impl.execute_count >= 2


# ---------------------------------------------------------------------------
# 3. Visit limit allows multiple
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visit_limit_allows_multiple(runtime, goal):
    """A→B→A cycle with A.max_visits=2: A executes twice before skip."""
    node_a = NodeSpec(
        id="a",
        name="A",
        description="entry allows two visits",
        node_type="event_loop",
        output_keys=["a_out"],
        max_node_visits=2,
    )
    node_b = NodeSpec(
        id="b",
        name="B",
        description="middle node",
        node_type="event_loop",
        output_keys=["b_out"],
        max_node_visits=0,  # unlimited
    )

    graph = GraphSpec(
        id="cycle_graph",
        goal_id="g1",
        name="Cycle Graph",
        entry_node="a",
        nodes=[node_a, node_b],
        edges=[
            EdgeSpec(id="a_to_b", source="a", target="b", condition=EdgeCondition.ON_SUCCESS),
            EdgeSpec(id="b_to_a", source="b", target="a", condition=EdgeCondition.ON_SUCCESS),
        ],
        terminal_nodes=[],
        max_steps=10,
    )

    a_impl = SuccessNode({"a_out": "from_a"})
    b_impl = SuccessNode({"b_out": "from_b"})

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("a", a_impl)
    executor.register_node("b", b_impl)

    result = await executor.execute(graph, goal, {})

    # A should execute exactly twice
    assert a_impl.execute_count == 2
    # Path should contain "a" exactly twice
    assert result.path.count("a") == 2
    # Visit count includes skipped visits too
    assert result.node_visit_counts["a"] >= 3


# ---------------------------------------------------------------------------
# 4. Visit limit zero = unlimited
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visit_limit_zero_unlimited(runtime, goal):
    """max_node_visits=0 means unlimited; max_steps is the only guard."""
    node_a = NodeSpec(
        id="a",
        name="A",
        description="unlimited visits",
        node_type="event_loop",
        output_keys=["a_out"],
        max_node_visits=0,
    )
    node_b = NodeSpec(
        id="b",
        name="B",
        description="middle node",
        node_type="event_loop",
        output_keys=["b_out"],
        max_node_visits=0,
    )

    graph = GraphSpec(
        id="cycle_graph",
        goal_id="g1",
        name="Cycle Graph",
        entry_node="a",
        nodes=[node_a, node_b],
        edges=[
            EdgeSpec(id="a_to_b", source="a", target="b", condition=EdgeCondition.ON_SUCCESS),
            EdgeSpec(id="b_to_a", source="b", target="a", condition=EdgeCondition.ON_SUCCESS),
        ],
        terminal_nodes=[],
        max_steps=6,  # A,B,A,B,A,B
    )

    a_impl = SuccessNode({"a_out": "from_a"})
    b_impl = SuccessNode({"b_out": "from_b"})

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("a", a_impl)
    executor.register_node("b", b_impl)

    result = await executor.execute(graph, goal, {})

    # With max_steps=6: A,B,A,B,A,B → each executes 3 times
    assert a_impl.execute_count == 3
    assert b_impl.execute_count == 3
    assert result.steps_executed == 6


# ---------------------------------------------------------------------------
# 5. Conditional feedback edge fires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conditional_feedback_edge(runtime, goal):
    """Writer→Director backward edge fires when needs_revision==True in output.

    Edge conditions evaluate `output` (current node result) and `memory`
    (accumulated shared state). The writer's output hasn't been written to
    memory yet when edges are evaluated, so we use `output.get(...)`.
    """
    director = NodeSpec(
        id="director",
        name="Director",
        description="plans work",
        node_type="event_loop",
        output_keys=["plan"],
        max_node_visits=2,
    )
    writer = NodeSpec(
        id="writer",
        name="Writer",
        description="writes draft",
        node_type="event_loop",
        output_keys=["draft", "needs_revision"],
        max_node_visits=2,
    )
    output_node = NodeSpec(
        id="output",
        name="Output",
        description="final output",
        node_type="event_loop",
        output_keys=["final"],
    )

    graph = GraphSpec(
        id="feedback_graph",
        goal_id="g1",
        name="Feedback Graph",
        entry_node="director",
        nodes=[director, writer, output_node],
        edges=[
            EdgeSpec(
                id="director_to_writer",
                source="director",
                target="writer",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            # Forward path: writer → output (when NOT needs_revision)
            EdgeSpec(
                id="writer_to_output",
                source="writer",
                target="output",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('needs_revision') != True",
                priority=0,
            ),
            # Feedback path: writer → director (when needs_revision)
            EdgeSpec(
                id="writer_feedback",
                source="writer",
                target="director",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('needs_revision') == True",
                priority=-1,
            ),
        ],
        terminal_nodes=["output"],
        max_steps=10,
    )

    director_impl = SuccessNode({"plan": "research AI"})
    # Writer: first call sets needs_revision=True, second sets False
    writer_impl = StatefulNode(
        [
            {"draft": "draft_v1", "needs_revision": True},
            {"draft": "draft_v2", "needs_revision": False},
        ]
    )
    output_impl = SuccessNode({"final": "done"})

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("director", director_impl)
    executor.register_node("writer", writer_impl)
    executor.register_node("output", output_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    # Director executed twice (initial + feedback)
    assert director_impl.execute_count == 2
    # Writer executed twice (first draft rejected, second accepted)
    assert writer_impl.execute_count == 2
    # Output executed once
    assert output_impl.execute_count == 1
    # Full path: director → writer → director → writer → output
    assert result.path == ["director", "writer", "director", "writer", "output"]


# ---------------------------------------------------------------------------
# 6. Conditional feedback edge does NOT fire
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conditional_feedback_false(runtime, goal):
    """Writer→Director backward edge does NOT fire when needs_revision is False."""
    director = NodeSpec(
        id="director",
        name="Director",
        description="plans work",
        node_type="event_loop",
        output_keys=["plan"],
        max_node_visits=2,
    )
    writer = NodeSpec(
        id="writer",
        name="Writer",
        description="writes draft",
        node_type="event_loop",
        output_keys=["draft", "needs_revision"],
    )
    output_node = NodeSpec(
        id="output",
        name="Output",
        description="final output",
        node_type="event_loop",
        output_keys=["final"],
    )

    graph = GraphSpec(
        id="feedback_graph",
        goal_id="g1",
        name="Feedback Graph",
        entry_node="director",
        nodes=[director, writer, output_node],
        edges=[
            EdgeSpec(
                id="director_to_writer",
                source="director",
                target="writer",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="writer_to_output",
                source="writer",
                target="output",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('needs_revision') != True",
                priority=0,
            ),
            EdgeSpec(
                id="writer_feedback",
                source="writer",
                target="director",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('needs_revision') == True",
                priority=-1,
            ),
        ],
        terminal_nodes=["output"],
        max_steps=10,
    )

    director_impl = SuccessNode({"plan": "research AI"})
    # Writer always outputs good draft (no revision needed)
    writer_impl = SuccessNode({"draft": "perfect_draft", "needs_revision": False})
    output_impl = SuccessNode({"final": "done"})

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("director", director_impl)
    executor.register_node("writer", writer_impl)
    executor.register_node("output", output_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    # Director only executed once (no feedback loop)
    assert director_impl.execute_count == 1
    # Writer only executed once
    assert writer_impl.execute_count == 1
    # Output executed
    assert output_impl.execute_count == 1
    # Straight-through path
    assert result.path == ["director", "writer", "output"]


# ---------------------------------------------------------------------------
# 7. Visit counts in ExecutionResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visit_counts_in_result(runtime, goal):
    """ExecutionResult.node_visit_counts is populated with actual visit counts."""
    node_a = NodeSpec(
        id="a",
        name="A",
        description="entry",
        node_type="event_loop",
        output_keys=["a_out"],
    )
    node_b = NodeSpec(
        id="b",
        name="B",
        description="terminal",
        node_type="event_loop",
        input_keys=["a_out"],
        output_keys=["b_out"],
    )

    graph = GraphSpec(
        id="linear_graph",
        goal_id="g1",
        name="Linear Graph",
        entry_node="a",
        nodes=[node_a, node_b],
        edges=[
            EdgeSpec(id="a_to_b", source="a", target="b", condition=EdgeCondition.ON_SUCCESS),
        ],
        terminal_nodes=["b"],
    )

    executor = GraphExecutor(runtime=runtime)
    executor.register_node("a", SuccessNode({"a_out": "x"}))
    executor.register_node("b", SuccessNode({"b_out": "y"}))

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert result.node_visit_counts == {"a": 1, "b": 1}


# ---------------------------------------------------------------------------
# 8. Conditional priority prevents fan-out
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conditional_priority_prevents_fanout(runtime, goal):
    """When multiple CONDITIONAL edges match, only highest-priority fires.

    Simulates: writer produces output where both forward and feedback
    conditions could match.  The higher-priority forward edge should win;
    the executor must NOT treat this as fan-out.
    """
    writer = NodeSpec(
        id="writer",
        name="Writer",
        description="produces output",
        node_type="event_loop",
        output_keys=["draft", "needs_revision"],
    )
    output_node = NodeSpec(
        id="output",
        name="Output",
        description="forward target",
        node_type="event_loop",
        output_keys=["final"],
    )
    director = NodeSpec(
        id="director",
        name="Director",
        description="feedback target",
        node_type="event_loop",
        output_keys=["plan"],
        max_node_visits=2,
    )

    graph = GraphSpec(
        id="priority_graph",
        goal_id="g1",
        name="Priority Graph",
        entry_node="writer",
        nodes=[writer, output_node, director],
        edges=[
            # Forward: higher priority (1)
            EdgeSpec(
                id="writer_to_output",
                source="writer",
                target="output",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('draft') is not None",
                priority=1,
            ),
            # Feedback: lower priority (-1)
            EdgeSpec(
                id="writer_to_director",
                source="writer",
                target="director",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('needs_revision') == True",
                priority=-1,
            ),
        ],
        terminal_nodes=["output"],
        max_steps=10,
    )

    # Writer sets BOTH output keys — both conditions are true
    writer_impl = SuccessNode({"draft": "my draft", "needs_revision": True})
    output_impl = SuccessNode({"final": "done"})
    director_impl = SuccessNode({"plan": "plan"})

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=True)
    executor.register_node("writer", writer_impl)
    executor.register_node("output", output_impl)
    executor.register_node("director", director_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    # Forward edge (priority 1) wins — output executes, director does NOT
    assert output_impl.execute_count == 1
    assert director_impl.execute_count == 0
    assert result.path == ["writer", "output"]
