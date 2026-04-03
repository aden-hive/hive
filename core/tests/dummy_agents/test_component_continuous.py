"""Component tests: Continuous Conversation Mode — threading, buffer passing.

Exercises conversation threading across nodes to verify that downstream
nodes receive context from upstream nodes in continuous mode.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor

SET_OUTPUT_INSTRUCTION = (
    "You MUST call the set_output tool to provide your answer. "
    "Do not just write text — call set_output with the correct key and value."
)


def _build_pipeline_graph(conversation_mode: str = "continuous") -> GraphSpec:
    """Two-node pipeline: intake captures input, transform uppercases it."""
    return GraphSpec(
        id="continuous-pipeline",
        goal_id="dummy",
        entry_node="intake",
        entry_points={"start": "intake"},
        terminal_nodes=["transform"],
        conversation_mode=conversation_mode,
        nodes=[
            NodeSpec(
                id="intake",
                name="Intake",
                description="Captures raw input",
                node_type="event_loop",
                input_keys=["raw"],
                output_keys=["captured"],
                system_prompt=(
                    "Read the 'raw' input value and call set_output with "
                    "key='captured' and the same value. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="transform",
                name="Transform",
                description="Uppercases the value",
                node_type="event_loop",
                input_keys=["value"],
                output_keys=["result"],
                system_prompt=(
                    "Read the 'value' input, convert it to UPPERCASE, "
                    "then call set_output with key='result' and the uppercased value. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="intake-to-transform",
                source="intake",
                target="transform",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"value": "captured"},
            ),
        ],
        memory_keys=["raw", "captured", "value", "result"],
    )


@pytest.mark.asyncio
async def test_continuous_pipeline_traverses(runtime, goal, llm_provider):
    """Continuous mode pipeline should traverse both nodes."""
    graph = _build_pipeline_graph(conversation_mode="continuous")
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})

    result = await executor.execute(
        graph, goal, {"raw": "hello"}, validate_graph=False
    )

    assert result.success
    assert result.path == ["intake", "transform"]
    assert result.output.get("result") is not None


@pytest.mark.asyncio
async def test_continuous_data_flows_through(runtime, goal, llm_provider):
    """Data from node 1's output should be available to node 2 via input_mapping."""
    graph = _build_pipeline_graph(conversation_mode="continuous")
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})

    result = await executor.execute(
        graph, goal, {"raw": "test_data"}, validate_graph=False
    )

    assert result.success
    assert result.output.get("result") is not None
    # The transform node should have produced something based on the input
    assert len(str(result.output["result"])) > 0


@pytest.mark.asyncio
async def test_isolated_pipeline_traverses(runtime, goal, llm_provider):
    """Isolated mode pipeline should also traverse both nodes."""
    graph = _build_pipeline_graph(conversation_mode="isolated")
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})

    result = await executor.execute(
        graph, goal, {"raw": "data"}, validate_graph=False
    )

    assert result.success
    assert result.path == ["intake", "transform"]


@pytest.mark.asyncio
async def test_continuous_three_node_chain(runtime, goal, llm_provider):
    """Three-node continuous pipeline should thread conversation end-to-end."""
    graph = GraphSpec(
        id="three-node-chain",
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
                input_keys=["input"],
                output_keys=["a_out"],
                system_prompt=(
                    "Read the 'input' value and call set_output with "
                    "key='a_out' and the same value. " + SET_OUTPUT_INSTRUCTION
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
                    "Read the 'b_in' value and call set_output with "
                    "key='b_out' and value='processed_' followed by the input. "
                    + SET_OUTPUT_INSTRUCTION
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
                    "Read the 'c_in' value and call set_output with "
                    "key='result' and the same value. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="a-to-b",
                source="a",
                target="b",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"b_in": "a_out"},
            ),
            EdgeSpec(
                id="b-to-c",
                source="b",
                target="c",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"c_in": "b_out"},
            ),
        ],
        memory_keys=["input", "a_out", "b_in", "b_out", "c_in", "result"],
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})
    result = await executor.execute(
        graph, goal, {"input": "payload"}, validate_graph=False
    )

    assert result.success
    assert result.path == ["a", "b", "c"]
    assert result.steps_executed == 3
    assert result.output.get("result") is not None
