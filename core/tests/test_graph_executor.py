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
                node_type="event_loop",
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
                node_type="event_loop",
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


# ---- Fake event bus that records calls ----
class FakeEventBus:
    def __init__(self):
        self.events = []

    async def emit_node_loop_started(self, **kwargs):
        self.events.append(("started", kwargs))

    async def emit_node_loop_completed(self, **kwargs):
        self.events.append(("completed", kwargs))

    async def emit_edge_traversed(self, **kwargs):
        self.events.append(("edge_traversed", kwargs))

    async def emit_execution_paused(self, **kwargs):
        self.events.append(("execution_paused", kwargs))

    async def emit_execution_resumed(self, **kwargs):
        self.events.append(("execution_resumed", kwargs))

    async def emit_node_retry(self, **kwargs):
        self.events.append(("node_retry", kwargs))


@pytest.mark.asyncio

# ---- Fake event_loop node (registered, so executor won't emit for it) ----
class FakeEventLoopNode:
    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(success=True, output={"result": "loop-done"}, tokens_used=1, latency_ms=1)


@pytest.mark.asyncio
async def test_executor_skips_events_for_event_loop_nodes():
    """Executor should NOT emit events for event_loop nodes (they emit their own)."""
    runtime = DummyRuntime()
    event_bus = FakeEventBus()

    graph = GraphSpec(
        id="graph-el",
        goal_id="g-el",
        nodes=[
            NodeSpec(
                id="el1",
                name="event-loop-node",
                description="event loop node",
                node_type="event_loop",
                input_keys=[],
                output_keys=["result"],
                max_retries=0,
            ),
        ],
        edges=[],
        entry_node="el1",
    )

    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"el1": FakeEventLoopNode()},
        event_bus=event_bus,
        stream_id="test-stream",
    )

    goal = Goal(id="g-el", name="el-test", description="test event_loop guard")
    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
    # No events should have been emitted — event_loop nodes are skipped
    assert len(event_bus.events) == 0


@pytest.mark.asyncio
async def test_executor_no_events_without_event_bus():
    """Executor should work fine without an event bus (backward compat)."""
    runtime = DummyRuntime()

    graph = GraphSpec(
        id="graph-nobus",
        goal_id="g-nobus",
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
    )

    # No event_bus passed — should not crash
    executor = GraphExecutor(
        runtime=runtime,
        node_registry={"n1": SuccessNode()},
    )

    goal = Goal(id="g-nobus", name="nobus-test", description="no event bus")
    result = await executor.execute(graph=graph, goal=goal)

    assert result.success is True
