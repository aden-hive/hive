"""Component tests: EventLoopNode — iteration limits, output accumulation, stall safety.

Exercises the core multi-turn LLM loop through single-node graphs with
real LLM calls to verify iteration control and termination behavior.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.node import NodeSpec

from .conftest import make_executor


@pytest.mark.asyncio
async def test_event_loop_single_turn_set_output(runtime, goal, llm_provider):
    """LLM calls set_output on first turn — node should terminate with output."""
    graph = GraphSpec(
        id="single-turn",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Immediately set output",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "Call set_output with key='result' and value='done'. "
                    "Do not write any text. Just call the tool."
                ),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.output.get("result") is not None
    assert result.steps_executed == 1


@pytest.mark.asyncio
async def test_event_loop_multi_turn_tool_use(
    runtime, goal, llm_provider, tool_registry
):
    """LLM calls a tool, gets result, then calls set_output — multi-turn flow."""
    graph = GraphSpec(
        id="multi-turn",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Use a tool then set output",
                node_type="event_loop",
                output_keys=["result"],
                tools=["get_current_time"],
                system_prompt=(
                    "First call get_current_time with timezone='UTC'. "
                    "Then call set_output with key='result' and the day_of_week "
                    "from the tool response."
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
    )
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.output.get("result") is not None


@pytest.mark.asyncio
async def test_event_loop_max_iterations_respected(runtime, goal, llm_provider):
    """Node must terminate after max_iterations even without set_output."""
    graph = GraphSpec(
        id="stuck-node",
        goal_id="dummy",
        entry_node="stuck",
        entry_points={"start": "stuck"},
        terminal_nodes=["stuck"],
        nodes=[
            NodeSpec(
                id="stuck",
                name="Stuck",
                description="Never sets output",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "You are thinking deeply. Respond with a short thought. "
                    "Never call set_output."
                ),
                max_tokens=32,
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 3})
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    # Should terminate (not hang) — the node was visited
    assert result.steps_executed == 1


@pytest.mark.asyncio
async def test_event_loop_multiple_output_keys(runtime, goal, llm_provider):
    """LLM should be able to set multiple output keys in a single node."""
    graph = GraphSpec(
        id="multi-output",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Set two output keys",
                node_type="event_loop",
                output_keys=["name", "greeting"],
                system_prompt=(
                    "Call set_output twice: "
                    "first with key='name' and value='Alice', "
                    "then with key='greeting' and value='Hello Alice'. "
                    "Do not write any text."
                ),
            ),
        ],
        edges=[],
        memory_keys=["name", "greeting"],
        conversation_mode="continuous",
    )
    executor = make_executor(runtime, llm_provider, loop_config={"max_iterations": 5})
    result = await executor.execute(graph, goal, {}, validate_graph=False)

    assert result.success
    assert result.output.get("name") is not None
    assert result.output.get("greeting") is not None
