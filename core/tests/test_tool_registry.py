"""Tests for ToolRegistry JSON handling when tools return invalid JSON.

These tests exercise the discover_from_module() path, where tools are
registered via a TOOLS dict and a unified tool_executor that returns
ToolResult instances. Historically, invalid JSON in ToolResult.content
could cause a json.JSONDecodeError and crash execution.
"""

import textwrap
from pathlib import Path

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


import json

from framework.llm.provider import Tool, ToolUse


def test_register_function_generates_schema_and_required_fields() -> None:
    registry = ToolRegistry()

    def example_tool(
        a: str,
        b: int,
        c: float,
        d: bool,
        e: dict,
        f: list,
        g: str = "default",
    ) -> dict:
        return {
            "a": a,
            "b": b,
            "c": c,
            "d": d,
            "e": e,
            "f": f,
            "g": g,
        }

    registry.register_function(example_tool, name="example_tool", description="Example tool.")
    tool = registry.get_tools()["example_tool"]

    assert tool.name == "example_tool"
    assert tool.description == "Example tool."
    assert tool.parameters["type"] == "object"

    props = tool.parameters["properties"]
    assert props["a"]["type"] == "string"
    assert props["b"]["type"] == "integer"
    assert props["c"]["type"] == "number"
    assert props["d"]["type"] == "boolean"
    assert props["e"]["type"] == "object"
    assert props["f"]["type"] == "array"
    assert props["g"]["type"] == "string"

    # Only args without defaults are required.
    assert tool.parameters["required"] == ["a", "b", "c", "d", "e", "f"]


def test_get_executor_returns_error_for_unknown_tool() -> None:
    registry = ToolRegistry()
    executor = registry.get_executor()

    result = executor(ToolUse(id="call_1", name="does_not_exist", input={}))

    assert result.is_error is True
    payload = json.loads(result.content)
    assert "Unknown tool: does_not_exist" in payload["error"]


def test_get_executor_executes_tool_and_wraps_result_as_toolresult() -> None:
    registry = ToolRegistry()

    def add(x: int, y: int) -> dict:
        return {"sum": x + y}

    registry.register_function(add)
    executor = registry.get_executor()

    result = executor(ToolUse(id="call_add", name="add", input={"x": 2, "y": 3}))

    assert result.is_error is False
    assert json.loads(result.content) == {"sum": 5}


def test_get_executor_catches_exceptions_and_returns_error_toolresult() -> None:
    registry = ToolRegistry()

    def boom() -> dict:
        raise RuntimeError("kaboom")

    registry.register_function(boom)
    executor = registry.get_executor()

    result = executor(ToolUse(id="call_boom", name="boom", input={}))

    assert result.is_error is True
    payload = json.loads(result.content)
    assert payload["error"] == "kaboom"


def test_register_allows_custom_tool_and_executor() -> None:
    registry = ToolRegistry()

    registry.register(
        name="custom",
        tool=Tool(name="custom", description="Custom tool."),
        executor=lambda inputs: {"ok": True, "inputs": inputs},
    )

    executor = registry.get_executor()
    result = executor(ToolUse(id="call_custom", name="custom", input={"a": 1}))

    assert result.is_error is False
    assert json.loads(result.content) == {"ok": True, "inputs": {"a": 1}}


def test_get_tools_and_has_tool_and_registered_names() -> None:
    registry = ToolRegistry()
    assert registry.get_tools() == {}
    assert registry.get_registered_names() == []
    assert registry.has_tool("x") is False

    registry.register(
        name="x",
        tool=Tool(name="x", description="X tool."),
        executor=lambda inputs: {"ok": True},
    )

    assert registry.has_tool("x") is True
    assert registry.get_registered_names() == ["x"]
    assert registry.get_tools()["x"].name == "x"


def test_tool_decorator_sets_metadata_defaults() -> None:
    from framework.runner.tool_registry import tool

    @tool()
    def f() -> dict:
        """F docstring."""
        return {"ok": True}

    assert f._tool_metadata["name"] == "f"
    assert f._tool_metadata["description"] == "F docstring."


def test_tool_decorator_sets_metadata_custom() -> None:
    from framework.runner.tool_registry import tool

    @tool(name="custom_name", description="Custom description.")
    def f() -> dict:
        return {"ok": True}

    assert f._tool_metadata["name"] == "custom_name"
    assert f._tool_metadata["description"] == "Custom description."


def test_cleanup_disconnects_all_mcp_clients() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.disconnected = 0

        def disconnect(self) -> None:
            self.disconnected += 1

    registry = ToolRegistry()
    c1 = FakeClient()
    c2 = FakeClient()
    registry._mcp_clients = [c1, c2]  # intentionally poking internals for unit test

    registry.cleanup()

    assert c1.disconnected == 1
    assert c2.disconnected == 1
    assert registry._mcp_clients == []
