"""Component tests: Worker Communication — event flow, completion.

Exercises the full worker execution lifecycle with EventBus
subscriptions to verify that the exact events are published in
the correct order, with correct data, simulating the queen-worker
communication contract.
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
    "Do not just write text — call set_output with the correct "
    "key and value."
)


@dataclass
class EventCapture:
    """Captures events from the bus for assertion."""

    events: list[AgentEvent] = field(default_factory=list)

    def of_type(self, *event_types: EventType) -> list[AgentEvent]:
        return [e for e in self.events if e.type in event_types]

    def tool_calls(self) -> list[dict]:
        """Extract tool call data from TOOL_CALL_COMPLETED."""
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
    """Create an EventBus with a capture handler."""
    bus = EventBus()
    capture = EventCapture()

    async def _capture_all(event: AgentEvent) -> None:
        capture.events.append(event)

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


# -------------------------------------------------------------------
# Tests: Worker Completion Events
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_emits_loop_lifecycle_events(runtime, goal, llm_provider, tmp_path, artifact):
    """Worker must emit STARTED -> iterations -> COMPLETED."""
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
                system_prompt=("Call set_output with key='result' and value='done'. " + SET_OUTPUT),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime,
        llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=(
            "success=True, lifecycle events in correct order: STARTED -> iterations -> COMPLETED"
        ),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    loop_started = capture.of_type(EventType.NODE_LOOP_STARTED)
    loop_completed = capture.of_type(
        EventType.NODE_LOOP_COMPLETED,
    )
    iterations = capture.of_type(EventType.NODE_LOOP_ITERATION)

    artifact.check(
        "NODE_LOOP_STARTED emitted",
        len(loop_started) >= 1,
        actual=str(len(loop_started)),
        expected_val=">=1",
    )
    assert len(loop_started) >= 1, "Missing NODE_LOOP_STARTED"

    artifact.check(
        "NODE_LOOP_COMPLETED emitted",
        len(loop_completed) >= 1,
        actual=str(len(loop_completed)),
        expected_val=">=1",
    )
    assert len(loop_completed) >= 1, "Missing NODE_LOOP_COMPLETED"

    artifact.check(
        "NODE_LOOP_ITERATION emitted",
        len(iterations) >= 1,
        actual=str(len(iterations)),
        expected_val=">=1",
    )
    assert len(iterations) >= 1, "Missing NODE_LOOP_ITERATION"

    start_idx = capture.events.index(loop_started[0])
    end_idx = capture.events.index(loop_completed[0])
    artifact.check(
        "STARTED precedes COMPLETED",
        start_idx < end_idx,
        actual=f"start={start_idx}, end={end_idx}",
        expected_val="start < end",
    )
    assert start_idx < end_idx, "LOOP_STARTED must precede LOOP_COMPLETED"


@pytest.mark.asyncio
async def test_worker_emits_llm_turn_with_token_counts(
    runtime, goal, llm_provider, tmp_path, artifact
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
                system_prompt=("Call set_output with key='result' and value='ok'. " + SET_OUTPUT),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime,
        llm_provider,
        loop_config={"max_iterations": 3},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=("success=True, LLM_TURN_COMPLETE events with positive token counts and model"),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    llm_turns = capture.of_type(EventType.LLM_TURN_COMPLETE)

    artifact.check(
        "LLM_TURN_COMPLETE emitted",
        len(llm_turns) >= 1,
        actual=str(len(llm_turns)),
        expected_val=">=1",
    )
    assert len(llm_turns) >= 1, "No LLM_TURN_COMPLETE events"

    for i, turn in enumerate(llm_turns):
        in_tok = turn.data.get("input_tokens", 0)
        out_tok = turn.data.get("output_tokens", 0)
        model = turn.data.get("model", "")

        artifact.check(
            f"turn[{i}] input_tokens > 0",
            in_tok > 0,
            actual=str(in_tok),
            expected_val=">0",
        )
        assert in_tok > 0, "input_tokens should be > 0"

        artifact.check(
            f"turn[{i}] output_tokens > 0",
            out_tok > 0,
            actual=str(out_tok),
            expected_val=">0",
        )
        assert out_tok > 0, "output_tokens should be > 0"

        artifact.check(
            f"turn[{i}] model populated",
            bool(model),
            actual=repr(model),
            expected_val="non-empty string",
        )
        assert turn.data.get("model"), "model should be populated"


@pytest.mark.asyncio
async def test_worker_tool_calls_emit_events(
    runtime,
    goal,
    llm_provider,
    tool_registry,
    tmp_path,
    artifact,
):
    """Tool calls must emit STARTED and COMPLETED events."""
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
                    "Then call set_output with key='result' and "
                    "the day_of_week. " + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=(
            "success=True, output['result'] set, tool events for get_current_time and set_output"
        ),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    actual_output = result.output.get("result")
    artifact.check(
        "output['result'] is set",
        actual_output is not None,
        actual=repr(actual_output),
        expected_val="non-None value",
    )
    assert result.output.get("result") is not None

    tool_started = capture.of_type(EventType.TOOL_CALL_STARTED)
    tool_completed = capture.of_type(
        EventType.TOOL_CALL_COMPLETED,
    )

    artifact.check(
        "TOOL_CALL_STARTED emitted",
        len(tool_started) >= 1,
        actual=str(len(tool_started)),
        expected_val=">=1",
    )
    assert len(tool_started) >= 1, "No TOOL_CALL_STARTED events"

    artifact.check(
        "TOOL_CALL_COMPLETED emitted",
        len(tool_completed) >= 1,
        actual=str(len(tool_completed)),
        expected_val=">=1",
    )
    assert len(tool_completed) >= 1, "No TOOL_CALL_COMPLETED"

    tool_names = capture.tool_names_called()
    artifact.check(
        "get_current_time called",
        "get_current_time" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'get_current_time'",
    )
    assert "get_current_time" in tool_names

    artifact.check(
        "set_output called",
        "set_output" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'set_output'",
    )
    assert "set_output" in tool_names

    for tc in capture.tool_calls():
        tn = tc.get("tool_name")
        if tn in ("get_current_time", "set_output"):
            is_err = tc.get("is_error")
            artifact.check(
                f"tool {tn} no error",
                not is_err,
                actual=str(is_err),
                expected_val="False",
            )
            assert not is_err, f"Tool {tn} errored"


@pytest.mark.asyncio
async def test_worker_output_key_set_event(runtime, goal, llm_provider, tmp_path, artifact):
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
        runtime,
        llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=("success=True, output['name'] and output['status'] set, OUTPUT_KEY_SET for both"),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    actual_name = result.output.get("name")
    artifact.check(
        "output['name'] is set",
        actual_name is not None,
        actual=repr(actual_name),
        expected_val="non-None value",
    )
    assert result.output.get("name") is not None

    actual_status = result.output.get("status")
    artifact.check(
        "output['status'] is set",
        actual_status is not None,
        actual=repr(actual_status),
        expected_val="non-None value",
    )
    assert result.output.get("status") is not None

    keys_set = capture.output_keys_set()

    artifact.check(
        "OUTPUT_KEY_SET for 'name'",
        "name" in keys_set,
        actual=str(sorted(keys_set)),
        expected_val="contains 'name'",
    )
    assert "name" in keys_set, f"Missing OUTPUT_KEY_SET for 'name', got: {keys_set}"

    artifact.check(
        "OUTPUT_KEY_SET for 'status'",
        "status" in keys_set,
        actual=str(sorted(keys_set)),
        expected_val="contains 'status'",
    )
    assert "status" in keys_set, f"Missing OUTPUT_KEY_SET for 'status', got: {keys_set}"


# -------------------------------------------------------------------
# Tests: Multi-Node Worker Communication
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_pipeline_data_integrity(
    runtime,
    goal,
    llm_provider,
    tool_registry,
    tmp_path,
    artifact,
):
    """Data from node 1 must arrive at node 2, verified end-to-end."""
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
                description="Produces a timestamped value",
                node_type="event_loop",
                output_keys=["payload"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Extract the 'date' field from the result. "
                    "Call set_output with key='payload' and the "
                    "date string as value. " + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="consumer",
                name="Consumer",
                description="Verifies received data",
                node_type="event_loop",
                input_keys=["data"],
                output_keys=["result"],
                system_prompt=(
                    "Read the 'data' input. It should contain a "
                    "date string. Call set_output with "
                    "key='result' and value='VERIFIED|' followed "
                    "by the first 10 characters of the data "
                    "input. " + SET_OUTPUT
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
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=(
            "success=True, clean, "
            "path=['producer','consumer'], steps=2, "
            "output starts with VERIFIED|"
        ),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    artifact.check(
        "clean success",
        result.is_clean_success,
        actual=str(result.execution_quality),
        expected_val="clean",
    )
    assert result.is_clean_success, f"quality={result.execution_quality}"

    artifact.check(
        "path matches",
        result.path == ["producer", "consumer"],
        actual=str(result.path),
        expected_val="['producer', 'consumer']",
    )
    assert result.path == ["producer", "consumer"]

    artifact.check(
        "steps_executed is 2",
        result.steps_executed == 2,
        actual=str(result.steps_executed),
        expected_val="2",
    )
    assert result.steps_executed == 2

    output = result.output.get("result")
    artifact.check(
        "consumer set 'result'",
        output is not None,
        actual=repr(output),
        expected_val="non-None value",
    )
    assert output is not None, "Consumer did not set 'result'"

    artifact.check(
        "output starts with VERIFIED|",
        output.startswith("VERIFIED|"),
        actual=repr(output),
        expected_val="starts with 'VERIFIED|'",
    )
    assert output.startswith("VERIFIED|"), f"Expected VERIFIED|..., got: {output}"

    artifact.check(
        "total_tokens > 0",
        result.total_tokens > 0,
        actual=str(result.total_tokens),
        expected_val=">0",
    )
    assert result.total_tokens > 0

    artifact.check(
        "total_tokens < 100000",
        result.total_tokens < 100_000,
        actual=str(result.total_tokens),
        expected_val="<100000",
    )
    assert result.total_tokens < 100_000, f"Unexpectedly high tokens: {result.total_tokens}"

    keys_set = capture.output_keys_set()

    artifact.check(
        "producer set 'payload'",
        "payload" in keys_set,
        actual=str(sorted(keys_set)),
        expected_val="contains 'payload'",
    )
    assert "payload" in keys_set, "Producer didn't set 'payload'"

    artifact.check(
        "consumer set 'result' key",
        "result" in keys_set,
        actual=str(sorted(keys_set)),
        expected_val="contains 'result'",
    )
    assert "result" in keys_set, "Consumer didn't set 'result'"

    tool_names = capture.tool_names_called()
    artifact.check(
        "get_current_time called",
        "get_current_time" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'get_current_time'",
    )
    assert "get_current_time" in tool_names


@pytest.mark.asyncio
async def test_worker_multi_node_output_propagation(
    runtime, goal, llm_provider, tmp_path, artifact
):
    """Data from node A must arrive at node B in final output."""
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
                    "Call set_output with key='code' and "
                    "value='ALPHA_BRAVO_42'. "
                    "Do not write any text." + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="formatter",
                name="Formatter",
                description="Wraps code in brackets",
                node_type="event_loop",
                input_keys=["raw_code"],
                output_keys=["result"],
                system_prompt=(
                    "Read the 'raw_code' input value. "
                    "Call set_output with key='result' and "
                    "value='[' followed by the raw_code value "
                    "followed by ']'. "
                    "Example: if raw_code is 'XYZ', output "
                    "should be '[XYZ]'. " + SET_OUTPUT
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
        runtime,
        llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
        event_bus=bus,
        stream_id="worker",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=(
            "success=True, "
            "path=['generator','formatter'], steps=2, "
            "output contains [ALPHA_BRAVO_42]"
        ),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    artifact.check(
        "path matches",
        result.path == ["generator", "formatter"],
        actual=str(result.path),
        expected_val="['generator', 'formatter']",
    )
    assert result.path == ["generator", "formatter"]

    artifact.check(
        "steps_executed is 2",
        result.steps_executed == 2,
        actual=str(result.steps_executed),
        expected_val="2",
    )
    assert result.steps_executed == 2

    output = result.output.get("result")
    artifact.check(
        "formatter set 'result'",
        output is not None,
        actual=repr(output),
        expected_val="non-None value",
    )
    assert output is not None, "Formatter did not set 'result'"

    has_brackets = "[" in output and "]" in output
    artifact.check(
        "output has bracket wrapping",
        has_brackets,
        actual=repr(output),
        expected_val="contains '[' and ']'",
    )
    assert has_brackets, f"Expected bracket wrapping, got: {output}"

    artifact.check(
        "output contains ALPHA_BRAVO_42",
        "ALPHA_BRAVO_42" in output,
        actual=repr(output),
        expected_val="contains 'ALPHA_BRAVO_42'",
    )
    assert "ALPHA_BRAVO_42" in output, f"Code word missing from output: {output}"

    keys_set = capture.output_keys_set()
    artifact.check(
        "'code' in keys_set",
        "code" in keys_set,
        actual=str(sorted(keys_set)),
        expected_val="contains 'code'",
    )
    assert "code" in keys_set

    artifact.check(
        "'result' in keys_set",
        "result" in keys_set,
        actual=str(sorted(keys_set)),
        expected_val="contains 'result'",
    )
    assert "result" in keys_set


# -------------------------------------------------------------------
# Tests: Escalation Event Flow
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_worker_escalation_emits_event_with_reason(
    runtime, goal, llm_provider, tmp_path, artifact
):
    """Worker calling escalate must emit ESCALATION_REQUESTED.

    After calling escalate, the worker blocks waiting for queen
    input. Since there's no queen in this test, we run with a
    short timeout and verify the escalation event was emitted.
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
                    "Call the escalate tool with "
                    "reason='missing credentials for API'. "
                    "Do not call set_output. "
                    "Do not write any text first."
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

    try:
        await asyncio.wait_for(
            executor.execute(
                graph,
                goal,
                {},
                validate_graph=False,
            ),
            timeout=30,
        )
    except (TimeoutError, asyncio.TimeoutError):
        pass  # Expected: worker hangs waiting for queen

    escalations = capture.of_type(EventType.ESCALATION_REQUESTED)
    all_types = [e.type.value for e in capture.events]

    artifact.record_value(
        "escalation_count",
        len(escalations),
        expected=(">=1 ESCALATION_REQUESTED with non-empty reason, stream_id='worker'"),
    )
    artifact.record_value("all_event_types", all_types)

    artifact.check(
        "escalation event emitted",
        len(escalations) >= 1,
        actual=str(len(escalations)),
        expected_val=">=1",
    )
    assert len(escalations) >= 1, f"No ESCALATION_REQUESTED event emitted. Events: {all_types}"

    esc_data = escalations[0].data
    reason = esc_data.get("reason", "")
    artifact.check(
        "reason is non-empty",
        bool(reason),
        actual=repr(reason),
        expected_val="non-empty string",
    )
    assert esc_data.get("reason"), "Escalation reason empty"

    artifact.check(
        "stream_id is 'worker'",
        escalations[0].stream_id == "worker",
        actual=repr(escalations[0].stream_id),
        expected_val="'worker'",
    )
    assert escalations[0].stream_id == "worker"

    artifact.check(
        "node_id is 'worker'",
        escalations[0].node_id == "worker",
        actual=repr(escalations[0].node_id),
        expected_val="'worker'",
    )
    assert escalations[0].node_id == "worker"
