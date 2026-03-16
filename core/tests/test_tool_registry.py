"""Tests for ToolRegistry JSON handling when tools return invalid JSON.

These tests exercise the discover_from_module() path, where tools are
registered via a TOOLS dict and a unified tool_executor that returns
ToolResult instances. Historically, invalid JSON in ToolResult.content
could cause a json.JSONDecodeError and crash execution.
"""

import textwrap
from pathlib import Path
from types import SimpleNamespace

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


class _RegistryFakeClient:
    def __init__(self, config):
        self.config = config
        self.connect_calls = 0
        self.disconnect_calls = 0

    def connect(self) -> None:
        self.connect_calls += 1

    def disconnect(self) -> None:
        self.disconnect_calls += 1

    def list_tools(self):
        return [
            SimpleNamespace(
                name="pooled_tool",
                description="Tool from MCP",
                input_schema={"type": "object", "properties": {}, "required": []},
            )
        ]

    def call_tool(self, tool_name, arguments):
        return [{"text": f"{tool_name}:{arguments}"}]


def test_register_mcp_server_uses_connection_manager_when_enabled(monkeypatch):
    registry = ToolRegistry()
    client = _RegistryFakeClient(SimpleNamespace(name="shared"))
    manager_calls: list[tuple[str, str]] = []

    class FakeManager:
        def acquire(self, config):
            manager_calls.append(("acquire", config.name))
            client.config = config
            return client

        def release(self, server_name: str) -> None:
            manager_calls.append(("release", server_name))

    monkeypatch.setattr(
        "framework.runner.mcp_connection_manager.MCPConnectionManager.get_instance",
        lambda: FakeManager(),
    )

    count = registry.register_mcp_server(
        {"name": "shared", "transport": "stdio", "command": "echo"},
        use_connection_manager=True,
    )

    assert count == 1
    assert manager_calls == [("acquire", "shared")]

    registry.cleanup()

    assert manager_calls == [("acquire", "shared"), ("release", "shared")]
    assert client.disconnect_calls == 0


def test_register_mcp_server_defaults_to_direct_client_behavior(monkeypatch):
    registry = ToolRegistry()
    created_clients: list[_RegistryFakeClient] = []

    def fake_client_factory(config):
        client = _RegistryFakeClient(config)
        created_clients.append(client)
        return client

    def fail_if_manager_used():
        raise AssertionError("connection manager should not be used by default")

    monkeypatch.setattr("framework.runner.mcp_client.MCPClient", fake_client_factory)
    monkeypatch.setattr(
        "framework.runner.mcp_connection_manager.MCPConnectionManager.get_instance",
        fail_if_manager_used,
    )

    count = registry.register_mcp_server(
        {"name": "direct", "transport": "stdio", "command": "echo"},
    )

    assert count == 1
    assert len(created_clients) == 1
    assert created_clients[0].connect_calls == 1

    registry.cleanup()

    assert created_clients[0].disconnect_calls == 1
