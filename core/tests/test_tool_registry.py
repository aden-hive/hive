"""Tests for ToolRegistry JSON handling when tools return invalid JSON.

These tests exercise the discover_from_module() path, where tools are
registered via a TOOLS dict and a unified tool_executor that returns
ToolResult instances. Historically, invalid JSON in ToolResult.content
could cause a json.JSONDecodeError and crash execution.
"""

import logging
import textwrap
from pathlib import Path

from framework.llm.provider import Tool, ToolUse
from framework.runner.tool_registry import ToolRegistry


def _write_tool_module(tmp_path: Path, content: str) -> Path:
    """Helper to write a temporary tools module."""
    module_path = tmp_path / "agent_tools.py"
    module_path.write_text(textwrap.dedent(content))
    return module_path


def test_discover_from_module_handles_invalid_json(tmp_path):
    """ToolRegistry should not crash when tool_executor returns invalid JSON."""
    module_src = """
        from framework.llm.provider import Tool, ToolUse, ToolResult

        TOOLS = {
            "bad_tool": Tool(
                name="bad_tool",
                description="Returns malformed JSON",
                parameters={"type": "object", "properties": {}},
            ),
        }

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            # Intentionally malformed JSON
            return ToolResult(
                tool_use_id=tool_use.id,
                content="not {valid json",
                is_error=False,
            )
    """
    module_path = _write_tool_module(tmp_path, module_src)

    registry = ToolRegistry()
    count = registry.discover_from_module(module_path)
    assert count == 1

    # Access the registered executor for "bad_tool"
    assert "bad_tool" in registry._tools  # noqa: SLF001 - testing internal registry
    registered = registry._tools["bad_tool"]

    # Should not raise, and should return a structured error dict
    result = registered.executor({})
    assert isinstance(result, dict)
    assert "error" in result
    assert "raw_content" in result
    assert result["raw_content"] == "not {valid json"


def test_discover_from_module_handles_empty_content(tmp_path):
    """ToolRegistry should handle empty ToolResult.content gracefully."""
    module_src = """
        from framework.llm.provider import Tool, ToolUse, ToolResult

        TOOLS = {
            "empty_tool": Tool(
                name="empty_tool",
                description="Returns empty content",
                parameters={"type": "object", "properties": {}},
            ),
        }

        def tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="",
                is_error=False,
            )
    """
    module_path = _write_tool_module(tmp_path, module_src)

    registry = ToolRegistry()
    count = registry.discover_from_module(module_path)
    assert count == 1

    assert "empty_tool" in registry._tools  # noqa: SLF001 - testing internal registry
    registered = registry._tools["empty_tool"]

    # Empty content should return an empty dict rather than crashing
    result = registered.executor({})
    assert isinstance(result, dict)
    assert result == {}


def test_tool_execution_error_logs_stack_trace_and_context(caplog):
    """ToolRegistry should log stack traces and context when tool execution fails."""
    registry = ToolRegistry()

    def failing_executor(inputs: dict) -> None:
        raise ValueError("Intentional test failure")

    tool = Tool(
        name="failing_tool",
        description="A tool that always fails",
        parameters={"type": "object", "properties": {}},
    )
    registry.register("failing_tool", tool, failing_executor)

    tool_use = ToolUse(
        id="test_call_123",
        name="failing_tool",
        input={"param": "value"},
    )

    with caplog.at_level(logging.ERROR):
        executor = registry.get_executor()
        result = executor(tool_use)

    assert result.is_error is True
    assert "Intentional test failure" in result.content

    assert any("failing_tool" in record.message for record in caplog.records)
    assert any("test_call_123" in record.message for record in caplog.records)
    assert any(record.exc_info is not None for record in caplog.records)


def test_tool_execution_error_logs_inputs(caplog):
    """ToolRegistry should log tool inputs when execution fails."""
    registry = ToolRegistry()

    def failing_executor(inputs: dict) -> None:
        raise RuntimeError("Tool failed")

    tool = Tool(
        name="input_logging_tool",
        description="Tests input logging",
        parameters={"type": "object", "properties": {"foo": {"type": "string"}}},
    )
    registry.register("input_logging_tool", tool, failing_executor)

    tool_use = ToolUse(
        id="call_456",
        name="input_logging_tool",
        input={"foo": "bar", "nested": {"key": "value"}},
    )

    with caplog.at_level(logging.ERROR):
        executor = registry.get_executor()
        executor(tool_use)

    log_messages = [record.message for record in caplog.records]
    full_log = " ".join(log_messages)
    assert '"foo": "bar"' in full_log or "'foo': 'bar'" in full_log


def test_unknown_tool_error_returns_proper_result():
    """ToolRegistry should return proper error for unknown tools."""
    registry = ToolRegistry()
    tool_use = ToolUse(
        id="unknown_call",
        name="nonexistent_tool",
        input={},
    )

    executor = registry.get_executor()
    result = executor(tool_use)

    assert result.is_error is True
    assert "Unknown tool" in result.content
    assert "nonexistent_tool" in result.content


def test_tool_execution_error_truncates_large_inputs(caplog):
    """ToolRegistry should truncate large inputs in error logs."""
    registry = ToolRegistry()

    def failing_executor(inputs: dict) -> None:
        raise RuntimeError("Tool failed")

    tool = Tool(
        name="large_input_tool",
        description="Tests input truncation",
        parameters={"type": "object", "properties": {}},
    )
    registry.register("large_input_tool", tool, failing_executor)

    large_input = {"data": "x" * 1000}
    tool_use = ToolUse(
        id="call_789",
        name="large_input_tool",
        input=large_input,
    )

    with caplog.at_level(logging.ERROR):
        executor = registry.get_executor()
        executor(tool_use)

    log_messages = [record.message for record in caplog.records]
    full_log = " ".join(log_messages)
    assert "...(truncated)" in full_log
