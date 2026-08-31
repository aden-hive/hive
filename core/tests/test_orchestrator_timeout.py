"""Tests for GraphExecutor / Orchestrator sequential node execution timeouts."""

import asyncio

import pytest

from framework.host.event_bus import EventBus, EventType
from framework.llm.provider import LLMProvider, LLMResponse
from framework.orchestrator import (
    EdgeCondition,
    EdgeSpec,
    Goal,
    GraphSpec,
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    Orchestrator,
    ParallelExecutionConfig,
)
from framework.tracker.decision_tracker import DecisionTracker as Runtime


class DummyLLM(LLMProvider):
    model: str = "dummy"

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="OK", model="dummy", stop_reason="stop")


class FastNode(NodeProtocol):
    """A node that completes quickly."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"status": "fast_done"})


class SlowHangingNode(NodeProtocol):
    """A node that hangs longer than timeout."""

    def __init__(self, delay: float = 10.0):
        self.delay = delay

    async def execute(self, ctx: NodeContext) -> NodeResult:
        await asyncio.sleep(self.delay)
        return NodeResult(success=True, output={"status": "slow_done"})


class FallbackNode(NodeProtocol):
    """A fallback node executed on failure."""

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output={"status": "fallback_done"})


@pytest.fixture
def runtime(tmp_path):
    return Runtime(storage_path=tmp_path / "tracker")


@pytest.fixture
def dummy_llm():
    return DummyLLM()


@pytest.mark.asyncio
async def test_sequential_entry_node_timeout(runtime, dummy_llm):
    """Test that a sequential entry node times out when exceeding node_timeout_seconds."""
    graph = GraphSpec(
        id="test_seq_timeout",
        name="Sequential Timeout Graph",
        goal_id="goal-1",
        entry_node="slow_node",
        terminal_nodes=["slow_node"],
        nodes=[
            NodeSpec(
                id="slow_node",
                name="Slow Hanging Node",
                description="Hangs indefinitely",
                node_type="custom",
            )
        ],
        edges=[],
    )

    node_registry = {
        "slow_node": SlowHangingNode(delay=5.0),
    }

    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        node_timeout_seconds=0.1,  # 100ms timeout
    )

    goal = Goal(id="goal-1", name="Test Sequential Timeout", description="Test sequential timeout")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    assert not result.success
    assert result.execution_quality == "failed"
    assert "slow_node" in result.nodes_with_failures
    assert result.error is not None
    assert "timed out after 0.1s" in result.error


@pytest.mark.asyncio
async def test_sequential_downstream_node_timeout(runtime, dummy_llm):
    """Test that a sequential downstream node times out when exceeding node_timeout_seconds."""
    graph = GraphSpec(
        id="test_seq_downstream_timeout",
        name="Downstream Timeout Graph",
        goal_id="goal-2",
        entry_node="start_node",
        terminal_nodes=["slow_node"],
        nodes=[
            NodeSpec(
                id="start_node",
                name="Start Node",
                description="Fast start node",
                node_type="custom",
            ),
            NodeSpec(
                id="slow_node",
                name="Slow Hanging Node",
                description="Hangs indefinitely",
                node_type="custom",
            ),
        ],
        edges=[
            EdgeSpec(
                id="e1",
                source="start_node",
                target="slow_node",
                condition=EdgeCondition.ON_SUCCESS,
            )
        ],
    )

    node_registry = {
        "start_node": FastNode(),
        "slow_node": SlowHangingNode(delay=5.0),
    }

    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        node_timeout_seconds=0.15,
    )

    goal = Goal(id="goal-2", name="Test Downstream Timeout", description="Test downstream timeout")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    assert not result.success
    assert "slow_node" in result.nodes_with_failures
    assert "timed out after 0.15s" in result.error
    assert "start_node" in result.path


@pytest.mark.asyncio
async def test_sequential_node_success_within_timeout(runtime, dummy_llm):
    """Test that sequential nodes complete successfully when within timeout."""
    graph = GraphSpec(
        id="test_seq_success",
        name="Sequential Success Graph",
        goal_id="goal-3",
        entry_node="start_node",
        terminal_nodes=["start_node"],
        nodes=[
            NodeSpec(
                id="start_node",
                name="Fast Start Node",
                description="Fast node",
                node_type="custom",
            ),
        ],
        edges=[],
    )

    node_registry = {
        "start_node": FastNode(),
    }

    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        node_timeout_seconds=2.0,
    )

    goal = Goal(id="goal-3", name="Test Fast Node", description="Test fast node")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    assert result.success
    assert result.output.get("status") == "fast_done"


@pytest.mark.asyncio
async def test_node_spec_custom_timeout_override(runtime, dummy_llm):
    """Test that NodeSpec.timeout_seconds overrides the orchestrator's default node_timeout_seconds."""
    graph = GraphSpec(
        id="test_node_override",
        name="Node Override Graph",
        goal_id="goal-4",
        entry_node="slow_node",
        terminal_nodes=["slow_node"],
        nodes=[
            NodeSpec(
                id="slow_node",
                name="Custom Timeout Node",
                description="Node with custom 0.1s timeout override",
                node_type="custom",
                timeout_seconds=0.1,  # Custom override
            )
        ],
        edges=[],
    )

    node_registry = {
        "slow_node": SlowHangingNode(delay=5.0),
    }

    # Global timeout is 300s, but node has 0.1s override
    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        node_timeout_seconds=300.0,
    )

    goal = Goal(id="goal-4", name="Test Node Override", description="Test node timeout override")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    assert not result.success
    assert "timed out after 0.1s" in result.error


@pytest.mark.asyncio
async def test_on_failure_edge_after_timeout(runtime, dummy_llm):
    """Test that ON_FAILURE edges are followed when a sequential node times out."""
    graph = GraphSpec(
        id="test_on_failure_timeout",
        name="ON_FAILURE Timeout Graph",
        goal_id="goal-5",
        entry_node="slow_node",
        terminal_nodes=["fallback_node"],
        nodes=[
            NodeSpec(
                id="slow_node",
                name="Slow Node",
                description="Hangs and times out",
                node_type="custom",
                timeout_seconds=0.1,
            ),
            NodeSpec(
                id="fallback_node",
                name="Fallback Node",
                description="Recovers after slow node failure",
                node_type="custom",
            ),
        ],
        edges=[
            EdgeSpec(
                id="e_fallback",
                source="slow_node",
                target="fallback_node",
                condition=EdgeCondition.ON_FAILURE,
            )
        ],
    )

    node_registry = {
        "slow_node": SlowHangingNode(delay=5.0),
        "fallback_node": FallbackNode(),
    }

    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        node_timeout_seconds=10.0,
    )

    goal = Goal(id="goal-5", name="Test ON_FAILURE", description="Test ON_FAILURE recovery")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    # The fallback node succeeded, and terminal node fallback_node completed
    assert result.success
    assert result.output.get("status") == "fallback_done"
    assert "fallback_node" in result.path


@pytest.mark.asyncio
async def test_fanout_branch_timeout_preservation(runtime, dummy_llm):
    """Test that fan-out branches continue to use branch_timeout_seconds."""
    graph = GraphSpec(
        id="test_fanout_timeout",
        name="Fanout Timeout Graph",
        goal_id="goal-6",
        entry_node="split_node",
        terminal_nodes=["branch1", "branch2"],
        nodes=[
            NodeSpec(
                id="split_node",
                name="Split Node",
                description="Entry node for fanout",
                node_type="custom",
            ),
            NodeSpec(
                id="branch1",
                name="Branch 1 (Fast)",
                description="Fast branch",
                node_type="custom",
            ),
            NodeSpec(
                id="branch2",
                name="Branch 2 (Slow)",
                description="Slow branch that times out",
                node_type="custom",
            ),
        ],
        edges=[
            EdgeSpec(
                id="e_b1",
                source="split_node",
                target="branch1",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="e_b2",
                source="split_node",
                target="branch2",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
    )

    node_registry = {
        "split_node": FastNode(),
        "branch1": FastNode(),
        "branch2": SlowHangingNode(delay=5.0),
    }

    parallel_config = ParallelExecutionConfig(
        branch_timeout_seconds=0.1,
        node_timeout_seconds=10.0,
    )

    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        parallel_config=parallel_config,
    )

    goal = Goal(id="goal-6", name="Test Fanout Timeout", description="Test fanout timeout")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    assert not result.success
    assert "branch2" in result.nodes_with_failures
    assert "Branch failed (timed out after 0.1s)" in result.error


@pytest.mark.asyncio
async def test_event_driven_mode_timeout(runtime, dummy_llm):
    """Test timeout handling in event-driven mode with EventBus."""
    event_bus = EventBus()
    stream_id = "test-stream-timeout"
    execution_id = "test-exec-timeout"

    graph = GraphSpec(
        id="test_event_timeout",
        name="Event-Driven Timeout Graph",
        goal_id="goal-7",
        entry_node="slow_node",
        terminal_nodes=["slow_node"],
        nodes=[
            NodeSpec(
                id="slow_node",
                name="Slow Hanging Node",
                description="Hangs indefinitely",
                node_type="custom",
                timeout_seconds=0.1,
            )
        ],
        edges=[],
    )

    node_registry = {
        "slow_node": SlowHangingNode(delay=5.0),
    }

    failed_events = []

    async def on_failed(event):
        failed_events.append(event)

    event_bus.subscribe(
        event_types=[EventType.WORKER_FAILED],
        handler=on_failed,
        filter_stream=stream_id,
        filter_execution=execution_id,
    )

    orchestrator = Orchestrator(
        runtime=runtime,
        llm=dummy_llm,
        node_registry=node_registry,
        event_bus=event_bus,
        stream_id=stream_id,
        execution_id=execution_id,
        node_timeout_seconds=10.0,
    )

    goal = Goal(id="goal-7", name="Test Event Timeout", description="Test event timeout")
    result = await orchestrator.execute(graph=graph, goal=goal, validate_graph=False)

    assert not result.success
    assert "slow_node" in result.nodes_with_failures
    assert len(failed_events) >= 1
    assert failed_events[0].data["worker_id"] == "slow_node"
