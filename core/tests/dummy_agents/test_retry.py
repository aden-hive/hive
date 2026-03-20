"""Retry agent: flaky node with retry limit and failure edges.

Uses deterministic FlakyNode (not LLM) since we need controlled failure patterns.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor
from .nodes import FlakyNode, SuccessNode


def _build_retry_graph(max_retries: int = 3, with_failure_edge: bool = False) -> GraphSpec:
    nodes = [
        NodeSpec(
            id="flaky",
            name="Flaky",
            description="Fails then succeeds",
            node_type="event_loop",
            output_keys=["status"],
            max_retries=max_retries,
        ),
        NodeSpec(
            id="done",
            name="Done",
            description="Terminal success node",
            node_type="event_loop",
            output_keys=["final"],
        ),
    ]
    edges = [
        EdgeSpec(
            id="flaky-to-done",
            source="flaky",
            target="done",
            condition=EdgeCondition.ON_SUCCESS,
        ),
    ]
    terminal_nodes = ["done"]

    if with_failure_edge:
        nodes.append(
            NodeSpec(
                id="error_handler",
                name="Error Handler",
                description="Handles exhausted retries",
                node_type="event_loop",
                output_keys=["error_handled"],
            )
        )
        edges.append(
            EdgeSpec(
                id="flaky-to-error",
                source="flaky",
                target="error_handler",
                condition=EdgeCondition.ON_FAILURE,
            )
        )
        terminal_nodes.append("error_handler")

    return GraphSpec(
        id="retry-graph",
        goal_id="dummy",
        entry_node="flaky",
        terminal_nodes=terminal_nodes,
        nodes=nodes,
        edges=edges,
        memory_keys=["status", "final", "error_handled"],
    )


@pytest.mark.asyncio
async def test_retry_succeeds_within_limit(runtime, goal, llm_provider):
    graph = _build_retry_graph(max_retries=3)
    flaky = FlakyNode(fail_times=2, output={"status": "recovered"})
    executor = make_executor(runtime, llm_provider)
    executor.register_node("flaky", flaky)
    executor.register_node("done", SuccessNode(output={"final": "complete"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.total_retries >= 2
    assert flaky.attempt_count == 3  # 2 failures + 1 success


@pytest.mark.asyncio
async def test_retry_exhaustion(runtime, goal, llm_provider):
    graph = _build_retry_graph(max_retries=3)
    flaky = FlakyNode(fail_times=10, output={"status": "recovered"})
    executor = make_executor(runtime, llm_provider)
    executor.register_node("flaky", flaky)
    executor.register_node("done", SuccessNode(output={"final": "complete"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert not result.success


@pytest.mark.asyncio
async def test_retry_with_on_failure_edge(runtime, goal, llm_provider):
    graph = _build_retry_graph(max_retries=2, with_failure_edge=True)
    flaky = FlakyNode(fail_times=10)
    error_handler = SuccessNode(output={"error_handled": True})
    executor = make_executor(runtime, llm_provider)
    executor.register_node("flaky", flaky)
    executor.register_node("done", SuccessNode(output={"final": "complete"}))
    executor.register_node("error_handler", error_handler)

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert "error_handler" in result.path
    assert error_handler.executed


@pytest.mark.asyncio
async def test_retry_tracking(runtime, goal, llm_provider):
    graph = _build_retry_graph(max_retries=3)
    flaky = FlakyNode(fail_times=2)
    executor = make_executor(runtime, llm_provider)
    executor.register_node("flaky", flaky)
    executor.register_node("done", SuccessNode(output={"final": "complete"}))

    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.retry_details.get("flaky", 0) >= 2
