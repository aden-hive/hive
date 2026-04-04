"""Component tests: Verified Outcomes — cross-checked, deterministic, no trust required.

These tests eliminate false positives by:
1. Using DETERMINISTIC inputs with KNOWN correct outputs
2. Cross-checking LLM output against ground truth (tool results, file contents)
3. Using REGEX validation instead of "is not None"
4. Running a VERIFIER node that independently checks the first node's work
5. Asserting on CONTENT, not just existence

If a test here passes, the output is provably correct — not just non-null.
"""

from __future__ import annotations

import json
import re

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor

SET_OUTPUT = (
    "You MUST call the set_output tool. "
    "Do not just write text — call set_output with the correct key and value."
)


# ---------------------------------------------------------------------------
# 1. Echo round-trip: input == output (exact match, no LLM creativity)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_echo_exact_content(runtime, goal, llm_provider, artifact):
    """Echo test with EXACT content verification — not just 'is not None'.

    The input is a unique token. The output must contain that exact token.
    This catches LLMs that hallucinate or paraphrase instead of echoing.
    """
    UNIQUE_TOKEN = "XRAY_7742_BRAVO_ECHO"

    graph = GraphSpec(
        id="verified-echo",
        goal_id="dummy",
        entry_node="echo",
        entry_points={"start": "echo"},
        terminal_nodes=["echo"],
        nodes=[
            NodeSpec(
                id="echo",
                name="Echo",
                description="Echoes input exactly",
                node_type="event_loop",
                input_keys=["input"],
                output_keys=["output"],
                system_prompt=(
                    "Read the 'input' value. Call set_output with key='output' "
                    "and the EXACT same string. Do not modify it. Do not add quotes "
                    "or punctuation. Just the raw string." + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["input", "output"],
        conversation_mode="continuous",
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})
    result = await executor.execute(graph, goal, {"input": UNIQUE_TOKEN}, validate_graph=False)
    artifact.record(
        result, expected="success=True, output['output'] contains exact token XRAY_7742_BRAVO_ECHO"
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    output = result.output.get("output", "")
    artifact.check(
        "output contains exact token",
        UNIQUE_TOKEN in output,
        actual=repr(output),
        expected_val=f"contains '{UNIQUE_TOKEN}'",
    )
    assert UNIQUE_TOKEN in output, f"Exact token '{UNIQUE_TOKEN}' not found in output: {output!r}"


# ---------------------------------------------------------------------------
# 2. Math verification: LLM computes, we verify the answer independently
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_tool_result_matches_ground_truth(
    runtime, goal, llm_provider, tool_registry, artifact
):
    """get_current_time returns real data — verify output matches tool's actual return.

    We call the tool directly (ground truth), then run the LLM graph,
    and verify the LLM's output contains the SAME day_of_week.
    This catches LLMs that hallucinate dates.
    """
    from framework.llm.provider import ToolUse

    # Step 1: Get ground truth by calling tool directly
    executor_fn = tool_registry.get_executor()
    tool_use = ToolUse(id="ground-truth", name="get_current_time", input={"timezone": "UTC"})
    ground_truth_result = executor_fn(tool_use)

    artifact.record_value(
        "ground_truth_is_error",
        ground_truth_result.is_error,
        expected="ground truth tool returns day_of_week matching LLM output",
    )
    assert not ground_truth_result.is_error

    # Parse the actual day_of_week from the tool
    gt_data = json.loads(ground_truth_result.content)
    actual_day = gt_data.get("day_of_week", "")
    artifact.record_value("ground_truth_day", actual_day)
    assert actual_day, f"Tool didn't return day_of_week: {gt_data}"

    # Step 2: Run LLM graph that uses the same tool
    graph = GraphSpec(
        id="verified-time",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Get current time and report day",
                node_type="event_loop",
                output_keys=["result"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Extract the day_of_week from the result. "
                    "Call set_output with key='result' and ONLY the day_of_week string "
                    "(e.g., 'Monday'). Nothing else." + SET_OUTPUT
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
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)
    artifact.record(
        result,
        expected=f"success=True, output['result'] matches ground truth day_of_week='{actual_day}'",
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    llm_day = (result.output.get("result") or "").strip()
    artifact.record_value("llm_day", llm_day)

    # Step 3: Cross-check — LLM's answer must match ground truth
    artifact.check(
        "LLM day matches ground truth",
        actual_day.lower() in llm_day.lower(),
        actual=repr(llm_day),
        expected_val=f"contains '{actual_day}'",
    )
    assert actual_day.lower() in llm_day.lower(), (
        f"LLM reported '{llm_day}' but tool returned '{actual_day}'. "
        f"The LLM hallucinated or misread the tool result."
    )


# ---------------------------------------------------------------------------
# 3. File artifact round-trip: write -> read -> binary compare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_artifact_binary_match(
    runtime, goal, llm_provider, tool_registry, tmp_path, artifact
):
    """Save a file, then verify the on-disk content matches EXACTLY.

    Does NOT rely on LLM to verify — we read the file ourselves.
    This catches save_data bugs, encoding issues, or LLM adding extra content.
    """
    PAYLOAD = "VERIFIED_PAYLOAD_99_ZULU"
    storage_path = tmp_path / "session"

    graph = GraphSpec(
        id="verified-artifact",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Writer",
                description="Saves exact payload to file",
                node_type="event_loop",
                input_keys=["task"],
                output_keys=["result"],
                tools=["save_data"],
                system_prompt=(
                    f"Call save_data with filename='verified.txt' and data='{PAYLOAD}'. "
                    "Then call set_output with key='result' and value='saved'. " + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["task", "result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=storage_path,
    )
    result = await executor.execute(graph, goal, {"task": "save the file"}, validate_graph=False)
    artifact.record(
        result,
        expected=(
            "success=True, file 'verified.txt' on disk matches VERIFIED_PAYLOAD_99_ZULU exactly"
        ),
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    # Cross-check: read the file ourselves — don't trust the LLM
    artifact_path = storage_path / "data" / "verified.txt"

    artifact.check(
        "file exists on disk",
        artifact_path.exists(),
        actual=str(artifact_path.exists()),
        expected_val="True",
    )
    assert artifact_path.exists(), f"File not created at {artifact_path}"

    actual_content = artifact_path.read_text(encoding="utf-8").strip()
    artifact.check(
        "file content matches payload",
        actual_content == PAYLOAD,
        actual=repr(actual_content),
        expected_val=repr(PAYLOAD),
    )
    assert actual_content == PAYLOAD, (
        f"File content mismatch.\n"
        f"  Expected: {PAYLOAD!r}\n"
        f"  Actual:   {actual_content!r}\n"
        f"The LLM may have modified the payload or save_data encoded it differently."
    )


# ---------------------------------------------------------------------------
# 4. Pipeline data integrity: track a token through N nodes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_pipeline_token_survives(runtime, goal, llm_provider, artifact):
    """Pass a unique token through 3 nodes — verify it arrives at the end.

    Each node is instructed to PRESERVE the token. If any node drops or
    modifies it, the final assertion catches it. This verifies input_mapping
    and continuous conversation actually deliver data correctly.
    """
    TOKEN = "TRACKING_TOKEN_88X"

    graph = GraphSpec(
        id="verified-pipeline",
        goal_id="dummy",
        entry_node="a",
        entry_points={"start": "a"},
        terminal_nodes=["c"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="a",
                name="Node A",
                description="First node",
                node_type="event_loop",
                input_keys=["token"],
                output_keys=["a_out"],
                system_prompt=(
                    "Read the 'token' input. Call set_output with key='a_out' "
                    "and the EXACT token value. Do not modify it." + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="b",
                name="Node B",
                description="Middle node",
                node_type="event_loop",
                input_keys=["b_in"],
                output_keys=["b_out"],
                system_prompt=(
                    "Read the 'b_in' input. Call set_output with key='b_out' "
                    "and the EXACT same value. Do not modify it." + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="c",
                name="Node C",
                description="Terminal node",
                node_type="event_loop",
                input_keys=["c_in"],
                output_keys=["result"],
                system_prompt=(
                    "Read the 'c_in' input. Call set_output with key='result' "
                    "and the EXACT same value. Do not modify it." + SET_OUTPUT
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="a-b",
                source="a",
                target="b",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"b_in": "a_out"},
            ),
            EdgeSpec(
                id="b-c",
                source="b",
                target="c",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"c_in": "b_out"},
            ),
        ],
        memory_keys=["token", "a_out", "b_in", "b_out", "c_in", "result"],
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})
    result = await executor.execute(graph, goal, {"token": TOKEN}, validate_graph=False)
    artifact.record(
        result,
        expected="success=True, path=['a','b','c'], output['result'] contains TRACKING_TOKEN_88X",
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    artifact.check(
        "path matches",
        result.path == ["a", "b", "c"],
        actual=str(result.path),
        expected_val="['a', 'b', 'c']",
    )
    assert result.path == ["a", "b", "c"]

    final_output = result.output.get("result", "")
    artifact.check(
        "token survives pipeline",
        TOKEN in final_output,
        actual=repr(final_output),
        expected_val=f"contains '{TOKEN}'",
    )
    assert TOKEN in final_output, (
        f"Token '{TOKEN}' lost in pipeline.\n"
        f"  Input: {TOKEN}\n"
        f"  Final output: {final_output!r}\n"
        f"  Path: {result.path}\n"
        f"Data was corrupted or dropped during node transitions."
    )


# ---------------------------------------------------------------------------
# 5. Structured format with regex validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_format_with_regex(runtime, goal, llm_provider, tool_registry, artifact):
    """Output must match a strict regex — not just 'contains a pipe character'.

    Format: STATUS|YYYY-MM-DD|DayName
    Regex validates each segment independently.
    """
    graph = GraphSpec(
        id="verified-format",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Produce formatted status string",
                node_type="event_loop",
                output_keys=["result"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Build this EXACT format: STATUS|<date>|<day_of_week>\n"
                    "Where <date> is YYYY-MM-DD format and <day_of_week> is the full day name.\n"
                    "Example: STATUS|2026-04-03|Thursday\n"
                    "Call set_output with key='result' and the formatted string.\n"
                    "Output ONLY the formatted string, nothing else." + SET_OUTPUT
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
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)
    artifact.record(
        result, expected="success=True, output['result'] matches regex STATUS|YYYY-MM-DD|DayName"
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    output = (result.output.get("result") or "").strip()
    artifact.record_value("raw_output", output)

    # Strict regex: STATUS|YYYY-MM-DD|DayName
    pattern = (
        r"^STATUS\|\d{4}-\d{2}-\d{2}\|(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$"
    )
    matches = bool(re.match(pattern, output))
    artifact.check(
        "output matches regex",
        matches,
        actual=repr(output),
        expected_val=f"matches pattern: {pattern}",
    )
    assert re.match(pattern, output), (
        f"Output does not match required format.\n"
        f"  Expected pattern: STATUS|YYYY-MM-DD|DayName\n"
        f"  Actual output:    {output!r}\n"
        f"  Regex:            {pattern}"
    )


# ---------------------------------------------------------------------------
# 6. Two-node cross-verification: writer + independent verifier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_two_node_cross_check(
    runtime, goal, llm_provider, tool_registry, tmp_path, artifact
):
    """Node 1 writes a file. Node 2 loads it and compares to expected.

    Both nodes operate INDEPENDENTLY on the same file. If the content
    doesn't match, the verifier reports MISMATCH. We also read the file
    ourselves as a triple-check.
    """
    EXPECTED = "CROSS_CHECK_ALPHA_42"
    storage_path = tmp_path / "session"

    graph = GraphSpec(
        id="verified-cross-check",
        goal_id="dummy",
        entry_node="writer",
        entry_points={"start": "writer"},
        terminal_nodes=["verifier"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="writer",
                name="Writer",
                description="Writes exact content to file",
                node_type="event_loop",
                output_keys=["filename"],
                tools=["save_data"],
                system_prompt=(
                    f"Call save_data with filename='crosscheck.txt' and data='{EXPECTED}'. "
                    "Then call set_output with key='filename' and value='crosscheck.txt'."
                    + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="verifier",
                name="Verifier",
                description="Loads file and verifies content",
                node_type="event_loop",
                input_keys=["filename"],
                output_keys=["result"],
                tools=["load_data"],
                system_prompt=(
                    "Load the file using load_data with the provided 'filename'. "
                    f"If the loaded content is exactly '{EXPECTED}', "
                    "call set_output with key='result' and value='VERIFIED'. "
                    "If it does NOT match, call set_output with key='result' "
                    "and value='MISMATCH:' followed by what you actually loaded." + SET_OUTPUT
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="write-to-verify",
                source="writer",
                target="verifier",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"filename": "filename"},
            ),
        ],
        memory_keys=["filename", "result"],
    )
    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=storage_path,
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)
    artifact.record(
        result,
        expected=(
            "success=True, path=['writer','verifier'], "
            "verifier output='VERIFIED', disk content "
            "matches CROSS_CHECK_ALPHA_42"
        ),
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    artifact.check(
        "path matches",
        result.path == ["writer", "verifier"],
        actual=str(result.path),
        expected_val="['writer', 'verifier']",
    )
    assert result.path == ["writer", "verifier"]

    # LLM-side verification
    verifier_output = result.output.get("result", "")
    artifact.check(
        "verifier output is VERIFIED",
        verifier_output == "VERIFIED",
        actual=repr(verifier_output),
        expected_val="'VERIFIED'",
    )
    assert verifier_output == "VERIFIED", (
        f"Verifier node reported: {verifier_output!r} (expected 'VERIFIED')"
    )

    # Our own independent verification (triple-check)
    artifact_path = storage_path / "data" / "crosscheck.txt"
    artifact.check(
        "file exists on disk",
        artifact_path.exists(),
        actual=str(artifact_path.exists()),
        expected_val="True",
    )
    assert artifact_path.exists(), f"File not found at {artifact_path}"

    actual = artifact_path.read_text(encoding="utf-8").strip()
    artifact.check(
        "disk content matches expected",
        actual == EXPECTED,
        actual=repr(actual),
        expected_val=repr(EXPECTED),
    )
    assert actual == EXPECTED, f"Disk content mismatch: expected {EXPECTED!r}, got {actual!r}"


# ---------------------------------------------------------------------------
# 7. Event bus cross-check: verify events match execution result
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verified_events_match_result(
    runtime, goal, llm_provider, tool_registry, tmp_path, artifact
):
    """Cross-check: events captured on bus must agree with ExecutionResult.

    If result says path=["a","b"], the events must show NODE_LOOP_COMPLETED
    for both "a" and "b". If result says tool X was called, TOOL_CALL_COMPLETED
    must contain X. This catches desynchronization between the event bus and
    the execution engine.
    """
    from framework.runtime.event_bus import EventBus, EventType

    bus = EventBus()
    completed_nodes = []
    tool_names = set()

    async def _capture_node(event):
        completed_nodes.append(event.node_id)

    async def _capture_tool(event):
        tool_names.add(event.data.get("tool_name", ""))

    bus.subscribe(event_types=[EventType.NODE_LOOP_COMPLETED], handler=_capture_node)
    bus.subscribe(event_types=[EventType.TOOL_CALL_COMPLETED], handler=_capture_tool)

    graph = GraphSpec(
        id="verified-events",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Uses tool then sets output",
                node_type="event_loop",
                output_keys=["result"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Then call set_output with key='result' and value='done'." + SET_OUTPUT
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
    result = await executor.execute(graph, goal, {}, validate_graph=False)
    artifact.record(
        result,
        expected=(
            "success=True, event bus nodes match "
            "result.path, tool events include "
            "get_current_time and set_output"
        ),
    )

    artifact.check(
        "execution succeeds", result.success, actual=str(result.success), expected_val="True"
    )
    assert result.success

    artifact.record_value("completed_nodes", completed_nodes)
    artifact.record_value("tool_names", sorted(tool_names))

    # Cross-check 1: path nodes match completed nodes
    for node_id in result.path:
        artifact.check(
            f"node '{node_id}' in completed events",
            node_id in completed_nodes,
            actual=str(completed_nodes),
            expected_val=f"contains '{node_id}'",
        )
        assert node_id in completed_nodes, (
            f"Node '{node_id}' in result.path but no NODE_LOOP_COMPLETED event. "
            f"Events saw: {completed_nodes}"
        )

    # Cross-check 2: get_current_time must appear in tool events
    artifact.check(
        "get_current_time in tool events",
        "get_current_time" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'get_current_time'",
    )
    assert "get_current_time" in tool_names, (
        f"get_current_time not in tool events. Captured: {tool_names}. "
        f"Result claims success but event bus disagrees."
    )

    # Cross-check 3: set_output must appear in tool events
    artifact.check(
        "set_output in tool events",
        "set_output" in tool_names,
        actual=str(sorted(tool_names)),
        expected_val="contains 'set_output'",
    )
    assert "set_output" in tool_names, (
        f"set_output not in tool events. Captured: {tool_names}. "
        f"Result has output but no set_output event."
    )
