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


def test_tools_mcp_server_connects(tool_registry, artifact):
    """MCP server should start and expose tools."""
    tools = tool_registry.get_tools()

    artifact.record_value(
        "tool_count",
        len(tools),
        expected="at least 1 tool exposed by MCP server",
    )
    artifact.record_value("tool_names", list(tools.keys()))

    artifact.check(
        "MCP server exposes tools",
        len(tools) > 0,
        actual=str(len(tools)),
        expected_val=">0",
    )
    assert len(tools) > 0, "MCP server should expose at least one tool"


def test_tools_registry_has_expected_tools(tool_registry, artifact):
    """hive-tools should expose the expected tool names."""
    tool_names = set(tool_registry.get_tools().keys())
    expected = {"example_tool", "get_current_time"}

    artifact.record_value(
        "tool_names",
        sorted(tool_names),
        expected="superset of {example_tool, get_current_time}",
    )
    artifact.record_value("expected_tools", sorted(expected))

    missing = expected - tool_names
    artifact.check(
        "expected tools present",
        expected.issubset(tool_names),
        actual=str(sorted(tool_names)),
        expected_val=f"superset of {sorted(expected)}",
    )
    assert expected.issubset(tool_names), f"Missing expected tools: {expected - tool_names}"


@pytest.mark.asyncio
async def test_tools_execute_example_tool(tool_registry, artifact):
    """Direct tool execution without LLM — verifies MCP round-trip."""
    executor = tool_registry.get_executor()
    tool_use = ToolUse(
        id="test-1",
        name="example_tool",
        input={"message": "hello", "uppercase": True},
    )
    result = executor(tool_use)

    artifact.record_value(
        "is_error",
        result.is_error,
        expected="not an error, content contains 'HELLO'",
    )
    artifact.record_value("content", result.content)

    artifact.check(
        "result is not error",
        not result.is_error,
        actual=str(result.is_error),
        expected_val="False",
    )
    assert not result.is_error

    artifact.check(
        "content contains HELLO",
        "HELLO" in result.content,
        actual=repr(result.content),
        expected_val="contains 'HELLO'",
    )
    assert "HELLO" in result.content


@pytest.mark.asyncio
async def test_tools_execute_get_current_time(tool_registry, artifact):
    """get_current_time should return a dict with date/time fields."""
    executor = tool_registry.get_executor()
    tool_use = ToolUse(
        id="test-2",
        name="get_current_time",
        input={"timezone": "UTC"},
    )
    result = executor(tool_use)

    artifact.record_value(
        "is_error",
        result.is_error,
        expected="not an error, content contains year (202x)",
    )
    artifact.record_value("content", result.content)

    artifact.check(
        "result is not error",
        not result.is_error,
        actual=str(result.is_error),
        expected_val="False",
    )
    assert not result.is_error

    artifact.check(
        "content contains year",
        "202" in result.content,
        actual=repr(result.content),
        expected_val="contains '202'",
    )
    # Should contain date-like content
    assert "202" in result.content, "Should contain a year (202x)"


@pytest.mark.asyncio
async def test_tools_llm_calls_tool_and_gets_result(
    runtime, llm_provider, tool_registry, goal, artifact
):
    """Full round-trip: LLM calls a tool and uses the result."""
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
                    "Use the example_tool to process the message "
                    "from the task input with uppercase=true. Then "
                    "call set_output with key='result' and "
                    "the tool's return value."
                ),
            ),
        ],
        edges=[],
        memory_keys=["task", "result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime,
        llm_provider,
        tool_registry=tool_registry,
        loop_config={"max_iterations": 5},
    )
    result = await executor.execute(
        graph,
        goal,
        {"task": "Process the word 'hello'"},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected="success=True, output['result'] is set",
    )

    artifact.check(
        "execution succeeds",
        result.success,
        actual=str(result.success),
        expected_val="True",
    )
    assert result.success

    actual_output = result.output.get("result")
    artifact.check(
        "output['result'] is set",
        actual_output is not None,
        actual=repr(actual_output),
        expected_val="non-None value",
    )
    assert result.output.get("result") is not None
