"""Tests for account info tool with FastMCP."""

from unittest.mock import MagicMock

import pytest
from fastmcp import FastMCP

from aden_tools.tools.account_info_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


def _get_tool_fn(mcp: FastMCP, name: str):
    """Helper to fetch a registered tool's underlying function."""
    return mcp._tool_manager._tools[name].fn


# ============================================================================
# No-Credentials Path
# ============================================================================


class TestAccountInfoNoCredentials:
    """Tests for the no-credential-store-configured path."""

    def test_no_credentials_returns_friendly_message(self, mcp: FastMCP):
        """Without a credential adapter, tool returns empty accounts + message."""
        register_tools(mcp, credentials=None)
        fn = _get_tool_fn(mcp, "get_account_info")

        result = fn()

        assert result == {
            "accounts": [],
            "message": "No credential store configured",
        }

    def test_no_credentials_with_provider_arg(self, mcp: FastMCP):
        """Provider filter is ignored when no credential store is configured."""
        register_tools(mcp, credentials=None)
        fn = _get_tool_fn(mcp, "get_account_info")

        result = fn(provider="google")

        assert result["accounts"] == []
        assert "message" in result


# ============================================================================
# All-Accounts Path
# ============================================================================


class TestAccountInfoAllAccounts:
    """Tests for listing every connected account (no provider filter)."""

    def test_all_accounts_success(self, mcp: FastMCP):
        """Empty provider arg routes to get_all_account_info()."""
        creds = MagicMock()
        creds.get_all_account_info.return_value = [
            {"provider": "google", "account_id": "g1", "identity": "a@example.com"},
            {"provider": "github", "account_id": "gh1", "identity": "octocat"},
        ]
        register_tools(mcp, credentials=creds)
        fn = _get_tool_fn(mcp, "get_account_info")

        result = fn()

        creds.get_all_account_info.assert_called_once_with()
        creds.list_accounts.assert_not_called()
        assert result["count"] == 2
        assert result["accounts"][0]["provider"] == "google"

    def test_all_accounts_empty(self, mcp: FastMCP):
        """No connected accounts returns count=0."""
        creds = MagicMock()
        creds.get_all_account_info.return_value = []
        register_tools(mcp, credentials=creds)
        fn = _get_tool_fn(mcp, "get_account_info")

        result = fn()

        assert result == {"accounts": [], "count": 0}


# ============================================================================
# Provider-Filter Path
# ============================================================================


class TestAccountInfoProviderFilter:
    """Tests for the provider-filtered branch (credential-retrieval-from-store)."""

    def test_provider_filter_calls_list_accounts(self, mcp: FastMCP):
        """Provider arg routes to list_accounts(provider) on the adapter."""
        creds = MagicMock()
        creds.list_accounts.return_value = [
            {"provider": "google", "account_id": "g1", "identity": "a@example.com"},
        ]
        register_tools(mcp, credentials=creds)
        fn = _get_tool_fn(mcp, "get_account_info")

        result = fn(provider="google")

        creds.list_accounts.assert_called_once_with("google")
        creds.get_all_account_info.assert_not_called()
        assert result["count"] == 1
        assert result["accounts"][0]["provider"] == "google"

    def test_provider_filter_no_matches(self, mcp: FastMCP):
        """Unknown provider returns count=0 and empty accounts list."""
        creds = MagicMock()
        creds.list_accounts.return_value = []
        register_tools(mcp, credentials=creds)
        fn = _get_tool_fn(mcp, "get_account_info")

        result = fn(provider="nonexistent")

        creds.list_accounts.assert_called_once_with("nonexistent")
        assert result == {"accounts": [], "count": 0}


# ============================================================================
# Tool Registration
# ============================================================================


class TestAccountInfoToolRegistration:
    """Tests for tool registration."""

    def test_tool_registered_without_credentials(self, mcp: FastMCP):
        """get_account_info is registered even when no credentials are provided."""
        register_tools(mcp)
        assert "get_account_info" in mcp._tool_manager._tools

    def test_tool_registered_with_credentials(self, mcp: FastMCP):
        """get_account_info is registered when a credential adapter is provided."""
        register_tools(mcp, credentials=MagicMock())
        assert "get_account_info" in mcp._tool_manager._tools
