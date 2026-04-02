"""Tests for MCP structured error formatting."""

import pytest

from framework.runner.mcp_errors import (
    MCPAuthError,
    MCPError,
    MCPErrorCode,
    MCPToolNotFoundError,
)


def test_mcp_error_code_stored():
    err = MCPError(
        code=MCPErrorCode.MCP_AUTH_MISSING,
        what="Could not connect to server 'jira'",
        why="JIRA_API_TOKEN is not set",
        fix="Run: hive mcp config jira --set JIRA_API_TOKEN=<token>",
    )
    assert err.code == MCPErrorCode.MCP_AUTH_MISSING


def test_mcp_error_message_format():
    err = MCPError(
        code=MCPErrorCode.MCP_AUTH_MISSING,
        what="Could not connect to server 'jira'",
        why="JIRA_API_TOKEN is not set",
        fix="Run: hive mcp config jira --set JIRA_API_TOKEN=<token>",
    )
    expected = (
        "[MCP_AUTH_MISSING]\n"
        "What failed: Could not connect to server 'jira'\n"
        "Why: JIRA_API_TOKEN is not set\n"
        "Fix: Run: hive mcp config jira --set JIRA_API_TOKEN=<token>"
    )
    assert str(err) == expected


def test_mcp_tool_not_found_error():
    err = MCPToolNotFoundError(server="github", tool_name="create_pr")
    assert err.code == MCPErrorCode.MCP_TOOL_NOT_FOUND
    assert "create_pr" in str(err)
    assert "github" in str(err)


def test_mcp_auth_error():
    err = MCPAuthError(server="jira", env_var="JIRA_API_TOKEN")
    assert err.code == MCPErrorCode.MCP_AUTH_MISSING
    assert "JIRA_API_TOKEN" in str(err)


def test_mcp_client_raises_structured_error_for_missing_tool():
    from framework.runner.mcp_client import MCPClient, MCPServerConfig

    config = MCPServerConfig(name="test-server", transport="stdio")
    client = MCPClient(config)
    client._connected = True
    client._tools = {}  # empty — no tools registered

    with pytest.raises(MCPToolNotFoundError) as exc_info:
        client.call_tool("nonexistent_tool", {})

    assert exc_info.value.code == MCPErrorCode.MCP_TOOL_NOT_FOUND
    assert "test-server" in str(exc_info.value)
    assert "nonexistent_tool" in str(exc_info.value)
