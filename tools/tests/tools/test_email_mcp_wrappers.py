"""Tests for the generic Email Tool MCP wrappers."""

from unittest.mock import MagicMock, patch
import pytest

from fastmcp import FastMCP
from aden_tools.tools.email_tool import register_tools


@pytest.fixture
def email_send_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["email_send"].fn


@pytest.fixture
def email_list_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["email_list"].fn


@pytest.fixture
def email_search_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["email_search"].fn


@pytest.fixture
def email_read_fn(mcp: FastMCP):
    register_tools(mcp)
    return mcp._tool_manager._tools["email_read"].fn


class TestEmailToolsWrapper:

    def test_send_email_missing_body_returns_error(self, email_send_fn):
        res = email_send_fn(to=["user@example.com"], subject="Test subject")
        assert "error" in res
        assert "or body_html must be provided" in res["error"]

    @patch("aden_tools.tools.email_tool.registry.ProviderRegistry.get_provider")
    def test_send_email_success(self, mock_get_provider, email_send_fn):
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"success": True, "message_id": "123"}
        mock_provider.send_email.return_value = mock_response
        
        mock_get_provider.return_value = mock_provider

        res = email_send_fn(
            to=["user@example.com"], 
            subject="Test subject",
            body_text="Hello",
            provider="mock"
        )
        
        assert res.get("success") is True
        assert res.get("message_id") == "123"
        mock_provider.send_email.assert_called_once()

    @patch("aden_tools.tools.email_tool.registry.ProviderRegistry.get_provider")
    def test_list_emails_success(self, mock_get_provider, email_list_fn):
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"messages": [], "provider": "mock"}
        mock_provider.list_emails.return_value = mock_response
        
        mock_get_provider.return_value = mock_provider

        res = email_list_fn(folder="inbox", limit=5, provider="mock")
        
        assert "messages" in res
        assert res.get("provider") == "mock"
        mock_provider.list_emails.assert_called_once()

    @patch("aden_tools.tools.email_tool.registry.ProviderRegistry.get_provider")
    def test_read_email_success(self, mock_get_provider, email_read_fn):
        mock_provider = MagicMock()
        mock_response = MagicMock()
        mock_response.model_dump.return_value = {"message": {"body_text": "text"}, "provider": "mock"}
        mock_provider.read_email.return_value = mock_response
        
        mock_get_provider.return_value = mock_provider

        res = email_read_fn(message_id="msg123", provider="mock")
        
        assert "message" in res
        mock_provider.read_email.assert_called_once()

    @patch("aden_tools.tools.email_tool.registry.ProviderRegistry.get_provider")
    def test_tool_exceptions_caught(self, mock_get_provider, email_search_fn):
        mock_provider = MagicMock()
        mock_provider.search_emails.side_effect = Exception("Provider crashed")
        
        mock_get_provider.return_value = mock_provider

        res = email_search_fn(query="urgent")
        assert "error" in res
        assert "Provider crashed" in res["error"]
