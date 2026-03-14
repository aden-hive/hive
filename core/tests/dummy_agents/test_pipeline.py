"""Pipeline agent: linear 3-node chain with real LLM at each step.

Tests input_mapping, conversation modes, and multi-node traversal.
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
    return GraphSpec(
        id="pipeline-graph",
        goal_id="dummy",
        entry_node="intake",
        entry_points={"start": "intake"},
        terminal_nodes=["output"],
        conversation_mode=conversation_mode,
        nodes=[
            NodeSpec(
                id="intake",
                name="Intake",
                description="Captures raw input and passes it along",
                node_type="event_loop",
                input_keys=["raw"],
                output_keys=["captured"],
                system_prompt=(
                    "You are the intake node. Read the 'raw' input value from the user "
                    "message, then call set_output with key='captured' and the same value. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="transform",
                name="Transform",
                description="Uppercases the input value",
                node_type="event_loop",
                input_keys=["value"],
                output_keys=["transformed"],
                system_prompt=(
                    "You are a transform node. Read the 'value' input from the user "
                    "message, convert it to UPPERCASE, then call set_output with "
                    "key='transformed' and the uppercased value. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="output",
                name="Output",
                description="Formats final result",
                node_type="event_loop",
                input_keys=["value"],
                output_keys=["result"],
                system_prompt=(
                    "You are the output node. Read the 'value' input from the user "
                    "message, prefix it with 'Result: ', then call set_output with "
                    "key='result' and the prefixed value. " + SET_OUTPUT_INSTRUCTION
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
            EdgeSpec(
                id="transform-to-output",
                source="transform",
                target="output",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={"value": "transformed"},
            ),
        ],
        memory_keys=["raw", "captured", "value", "transformed", "result"],
    )


@pytest.mark.asyncio
async def test_pipeline_linear_traversal(runtime, goal, llm_provider):
    graph = _build_pipeline_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(graph, goal, {"raw": "hello"}, validate_graph=False)

    assert result.success
    assert result.path == ["intake", "transform", "output"]
    assert result.steps_executed == 3


@pytest.mark.asyncio
async def test_pipeline_input_mapping(runtime, goal, llm_provider):
    """Verify input_mapping wires source output keys to target input keys."""
    graph = _build_pipeline_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(graph, goal, {"raw": "test value"}, validate_graph=False)

    assert result.success
    assert result.steps_executed == 3
    assert result.output.get("result") is not None


@pytest.mark.asyncio
async def test_pipeline_continuous_conversation(runtime, goal, llm_provider):
    graph = _build_pipeline_graph(conversation_mode="continuous")
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(graph, goal, {"raw": "data"}, validate_graph=False)

    assert result.success
    assert len(result.path) == 3


@pytest.mark.asyncio
async def test_pipeline_isolated_conversation(runtime, goal, llm_provider):
    graph = _build_pipeline_graph(conversation_mode="isolated")
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(graph, goal, {"raw": "data"}, validate_graph=False)

    assert result.success
    assert len(result.path) == 3
