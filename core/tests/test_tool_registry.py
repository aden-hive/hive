"""Tests for ToolRegistry JSON handling when tools return invalid JSON.

These tests exercise the discover_from_module() path, where tools are
registered via a TOOLS dict and a unified tool_executor that returns
ToolResult instances. Historically, invalid JSON in ToolResult.content
could cause a json.JSONDecodeError and crash execution.
"""

import logging
import textwrap
from pathlib import Path
from types import SimpleNamespace

from framework.llm.provider import Tool, ToolUse
from framework.loader.tool_registry import ToolRegistry


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
        "framework.loader.mcp_connection_manager.MCPConnectionManager.get_instance",
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
        "framework.loader.mcp_connection_manager.MCPConnectionManager.get_instance",
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

    monkeypatch.setattr("framework.loader.mcp_client.MCPClient", fake_client_factory)

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

    def fake_register(server_config, use_connection_manager=True, **kwargs):
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
        "framework.loader.tool_registry.logger.info",
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


# ---------------------------------------------------------------------------
# register_function — type inference and required/optional parameters
# ---------------------------------------------------------------------------


def test_register_function_infers_type_hints():
    """register_function should map Python type annotations to JSON schema types."""
    registry = ToolRegistry()

    def my_func(a: int, b: float, c: bool, d: dict, e: list, f: str = "x") -> None:
        pass

    registry.register_function(my_func)

    tool = registry.get_tools()["my_func"]
    props = tool.parameters["properties"]
    assert props["a"]["type"] == "integer"
    assert props["b"]["type"] == "number"
    assert props["c"]["type"] == "boolean"
    assert props["d"]["type"] == "object"
    assert props["e"]["type"] == "array"
    assert props["f"]["type"] == "string"


def test_register_function_required_vs_optional():
    """Parameters without defaults should appear in 'required'."""
    registry = ToolRegistry()

    def my_func(required_param: str, optional_param: int = 5) -> None:
        pass

    registry.register_function(my_func)

    tool = registry.get_tools()["my_func"]
    required = tool.parameters["required"]
    assert "required_param" in required
    assert "optional_param" not in required


def test_register_function_custom_name_and_description():
    """register_function should accept explicit name and description overrides."""
    registry = ToolRegistry()

    def original_name() -> None:
        """Original docstring."""
        pass

    registry.register_function(original_name, name="custom_name", description="Custom desc")
    tools = registry.get_tools()
    assert "custom_name" in tools
    assert "original_name" not in tools
    assert tools["custom_name"].description == "Custom desc"


def test_register_function_falls_back_to_docstring():
    """register_function should use the docstring if no description is given."""
    registry = ToolRegistry()

    def my_tool() -> None:
        """My docstring."""
        pass

    registry.register_function(my_tool)
    tool = registry.get_tools()["my_tool"]
    assert tool.description == "My docstring."


def test_register_function_executor_calls_function():
    """The executor created by register_function should call the underlying function."""
    registry = ToolRegistry()
    calls = []

    def multiply(x: int, y: int) -> int:
        calls.append((x, y))
        return x * y

    registry.register_function(multiply)
    tool_use = ToolUse(id="call_1", name="multiply", input={"x": 3, "y": 4})
    executor = registry.get_executor()
    result = executor(tool_use)

    assert calls == [(3, 4)]
    assert "12" in result.content


# ---------------------------------------------------------------------------
# @tool decorator discovery via discover_from_module
# ---------------------------------------------------------------------------


def test_discover_from_module_finds_tool_decorated_functions(tmp_path):
    """discover_from_module should pick up functions decorated with @tool."""
    module_src = """
        from framework.loader.tool_registry import tool

        @tool(description="Say hello")
        def greet(name: str) -> str:
            return f"Hello {name}"
    """
    module_path = tmp_path / "agent_tools.py"
    module_path.write_text(textwrap.dedent(module_src))

    registry = ToolRegistry()
    count = registry.discover_from_module(module_path)
    assert count == 1
    assert "greet" in registry.get_tools()


def test_discover_from_module_returns_zero_for_missing_file(tmp_path):
    """discover_from_module should return 0 when the file does not exist."""
    registry = ToolRegistry()
    count = registry.discover_from_module(tmp_path / "nonexistent.py")
    assert count == 0


def test_discover_from_module_registers_mock_executor_without_tool_executor(tmp_path):
    """When TOOLS dict exists but no tool_executor, a mock executor is used."""
    module_src = """
        from framework.llm.provider import Tool

        TOOLS = {
            "mock_tool": Tool(
                name="mock_tool",
                description="Has no executor",
                parameters={"type": "object", "properties": {}},
            ),
        }
    """
    module_path = tmp_path / "agent_tools.py"
    module_path.write_text(textwrap.dedent(module_src))

    registry = ToolRegistry()
    count = registry.discover_from_module(module_path)
    assert count == 1

    registered = registry._tools["mock_tool"]  # noqa: SLF001
    result = registered.executor({"foo": "bar"})
    assert result == {"mock": True, "inputs": {"foo": "bar"}}


# ---------------------------------------------------------------------------
# has_tool / get_registered_names
# ---------------------------------------------------------------------------


def test_has_tool_returns_true_for_registered_tool():
    registry = ToolRegistry()
    tool = Tool(name="t", description="d", parameters={"type": "object", "properties": {}})
    registry.register("t", tool, lambda inputs: inputs)
    assert registry.has_tool("t") is True


def test_has_tool_returns_false_for_missing_tool():
    registry = ToolRegistry()
    assert registry.has_tool("not_there") is False


def test_get_registered_names_lists_all_tools():
    registry = ToolRegistry()
    for name in ("alpha", "beta", "gamma"):
        t = Tool(name=name, description="d", parameters={"type": "object", "properties": {}})
        registry.register(name, t, lambda inputs: inputs)
    assert set(registry.get_registered_names()) == {"alpha", "beta", "gamma"}


# ---------------------------------------------------------------------------
# Session context injection
# ---------------------------------------------------------------------------


def test_session_context_is_injected_into_mcp_tool_call(monkeypatch):
    """Context params in session context should be forwarded to MCP tool calls."""
    registry = ToolRegistry()
    registry.set_session_context(workspace_id="ws-123", agent_id="agent-99")

    received: list[dict] = []

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def connect(self):
            pass

        def disconnect(self):
            pass

        def list_tools(self):
            return [
                SimpleNamespace(
                    name="ctx_tool",
                    description="context tool",
                    input_schema={
                        "type": "object",
                        "properties": {
                            "workspace_id": {"type": "string"},
                            "agent_id": {"type": "string"},
                        },
                        "required": [],
                    },
                )
            ]

        def call_tool(self, tool_name, arguments):
            received.append(dict(arguments))
            return {"result": "ok"}

    monkeypatch.setattr("framework.loader.mcp_client.MCPClient", FakeClient)

    registry.register_mcp_server(
        {"name": "ctx-server", "transport": "stdio", "command": "echo"},
        use_connection_manager=False,
    )

    tool_use = ToolUse(id="c1", name="ctx_tool", input={})
    executor = registry.get_executor()
    executor(tool_use)

    assert received, "call_tool was never called"
    assert received[0].get("workspace_id") == "ws-123"
    assert received[0].get("agent_id") == "agent-99"


# ---------------------------------------------------------------------------
# Execution context (contextvars isolation)
# ---------------------------------------------------------------------------


def test_execution_context_overrides_session_context(monkeypatch):
    """Execution context values should win over session context for the same key."""
    registry = ToolRegistry()
    registry.set_session_context(workspace_id="session-ws")
    received: list[dict] = []

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def connect(self):
            pass

        def disconnect(self):
            pass

        def list_tools(self):
            return [
                SimpleNamespace(
                    name="exec_tool",
                    description="execution context tool",
                    input_schema={
                        "type": "object",
                        "properties": {"workspace_id": {"type": "string"}},
                        "required": [],
                    },
                )
            ]

        def call_tool(self, tool_name, arguments):
            received.append(dict(arguments))
            return {"result": "ok"}

    monkeypatch.setattr("framework.loader.mcp_client.MCPClient", FakeClient)
    registry.register_mcp_server(
        {"name": "exec-server", "transport": "stdio", "command": "echo"},
        use_connection_manager=False,
    )

    token = ToolRegistry.set_execution_context(workspace_id="exec-ws")
    try:
        tool_use = ToolUse(id="c2", name="exec_tool", input={})
        executor = registry.get_executor()
        executor(tool_use)
    finally:
        ToolRegistry.reset_execution_context(token)

    assert received, "call_tool was never called"
    assert received[0]["workspace_id"] == "exec-ws"


# ---------------------------------------------------------------------------
# _convert_mcp_tool_to_framework_tool — CONTEXT_PARAMS stripped
# ---------------------------------------------------------------------------


def test_convert_mcp_tool_strips_context_params():
    """CONTEXT_PARAMS should be removed from the LLM-facing tool schema."""
    registry = ToolRegistry()
    mcp_tool = SimpleNamespace(
        name="some_tool",
        description="a tool",
        input_schema={
            "type": "object",
            "properties": {
                "agent_id": {"type": "string"},  # context param → stripped
                "data_dir": {"type": "string"},  # context param → stripped
                "query": {"type": "string"},  # regular param → kept
            },
            "required": ["agent_id", "query"],
        },
    )
    tool = registry._convert_mcp_tool_to_framework_tool(mcp_tool)  # noqa: SLF001
    props = tool.parameters["properties"]
    assert "agent_id" not in props
    assert "data_dir" not in props
    assert "query" in props
    # agent_id should also be stripped from required
    assert "agent_id" not in tool.parameters["required"]
    assert "query" in tool.parameters["required"]


# ---------------------------------------------------------------------------
# load_mcp_config — both JSON config formats
# ---------------------------------------------------------------------------


def test_load_mcp_config_list_format(tmp_path, monkeypatch):
    """load_mcp_config should accept the {\"servers\": [...]} list format."""
    config_file = tmp_path / "mcp_servers.json"
    config_file.write_text('{"servers": [{"name": "s1", "transport": "http", "url": "http://localhost:9000"}]}')

    called_with = []

    def fake_load_registry(server_list, **kwargs):
        called_with.extend(server_list)
        return []

    registry = ToolRegistry()
    monkeypatch.setattr(registry, "load_registry_servers", fake_load_registry)
    registry.load_mcp_config(config_file)

    assert len(called_with) == 1
    assert called_with[0]["name"] == "s1"


def test_load_mcp_config_dict_format(tmp_path, monkeypatch):
    """load_mcp_config should accept the {\"server-name\": {...}} dict format."""
    config_file = tmp_path / "mcp_servers.json"
    config_file.write_text('{"my-server": {"transport": "http", "url": "http://localhost:9001"}}')

    called_with = []

    def fake_load_registry(server_list, **kwargs):
        called_with.extend(server_list)
        return []

    registry = ToolRegistry()
    monkeypatch.setattr(registry, "load_registry_servers", fake_load_registry)
    registry.load_mcp_config(config_file)

    assert len(called_with) == 1
    assert called_with[0]["name"] == "my-server"


def test_load_mcp_config_handles_invalid_json(tmp_path, caplog):
    """load_mcp_config should log a warning and return gracefully on bad JSON."""
    bad_file = tmp_path / "bad.json"
    bad_file.write_text("{not valid json")

    registry = ToolRegistry()
    with caplog.at_level(logging.WARNING):
        registry.load_mcp_config(bad_file)

    assert any("Failed to load MCP config" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# resync_mcp_servers_if_needed — no-op when nothing changed
# ---------------------------------------------------------------------------


def test_resync_returns_false_when_no_clients():
    """resync_mcp_servers_if_needed should return False immediately with no clients."""
    registry = ToolRegistry()
    assert registry.resync_mcp_servers_if_needed() is False


def test_resync_returns_false_when_credentials_unchanged(tmp_path, monkeypatch):
    """Resync should return False when neither credentials nor ADEN_API_KEY changed."""
    config_file = tmp_path / "mcp_servers.json"
    config_file.write_text('{"servers": []}')

    registry = ToolRegistry()
    # Simulate that MCP was loaded (need at least one client and a config path)
    registry._mcp_config_path = config_file  # noqa: SLF001

    class _FakeClient:
        config = SimpleNamespace(name="stub")

        def disconnect(self):
            pass

    registry._mcp_clients.append(_FakeClient())  # noqa: SLF001
    registry._mcp_cred_snapshot = set()  # noqa: SLF001
    registry._mcp_aden_key_snapshot = None  # noqa: SLF001

    # No credentials on disk and env var not set → nothing changed
    monkeypatch.delenv("ADEN_API_KEY", raising=False)
    monkeypatch.setattr(registry, "_snapshot_credentials", lambda: set())

    assert registry.resync_mcp_servers_if_needed() is False


class TestMcpToolProducesImageFlag:
    """Verify _convert_mcp_tool_to_framework_tool sets produces_image from the name.

    This is the detection step that the filter in AgentLoop depends on —
    if the regex regresses, text-only models will start seeing screenshot
    tools they can't use.
    """

    @staticmethod
    def _mcp_tool(name: str):
        return SimpleNamespace(
            name=name,
            description=f"{name} description",
            input_schema={"type": "object", "properties": {}, "required": []},
            server_name="test",
        )

    def test_screenshot_flagged(self):
        registry = ToolRegistry()
        mcp = self._mcp_tool("browser_screenshot")
        tool = registry._convert_mcp_tool_to_framework_tool(mcp)  # noqa: SLF001
        assert tool.produces_image is True

    def test_snapshot_not_flagged(self):
        """browser_snapshot returns a DOM tree, not an image — must not match."""
        registry = ToolRegistry()
        mcp = self._mcp_tool("browser_snapshot")
        tool = registry._convert_mcp_tool_to_framework_tool(mcp)  # noqa: SLF001
        assert tool.produces_image is False

    def test_case_insensitive_match(self):
        registry = ToolRegistry()
        mcp = self._mcp_tool("TakeScreenshot")
        tool = registry._convert_mcp_tool_to_framework_tool(mcp)  # noqa: SLF001
        assert tool.produces_image is True

    def test_plain_tool_not_flagged(self):
        registry = ToolRegistry()
        mcp = self._mcp_tool("read_file")
        tool = registry._convert_mcp_tool_to_framework_tool(mcp)  # noqa: SLF001
        assert tool.produces_image is False

    def test_image_suffix_variants_flagged(self):
        registry = ToolRegistry()
        for name in ("capture_image", "render_image", "get_image", "snapshot_image"):
            tool = registry._convert_mcp_tool_to_framework_tool(self._mcp_tool(name))  # noqa: SLF001
            assert tool.produces_image is True, f"{name} should be flagged"


# ---------------------------------------------------------------------------
# Concurrency-safe flag propagation
# ---------------------------------------------------------------------------


def test_mcp_tool_conversion_marks_known_safe_tools():
    """MCP tools whose names are in CONCURRENCY_SAFE_TOOLS become concurrency_safe."""
    from framework.loader.mcp_client import MCPTool

    registry = ToolRegistry()

    safe_mcp = MCPTool(
        name="read_file",
        description="",
        input_schema={"type": "object", "properties": {}, "required": []},
        server_name="stub",
    )
    unsafe_mcp = MCPTool(
        name="execute_command",
        description="",
        input_schema={"type": "object", "properties": {}, "required": []},
        server_name="stub",
    )

    safe_tool = registry._convert_mcp_tool_to_framework_tool(safe_mcp)  # noqa: SLF001
    unsafe_tool = registry._convert_mcp_tool_to_framework_tool(unsafe_mcp)  # noqa: SLF001

    assert safe_tool.concurrency_safe is True
    assert unsafe_tool.concurrency_safe is False


def test_concurrency_safe_allowlist_is_conservative():
    """Every listed name must denote a read-only operation.

    This test is a guard against someone casually adding a write-capable
    tool to the allowlist. If a new name is added here, justify it in the
    comment above the set in tool_registry.py.
    """
    from framework.loader.tool_registry import ToolRegistry

    allowlist = ToolRegistry.CONCURRENCY_SAFE_TOOLS

    # Positive assertions: known-safe read operations are present.
    for name in ("read_file", "grep", "glob", "list_directory", "web_search"):
        assert name in allowlist, f"{name} should be concurrency-safe"

    # Negative assertions: nothing that mutates state is allowed in.
    for forbidden in (
        "execute_command",
        "write_file",
        "hashline_edit",
        "browser_click",
        "browser_type",
        "browser_navigate",
    ):
        assert forbidden not in allowlist, f"{forbidden} must not be concurrency-safe"
