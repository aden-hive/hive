"""Echo agent: single-node worker that echoes input to output.

Tests basic node lifecycle with a real LLM call — simplest possible worker.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor


def _build_echo_graph() -> GraphSpec:
    return GraphSpec(
        id="echo-graph",
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
                    "You are an echo node. Your ONLY job is to read the 'input' value "
                    "provided in the user message, then immediately call the set_output "
                    "tool with key='output' and value set to the EXACT same string. "
                    "Do not add any text or explanation. Just call set_output."
                ),
            ),
        ],
        edges=[],
        memory_keys=["input", "output"],
        conversation_mode="continuous",
    )


@pytest.mark.asyncio
async def test_echo_basic(runtime, goal, llm_provider):
    graph = _build_echo_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(graph, goal, {"input": "hello"}, validate_graph=False)

    assert result.success
    assert result.output.get("output") is not None
    assert result.path == ["echo"]
    assert result.steps_executed == 1


@pytest.mark.asyncio
async def test_echo_empty_input(runtime, goal, llm_provider):
    graph = _build_echo_graph()
    executor = make_executor(runtime, llm_provider)

    result = await executor.execute(graph, goal, {"input": ""}, validate_graph=False)

    assert result.success
    assert "output" in result.output
