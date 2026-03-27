"""
Tests for GOAL_ACHIEVED event emission.

Covers:
- emit_goal_achieved() publishes correct AgentEvent
- GraphExecutor emits GOAL_ACHIEVED on terminal-node success
- Event data contains goal_name, goal_description, and output
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.runtime.core import Runtime
from framework.runtime.event_bus import AgentEvent, EventBus, EventType

# --- Test node implementations ---


class SuccessNode(NodeProtocol):
    """Always succeeds with configurable output."""

    def __init__(self, output: dict | None = None):
        self._output = output or {"result": "ok"}

    async def execute(self, ctx: NodeContext) -> NodeResult:
        return NodeResult(success=True, output=self._output, tokens_used=10, latency_ms=5)


# --- EventBus unit tests ---


@pytest.mark.asyncio
async def test_emit_goal_achieved_publishes_correct_event():
    """emit_goal_achieved() publishes an AgentEvent with correct type and data."""
    bus = EventBus()
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    bus.subscribe(event_types=[EventType.GOAL_ACHIEVED], handler=handler)

    await bus.emit_goal_achieved(
        stream_id="s1",
        execution_id="e1",
        goal_name="Build feature",
        goal_description="Implement the widget",
        output={"widget": "done"},
    )

    assert len(received) == 1
    event = received[0]
    assert event.type == EventType.GOAL_ACHIEVED
    assert event.stream_id == "s1"
    assert event.execution_id == "e1"
    assert event.data["goal_name"] == "Build feature"
    assert event.data["goal_description"] == "Implement the widget"
    assert event.data["output"] == {"widget": "done"}


@pytest.mark.asyncio
async def test_emit_goal_achieved_defaults_output_to_empty_dict():
    """When output is None, data['output'] should be an empty dict."""
    bus = EventBus()
    received: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        received.append(event)

    bus.subscribe(event_types=[EventType.GOAL_ACHIEVED], handler=handler)

    await bus.emit_goal_achieved(
        stream_id="s1",
        execution_id="e1",
        goal_name="Test",
        goal_description="Desc",
    )

    assert received[0].data["output"] == {}


# --- Executor integration tests ---


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
    return Goal(id="g1", name="Test Goal", description="A test goal for events")


@pytest.fixture
def event_bus():
    bus = EventBus()
    bus.emit_goal_achieved = AsyncMock(wraps=bus.emit_goal_achieved)
    return bus


def _make_linear_graph(node: NodeSpec) -> GraphSpec:
    """Build a simple two-node linear graph: source → terminal."""
    source = NodeSpec(
        id="source",
        name="Source",
        description="entry",
        node_type="event_loop",
        output_keys=["data"],
    )
    return GraphSpec(
        id="test_graph",
        goal_id="g1",
        name="Test Graph",
        entry_node="source",
        nodes=[source, node],
        edges=[
            EdgeSpec(
                id="source_to_terminal",
                source="source",
                target=node.id,
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        terminal_nodes=[node.id],
    )


@pytest.mark.asyncio
async def test_executor_emits_goal_achieved_on_success(runtime, goal, event_bus):
    """GraphExecutor emits GOAL_ACHIEVED when execution completes successfully."""
    terminal = SuccessNode(output={"answer": 42})
    terminal_spec = NodeSpec(
        id="terminal",
        name="Terminal",
        description="terminal node",
        node_type="event_loop",
        output_keys=["answer"],
    )
    graph = _make_linear_graph(terminal_spec)

    source_node = SuccessNode(output={"data": "input"})
    node_registry = {
        "source": source_node,
        "terminal": terminal,
    }

    executor = GraphExecutor(
        runtime=runtime,
        llm=MagicMock(),
        tools=[],
        tool_executor=None,
        node_registry=node_registry,
        event_bus=event_bus,
        stream_id="stream_1",
        execution_id="exec_1",
    )

    result = await executor.execute(graph, goal)

    assert result.success
    event_bus.emit_goal_achieved.assert_awaited_once()
    call_kwargs = event_bus.emit_goal_achieved.call_args.kwargs
    assert call_kwargs["stream_id"] == "stream_1"
    assert call_kwargs["execution_id"] == "exec_1"
    assert call_kwargs["goal_name"] == "Test Goal"
    assert call_kwargs["goal_description"] == "A test goal for events"


@pytest.mark.asyncio
async def test_executor_no_goal_achieved_without_event_bus(runtime, goal):
    """GraphExecutor does not crash when event_bus is None."""
    terminal = SuccessNode()
    terminal_spec = NodeSpec(
        id="terminal",
        name="Terminal",
        description="terminal node",
        node_type="event_loop",
        output_keys=["result"],
    )
    graph = _make_linear_graph(terminal_spec)

    source_node = SuccessNode(output={"data": "input"})
    node_registry = {
        "source": source_node,
        "terminal": terminal,
    }

    executor = GraphExecutor(
        runtime=runtime,
        llm=MagicMock(),
        tools=[],
        tool_executor=None,
        node_registry=node_registry,
        event_bus=None,
        stream_id="stream_1",
        execution_id="exec_1",
    )

    result = await executor.execute(graph, goal)
    assert result.success
