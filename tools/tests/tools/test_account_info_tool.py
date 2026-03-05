"""Tests for account_info_tool - query connected accounts at runtime."""

from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from aden_tools.tools.account_info_tool.account_info_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


@pytest.fixture
def tool_fns_with_creds(mcp: FastMCP):
    mock_creds = MagicMock()
    mock_creds.list_accounts.return_value = [
        {"id": "acc1", "provider": "google", "email": "user@example.com"}
    ]
    mock_creds.get_all_account_info.return_value = [
        {"id": "acc1", "provider": "google", "email": "user@example.com"},
        {"id": "acc2", "provider": "slack", "workspace": "my-team"},
    ]
    register_tools(mcp, credentials=mock_creds)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}, mock_creds


class TestGetAccountInfoNoCredentials:
    def test_no_credentials_returns_empty(self, tool_fns):
        result = tool_fns["get_account_info"]()
        assert result["accounts"] == []
        assert "message" in result

    def test_no_credentials_with_provider_returns_empty(self, tool_fns):
        result = tool_fns["get_account_info"](provider="google")
        assert result["accounts"] == []


class TestGetAccountInfoWithCredentials:
    def test_all_accounts_returned(self, tool_fns_with_creds):
        tool_fns, mock_creds = tool_fns_with_creds
        result = tool_fns["get_account_info"]()
        assert result["count"] == 2
        assert len(result["accounts"]) == 2
        mock_creds.get_all_account_info.assert_called_once()

    def test_filter_by_provider(self, tool_fns_with_creds):
        tool_fns, mock_creds = tool_fns_with_creds
        result = tool_fns["get_account_info"](provider="google")
        assert result["count"] == 1
        assert result["accounts"][0]["provider"] == "google"
        mock_creds.list_accounts.assert_called_once_with("google")

    def test_empty_provider_returns_all(self, tool_fns_with_creds):
        tool_fns, mock_creds = tool_fns_with_creds
        tool_fns["get_account_info"](provider="")
        mock_creds.get_all_account_info.assert_called_once()

    def test_count_matches_accounts_length(self, tool_fns_with_creds):
        tool_fns, _ = tool_fns_with_creds
        result = tool_fns["get_account_info"]()
        assert result["count"] == len(result["accounts"])
