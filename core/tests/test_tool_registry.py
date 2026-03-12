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


def test_register_mcp_server_required_raises_on_failure():
    """register_mcp_server should raise MCPServerConnectionError for required servers."""
    import pytest

    from framework.credentials.models import MCPServerConnectionError

    registry = ToolRegistry()

    with pytest.raises(MCPServerConnectionError) as exc_info:
        registry.register_mcp_server(
            {
                "name": "required-server",
                "transport": "stdio",
                "command": "nonexistent_command_that_will_fail",
                "args": [],
            },
            optional=False,
        )

    assert "required-server" in str(exc_info.value)
    assert exc_info.value.server_name == "required-server"


def test_register_mcp_server_optional_logs_warning_on_failure(caplog):
    """register_mcp_server should log warning for optional servers, not raise."""
    import logging

    registry = ToolRegistry()

    with caplog.at_level(logging.WARNING):
        result = registry.register_mcp_server(
            {
                "name": "optional-server",
                "transport": "stdio",
                "command": "nonexistent_command_that_will_fail",
                "args": [],
            },
            optional=True,
        )

    assert result == 0
    assert any("optional-server" in record.message for record in caplog.records)


def test_load_mcp_config_required_server_failure(tmp_path):
    """load_mcp_config should raise MCPServerConnectionError for required servers."""
    import json

    import pytest

    from framework.credentials.models import MCPServerConnectionError

    config = {
        "required-server": {
            "transport": "stdio",
            "command": "nonexistent_command_that_will_fail",
            "args": [],
        }
    }
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(json.dumps(config))

    registry = ToolRegistry()

    with pytest.raises(MCPServerConnectionError) as exc_info:
        registry.load_mcp_config(config_path)

    assert exc_info.value.server_name == "required-server"


def test_load_mcp_config_optional_server_failure(tmp_path, caplog):
    """load_mcp_config should not raise for optional servers."""
    import json
    import logging

    config = {
        "optional-server": {
            "transport": "stdio",
            "command": "nonexistent_command_that_will_fail",
            "args": [],
            "optional": True,
        }
    }
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(json.dumps(config))

    registry = ToolRegistry()

    with caplog.at_level(logging.WARNING):
        registry.load_mcp_config(config_path)

    assert any("optional-server" in record.message for record in caplog.records)


def test_load_mcp_config_mixed_required_and_optional(tmp_path):
    """load_mcp_config should fail fast on first required server failure."""
    import json

    import pytest

    from framework.credentials.models import MCPServerConnectionError

    config = {
        "first-optional": {
            "transport": "stdio",
            "command": "nonexistent_command",
            "args": [],
            "optional": True,
        },
        "required-fails": {
            "transport": "stdio",
            "command": "nonexistent_command",
            "args": [],
        },
        "second-optional": {
            "transport": "stdio",
            "command": "nonexistent_command",
            "args": [],
            "optional": True,
        },
    }
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(json.dumps(config))

    registry = ToolRegistry()

    with pytest.raises(MCPServerConnectionError) as exc_info:
        registry.load_mcp_config(config_path)

    assert exc_info.value.server_name == "required-fails"
