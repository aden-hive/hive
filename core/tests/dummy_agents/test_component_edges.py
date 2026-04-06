"""Component tests: Edge Evaluation — conditional routing, LLM_DECIDE.

Exercises edge conditions with real LLM calls to verify that routing
decisions work correctly across providers.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor

SET_OUTPUT_INSTRUCTION = (
    "You MUST call the set_output tool to provide your answer. "
    "Do not just write text — call set_output with the correct "
    "key and value."
)


@pytest.mark.asyncio
async def test_edge_conditional_true_path(runtime, goal, llm_provider, artifact):
    """Conditional edge with True expression should be traversed."""
    graph = GraphSpec(
        id="cond-true",
        goal_id="dummy",
        entry_node="source",
        entry_points={"start": "source"},
        terminal_nodes=["target"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="source",
                name="Source",
                description="Produces label=yes",
                node_type="event_loop",
                output_keys=["label"],
                system_prompt=(
                    "Call set_output with key='label' and value='yes'. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="target",
                name="Target",
                description="Terminal node",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "Call set_output with key='result' and "
                    "value='reached'. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="source-to-target",
                source="source",
                target="target",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('label') == 'yes'",
            ),
        ],
        memory_keys=["label", "result"],
    )
    executor = make_executor(
        runtime,
        llm_provider,
        loop_config={"max_iterations": 3},
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected="success=True, path=['source','target']",
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
        result.path == ["source", "target"],
        actual=str(result.path),
        expected_val="['source', 'target']",
    )
    assert result.path == ["source", "target"]


@pytest.mark.asyncio
async def test_edge_conditional_false_path(runtime, goal, llm_provider, artifact):
    """Conditional edge with False expression should NOT be traversed."""
    graph = GraphSpec(
        id="cond-false",
        goal_id="dummy",
        entry_node="source",
        entry_points={"start": "source"},
        terminal_nodes=["source", "target"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="source",
                name="Source",
                description="Produces label=no",
                node_type="event_loop",
                output_keys=["label"],
                system_prompt=(
                    "Call set_output with key='label' and value='no'. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="target",
                name="Target",
                description="Should not be reached",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=("Call set_output with key='result' and value='bad'."),
            ),
        ],
        edges=[
            EdgeSpec(
                id="source-to-target",
                source="source",
                target="target",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('label') == 'yes'",
            ),
        ],
        memory_keys=["label", "result"],
    )
    executor = make_executor(
        runtime,
        llm_provider,
        loop_config={"max_iterations": 3},
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected="success=True, 'target' not in path",
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    artifact.check(
        "target not in path",
        "target" not in result.path,
        actual=str(result.path),
        expected_val="path without 'target'",
    )
    assert "target" not in result.path


@pytest.mark.asyncio
async def test_edge_priority_selects_higher(runtime, goal, llm_provider, artifact):
    """When multiple conditional edges match, higher priority wins."""
    graph = GraphSpec(
        id="priority-test",
        goal_id="dummy",
        entry_node="source",
        entry_points={"start": "source"},
        terminal_nodes=["high", "low"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="source",
                name="Source",
                description="Sets value=match",
                node_type="event_loop",
                output_keys=["value"],
                system_prompt=(
                    "Call set_output with key='value' and value='match'. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="high",
                name="High Priority",
                description="High priority terminal",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "Call set_output with key='result' and value='HIGH'. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="low",
                name="Low Priority",
                description="Low priority terminal",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "Call set_output with key='result' and value='LOW'. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="to-high",
                source="source",
                target="high",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('value') == 'match'",
                priority=10,
            ),
            EdgeSpec(
                id="to-low",
                source="source",
                target="low",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('value') == 'match'",
                priority=1,
            ),
        ],
        memory_keys=["value", "result"],
    )
    executor = make_executor(
        runtime,
        llm_provider,
        loop_config={"max_iterations": 3},
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected="success=True, path=['source','high']",
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
        result.path == ["source", "high"],
        actual=str(result.path),
        expected_val="['source', 'high']",
    )
    assert result.path == ["source", "high"]
