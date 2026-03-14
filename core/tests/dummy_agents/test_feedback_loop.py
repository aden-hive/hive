"""Feedback loop agent: draft/review cycle with max_node_visits limit.

Uses StatefulNode for review to control loop iterations deterministically.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeResult, NodeSpec

from .conftest import make_executor
from .nodes import StatefulNode, SuccessNode


def _build_feedback_graph(max_visits: int = 3) -> GraphSpec:
    return GraphSpec(
        id="feedback-graph",
        goal_id="dummy",
        entry_node="draft",
        terminal_nodes=["done"],
        nodes=[
            NodeSpec(
                id="draft",
                name="Draft",
                description="Produces a draft",
                node_type="event_loop",
                output_keys=["draft_output"],
                max_node_visits=max_visits,
            ),
            NodeSpec(
                id="review",
                name="Review",
                description="Reviews the draft",
                node_type="event_loop",
                input_keys=["draft_output"],
                output_keys=["approved"],
            ),
            NodeSpec(
                id="done",
                name="Done",
                description="Final node",
                node_type="event_loop",
                output_keys=["final"],
            ),
        ],
        edges=[
            EdgeSpec(
                id="draft-to-review",
                source="draft",
                target="review",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="review-to-draft",
                source="review",
                target="draft",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('approved') == False",
                priority=1,
            ),
            EdgeSpec(
                id="review-to-done",
                source="review",
                target="done",
                condition=EdgeCondition.CONDITIONAL,
                condition_expr="output.get('approved') == True",
                priority=0,
            ),
        ],
        memory_keys=["draft_output", "approved", "final"],
    )


@pytest.mark.asyncio
async def test_feedback_loop_terminates(runtime, goal, llm_provider):
    """Loop should terminate: draft visits are capped, review eventually approves."""
    graph = _build_feedback_graph(max_visits=3)
    executor = make_executor(runtime, llm_provider)
    executor.register_node("draft", SuccessNode(output={"draft_output": "v1"}))
    executor.register_node(
        "review",
        StatefulNode(
            [
                NodeResult(success=True, output={"approved": False}),
                NodeResult(success=True, output={"approved": False}),
                NodeResult(success=True, output={"approved": True}),
            ]
        ),
    )
    executor.register_node("done", SuccessNode(output={"final": "done"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.node_visit_counts.get("draft", 0) == 3
    assert "done" in result.path


@pytest.mark.asyncio
async def test_feedback_loop_visit_counts(runtime, goal, llm_provider):
    graph = _build_feedback_graph(max_visits=3)
    executor = make_executor(runtime, llm_provider)
    executor.register_node("draft", SuccessNode(output={"draft_output": "v1"}))
    executor.register_node(
        "review",
        StatefulNode(
            [
                NodeResult(success=True, output={"approved": False}),
                NodeResult(success=True, output={"approved": True}),
            ]
        ),
    )
    executor.register_node("done", SuccessNode(output={"final": "done"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.node_visit_counts.get("draft", 0) == 2
    assert result.node_visit_counts.get("review", 0) == 2


@pytest.mark.asyncio
async def test_feedback_loop_early_exit(runtime, goal, llm_provider):
    """Review approves on first iteration — loop exits before max."""
    graph = _build_feedback_graph(max_visits=5)
    executor = make_executor(runtime, llm_provider)
    executor.register_node("draft", SuccessNode(output={"draft_output": "perfect"}))
    executor.register_node(
        "review",
        StatefulNode(
            [
                NodeResult(success=True, output={"approved": True}),
            ]
        ),
    )
    executor.register_node("done", SuccessNode(output={"final": "done"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.node_visit_counts.get("draft", 0) == 1
    assert "done" in result.path
