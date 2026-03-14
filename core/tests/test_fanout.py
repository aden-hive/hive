"""
Tests for fan-out / fan-in parallel execution in GraphExecutor.

Covers:
- Fan-out triggers with multiple ON_SUCCESS edges
- Concurrent branch execution
- Convergence at fan-in node
- fail_all / continue_others / wait_all strategies
- Branch timeout
- Memory conflict strategies
- Per-branch retry
- Single-edge paths unaffected
"""

from unittest.mock import MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor, ParallelExecutionConfig
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime

# --- Test node implementations ---


class SuccessNode(NodeProtocol):
    """Always succeeds with configurable output."""

    def __init__(self, output: dict | None = None):
        self._output = output or {"result": "ok"}
        self.executed = False

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.executed = True
        return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)


class FailNode(NodeProtocol):
    """Always fails."""

    def __init__(self):
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(success=False, error="branch failed")


class FlakyNode(NodeProtocol):
    """Fails N times, then succeeds."""

    def __init__(self, fail_times: int = 1, output: dict | None = None):
        self.fail_times = fail_times
        self.attempt_count = 0
        self._output = output or {"result": "recovered"}

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        if self.attempt_count <= self.fail_times:
            return NodeResult(success=False, error=f"fail #{self.attempt_count}")
        return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)


class TimingNode(NodeProtocol):
    """Records execution order to a shared list."""

    def __init__(self, label: str, order_tracker: list):
        self.label = label
        self.order_tracker = order_tracker

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.order_tracker.append(self.label)
        return NodeResult(
            success=True, output={f"{self.label}_done": True}, tokens_used=1, latency_ms=1
        )


class ExceptionNode(NodeProtocol):
    """Raises an exception during execution."""

    def __init__(self, message: str = "Branch crashed"):
        self.executed = False
        self.message = message

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.executed = True
        raise RuntimeError(self.message)


# --- Fixtures ---


@pytest.fixture
def runtime():
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
    return Goal(id="g1", name="Test", description="Fanout tests")


def _make_fanout_graph(
    branch_nodes: list[NodeSpec],
    fan_in_node: NodeSpec | None = None,
    source_node: NodeSpec | None = None,
) -> GraphSpec:
    """
    Build a diamond graph:

        source
       / | \\
      b0 b1 b2 ...
       \\ | /
       fan_in
    """
    if source_node is None:
        source_node = NodeSpec(
            id="source",
            name="Source",
            description="entry",
            node_type="event_loop",
            output_keys=["data"],
        )

    nodes = [source_node] + branch_nodes
    terminal_nodes = [b.id for b in branch_nodes]

    edges = [
        EdgeSpec(
            id=f"source_to_{b.id}",
            source="source",
            target=b.id,
            condition=EdgeCondition.ON_SUCCESS,
        )
        for b in branch_nodes
    ]

    if fan_in_node is not None:
        nodes.append(fan_in_node)
        terminal_nodes = [fan_in_node.id]
        for b in branch_nodes:
            edges.append(
                EdgeSpec(
                    id=f"{b.id}_to_{fan_in_node.id}",
                    source=b.id,
                    target=fan_in_node.id,
                    condition=EdgeCondition.ON_SUCCESS,
                )
            )

    return GraphSpec(
        id="fanout_graph",
        goal_id="g1",
        name="Fanout Graph",
        entry_node="source",
        nodes=nodes,
        edges=edges,
        terminal_nodes=terminal_nodes,
    )


# === 1. Fan-out triggers with multiple ON_SUCCESS edges ===


@pytest.mark.asyncio
async def test_fanout_triggers_on_multiple_success_edges(runtime, goal):
    """Fan-out should activate when a node has >1 ON_SUCCESS outgoing edges."""
    b1 = NodeSpec(
        id="b1", name="B1", description="branch 1", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="branch 2", node_type="event_loop", output_keys=["b2_out"]
    )

    graph = _make_fanout_graph([b1, b2])

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=True)
    source_impl = SuccessNode({"data": "x"})
    b1_impl = SuccessNode({"b1_out": "done1"})
    b2_impl = SuccessNode({"b2_out": "done2"})
    executor.register_node("source", source_impl)
    executor.register_node("b1", b1_impl)
    executor.register_node("b2", b2_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert b1_impl.executed
    assert b2_impl.executed


# === 2. All branches execute concurrently ===


@pytest.mark.asyncio
async def test_branches_execute_concurrently(runtime, goal):
    """All fan-out branches should be launched via asyncio.gather (concurrent)."""
    order = []
    b1 = NodeSpec(
        id="b1", name="B1", description="branch 1", node_type="event_loop", output_keys=["b1_done"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="branch 2", node_type="event_loop", output_keys=["b2_done"]
    )

    graph = _make_fanout_graph([b1, b2])

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=True)
    executor.register_node("source", SuccessNode({"data": "x"}))
    executor.register_node("b1", TimingNode("b1", order))
    executor.register_node("b2", TimingNode("b2", order))

    result = await executor.execute(graph, goal, {})

    assert result.success
    # Both executed
    assert "b1" in order
    assert "b2" in order


# === 3. Convergence at fan-in node ===


@pytest.mark.asyncio
async def test_convergence_at_fan_in_node(runtime, goal):
    """After fan-out branches complete, execution should continue at convergence node."""
    b1 = NodeSpec(
        id="b1", name="B1", description="branch 1", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="branch 2", node_type="event_loop", output_keys=["b2_out"]
    )
    merge = NodeSpec(
        id="merge",
        name="Merge",
        description="fan-in",
        node_type="event_loop",
        output_keys=["merged"],
    )

    graph = _make_fanout_graph([b1, b2], fan_in_node=merge)

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=True)
    executor.register_node("source", SuccessNode({"data": "x"}))
    executor.register_node("b1", SuccessNode({"b1_out": "1"}))
    executor.register_node("b2", SuccessNode({"b2_out": "2"}))
    merge_impl = SuccessNode({"merged": "done"})
    executor.register_node("merge", merge_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert merge_impl.executed
    assert "merge" in result.path


# === 4. fail_all strategy ===


@pytest.mark.asyncio
async def test_fail_all_strategy_raises_on_branch_failure(runtime, goal):
    """fail_all should raise RuntimeError if any branch fails."""
    b1 = NodeSpec(
        id="b1", name="B1", description="ok branch", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2",
        name="B2",
        description="bad branch",
        node_type="event_loop",
        output_keys=["b2_out"],
        max_retries=1,
    )

    graph = _make_fanout_graph([b1, b2])

    config = ParallelExecutionConfig(on_branch_failure="fail_all")
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )
    executor.register_node("source", SuccessNode({"data": "x"}))
    executor.register_node("b1", SuccessNode({"b1_out": "ok"}))
    executor.register_node("b2", FailNode())

    result = await executor.execute(graph, goal, {})

    # fail_all raises RuntimeError which gets caught by the outer try/except
    assert not result.success
    assert "failed" in result.error.lower()


# === 5. continue_others strategy ===


@pytest.mark.asyncio
async def test_continue_others_strategy_allows_partial_success(runtime, goal):
    """continue_others should let successful branches complete even if one fails."""
    b1 = NodeSpec(
        id="b1", name="B1", description="ok", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2",
        name="B2",
        description="fail",
        node_type="event_loop",
        output_keys=["b2_out"],
        max_retries=1,
    )

    graph = _make_fanout_graph([b1, b2])

    config = ParallelExecutionConfig(on_branch_failure="continue_others")
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )
    executor.register_node("source", SuccessNode({"data": "x"}))
    b1_impl = SuccessNode({"b1_out": "ok"})
    executor.register_node("b1", b1_impl)
    executor.register_node("b2", FailNode())

    result = await executor.execute(graph, goal, {})

    # Should not fail because continue_others tolerates branch failures
    assert result.success or b1_impl.executed


# === 6. wait_all strategy ===


@pytest.mark.asyncio
async def test_wait_all_strategy_collects_all_results(runtime, goal):
    """wait_all should wait for all branches before proceeding."""
    b1 = NodeSpec(
        id="b1", name="B1", description="ok", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2",
        name="B2",
        description="fail",
        node_type="event_loop",
        output_keys=["b2_out"],
        max_retries=1,
    )

    graph = _make_fanout_graph([b1, b2])

    config = ParallelExecutionConfig(on_branch_failure="wait_all")
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )
    executor.register_node("source", SuccessNode({"data": "x"}))
    b1_impl = SuccessNode({"b1_out": "ok"})
    b2_impl = FailNode()
    executor.register_node("b1", b1_impl)
    executor.register_node("b2", b2_impl)

    await executor.execute(graph, goal, {})

    # Both branches should have executed regardless
    assert b1_impl.executed
    assert b2_impl.attempt_count >= 1


# === 7. Per-branch retry ===


@pytest.mark.asyncio
async def test_per_branch_retry(runtime, goal):
    """Each branch should retry up to its node's max_retries."""
    b1 = NodeSpec(
        id="b1",
        name="B1",
        description="flaky",
        node_type="event_loop",
        output_keys=["b1_out"],
        max_retries=5,
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="solid", node_type="event_loop", output_keys=["b2_out"]
    )

    graph = _make_fanout_graph([b1, b2])

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=True)
    executor.register_node("source", SuccessNode({"data": "x"}))
    flaky = FlakyNode(fail_times=3, output={"b1_out": "recovered"})
    executor.register_node("b1", flaky)
    executor.register_node("b2", SuccessNode({"b2_out": "ok"}))

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert flaky.attempt_count == 4  # 3 fails + 1 success


# === 8. Single-edge path unaffected ===


@pytest.mark.asyncio
async def test_single_edge_no_parallel_overhead(runtime, goal):
    """A single outgoing edge should follow normal sequential path, not fan-out."""
    n1 = NodeSpec(
        id="n1", name="N1", description="entry", node_type="event_loop", output_keys=["out1"]
    )
    n2 = NodeSpec(
        id="n2",
        name="N2",
        description="next",
        node_type="event_loop",
        input_keys=["out1"],
        output_keys=["out2"],
    )

    graph = GraphSpec(
        id="seq_graph",
        goal_id="g1",
        name="Sequential",
        entry_node="n1",
        nodes=[n1, n2],
        edges=[EdgeSpec(id="e1", source="n1", target="n2", condition=EdgeCondition.ON_SUCCESS)],
        terminal_nodes=["n2"],
    )

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=True)
    executor.register_node("n1", SuccessNode({"out1": "a"}))
    n2_impl = SuccessNode({"out2": "b"})
    executor.register_node("n2", n2_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert n2_impl.executed
    assert result.path == ["n1", "n2"]


# === 9. detect_fan_out_nodes static analysis ===


def test_detect_fan_out_nodes():
    """GraphSpec.detect_fan_out_nodes should identify fan-out topology."""
    b1 = NodeSpec(id="b1", name="B1", description="b", node_type="event_loop", output_keys=["x"])
    b2 = NodeSpec(id="b2", name="B2", description="b", node_type="event_loop", output_keys=["y"])
    graph = _make_fanout_graph([b1, b2])

    fan_outs = graph.detect_fan_out_nodes()

    assert "source" in fan_outs
    assert set(fan_outs["source"]) == {"b1", "b2"}


# === 10. detect_fan_in_nodes static analysis ===


def test_detect_fan_in_nodes():
    """GraphSpec.detect_fan_in_nodes should identify convergence topology."""
    b1 = NodeSpec(id="b1", name="B1", description="b", node_type="event_loop", output_keys=["x"])
    b2 = NodeSpec(id="b2", name="B2", description="b", node_type="event_loop", output_keys=["y"])
    merge = NodeSpec(
        id="merge", name="Merge", description="m", node_type="event_loop", output_keys=["z"]
    )
    graph = _make_fanout_graph([b1, b2], fan_in_node=merge)

    fan_ins = graph.detect_fan_in_nodes()

    assert "merge" in fan_ins
    assert set(fan_ins["merge"]) == {"b1", "b2"}


# === 11. Parallel disabled falls back to sequential ===


@pytest.mark.asyncio
async def test_parallel_disabled_uses_sequential(runtime, goal):
    """When enable_parallel_execution=False, multi-edge should follow first match only."""
    b1 = NodeSpec(
        id="b1", name="B1", description="b1", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="b2", node_type="event_loop", output_keys=["b2_out"]
    )

    graph = _make_fanout_graph([b1, b2])

    executor = GraphExecutor(runtime=runtime, enable_parallel_execution=False)
    executor.register_node("source", SuccessNode({"data": "x"}))
    b1_impl = SuccessNode({"b1_out": "ok"})
    b2_impl = SuccessNode({"b2_out": "ok"})
    executor.register_node("b1", b1_impl)
    executor.register_node("b2", b2_impl)

    result = await executor.execute(graph, goal, {})

    assert result.success
    # Only one branch should have executed (sequential follows first edge)
    executed_count = sum([b1_impl.executed, b2_impl.executed])
    assert executed_count == 1


# === 12. All branches execute even when one raises exception ===


@pytest.mark.asyncio
async def test_all_branches_execute_despite_exception(runtime, goal):
    """All branches should execute even when one raises an exception."""
    b1 = NodeSpec(
        id="b1", name="B1", description="ok", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2",
        name="B2",
        description="crashes",
        node_type="event_loop",
        output_keys=["b2_out"],
        max_retries=1,
    )
    b3 = NodeSpec(
        id="b3", name="B3", description="ok", node_type="event_loop", output_keys=["b3_out"]
    )

    graph = _make_fanout_graph([b1, b2, b3])

    config = ParallelExecutionConfig(on_branch_failure="continue_others")
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )
    executor.register_node("source", SuccessNode({"data": "x"}))
    b1_impl = SuccessNode({"b1_out": "ok"})
    b2_impl = ExceptionNode("Branch B2 crashed!")
    b3_impl = SuccessNode({"b3_out": "ok"})
    executor.register_node("b1", b1_impl)
    executor.register_node("b2", b2_impl)
    executor.register_node("b3", b3_impl)

    result = await executor.execute(graph, goal, {})

    assert b1_impl.executed, "Branch B1 should have executed"
    assert b2_impl.executed, "Branch B2 should have executed (despite exception)"
    assert b3_impl.executed, "Branch B3 should have executed"
    assert result.success, "Execution should succeed with continue_others strategy"


# === 13. Memory conflict strategy: error ===


@pytest.mark.asyncio
async def test_memory_conflict_error_strategy(runtime, goal):
    """memory_conflict_strategy='error' should raise when branches write same key."""
    b1 = NodeSpec(
        id="b1", name="B1", description="branch 1", node_type="event_loop", output_keys=["b1_key"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="branch 2", node_type="event_loop", output_keys=["b2_key"]
    )

    graph = _make_fanout_graph([b1, b2])

    config = ParallelExecutionConfig(
        on_branch_failure="continue_others", memory_conflict_strategy="error"
    )
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )
    executor.register_node("source", SuccessNode({"data": "x"}))
    executor.register_node("b1", SuccessNode({"shared": "value1", "b1_key": "b1"}))
    executor.register_node("b2", SuccessNode({"shared": "value2", "b2_key": "b2"}))

    result = await executor.execute(graph, goal, {})

    assert not result.success
    assert "conflict" in result.error.lower() or "shared" in result.error.lower()


# === 14. Memory conflict strategy: first_wins ===


@pytest.mark.asyncio
async def test_memory_conflict_first_wins_strategy(runtime, goal):
    """memory_conflict_strategy='first_wins' should keep first value for conflicting keys."""
    b1 = NodeSpec(
        id="b1", name="B1", description="branch 1", node_type="event_loop", output_keys=["b1_key"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="branch 2", node_type="event_loop", output_keys=["b2_key"]
    )
    merge = NodeSpec(
        id="merge",
        name="Merge",
        description="fan-in",
        node_type="event_loop",
        input_keys=["shared"],
        output_keys=["merged"],
    )

    graph = _make_fanout_graph([b1, b2], fan_in_node=merge)

    config = ParallelExecutionConfig(
        on_branch_failure="continue_others", memory_conflict_strategy="first_wins"
    )
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )

    captured_memory = {}
    execution_order = []

    class OrderTrackingSuccessNode(NodeProtocol):
        def __init__(self, output: dict, label: str):
            self._output = output
            self.label = label

        async def execute(self, ctx: NodeContext) -> NodeResult:
            execution_order.append(self.label)
            return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)

    class MemoryCaptureNode(NodeProtocol):
        def __init__(self, output: dict):
            self._output = output

        async def execute(self, ctx: NodeContext) -> NodeResult:
            captured_memory.update(ctx.memory.read_all())
            execution_order.append("merge")
            return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)

    executor.register_node("source", OrderTrackingSuccessNode({"data": "x"}, "source"))
    executor.register_node("b1", OrderTrackingSuccessNode({"shared": "first_value"}, "b1"))
    executor.register_node("b2", OrderTrackingSuccessNode({"shared": "second_value"}, "b2"))
    executor.register_node("merge", MemoryCaptureNode({"merged": "done"}))

    result = await executor.execute(graph, goal, {})

    assert result.success, f"Execution failed: {result.error}"
    assert "b1" in execution_order, "Branch B1 should have executed"
    assert "b2" in execution_order, "Branch B2 should have executed"
    assert "merge" in execution_order, "Merge node should have executed"
    assert captured_memory.get("shared") == "first_value", (
        f"First value should win, got: {captured_memory.get('shared')}"
    )


# === 15. Memory conflict strategy: last_wins (default) ===


@pytest.mark.asyncio
async def test_memory_conflict_last_wins_strategy(runtime, goal):
    """memory_conflict_strategy='last_wins' should keep last value for conflicting keys."""
    b1 = NodeSpec(
        id="b1", name="B1", description="branch 1", node_type="event_loop", output_keys=["b1_key"]
    )
    b2 = NodeSpec(
        id="b2", name="B2", description="branch 2", node_type="event_loop", output_keys=["b2_key"]
    )
    merge = NodeSpec(
        id="merge",
        name="Merge",
        description="fan-in",
        node_type="event_loop",
        input_keys=["shared"],
        output_keys=["merged"],
    )

    graph = _make_fanout_graph([b1, b2], fan_in_node=merge)

    config = ParallelExecutionConfig(
        on_branch_failure="continue_others", memory_conflict_strategy="last_wins"
    )
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )

    captured_memory = {}
    execution_order = []

    class OrderTrackingSuccessNode(NodeProtocol):
        def __init__(self, output: dict, label: str):
            self._output = output
            self.label = label

        async def execute(self, ctx: NodeContext) -> NodeResult:
            execution_order.append(self.label)
            return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)

    class MemoryCaptureNode(NodeProtocol):
        def __init__(self, output: dict):
            self._output = output

        async def execute(self, ctx: NodeContext) -> NodeResult:
            captured_memory.update(ctx.memory.read_all())
            execution_order.append("merge")
            return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)

    executor.register_node("source", OrderTrackingSuccessNode({"data": "x"}, "source"))
    executor.register_node("b1", OrderTrackingSuccessNode({"shared": "first_value"}, "b1"))
    executor.register_node("b2", OrderTrackingSuccessNode({"shared": "second_value"}, "b2"))
    executor.register_node("merge", MemoryCaptureNode({"merged": "done"}))

    result = await executor.execute(graph, goal, {})

    assert result.success, f"Execution failed: {result.error}"
    assert "b1" in execution_order, "Branch B1 should have executed"
    assert "b2" in execution_order, "Branch B2 should have executed"
    assert "merge" in execution_order, "Merge node should have executed"
    assert captured_memory.get("shared") == "second_value", (
        f"Last value should win, got: {captured_memory.get('shared')}"
    )


# === 16. Exception in one branch doesn't hide other branch results ===


@pytest.mark.asyncio
async def test_exception_doesnt_hide_other_branch_results(runtime, goal):
    """When one branch raises an exception, successful branch outputs should still be available."""
    b1 = NodeSpec(
        id="b1", name="B1", description="ok", node_type="event_loop", output_keys=["b1_out"]
    )
    b2 = NodeSpec(
        id="b2",
        name="B2",
        description="crashes",
        node_type="event_loop",
        output_keys=["b2_out"],
        max_retries=1,
    )
    merge = NodeSpec(
        id="merge",
        name="Merge",
        description="fan-in",
        node_type="event_loop",
        input_keys=["b1_out"],
        output_keys=["merged"],
    )

    graph = _make_fanout_graph([b1, b2], fan_in_node=merge)

    config = ParallelExecutionConfig(on_branch_failure="continue_others")
    executor = GraphExecutor(
        runtime=runtime, enable_parallel_execution=True, parallel_config=config
    )

    captured_memory = {}

    class MemoryCaptureNode(NodeProtocol):
        def __init__(self, output: dict):
            self._output = output

        async def execute(self, ctx: NodeContext) -> NodeResult:
            captured_memory.update(ctx.memory.read_all())
            return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)

    executor.register_node("source", SuccessNode({"data": "x"}))
    executor.register_node("b1", SuccessNode({"b1_out": "successful_output"}))
    executor.register_node("b2", ExceptionNode("Branch B2 crashed!"))
    executor.register_node("merge", MemoryCaptureNode({"merged": "done"}))

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert captured_memory.get("b1_out") == "successful_output", (
        "Successful branch output should be available"
    )
