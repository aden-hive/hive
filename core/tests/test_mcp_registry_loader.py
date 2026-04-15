from __future__ import annotations

from typing import Any

from framework.loader.mcp_client import MCPTool
from framework.loader.tool_registry import ToolRegistry


def _patch_connection_manager_for_fake_stdio(monkeypatch, tool_map: dict[str, list[str]]) -> None:
    """Avoid spawning real stdio MCP processes; return in-memory clients per server name."""

    class FakeMCPClient:
        def __init__(self, config: Any):
            self.config = config

        def connect(self) -> None:
            return

        def disconnect(self) -> None:
            return

        def list_tools(self) -> list[MCPTool]:
            names = tool_map.get(self.config.name, [])
            return [_make_tool(n, self.config.name) for n in names]

        def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
            raise NotImplementedError

    class FakeManager:
        def acquire(self, config: Any) -> FakeMCPClient:
            return FakeMCPClient(config)

        def release(self, _server_name: str) -> None:
            return

    monkeypatch.setattr(
        "framework.loader.mcp_connection_manager.MCPConnectionManager.get_instance",
        lambda: FakeManager(),
    )


def _make_tool(name: str, server_name: str) -> MCPTool:
    return MCPTool(
        name=name,
        description=f"{name} from {server_name}",
        input_schema={"type": "object", "properties": {}, "required": []},
        server_name=server_name,
    )


def test_registry_first_wins_collisions(monkeypatch):
    """
    When multiple registry servers expose the same tool name, the first server
    in load order should win and later servers should not overwrite it.
    """

    tool_map: dict[str, list[str]] = {
        "s1": ["tool_common", "tool_hive"],
        "s2": ["tool_common", "tool_coder"],
    }
    _patch_connection_manager_for_fake_stdio(monkeypatch, tool_map)

    resolved_servers = [
        {"name": "s1", "transport": "stdio", "command": "fake", "args": [], "cwd": None},
        {"name": "s2", "transport": "stdio", "command": "fake", "args": [], "cwd": None},
    ]

    registry = ToolRegistry()
    registry.load_registry_servers(
        resolved_servers,
        log_summary=False,
        preserve_existing_tools=True,
        log_collisions=True,
    )

    assert registry.has_tool("tool_common") is True
    assert registry.has_tool("tool_hive") is True
    assert registry.has_tool("tool_coder") is True

    assert registry.get_server_tool_names("s1") == {"tool_common", "tool_hive"}
    assert registry.get_server_tool_names("s2") == {"tool_coder"}


def test_registry_precedence_over_existing_mcp_servers(monkeypatch):
    """Registry-loaded tools should not overwrite already registered MCP tools."""

    tool_map: dict[str, list[str]] = {
        "pre": ["tool_common", "tool_pre"],
        "s1": ["tool_common", "tool_hive"],
        "s2": ["tool_common", "tool_coder"],
    }
    _patch_connection_manager_for_fake_stdio(monkeypatch, tool_map)

    resolved_servers = [
        {"name": "s1", "transport": "stdio", "command": "fake", "args": [], "cwd": None},
        {"name": "s2", "transport": "stdio", "command": "fake", "args": [], "cwd": None},
    ]

    registry = ToolRegistry()
    registry.register_mcp_server(
        {"name": "pre", "transport": "stdio", "command": "fake", "args": [], "cwd": None}
    )

    registry.load_registry_servers(
        resolved_servers,
        log_summary=False,
        preserve_existing_tools=True,
        log_collisions=True,
    )

    assert registry.get_server_tool_names("pre") == {"tool_common", "tool_pre"}
    assert registry.get_server_tool_names("s1") == {"tool_hive"}
    assert registry.get_server_tool_names("s2") == {"tool_coder"}


def test_registry_max_tools_cap(monkeypatch):
    """max_tools caps the total number of newly added tools from registry servers."""

    tool_map: dict[str, list[str]] = {
        "s1": ["tool_a", "tool_b"],
        "s2": ["tool_c"],
    }
    _patch_connection_manager_for_fake_stdio(monkeypatch, tool_map)

    resolved_servers = [
        {"name": "s1", "transport": "stdio", "command": "fake", "args": [], "cwd": None},
        {"name": "s2", "transport": "stdio", "command": "fake", "args": [], "cwd": None},
    ]

    registry = ToolRegistry()
    registry.load_registry_servers(
        resolved_servers,
        log_summary=False,
        preserve_existing_tools=True,
        max_tools=2,
    )

    assert registry.has_tool("tool_a") is True
    assert registry.has_tool("tool_b") is True
    assert registry.has_tool("tool_c") is False
