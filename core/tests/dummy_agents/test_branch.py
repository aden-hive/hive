"""Branch agent: LLM classifies input, conditional edges route to different paths.

Tests conditional edge evaluation with real LLM output.
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


def _build_branch_graph() -> GraphSpec:
    return GraphSpec(
        id="branch-graph",
        goal_id="dummy",
        entry_node="classify",
        entry_points={"start": "classify"},
        terminal_nodes=["positive", "negative"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="classify",
                name="Classify",
                description="Classifies input sentiment",
                node_type="event_loop",
                input_keys=["text"],
                output_keys=["score", "label"],
                system_prompt=(
                    "You are a sentiment classifier. Read the 'text' input and determine "
                    "if the sentiment is positive or negative.\n\n"
                    "You MUST call set_output TWICE:\n"
                    "1. set_output(key='score', value='<number>') — a score between 0.0 "
                    "and 1.0 where >0.5 means positive\n"
                    "2. set_output(key='label', value='positive') or "
                    "set_output(key='label', value='negative')\n\n" + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="positive",
                name="Positive Handler",
                description="Handles positive sentiment",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "The input was classified as positive. Call set_output with "
                    "key='result' and a brief one-sentence acknowledgment. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="negative",
                name="Negative Handler",
                description="Handles negative sentiment",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "The input was classified as negative. Call set_output with "
                    "key='result' and a brief one-sentence acknowledgment. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="classify-to-positive",
                source="classify",
                target="positive",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('label') == 'positive'",
                priority=1,
            ),
            EdgeSpec(
                id="classify-to-negative",
                source="classify",
                target="negative",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('label') == 'negative'",
                priority=0,
            ),
        ],
        memory_keys=["text", "score", "label", "result"],
    )


@pytest.mark.asyncio
async def test_branch_positive_path(runtime, goal, llm_provider):
    graph = _build_branch_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(
        graph, goal, {"text": "I love this product, it's amazing!"}, validate_graph=False
    )

    assert result.success
    assert result.path == ["classify", "positive"]


@pytest.mark.asyncio
async def test_branch_negative_path(runtime, goal, llm_provider):
    graph = _build_branch_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(
        graph, goal, {"text": "This is terrible and broken, I hate it."}, validate_graph=False
    )

    assert result.success
    assert result.path == ["classify", "negative"]


@pytest.mark.asyncio
async def test_branch_two_nodes_traversed(runtime, goal, llm_provider):
    """Regardless of which branch, exactly 2 nodes should execute."""
    graph = _build_branch_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(
        graph, goal, {"text": "The weather is nice today."}, validate_graph=False
    )

    assert result.success
    assert result.steps_executed == 2
    assert len(result.path) == 2
