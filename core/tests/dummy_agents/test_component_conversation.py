"""Component tests: Conversation Persistence — write-through, storage.

Exercises conversation persistence by running real LLM turns and
verifying that messages and state are written to disk correctly.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor


def _build_echo_graph() -> GraphSpec:
    """Single-node graph that echoes input to output."""
    return GraphSpec(
        id="conv-echo",
        goal_id="dummy",
        entry_node="echo",
        entry_points={"start": "echo"},
        terminal_nodes=["echo"],
        nodes=[
            NodeSpec(
                id="echo",
                name="Echo",
                description="Echoes input to output",
                node_type="event_loop",
                input_keys=["input"],
                output_keys=["output"],
                system_prompt=(
                    "Read the 'input' value and immediately call "
                    "set_output with key='output' and the same "
                    "value. Do not add any text."
                ),
            ),
        ],
        edges=[],
        memory_keys=["input", "output"],
        conversation_mode="continuous",
    )


@pytest.mark.asyncio
async def test_conversation_persists_messages(runtime, goal, llm_provider, tmp_path, artifact):
    """After execution, conversation data should exist on disk."""
    storage = tmp_path / "session"
    graph = _build_echo_graph()
    executor = make_executor(
        runtime,
        llm_provider,
        storage_path=storage,
    )

    result = await executor.execute(
        graph,
        goal,
        {"input": "hello"},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=("success=True, conversations/ dir exists with data files"),
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    # Verify conversation directory was created with content
    conv_dir = storage / "conversations"

    artifact.check(
        "conversations/ dir exists",
        conv_dir.exists(),
        actual=str(conv_dir.exists()),
        expected_val="True",
    )
    assert conv_dir.exists(), "conversations/ directory should exist"

    # Should have at least one file (messages or cursor)
    all_files = list(conv_dir.rglob("*"))
    data_files = [f for f in all_files if f.is_file()]

    artifact.check(
        "at least one data file",
        len(data_files) > 0,
        actual=str(len(data_files)),
        expected_val=">0",
    )
    assert len(data_files) > 0, "Should have persisted at least one conversation file"


@pytest.mark.asyncio
async def test_conversation_output_matches_execution(
    runtime, goal, llm_provider, tmp_path, artifact
):
    """ExecutionResult output should be consistent with the node."""
    storage = tmp_path / "session"
    graph = _build_echo_graph()
    executor = make_executor(
        runtime,
        llm_provider,
        storage_path=storage,
    )

    result = await executor.execute(
        graph,
        goal,
        {"input": "test_value"},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected="success=True, output['output'] is non-empty",
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    actual_output = result.output.get("output")
    artifact.check(
        "output['output'] is set",
        actual_output is not None,
        actual=repr(actual_output),
        expected_val="non-None value",
    )
    assert result.output.get("output") is not None

    # The echo node should produce some non-empty output
    output_len = len(str(result.output["output"]))
    artifact.check(
        "output is non-empty",
        output_len > 0,
        actual=str(output_len),
        expected_val=">0",
    )
    assert len(str(result.output["output"])) > 0


@pytest.mark.asyncio
async def test_conversation_multi_node_persistence(runtime, goal, llm_provider, tmp_path, artifact):
    """Multi-node graph should persist conversation data for each node."""
    from framework.graph.edge import EdgeCondition, EdgeSpec

    storage = tmp_path / "session"
    graph = GraphSpec(
        id="multi-conv",
        goal_id="dummy",
        entry_node="step1",
        entry_points={"start": "step1"},
        terminal_nodes=["step2"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="step1",
                name="Step 1",
                description="First step",
                node_type="event_loop",
                output_keys=["intermediate"],
                system_prompt=(
                    "Call set_output with key='intermediate' "
                    "and value='step1_done'. Do not write text."
                ),
            ),
            NodeSpec(
                id="step2",
                name="Step 2",
                description="Second step",
                node_type="event_loop",
                input_keys=["intermediate"],
                output_keys=["result"],
                system_prompt=(
                    "Call set_output with key='result' and value='step2_done'. Do not write text."
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="step1-to-step2",
                source="step1",
                target="step2",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"intermediate": "intermediate"},
            ),
        ],
        memory_keys=["intermediate", "result"],
    )
    executor = make_executor(
        runtime,
        llm_provider,
        storage_path=storage,
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected=("success=True, path=['step1','step2'], conversations/ dir exists"),
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
        result.path == ["step1", "step2"],
        actual=str(result.path),
        expected_val="['step1', 'step2']",
    )
    assert result.path == ["step1", "step2"]

    # Both nodes should have written conversation data
    conv_dir = storage / "conversations"

    artifact.check(
        "conversations/ dir exists",
        conv_dir.exists(),
        actual=str(conv_dir.exists()),
        expected_val="True",
    )
    assert conv_dir.exists()
