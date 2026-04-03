"""Component tests: Worker Communication — event flow, completion, failure.

Exercises the full worker execution lifecycle with EventBus subscriptions
to verify that the exact events are published in the correct order, with
correct data, simulating the queen-worker communication contract.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec
from framework.runtime.event_bus import AgentEvent, EventBus, EventType

from .conftest import make_executor

SET_OUTPUT = (
    "You MUST call the set_output tool. "
    "Do not just write text — call set_output with the correct key and value."
)


@dataclass
class EventCapture:
    """Captures events from the bus for assertion."""

    events: list[AgentEvent] = field(default_factory=list)

    def of_type(self, *event_types: EventType) -> list[AgentEvent]:
        return [e for e in self.events if e.type in event_types]

    def tool_calls(self) -> list[dict]:
        """Extract tool call data from TOOL_CALL_COMPLETED events."""
        return [e.data for e in self.of_type(EventType.TOOL_CALL_COMPLETED)]

    def tool_names_called(self) -> set[str]:
        """Unique tool names that were called."""
        return {e.data.get("tool_name", "") for e in self.of_type(EventType.TOOL_CALL_COMPLETED)}

    def verdicts(self) -> list[str]:
        """Judge verdicts in order."""
        return [e.data.get("action", "") for e in self.of_type(EventType.JUDGE_VERDICT)]

    def output_keys_set(self) -> set[str]:
        """Output keys that were set."""
        return {e.data.get("key", "") for e in self.of_type(EventType.OUTPUT_KEY_SET)}


def _make_event_bus_and_capture() -> tuple[EventBus, EventCapture]:
    """Create an EventBus with a capture handler subscribed to all events."""
    bus = EventBus()
    capture = EventCapture()

    async def _capture_all(event: AgentEvent) -> None:
        capture.events.append(event)

    # Subscribe to the key event types we want to verify
    bus.subscribe(
        event_types=[
            EventType.NODE_LOOP_STARTED,
            EventType.NODE_LOOP_ITERATION,
            EventType.NODE_LOOP_COMPLETED,
            EventType.LLM_TURN_COMPLETE,
            EventType.TOOL_CALL_STARTED,
            EventType.TOOL_CALL_COMPLETED,
            EventType.JUDGE_VERDICT,
            EventType.OUTPUT_KEY_SET,
            EventType.EXECUTION_COMPLETED,
            EventType.EXECUTION_FAILED,
            EventType.ESCALATION_REQUESTED,
            EventType.NODE_STALLED,
        ],
        handler=_capture_all,
    )
    return bus, capture


# ---------------------------------------------------------------------------
# Tests: Worker Completion Events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_emits_loop_lifecycle_events(runtime, goal, llm_provider, tmp_path):
    """Worker execution must emit LOOP_STARTED → iterations → LOOP_COMPLETED."""
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="lifecycle-events",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Simple output",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='done'. " + SET_OUTPUT,
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime, llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success

    # Verify lifecycle event ordering
    loop_started = capture.of_type(EventType.NODE_LOOP_STARTED)
    loop_completed = capture.of_type(EventType.NODE_LOOP_COMPLETED)
    iterations = capture.of_type(EventType.NODE_LOOP_ITERATION)

    assert len(loop_started) >= 1, "Missing NODE_LOOP_STARTED"
    assert len(loop_completed) >= 1, "Missing NODE_LOOP_COMPLETED"
    assert len(iterations) >= 1, "Missing NODE_LOOP_ITERATION"

    # STARTED must come before COMPLETED
    start_idx = capture.events.index(loop_started[0])
    end_idx = capture.events.index(loop_completed[0])
    assert start_idx < end_idx, "LOOP_STARTED must precede LOOP_COMPLETED"


@pytest.mark.asyncio
async def test_worker_emits_llm_turn_with_token_counts(
    runtime, goal, llm_provider, tmp_path
):
    """Each LLM turn must emit LLM_TURN_COMPLETE with token counts."""
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="token-count",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Simple output",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='ok'. " + SET_OUTPUT,
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime, llm_provider,
        loop_config={"max_iterations": 3},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success

    llm_turns = capture.of_type(EventType.LLM_TURN_COMPLETE)
    assert len(llm_turns) >= 1, "No LLM_TURN_COMPLETE events"

    for turn in llm_turns:
        assert turn.data.get("input_tokens", 0) > 0, "input_tokens should be > 0"
        assert turn.data.get("output_tokens", 0) > 0, "output_tokens should be > 0"
        assert turn.data.get("model"), "model should be populated"


@pytest.mark.asyncio
async def test_worker_tool_calls_emit_events(
    runtime, goal, llm_provider, tool_registry, tmp_path
):
    """Tool calls must emit TOOL_CALL_STARTED and TOOL_CALL_COMPLETED events."""
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="tool-events",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Use get_current_time then set output",
                node_type="event_loop",
                output_keys=["result"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Then call set_output with key='result' and the day_of_week. "
                    + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime, llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.output.get("result") is not None

    # Verify tool events
    tool_started = capture.of_type(EventType.TOOL_CALL_STARTED)
    tool_completed = capture.of_type(EventType.TOOL_CALL_COMPLETED)
    assert len(tool_started) >= 1, "No TOOL_CALL_STARTED events"
    assert len(tool_completed) >= 1, "No TOOL_CALL_COMPLETED events"

    # get_current_time must be among the tools called
    assert "get_current_time" in capture.tool_names_called()

    # set_output must also appear (synthetic tool)
    assert "set_output" in capture.tool_names_called()

    # Tool calls should not have errors
    for tc in capture.tool_calls():
        if tc.get("tool_name") in ("get_current_time", "set_output"):
            assert not tc.get("is_error"), f"Tool {tc.get('tool_name')} errored"


@pytest.mark.asyncio
async def test_worker_output_key_set_event(runtime, goal, llm_provider, tmp_path):
    """set_output must emit OUTPUT_KEY_SET event with the key name."""
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="output-key-event",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Set two output keys",
                node_type="event_loop",
                output_keys=["name", "status"],
                system_prompt=(
                    "Call set_output twice: "
                    "first key='name' value='test', "
                    "then key='status' value='ok'. " + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["name", "status"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime, llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.output.get("name") is not None
    assert result.output.get("status") is not None

    # Verify OUTPUT_KEY_SET events for both keys
    keys_set = capture.output_keys_set()
    assert "name" in keys_set, f"Missing OUTPUT_KEY_SET for 'name', got: {keys_set}"
    assert "status" in keys_set, f"Missing OUTPUT_KEY_SET for 'status', got: {keys_set}"


# ---------------------------------------------------------------------------
# Tests: Multi-Node Worker Communication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_pipeline_data_integrity(
    runtime, goal, llm_provider, tool_registry, tmp_path
):
    """Data produced by node 1 must arrive at node 2 via input_mapping, verified end-to-end."""
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="data-integrity",
        goal_id="dummy",
        entry_node="producer",
        entry_points={"start": "producer"},
        terminal_nodes=["consumer"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="producer",
                name="Producer",
                description="Produces a timestamped value using a real tool",
                node_type="event_loop",
                output_keys=["payload"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Extract the 'date' field from the result. "
                    "Call set_output with key='payload' and the date string as value. "
                    + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="consumer",
                name="Consumer",
                description="Verifies received data contains a date",
                node_type="event_loop",
                input_keys=["data"],
                output_keys=["result"],
                system_prompt=(
                    "Read the 'data' input. It should contain a date string. "
                    "Call set_output with key='result' and value='VERIFIED|' followed by "
                    "the first 10 characters of the data input. " + SET_OUTPUT
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="produce-to-consume",
                source="producer",
                target="consumer",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"data": "payload"},
            ),
        ],
        memory_keys=["payload", "data", "result"],
    )
    executor = make_executor(
        runtime, llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    # Strict outcome verification
    assert result.success
    assert result.is_clean_success, f"quality={result.execution_quality}"
    assert result.path == ["producer", "consumer"]
    assert result.steps_executed == 2

    # Output must be present and correctly structured
    output = result.output.get("result")
    assert output is not None, "Consumer did not set 'result'"
    assert output.startswith("VERIFIED|"), f"Expected VERIFIED|..., got: {output}"

    # Token counts should be reasonable (not zero, not astronomical)
    assert result.total_tokens > 0
    assert result.total_tokens < 100_000, f"Unexpectedly high tokens: {result.total_tokens}"

    # Both nodes should have set their output keys
    keys_set = capture.output_keys_set()
    assert "payload" in keys_set, "Producer didn't set 'payload'"
    assert "result" in keys_set, "Consumer didn't set 'result'"

    # get_current_time must have been called (in producer)
    assert "get_current_time" in capture.tool_names_called()


@pytest.mark.asyncio
async def test_worker_multi_node_output_propagation(
    runtime, goal, llm_provider, tmp_path
):
    """Data from node A's output must arrive at node B and be reflected in final output."""
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="output-propagation",
        goal_id="dummy",
        entry_node="generator",
        entry_points={"start": "generator"},
        terminal_nodes=["formatter"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="generator",
                name="Generator",
                description="Generates a code word",
                node_type="event_loop",
                output_keys=["code"],
                system_prompt=(
                    "Call set_output with key='code' and value='ALPHA_BRAVO_42'. "
                    "Do not write any text." + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="formatter",
                name="Formatter",
                description="Wraps received code in brackets",
                node_type="event_loop",
                input_keys=["raw_code"],
                output_keys=["result"],
                system_prompt=(
                    "Read the 'raw_code' input value. "
                    "Call set_output with key='result' and value='[' followed by "
                    "the raw_code value followed by ']'. "
                    "Example: if raw_code is 'XYZ', output should be '[XYZ]'. " + SET_OUTPUT
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="gen-to-fmt",
                source="generator",
                target="formatter",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"raw_code": "code"},
            ),
        ],
        memory_keys=["code", "raw_code", "result"],
    )
    executor = make_executor(
        runtime, llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.path == ["generator", "formatter"]
    assert result.steps_executed == 2

    # Verify output structure
    output = result.output.get("result")
    assert output is not None, "Formatter did not set 'result'"
    assert "[" in output and "]" in output, f"Expected bracket wrapping, got: {output}"
    assert "ALPHA_BRAVO_42" in output, f"Code word missing from output: {output}"

    # Both nodes should have set their output keys
    keys_set = capture.output_keys_set()
    assert "code" in keys_set
    assert "result" in keys_set


# ---------------------------------------------------------------------------
# Tests: Escalation Event Flow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_escalation_emits_event_with_reason(
    runtime, goal, llm_provider, tmp_path
):
    """Worker calling escalate must emit ESCALATION_REQUESTED with the reason.

    After calling escalate, the worker blocks waiting for queen input.
    Since there's no queen in this test, we run with a short timeout and
    verify the escalation event was emitted before the timeout.
    """
    bus, capture = _make_event_bus_and_capture()

    graph = GraphSpec(
        id="escalation-reason",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Must escalate immediately",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "You are blocked and need human help. "
                    "Call the escalate tool with reason='missing credentials for API'. "
                    "Do not call set_output. Do not write any text first."
                ),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    from framework.graph.executor import GraphExecutor

    executor = GraphExecutor(
        runtime=runtime,
        llm=llm_provider,
        loop_config={"max_iterations": 3},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )

    # Worker will block after escalate (waiting for queen).
    # Use a short timeout — we only need the escalation event to fire.
    try:
        await asyncio.wait_for(
            executor.execute(graph, goal, {}, validate_graph=False),
            timeout=30,
        )
    except (TimeoutError, asyncio.TimeoutError):
        pass  # Expected: worker hangs waiting for queen input

    # Verify escalation event was emitted before the timeout
    escalations = capture.of_type(EventType.ESCALATION_REQUESTED)
    assert len(escalations) >= 1, (
        f"No ESCALATION_REQUESTED event emitted. "
        f"Events captured: {[e.type.value for e in capture.events]}"
    )

    esc_data = escalations[0].data
    assert esc_data.get("reason"), "Escalation reason should not be empty"
    assert escalations[0].stream_id == "worker"
    assert escalations[0].node_id == "worker"
