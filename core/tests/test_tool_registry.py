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


def test_register_mcp_server_defaults_to_connection_manager(monkeypatch):
    """Default behavior uses the connection manager (reuse enabled by default)."""
    registry = ToolRegistry()
    created_clients: list[_RegistryFakeClient] = []

    def fake_client_factory(config):
        client = _RegistryFakeClient(config)
        created_clients.append(client)
        return client

    class FakeManager:
        def acquire(self, config):
            return fake_client_factory(config)

        def release(self, server_name):
            pass

    monkeypatch.setattr(
        "framework.runner.mcp_connection_manager.MCPConnectionManager.get_instance",
        lambda: FakeManager(),
    )

    count = registry.register_mcp_server(
        {"name": "direct", "transport": "stdio", "command": "echo"},
    )

    assert count == 1
    assert len(created_clients) == 1


def test_register_mcp_server_direct_client_when_manager_disabled(monkeypatch):
    """When use_connection_manager=False, a direct MCPClient is created."""
    registry = ToolRegistry()
    created_clients: list[_RegistryFakeClient] = []

    def fake_client_factory(config):
        client = _RegistryFakeClient(config)
        created_clients.append(client)
        return client

    monkeypatch.setattr("framework.runner.mcp_client.MCPClient", fake_client_factory)

    count = registry.register_mcp_server(
        {"name": "direct", "transport": "stdio", "command": "echo"},
        use_connection_manager=False,
    )

    assert count == 1
    assert len(created_clients) == 1
    assert created_clients[0].connect_calls == 1

    registry.cleanup()

    assert created_clients[0].disconnect_calls == 1


def test_load_registry_servers_retries_when_registration_returns_zero(monkeypatch):
    registry = ToolRegistry()
    attempts = {"count": 0}

    def fake_register(server_config, use_connection_manager=True):
        attempts["count"] += 1
        return 0 if attempts["count"] == 1 else 2

    monkeypatch.setattr(registry, "register_mcp_server", fake_register)
    monkeypatch.setattr("time.sleep", lambda _: None)

    results = registry.load_registry_servers(
        [{"name": "jira", "transport": "http", "url": "http://localhost:4010"}],
        log_summary=False,
    )

    assert attempts["count"] == 2
    assert results == [
        {
            "server": "jira",
            "status": "loaded",
            "tools_loaded": 2,
            "skipped_reason": None,
        }
    ]


def test_load_registry_servers_marks_failures_as_skipped(monkeypatch):
    registry = ToolRegistry()

    monkeypatch.setattr(registry, "register_mcp_server", lambda *args, **kwargs: 0)
    monkeypatch.setattr("time.sleep", lambda _: None)

    results = registry.load_registry_servers(
        [{"name": "jira", "transport": "http", "url": "http://localhost:4010"}],
        log_summary=False,
    )

    assert results == [
        {
            "server": "jira",
            "status": "skipped",
            "tools_loaded": 0,
            "skipped_reason": "registered 0 tools",
        }
    ]


def test_load_registry_servers_emits_structured_log_fields(monkeypatch):
    registry = ToolRegistry()
    captured_logs: list[tuple[str, dict | None]] = []

    monkeypatch.setattr(registry, "register_mcp_server", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        "framework.runner.tool_registry.logger.info",
        lambda message, *args, **kwargs: captured_logs.append((message, kwargs.get("extra"))),
    )

    registry.load_registry_servers(
        [{"name": "jira", "transport": "http", "url": "http://localhost:4010"}],
        log_summary=True,
    )

    assert captured_logs == [
        (
            "MCP registry server resolution",
            {
                "event": "mcp_registry_server_resolution",
                "server": "jira",
                "status": "loaded",
                "tools_loaded": 2,
                "skipped_reason": None,
            },
        )
    ]
