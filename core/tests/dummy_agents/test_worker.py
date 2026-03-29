"""Worker agent: single-node event loop with real MCP tools.

Tests the core worker pattern — a single EventLoopNode that uses real
hive-tools (example_tool, get_current_time, save_data/load_data) to
accomplish tasks, matching how real agents are structured.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec

from .conftest import make_executor


def _build_worker_graph(tools: list[str]) -> GraphSpec:
    """Single-node worker agent with MCP tools — matches real agent structure."""
    return GraphSpec(
        id="worker-graph",
        goal_id="worker-goal",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="General-purpose worker with tools",
                node_type="event_loop",
                input_keys=["task"],
                output_keys=["result"],
                tools=tools,
                system_prompt=(
                    "You are a worker agent with access to tools. "
                    "Read the 'task' input and complete it using the available tools. "
                    "When done, call set_output with key='result' and the final answer."
                ),
            ),
        ],
        edges=[],
        memory_keys=["task", "result"],
        conversation_mode="continuous",
    )


def _worker_goal() -> Goal:
    return Goal(
        id="worker-goal",
        name="Worker Agent",
        description="Complete a task using available tools",
    )


@pytest.mark.asyncio
async def test_worker_example_tool(runtime, llm_provider, tool_registry):
    """Worker uses example_tool to process text."""
    graph = _build_worker_graph(tools=["example_tool"])
    executor = make_executor(runtime, llm_provider, tool_registry=tool_registry)

    result = await executor.execute(
        graph,
        _worker_goal(),
        {"task": "Use the example_tool to process the message 'hello world' with uppercase=true"},
        validate_graph=False,
    )

    assert result.success
    assert result.output.get("result") is not None


@pytest.mark.asyncio
async def test_worker_time_tool(runtime, llm_provider, tool_registry):
    """Worker uses get_current_time to check the current time."""
    graph = _build_worker_graph(tools=["get_current_time"])
    executor = make_executor(runtime, llm_provider, tool_registry=tool_registry)

    result = await executor.execute(
        graph,
        _worker_goal(),
        {
            "task": "Use get_current_time to find the current time in UTC, "
            "and report the day of the week as the result"
        },
        validate_graph=False,
    )

    assert result.success
    assert result.output.get("result") is not None


@pytest.mark.asyncio
async def test_worker_data_tools(runtime, llm_provider, tool_registry, tmp_path):
    """Worker uses save_data and load_data to store and retrieve data."""
    graph = _build_worker_graph(tools=["save_data", "load_data"])
    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        storage_path=tmp_path / "storage",
    )

    result = await executor.execute(
        graph,
        _worker_goal(),
        {
            "task": f"Use save_data to save the text 'test payload' to a file called "
            f"'test.txt' in the data_dir '{tmp_path}/data'. "
            f"Then use load_data to read it back from the same data_dir. "
            f"Report what you loaded as the result."
        },
        validate_graph=False,
    )

    assert result.success
    assert result.output.get("result") is not None


@pytest.mark.asyncio
async def test_worker_multi_tool(runtime, llm_provider, tool_registry):
    """Worker uses multiple tools in sequence."""
    graph = _build_worker_graph(tools=["example_tool", "get_current_time"])
    executor = make_executor(runtime, llm_provider, tool_registry=tool_registry)

    result = await executor.execute(
        graph,
        _worker_goal(),
        {
            "task": "First use get_current_time to find the current day of the week. "
            "Then use example_tool to process that day name with uppercase=true. "
            "Report the uppercased day name as the result."
        },
        validate_graph=False,
    )

    assert result.success
    assert result.output.get("result") is not None
