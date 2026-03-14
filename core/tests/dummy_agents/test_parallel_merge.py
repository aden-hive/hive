"""Parallel merge agent: fan-out to two branches, fan-in to merge node.

Tests parallel execution with real LLM at each branch.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import ParallelExecutionConfig
from framework.graph.node import NodeSpec

from .conftest import make_executor
from .nodes import FailNode

SET_OUTPUT_INSTRUCTION = (
    "You MUST call the set_output tool to provide your answer. "
    "Do not just write text — call set_output with the correct key and value."
)


def _build_parallel_graph() -> GraphSpec:
    return GraphSpec(
        id="parallel-graph",
        goal_id="dummy",
        entry_node="split",
        entry_points={"start": "split"},
        terminal_nodes=["merge"],
        conversation_mode="continuous",
        nodes=[
            NodeSpec(
                id="split",
                name="Split",
                description="Entry point that triggers parallel branches",
                node_type="event_loop",
                input_keys=["topic"],
                output_keys=["split_done"],
                system_prompt=(
                    "You are a dispatcher. Read the 'topic' input, then immediately "
                    "call set_output with key='split_done' and value='true'. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="analyze_a",
                name="Analyze Pros",
                description="Analyzes positive aspects",
                node_type="event_loop",
                output_keys=["result_a"],
                system_prompt=(
                    "Analyze the positive aspects of the topic. Then call set_output "
                    "with key='result_a' and a brief one-sentence analysis. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="analyze_b",
                name="Analyze Cons",
                description="Analyzes negative aspects",
                node_type="event_loop",
                output_keys=["result_b"],
                system_prompt=(
                    "Analyze the negative aspects of the topic. Then call set_output "
                    "with key='result_b' and a brief one-sentence analysis. "
                    + SET_OUTPUT_INSTRUCTION
                ),
            ),
            NodeSpec(
                id="merge",
                name="Merge",
                description="Combines both analyses",
                node_type="event_loop",
                input_keys=["result_a", "result_b"],
                output_keys=["merged"],
                system_prompt=(
                    "Read 'result_a' and 'result_b' from the input, combine them into "
                    "a one-sentence summary, then call set_output with key='merged' "
                    "and the summary. " + SET_OUTPUT_INSTRUCTION
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="split-to-a",
                source="split",
                target="analyze_a",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="split-to-b",
                source="split",
                target="analyze_b",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="a-to-merge",
                source="analyze_a",
                target="merge",
                condition=EdgeCondition.ON_SUCCESS,
            ),
            EdgeSpec(
                id="b-to-merge",
                source="analyze_b",
                target="merge",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        memory_keys=["topic", "split_done", "result_a", "result_b", "merged"],
    )


@pytest.mark.asyncio
async def test_parallel_both_succeed(runtime, goal, llm_provider):
    graph = _build_parallel_graph()
    config = ParallelExecutionConfig(on_branch_failure="fail_all")
    executor = make_executor(runtime, llm_provider, parallel_config=config)

    result = await executor.execute(graph, goal, {"topic": "remote work"}, validate_graph=False)

    assert result.success
    assert "split" in result.path
    assert "merge" in result.path
    assert result.output.get("merged") is not None


@pytest.mark.asyncio
async def test_parallel_branch_failure_fail_all(runtime, goal, llm_provider):
    """One branch fails with fail_all -> execution fails."""
    graph = _build_parallel_graph()
    config = ParallelExecutionConfig(on_branch_failure="fail_all")
    executor = make_executor(runtime, llm_provider, parallel_config=config)
    executor.register_node("analyze_b", FailNode(error="branch B failed"))

    result = await executor.execute(graph, goal, {"topic": "remote work"}, validate_graph=False)

    assert not result.success


@pytest.mark.asyncio
async def test_parallel_branch_failure_continue_others(runtime, goal, llm_provider):
    """One branch fails with continue_others -> surviving branch completes."""
    graph = _build_parallel_graph()
    config = ParallelExecutionConfig(on_branch_failure="continue_others")
    executor = make_executor(runtime, llm_provider, parallel_config=config)
    executor.register_node("analyze_b", FailNode(error="branch B failed"))

    result = await executor.execute(graph, goal, {"topic": "remote work"}, validate_graph=False)

    # With continue_others, execution can proceed past failed branches
    assert result.output.get("merged") is not None or result.output.get("result_a") is not None


@pytest.mark.asyncio
async def test_parallel_disjoint_output_keys(runtime, goal, llm_provider):
    """Verify both branches write to separate memory keys without conflicts."""
    graph = _build_parallel_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(
        graph, goal, {"topic": "artificial intelligence"}, validate_graph=False
    )

    assert result.success
    assert result.output.get("result_a") is not None
    assert result.output.get("result_b") is not None
