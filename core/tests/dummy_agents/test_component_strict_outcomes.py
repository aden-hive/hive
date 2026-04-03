"""Component tests: Strict Outcome Verification — exact output, path, quality, tokens.

These tests go beyond `assert result.success` and verify exact structural
outcomes: output values, execution path, visit counts, token bounds, and
execution quality. They prove the runtime delivers correct, repeatable
behavior under real LLM calls.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor

SET_OUTPUT = (
    "You MUST call the set_output tool. "
    "Do not just write text — call set_output with the correct key and value."
)


# ---------------------------------------------------------------------------
# Strict single-node outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_echo_exact_path_and_steps(runtime, goal, llm_provider):
    """Echo node: path must be exactly ['echo'], steps must be 1."""
    graph = GraphSpec(
        id="strict-echo",
        goal_id="dummy",
        entry_node="echo",
        entry_points={"start": "echo"},
        terminal_nodes=["echo"],
        nodes=[
            NodeSpec(
                id="echo",
                name="Echo",
                description="Echoes input",
                node_type="event_loop",
                input_keys=["input"],
                output_keys=["output"],
                system_prompt=(
                    "Read the 'input' value and call set_output with "
                    "key='output' and the exact same string. " + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["input", "output"],
        conversation_mode="continuous",
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})
    result = await executor.execute(
        graph, goal, {"input": "ECHO_TEST_42"}, validate_graph=False
    )

    assert result.success
    assert result.path == ["echo"]
    assert result.steps_executed == 1
    assert result.output.get("output") is not None
    assert result.execution_quality == "clean"
    assert result.total_retries == 0
    assert result.total_tokens > 0


@pytest.mark.asyncio
async def test_strict_clean_execution_quality(runtime, goal, llm_provider):
    """A simple set_output call should produce 'clean' execution quality."""
    graph = GraphSpec(
        id="strict-clean",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Set output immediately",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='clean'. " + SET_OUTPUT,
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.is_clean_success, (
        f"Expected clean success, got quality={result.execution_quality}, "
        f"retries={result.total_retries}, failures={result.nodes_with_failures}"
    )
    assert not result.had_partial_failures
    assert len(result.nodes_with_failures) == 0


# ---------------------------------------------------------------------------
# Strict multi-node outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_pipeline_path_ordering(runtime, goal, llm_provider):
    """Three-node pipeline must traverse in exact order: a → b → c."""
    graph = GraphSpec(
        id="strict-pipeline",
        goal_id="dummy",
        entry_node="a",
        entry_points={"start": "a"},
        terminal_nodes=["c"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="a", name="A", description="First",
                node_type="event_loop", output_keys=["a_out"],
                system_prompt="Call set_output with key='a_out' and value='from_a'. " + SET_OUTPUT,
            ),
            NodeSpec(
                id="b", name="B", description="Second",
                node_type="event_loop", input_keys=["b_in"], output_keys=["b_out"],
                system_prompt="Call set_output with key='b_out' and value='from_b'. " + SET_OUTPUT,
            ),
            NodeSpec(
                id="c", name="C", description="Third",
                node_type="event_loop", input_keys=["c_in"], output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='from_c'. " + SET_OUTPUT,
            ),
        ],
        edges=[
            EdgeSpec(id="a-b", source="a", target="b",
                     condition=EdgeCondition.ON_SUCCESS, input_mapping={"b_in": "a_out"}),
            EdgeSpec(id="b-c", source="b", target="c",
                     condition=EdgeCondition.ON_SUCCESS, input_mapping={"c_in": "b_out"}),
        ],
        memory_keys=["a_out", "b_in", "b_out", "c_in", "result"],
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.path == ["a", "b", "c"], f"Path was {result.path}"
    assert result.steps_executed == 3
    assert result.output.get("result") is not None

    # Visit counts: each node visited exactly once
    assert result.node_visit_counts.get("a", 0) == 1
    assert result.node_visit_counts.get("b", 0) == 1
    assert result.node_visit_counts.get("c", 0) == 1


@pytest.mark.asyncio
async def test_strict_branch_correct_terminal(runtime, goal, llm_provider):
    """Classifier node must route 'I love it' to the positive terminal."""
    graph = GraphSpec(
        id="strict-branch",
        goal_id="dummy",
        entry_node="classify",
        entry_points={"start": "classify"},
        terminal_nodes=["positive", "negative"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="classify", name="Classify", description="Sentiment classifier",
                node_type="event_loop", input_keys=["text"],
                output_keys=["label"],
                system_prompt=(
                    "Read the 'text' input. Determine if sentiment is positive or negative. "
                    "Call set_output with key='label' and value='positive' or 'negative'. "
                    + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="positive", name="Positive", description="Positive handler",
                node_type="event_loop", output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='POS'. " + SET_OUTPUT,
            ),
            NodeSpec(
                id="negative", name="Negative", description="Negative handler",
                node_type="event_loop", output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='NEG'. " + SET_OUTPUT,
            ),
        ],
        edges=[
            EdgeSpec(id="to-pos", source="classify", target="positive",
                     condition=EdgeCondition.CONDITIONAL,
                     condition_expr="output.get('label') == 'positive'", priority=1),
            EdgeSpec(id="to-neg", source="classify", target="negative",
                     condition=EdgeCondition.CONDITIONAL,
                     condition_expr="output.get('label') == 'negative'", priority=0),
        ],
        memory_keys=["text", "label", "result"],
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})
    result = await executor.execute(
        graph, goal, {"text": "I absolutely love this product, it's fantastic!"}, validate_graph=False
    )

    assert result.success
    assert result.path == ["classify", "positive"], f"Path was {result.path}"
    assert result.steps_executed == 2
    assert result.output.get("result") == "POS"


@pytest.mark.asyncio
async def test_strict_branch_negative_terminal(runtime, goal, llm_provider):
    """Classifier node must route hateful text to the negative terminal."""
    graph = GraphSpec(
        id="strict-branch-neg",
        goal_id="dummy",
        entry_node="classify",
        entry_points={"start": "classify"},
        terminal_nodes=["positive", "negative"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="classify", name="Classify", description="Sentiment classifier",
                node_type="event_loop", input_keys=["text"],
                output_keys=["label"],
                system_prompt=(
                    "Read the 'text' input. Determine if sentiment is positive or negative. "
                    "Call set_output with key='label' and value='positive' or 'negative'. "
                    + SET_OUTPUT
                ),
            ),
            NodeSpec(
                id="positive", name="Positive", description="Positive handler",
                node_type="event_loop", output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='POS'. " + SET_OUTPUT,
            ),
            NodeSpec(
                id="negative", name="Negative", description="Negative handler",
                node_type="event_loop", output_keys=["result"],
                system_prompt="Call set_output with key='result' and value='NEG'. " + SET_OUTPUT,
            ),
        ],
        edges=[
            EdgeSpec(id="to-pos", source="classify", target="positive",
                     condition=EdgeCondition.CONDITIONAL,
                     condition_expr="output.get('label') == 'positive'", priority=1),
            EdgeSpec(id="to-neg", source="classify", target="negative",
                     condition=EdgeCondition.CONDITIONAL,
                     condition_expr="output.get('label') == 'negative'", priority=0),
        ],
        memory_keys=["text", "label", "result"],
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})
    result = await executor.execute(
        graph, goal, {"text": "This is absolutely terrible and broken. Worst ever."}, validate_graph=False
    )

    assert result.success
    assert result.path == ["classify", "negative"], f"Path was {result.path}"
    assert result.steps_executed == 2
    assert result.output.get("result") == "NEG"


# ---------------------------------------------------------------------------
# Strict tool interaction outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_tool_output_format(
    runtime, goal, llm_provider, tool_registry, tmp_path
):
    """Worker must call get_current_time and produce output in STATUS|date|day format."""
    graph = GraphSpec(
        id="strict-tool-format",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Create formatted status string",
                node_type="event_loop",
                output_keys=["result"],
                tools=["get_current_time"],
                system_prompt=(
                    "Call get_current_time with timezone='UTC'. "
                    "Extract the 'date' and 'day_of_week' fields from the result. "
                    "Build this exact format: STATUS|<date>|<day_of_week> "
                    "(example: STATUS|2026-04-03|Thursday). "
                    "Call set_output with key='result' and this formatted string. "
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
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    output = result.output.get("result")
    assert output is not None, "No result output"

    # Strict format verification: STATUS|date|day_of_week
    parts = output.split("|")
    assert len(parts) == 3, f"Expected 3 pipe-separated parts, got {len(parts)}: {output}"
    assert parts[0] == "STATUS", f"First part should be STATUS, got: {parts[0]}"
    # Date part should look like YYYY-MM-DD
    assert len(parts[1]) >= 8, f"Date part too short: {parts[1]}"
    assert "-" in parts[1], f"Date part should contain dashes: {parts[1]}"
    # Day of week should be a recognizable day name
    valid_days = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
    assert parts[2] in valid_days, f"Invalid day_of_week: {parts[2]}"


@pytest.mark.asyncio
async def test_strict_artifact_creation_and_verification(
    runtime, goal, llm_provider, tool_registry, tmp_path
):
    """Single-node: saves a file via save_data, then verifies the artifact on disk."""
    storage_path = tmp_path / "session"
    graph = GraphSpec(
        id="strict-artifact",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Creates and verifies a file artifact",
                node_type="event_loop",
                input_keys=["task"],
                output_keys=["result"],
                tools=["save_data", "load_data"],
                system_prompt=(
                    "Follow these steps exactly:\n"
                    "1. Call save_data with filename='test_artifact.txt' and "
                    "data='INTEGRATION_TEST_PAYLOAD_XYZ'.\n"
                    "2. Call load_data with filename='test_artifact.txt'.\n"
                    "3. Call set_output with key='result' and the loaded content as value.\n"
                    + SET_OUTPUT
                ),
            ),
        ],
        edges=[],
        memory_keys=["task", "result"],
    )
    executor = make_executor(
        runtime, llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
        storage_path=storage_path,
    )
    result = await executor.execute(
        graph, goal, {"task": "Create and verify artifact"}, validate_graph=False
    )

    # Strict outcome verification
    assert result.success
    assert result.path == ["worker"], f"Path was {result.path}"
    assert result.steps_executed == 1

    # Output must be the loaded content
    output = result.output.get("result")
    assert output is not None, "Worker did not set 'result'"
    assert "INTEGRATION_TEST_PAYLOAD_XYZ" in output, (
        f"Expected payload in output, got: {output}"
    )

    # Verify the actual file exists on disk (save_data uses storage_path/data/)
    artifact_path = storage_path / "data" / "test_artifact.txt"
    assert artifact_path.exists(), f"Artifact not found at {artifact_path}"
    file_content = artifact_path.read_text(encoding="utf-8").strip()
    assert file_content == "INTEGRATION_TEST_PAYLOAD_XYZ", (
        f"File content mismatch: {file_content!r}"
    )


# ---------------------------------------------------------------------------
# Strict feedback loop outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_strict_feedback_loop_visit_counts(runtime, goal, llm_provider):
    """Feedback loop must respect max_node_visits and record visit counts."""
    from .nodes import StatefulNode, SuccessNode
    from framework.graph.node import NodeResult

    graph = GraphSpec(
        id="strict-feedback",
        goal_id="dummy",
        entry_node="draft",
        terminal_nodes=["done"],
        nodes=[
            NodeSpec(id="draft", name="Draft", description="Produces draft",
                     node_type="event_loop", output_keys=["draft_output"], max_node_visits=3),
            NodeSpec(id="review", name="Review", description="Reviews draft",
                     node_type="event_loop", input_keys=["draft_output"],
                     output_keys=["approved"]),
            NodeSpec(id="done", name="Done", description="Terminal",
                     node_type="event_loop", output_keys=["final"]),
        ],
        edges=[
            EdgeSpec(id="d-r", source="draft", target="review",
                     condition=EdgeCondition.ON_SUCCESS),
            EdgeSpec(id="r-d", source="review", target="draft",
                     condition=EdgeCondition.CONDITIONAL,
                     condition_expr="output.get('approved') == False", priority=1),
            EdgeSpec(id="r-done", source="review", target="done",
                     condition=EdgeCondition.CONDITIONAL,
                     condition_expr="output.get('approved') == True", priority=0),
        ],
        memory_keys=["draft_output", "approved", "final"],
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})

    # Deterministic nodes: reject twice, then approve
    executor.register_node("draft", SuccessNode(output={"draft_output": "v1"}))
    executor.register_node("review", StatefulNode([
        NodeResult(success=True, output={"approved": False}),
        NodeResult(success=True, output={"approved": False}),
        NodeResult(success=True, output={"approved": True}),
    ]))
    executor.register_node("done", SuccessNode(output={"final": "complete"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert "done" in result.path

    # Strict visit count verification
    assert result.node_visit_counts.get("draft", 0) == 3, (
        f"Draft should be visited 3 times, got {result.node_visit_counts.get('draft')}"
    )
    assert result.node_visit_counts.get("review", 0) == 3, (
        f"Review should be visited 3 times, got {result.node_visit_counts.get('review')}"
    )
    assert result.node_visit_counts.get("done", 0) == 1, (
        f"Done should be visited once, got {result.node_visit_counts.get('done')}"
    )

    # Final output must be from the 'done' node
    assert result.output.get("final") == "complete"
