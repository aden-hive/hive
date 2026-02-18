"""
Tests for Telegram Bot tool.

Covers:
- _TelegramClient methods (send_message, send_document, get_me)
- Error handling (API errors, invalid token, rate limiting)
- Credential retrieval (CredentialStoreAdapter vs env var)
- MCP tool functions (telegram_send_message, telegram_send_document)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.telegram_tool.telegram_tool import (
    _TelegramClient,
    register_tools,
)

# --- _TelegramClient tests ---


class TestTelegramClient:
    def setup_method(self):
        self.client = _TelegramClient("123456789:ABCdefGHIjklMNOpqrsTUVwxyz")

    def test_base_url(self):
        assert "123456789:ABCdefGHIjklMNOpqrsTUVwxyz" in self.client._base_url
        assert self.client._base_url.startswith("https://api.telegram.org/bot")

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"ok": True, "result": {"message_id": 123}}
        result = self.client._handle_response(response)
        assert result["ok"] is True
        assert result["result"]["message_id"] == 123

    def test_handle_response_401(self):
        response = MagicMock()
        response.status_code = 401
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Invalid" in result["error"]

    def test_handle_response_400(self):
        response = MagicMock()
        response.status_code = 400
        response.json.return_value = {"description": "Bad Request: chat not found"}
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Bad request" in result["error"]

    def test_handle_response_403(self):
        response = MagicMock()
        response.status_code = 403
        result = self.client._handle_response(response)
        assert "error" in result
        assert "blocked" in result["error"]

    def test_handle_response_404(self):
        response = MagicMock()
        response.status_code = 404
        result = self.client._handle_response(response)
        assert "error" in result
        assert "not found" in result["error"]

    def test_handle_response_429(self):
        response = MagicMock()
        response.status_code = 429
        result = self.client._handle_response(response)
        assert "error" in result
        assert "Rate limit" in result["error"]

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_send_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 456, "text": "Hello"},
        }
        mock_post.return_value = mock_response

        result = self.client.send_message(chat_id="123", text="Hello")

        mock_post.assert_called_once()
        assert result["ok"] is True
        assert result["result"]["message_id"] == 456

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_send_message_with_parse_mode(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_post.return_value = mock_response

        self.client.send_message(chat_id="123", text="<b>Bold</b>", parse_mode="HTML")

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["parse_mode"] == "HTML"

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_send_document(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 789, "document": {"file_id": "abc123"}},
        }
        mock_post.return_value = mock_response

        result = self.client.send_document(
            chat_id="123",
            document="https://example.com/file.pdf",
            caption="Test doc",
        )

        mock_post.assert_called_once()
        assert result["ok"] is True
        assert result["result"]["message_id"] == 789

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.get")
    def test_get_me(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"id": 123, "is_bot": True, "username": "test_bot"},
        }
        mock_get.return_value = mock_response

        result = self.client.get_me()

        mock_get.assert_called_once()
        assert result["ok"] is True
        assert result["result"]["is_bot"] is True


# --- register_tools tests ---


class TestRegisterTools:
    def setup_method(self):
        self.mcp = FastMCP("test-telegram")

    def test_register_tools_creates_tools(self):
        register_tools(self.mcp)

        # Check that tools are registered
        tool_names = [tool.name for tool in self.mcp._tool_manager._tools.values()]
        assert "telegram_send_message" in tool_names
        assert "telegram_send_document" in tool_names

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": ""}, clear=False)
    def test_send_message_no_token_error(self):
        register_tools(self.mcp, credentials=None)

        # Get the registered tool
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}
        send_message = tools["telegram_send_message"]

        # Call with no token configured
        with patch("os.getenv", return_value=None):
            result = send_message.fn(chat_id="123", text="test")

        assert "error" in result
        assert "not configured" in result["error"]

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_send_message_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {"message_id": 1}}
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}
        send_message = tools["telegram_send_message"]

        result = send_message.fn(chat_id="123", text="Hello!")

        assert result["ok"] is True

    def test_credentials_adapter_used(self):
        mock_credentials = MagicMock()
        mock_credentials.get.return_value = "token_from_store"

        register_tools(self.mcp, credentials=mock_credentials)
        tools = {t.name: t for t in self.mcp._tool_manager._tools.values()}

        # The credentials should be used when tools are called
        with patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True, "result": {}}
            mock_post.return_value = mock_response

            tools["telegram_send_message"].fn(chat_id="123", text="test")

            # Verify the token from credentials was used
            call_url = mock_post.call_args.args[0]
            assert "token_from_store" in call_url


# --- Error handling tests ---


class TestErrorHandling:
    def setup_method(self):
        self.client = _TelegramClient("test_token")

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_network_error(self, mock_post):
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        with pytest.raises(httpx.ConnectError):
            self.client.send_message(chat_id="123", text="test")

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_timeout_error(self, mock_post):
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        with pytest.raises(httpx.TimeoutException):
            self.client.send_message(chat_id="123", text="test")

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_tool_returns_error_on_timeout(self, mock_getenv, mock_post):
        """MCP tool should return error dict on timeout, not raise."""
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        mcp = FastMCP("test-telegram")
        register_tools(mcp, credentials=None)
        tools = {t.name: t for t in mcp._tool_manager._tools.values()}

        result = tools["telegram_send_message"].fn(chat_id="123", text="test")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_tool_returns_error_on_network_failure(self, mock_getenv, mock_post):
        """MCP tool should return error dict on network error, not raise."""
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        mcp = FastMCP("test-telegram")
        register_tools(mcp, credentials=None)
        tools = {t.name: t for t in mcp._tool_manager._tools.values()}

        result = tools["telegram_send_message"].fn(chat_id="123", text="test")

        assert "error" in result
        assert "network" in result["error"].lower() or "connection" in result["error"].lower()

    def test_handle_response_generic_error(self):
        response = MagicMock()
        response.status_code = 500
        response.json.return_value = {"description": "Internal server error"}
        response.text = "Internal server error"

        result = self.client._handle_response(response)

        assert "error" in result
        assert "500" in result["error"]
