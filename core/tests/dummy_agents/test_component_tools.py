"""Component tests: Tool Registry + MCP — connection, discovery, execution.

Exercises the ToolRegistry and MCP server independently from the graph
executor to isolate tool-layer issues from LLM/node logic.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.node import NodeSpec
from framework.llm.provider import ToolUse

from .conftest import make_executor


def test_tools_mcp_server_connects(tool_registry):
    """MCP server should start and expose tools."""
    tools = tool_registry.get_tools()
    assert len(tools) > 0, "MCP server should expose at least one tool"


def test_tools_registry_has_expected_tools(tool_registry):
    """hive-tools should expose the expected tool names."""
    tool_names = set(tool_registry.get_tools().keys())
    expected = {"example_tool", "get_current_time"}
    assert expected.issubset(tool_names), (
        f"Missing expected tools: {expected - tool_names}"
    )


@pytest.mark.asyncio
async def test_tools_execute_example_tool(tool_registry):
    """Direct tool execution without LLM — verifies MCP round-trip."""
    executor = tool_registry.get_executor()
    tool_use = ToolUse(id="test-1", name="example_tool", input={"message": "hello", "uppercase": True})
    result = executor(tool_use)
    assert not result.is_error
    assert "HELLO" in result.content


@pytest.mark.asyncio
async def test_tools_execute_get_current_time(tool_registry):
    """get_current_time should return a dict with date/time fields."""
    executor = tool_registry.get_executor()
    tool_use = ToolUse(id="test-2", name="get_current_time", input={"timezone": "UTC"})
    result = executor(tool_use)
    assert not result.is_error
    # Should contain date-like content
    assert "202" in result.content, "Should contain a year (202x)"


@pytest.mark.asyncio
async def test_tools_llm_calls_tool_and_gets_result(
    runtime, llm_provider, tool_registry, goal
):
    """Full round-trip: LLM calls a real tool and uses the result to set output."""
    graph = GraphSpec(
        id="tool-roundtrip",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Call example_tool and report result",
                node_type="event_loop",
                input_keys=["task"],
                output_keys=["result"],
                tools=["example_tool"],
                system_prompt=(
                    "Use the example_tool to process the message from the task input "
                    "with uppercase=true. Then call set_output with key='result' and "
                    "the tool's return value."
                ),
            ),
        ],
        edges=[],
        memory_keys=["task", "result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime, llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
    )
    result = await executor.execute(
        graph, goal, {"task": "Process the word 'hello'"}, validate_graph=False
    )
    assert result.success
    assert result.output.get("result") is not None
