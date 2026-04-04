"""Worker agent: single-node event loop with real MCP tools.

Tests the core worker pattern — a single EventLoopNode that uses real
hive-tools (example_tool, get_current_time, save_data/load_data) to
accomplish tasks, matching how real agents are structured.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
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


def _build_timestamped_note_graph() -> GraphSpec:
    """Two-node worker graph that creates and verifies a real file artifact."""
    return GraphSpec(
        id="timestamped-note-graph",
        goal_id="worker-goal",
        entry_node="collect_note",
        entry_points={"start": "collect_note"},
        terminal_nodes=["verify_note"],
        nodes=[
            NodeSpec(
                id="collect_note",
                name="Collect Note",
                description="Create a timestamped status note and save it",
                node_type="event_loop",
                input_keys=["data_dir"],
                output_keys=["filename", "expected_text"],
                tools=["get_current_time", "save_data"],
                system_prompt=(
                    "You are creating a small status note artifact. "
                    "First call get_current_time with timezone='UTC'. "
                    "Then build EXACTLY this one-line note format: "
                    "'STATUS|<date>|<day_of_week>|build green'. "
                    "Use the date and day_of_week values returned by the tool. "
                    "Next call save_data with filename='status.txt', the exact note text as data, "
                    "and the provided input key 'data_dir'. "
                    "After saving succeeds, call set_output twice: "
                    "set_output(key='filename', value='status.txt') and "
                    "set_output(key='expected_text', value=<the exact note text>). "
                    "Do not add extra punctuation, quotes, or explanation."
                ),
            ),
            NodeSpec(
                id="verify_note",
                name="Verify Note",
                description="Load the saved note and verify exact content",
                node_type="event_loop",
                input_keys=["data_dir", "filename", "expected_text"],
                output_keys=["result"],
                tools=["load_data"],
                system_prompt=(
                    "You are verifying a saved status note. "
                    "Use load_data with the provided 'filename' and 'data_dir'. "
                    "Compare the loaded content to the provided 'expected_text'. "
                    "If they match exactly, call set_output(key='result', value=<loaded content>). "
                    "If they do not match exactly, call set_output with a value that starts with "
                    "'MISMATCH|'. Do not add any other explanation."
                ),
            ),
        ],
        edges=[
            EdgeSpec(
                id="collect-to-verify",
                source="collect_note",
                target="verify_note",
                condition=EdgeCondition.ON_SUCCESS,
                input_mapping={
                    "filename": "filename",
                    "expected_text": "expected_text",
                },
            ),
        ],
        memory_keys=["data_dir", "filename", "expected_text", "result"],
        conversation_mode="continuous",
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


@pytest.mark.asyncio
async def test_worker_timestamped_note_artifact(runtime, llm_provider, tool_registry, tmp_path):
    """Worker graph creates a timestamped file artifact and verifies it exactly."""
    graph = _build_timestamped_note_graph()
    executor = make_executor(runtime, llm_provider, tool_registry=tool_registry)
    data_dir = tmp_path / "data"

    result = await executor.execute(
        graph,
        _worker_goal(),
        {"data_dir": str(data_dir)},
        validate_graph=False,
    )

    assert result.success
    assert result.path == ["collect_note", "verify_note"]

    output = result.output.get("result")
    assert output is not None
    assert not output.startswith("MISMATCH|")

    parts = output.split("|")
    assert len(parts) == 4
    assert parts[0] == "STATUS"
    assert parts[3] == "build green"

    artifact_path = data_dir / "status.txt"
    assert artifact_path.exists()
    assert artifact_path.read_text(encoding="utf-8") == output
