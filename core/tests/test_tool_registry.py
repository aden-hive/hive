"""Tests for ToolRegistry JSON handling when tools return invalid JSON.

These tests exercise the discover_from_module() path, where tools are
registered via a TOOLS dict and a unified tool_executor that returns
ToolResult instances. Historically, invalid JSON in ToolResult.content
could cause a json.JSONDecodeError and crash execution.
"""

from pathlib import Path
import textwrap

from framework.llm.provider import Tool, ToolResult
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

