"""
Test node execution hooks (pre/post) for GraphExecutor.

This test verifies Issue #877: Add Node Execution Hooks (Pre/Post) to GraphExecutor.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.executor import (
    GraphExecutor,
    NodeExecutionEvent,
    NodeExecutionResult,
)
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime


class SimpleTestNode(NodeProtocol):
    """A simple test node that returns a fixed result."""

    def __init__(self, output: dict | None = None):
        self.output = output or {"result": "success"}
        self.execute_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.execute_count += 1
        return NodeResult(success=True, output=self.output)


@pytest.fixture
def runtime():
    """Create a mock Runtime for testing."""
    runtime = MagicMock(spec=Runtime)
    runtime.start_run = MagicMock(return_value="test_run_id")
    runtime.decide = MagicMock(return_value="test_decision_id")
    runtime.record_outcome = MagicMock()
    runtime.end_run = MagicMock()
    runtime.report_problem = MagicMock()
    runtime.set_node = MagicMock()
    return runtime


@pytest.mark.asyncio
async def test_pre_execute_hook_is_called(runtime):
    """Test that pre_execute_hook is called before node execution."""

    hook_calls = []

    async def pre_hook(event: NodeExecutionEvent):
        hook_calls.append(("pre", event))

    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node",
        node_type="event_loop",
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="test_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["test_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test pre hook")

    executor = GraphExecutor(runtime=runtime, pre_execute_hook=pre_hook)
    test_node = SimpleTestNode()
    executor.register_node("test_node", test_node)

    result = await executor.execute(graph, goal, {"input": "test"})

    assert result.success
    assert len(hook_calls) == 1
    event = hook_calls[0][1]
    assert isinstance(event, NodeExecutionEvent)
    assert event.node_id == "test_node"
    assert event.node_name == "Test Node"
    assert event.node_type == "event_loop"
    assert event.attempt == 1
    assert event.input_data == {"input": "test"}


@pytest.mark.asyncio
async def test_post_execute_hook_is_called(runtime):
    """Test that post_execute_hook is called after node execution."""

    hook_calls = []

    async def post_hook(event: NodeExecutionResult):
        hook_calls.append(("post", event))

    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node",
        node_type="event_loop",
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="test_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["test_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test post hook")

    executor = GraphExecutor(runtime=runtime, post_execute_hook=post_hook)
    test_node = SimpleTestNode(output={"result": "success_value"})
    executor.register_node("test_node", test_node)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert len(hook_calls) == 1
    event = hook_calls[0][1]
    assert isinstance(event, NodeExecutionResult)
    assert event.node_id == "test_node"
    assert event.node_name == "Test Node"
    assert event.success is True
    assert event.output == {"result": "success_value"}


@pytest.mark.asyncio
async def test_both_hooks_are_called_in_order(runtime):
    """Test that pre and post hooks are called in correct order."""

    hook_order = []

    async def pre_hook(event: NodeExecutionEvent):
        hook_order.append("pre")

    async def post_hook(event: NodeExecutionResult):
        hook_order.append("post")

    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node",
        node_type="event_loop",
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="test_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["test_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test both hooks")

    executor = GraphExecutor(
        runtime=runtime,
        pre_execute_hook=pre_hook,
        post_execute_hook=post_hook,
    )
    test_node = SimpleTestNode()
    executor.register_node("test_node", test_node)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert hook_order == ["pre", "post"]


@pytest.mark.asyncio
async def test_hooks_receive_correct_attempt_number_on_retry(
    runtime, monkeypatch: pytest.MonkeyPatch
):
    """Test that hooks receive correct attempt numbers during retries."""

    monkeypatch.setattr("asyncio.sleep", AsyncMock())

    hook_attempts = []

    async def pre_hook(event: NodeExecutionEvent):
        hook_attempts.append(("pre", event.attempt))

    async def post_hook(event: NodeExecutionResult):
        hook_attempts.append(("post", event.attempt, event.success))

    class FlakyNode(NodeProtocol):
        def __init__(self, fail_times: int = 2):
            self.fail_times = fail_times
            self.attempt_count = 0

        async def execute(self, ctx: NodeContext) -> NodeResult:
            self.attempt_count += 1
            if self.attempt_count <= self.fail_times:
                return NodeResult(success=False, error=f"Failed attempt {self.attempt_count}")
            return NodeResult(success=True, output={"result": "ok"})

    node_spec = NodeSpec(
        id="flaky_node",
        name="Flaky Node",
        description="A node that fails before succeeding",
        max_retries=5,
        node_type="event_loop",
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="flaky_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["flaky_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test retry hooks")

    executor = GraphExecutor(
        runtime=runtime,
        pre_execute_hook=pre_hook,
        post_execute_hook=post_hook,
    )
    flaky_node = FlakyNode(fail_times=2)
    executor.register_node("flaky_node", flaky_node)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert hook_attempts == [
        ("pre", 1),
        ("post", 1, False),
        ("pre", 2),
        ("post", 2, False),
        ("pre", 3),
        ("post", 3, True),
    ]


@pytest.mark.asyncio
async def test_hooks_not_called_when_none(runtime):
    """Test that no hooks are called when None is passed."""

    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node",
        node_type="event_loop",
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="test_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["test_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test no hooks")

    executor = GraphExecutor(
        runtime=runtime,
        pre_execute_hook=None,
        post_execute_hook=None,
    )
    test_node = SimpleTestNode()
    executor.register_node("test_node", test_node)

    result = await executor.execute(graph, goal, {})

    assert result.success


@pytest.mark.asyncio
async def test_pre_hook_receives_memory_snapshot(runtime):
    """Test that pre_hook receives a snapshot of memory."""

    memory_snapshots = []

    async def pre_hook(event: NodeExecutionEvent):
        memory_snapshots.append(event.memory_snapshot)

    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node",
        node_type="event_loop",
        input_keys=["input_key"],
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="test_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["test_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test memory snapshot")

    executor = GraphExecutor(runtime=runtime, pre_execute_hook=pre_hook)
    test_node = SimpleTestNode()
    executor.register_node("test_node", test_node)

    result = await executor.execute(graph, goal, {"input_key": "input_value"})

    assert result.success
    assert len(memory_snapshots) == 1
    assert "input_key" in memory_snapshots[0]
    assert memory_snapshots[0]["input_key"] == "input_value"


@pytest.mark.asyncio
async def test_post_hook_receives_tokens_and_latency(runtime):
    """Test that post_hook receives tokens_used and latency_ms."""

    results = []

    async def post_hook(event: NodeExecutionResult):
        results.append(event)

    node_spec = NodeSpec(
        id="test_node",
        name="Test Node",
        description="A test node",
        node_type="event_loop",
        output_keys=["result"],
    )

    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="test_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["test_node"],
    )

    goal = Goal(id="test_goal", name="Test Goal", description="Test metrics")

    executor = GraphExecutor(runtime=runtime, post_execute_hook=post_hook)
    test_node = SimpleTestNode()
    executor.register_node("test_node", test_node)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert len(results) == 1
    assert results[0].tokens_used >= 0
    assert results[0].latency_ms >= 0
