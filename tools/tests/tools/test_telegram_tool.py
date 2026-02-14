"""
Tests for Telegram Bot tool.

Covers:
- _TelegramClient methods (send_message, send_document, get_me,
  edit_message_text, delete_message, forward_message, send_photo,
  send_chat_action, pin_chat_message, unpin_chat_message, get_chat)
- Error handling (API errors, invalid token, rate limiting)
- Credential retrieval (CredentialStoreAdapter vs env var)
- MCP tool functions (telegram_send_message, telegram_send_document,
  telegram_edit_message, telegram_delete_message, telegram_forward_message,
  telegram_send_photo, telegram_send_chat_action, telegram_get_chat,
  telegram_pin_message, telegram_unpin_message)
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

    # --- New client method tests ---

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_edit_message_text(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 456, "text": "Updated text"},
        }
        mock_post.return_value = mock_response

        result = self.client.edit_message_text(chat_id="123", message_id=456, text="Updated text")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "123"
        assert call_kwargs["json"]["message_id"] == 456
        assert call_kwargs["json"]["text"] == "Updated text"
        assert "editMessageText" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_edit_message_text_with_parse_mode(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_post.return_value = mock_response

        self.client.edit_message_text(
            chat_id="123", message_id=456, text="<b>Bold</b>", parse_mode="HTML"
        )

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["parse_mode"] == "HTML"

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_delete_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        result = self.client.delete_message(chat_id="123", message_id=456)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "123"
        assert call_kwargs["json"]["message_id"] == 456
        assert "deleteMessage" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_forward_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 789, "forward_date": 1234567890},
        }
        mock_post.return_value = mock_response

        result = self.client.forward_message(chat_id="456", from_chat_id="123", message_id=789)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "456"
        assert call_kwargs["json"]["from_chat_id"] == "123"
        assert call_kwargs["json"]["message_id"] == 789
        assert "forwardMessage" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_forward_message_silent(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_post.return_value = mock_response

        self.client.forward_message(
            chat_id="456",
            from_chat_id="123",
            message_id=789,
            disable_notification=True,
        )

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["disable_notification"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_send_photo(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {
                "message_id": 101,
                "photo": [{"file_id": "photo123", "width": 800, "height": 600}],
            },
        }
        mock_post.return_value = mock_response

        result = self.client.send_photo(
            chat_id="123",
            photo="https://example.com/image.jpg",
            caption="Test photo",
        )

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "123"
        assert call_kwargs["json"]["photo"] == "https://example.com/image.jpg"
        assert call_kwargs["json"]["caption"] == "Test photo"
        assert "sendPhoto" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_send_photo_no_caption(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": {}}
        mock_post.return_value = mock_response

        self.client.send_photo(chat_id="123", photo="https://example.com/image.jpg")

        call_kwargs = mock_post.call_args.kwargs
        assert "caption" not in call_kwargs["json"]

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_send_chat_action(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        result = self.client.send_chat_action(chat_id="123", action="typing")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "123"
        assert call_kwargs["json"]["action"] == "typing"
        assert "sendChatAction" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_pin_chat_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        result = self.client.pin_chat_message(chat_id="123", message_id=456)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "123"
        assert call_kwargs["json"]["message_id"] == 456
        assert "pinChatMessage" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_pin_chat_message_silent(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        self.client.pin_chat_message(chat_id="123", message_id=456, disable_notification=True)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["disable_notification"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_unpin_chat_message(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        result = self.client.unpin_chat_message(chat_id="123", message_id=456)

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "123"
        assert call_kwargs["json"]["message_id"] == 456
        assert "unpinChatMessage" in mock_post.call_args.args[0]
        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    def test_unpin_chat_message_most_recent(self, mock_post):
        """Omitting message_id should unpin the most recently pinned message."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        self.client.unpin_chat_message(chat_id="123")

        call_kwargs = mock_post.call_args.kwargs
        assert "message_id" not in call_kwargs["json"]

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.get")
    def test_get_chat(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {
                "id": -1001234567890,
                "title": "Test Group",
                "type": "supergroup",
                "description": "A test group",
            },
        }
        mock_get.return_value = mock_response

        result = self.client.get_chat(chat_id="-1001234567890")

        mock_get.assert_called_once()
        assert "getChat" in mock_get.call_args.args[0]
        assert result["ok"] is True
        assert result["result"]["type"] == "supergroup"


# --- register_tools tests ---


class TestRegisterTools:
    def setup_method(self):
        self.mcp = FastMCP("test-telegram")

    def test_register_tools_creates_tools(self):
        register_tools(self.mcp)

        # Check that all tools are registered
        tool_names = [tool.name for tool in self.mcp._tool_manager._tools.values()]
        assert "telegram_send_message" in tool_names
        assert "telegram_send_document" in tool_names
        assert "telegram_edit_message" in tool_names
        assert "telegram_delete_message" in tool_names
        assert "telegram_forward_message" in tool_names
        assert "telegram_send_photo" in tool_names
        assert "telegram_send_chat_action" in tool_names
        assert "telegram_get_chat" in tool_names
        assert "telegram_pin_message" in tool_names
        assert "telegram_unpin_message" in tool_names

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


# --- MCP tool tests for new operations ---


class TestNewToolOperations:
    """Tests for the 8 new MCP tool functions."""

    def setup_method(self):
        self.mcp = FastMCP("test-telegram")

    def _get_tools(self):
        return {t.name: t for t in self.mcp._tool_manager._tools.values()}

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_edit_message_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 456, "text": "Updated"},
        }
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_edit_message"].fn(chat_id="123", message_id=456, text="Updated")

        assert result["ok"] is True
        assert result["result"]["text"] == "Updated"

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_delete_message_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_delete_message"].fn(chat_id="123", message_id=456)

        assert result["success"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_forward_message_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 789},
        }
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_forward_message"].fn(
            chat_id="456", from_chat_id="123", message_id=789
        )

        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_send_photo_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {"message_id": 101, "photo": [{"file_id": "abc"}]},
        }
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_send_photo"].fn(chat_id="123", photo="https://example.com/img.jpg")

        assert result["ok"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_send_chat_action_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_send_chat_action"].fn(chat_id="123", action="typing")

        assert result["success"] is True

    def test_send_chat_action_invalid_action(self):
        """Invalid action should return error without making API call."""
        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        with patch("os.getenv", return_value="test_token"):
            result = tools["telegram_send_chat_action"].fn(chat_id="123", action="dancing")

        assert "error" in result
        assert "Invalid action" in result["error"]
        assert "help" in result

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.get")
    @patch("os.getenv", return_value="test_token")
    def test_get_chat_success(self, mock_getenv, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "ok": True,
            "result": {
                "id": -1001234567890,
                "title": "Test Group",
                "type": "supergroup",
            },
        }
        mock_get.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_get_chat"].fn(chat_id="-1001234567890")

        assert result["ok"] is True
        assert result["result"]["type"] == "supergroup"

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_pin_message_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_pin_message"].fn(chat_id="123", message_id=456)

        assert result["success"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_unpin_message_success(self, mock_getenv, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_unpin_message"].fn(chat_id="123", message_id=456)

        assert result["success"] is True

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_unpin_message_most_recent(self, mock_getenv, mock_post):
        """message_id=0 should unpin most recent (omit message_id from payload)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ok": True, "result": True}
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_unpin_message"].fn(chat_id="123", message_id=0)

        assert result["success"] is True
        # Verify message_id was NOT included in the API call
        call_kwargs = mock_post.call_args.kwargs
        assert "message_id" not in call_kwargs["json"]

    # --- No-token error tests for new tools ---

    @patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": ""}, clear=False)
    def test_new_tools_return_error_without_token(self):
        """All new tools should return error dict when no token is configured."""
        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()

        new_tool_calls = {
            "telegram_edit_message": {"chat_id": "1", "message_id": 1, "text": "x"},
            "telegram_delete_message": {"chat_id": "1", "message_id": 1},
            "telegram_forward_message": {
                "chat_id": "1",
                "from_chat_id": "2",
                "message_id": 1,
            },
            "telegram_send_photo": {"chat_id": "1", "photo": "http://x.com/a.jpg"},
            "telegram_send_chat_action": {"chat_id": "1", "action": "typing"},
            "telegram_get_chat": {"chat_id": "1"},
            "telegram_pin_message": {"chat_id": "1", "message_id": 1},
            "telegram_unpin_message": {"chat_id": "1"},
        }

        with patch("os.getenv", return_value=None):
            for tool_name, kwargs in new_tool_calls.items():
                result = tools[tool_name].fn(**kwargs)
                assert "error" in result, f"{tool_name} should return error without token"
                assert "not configured" in result["error"]


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


# --- Error handling tests for new operations ---


class TestNewOperationsErrorHandling:
    """Verify new MCP tools return error dicts on timeout/network errors."""

    def setup_method(self):
        self.mcp = FastMCP("test-telegram")

    def _get_tools(self):
        return {t.name: t for t in self.mcp._tool_manager._tools.values()}

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_edit_message_timeout(self, mock_getenv, mock_post):
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_edit_message"].fn(chat_id="123", message_id=1, text="test")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_delete_message_network_error(self, mock_getenv, mock_post):
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_delete_message"].fn(chat_id="123", message_id=1)

        assert "error" in result
        assert "network" in result["error"].lower() or "connection" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_forward_message_timeout(self, mock_getenv, mock_post):
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_forward_message"].fn(
            chat_id="456", from_chat_id="123", message_id=1
        )

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_send_photo_network_error(self, mock_getenv, mock_post):
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_send_photo"].fn(chat_id="123", photo="https://example.com/img.jpg")

        assert "error" in result
        assert "network" in result["error"].lower() or "connection" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.get")
    @patch("os.getenv", return_value="test_token")
    def test_get_chat_timeout(self, mock_getenv, mock_get):
        import httpx

        mock_get.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_get_chat"].fn(chat_id="123")

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_pin_message_timeout(self, mock_getenv, mock_post):
        import httpx

        mock_post.side_effect = httpx.TimeoutException("Request timed out")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_pin_message"].fn(chat_id="123", message_id=1)

        assert "error" in result
        assert "timed out" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_unpin_message_network_error(self, mock_getenv, mock_post):
        import httpx

        mock_post.side_effect = httpx.ConnectError("Connection failed")

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_unpin_message"].fn(chat_id="123", message_id=1)

        assert "error" in result
        assert "network" in result["error"].lower() or "connection" in result["error"].lower()

    @patch("aden_tools.tools.telegram_tool.telegram_tool.httpx.post")
    @patch("os.getenv", return_value="test_token")
    def test_delete_message_api_error_returned(self, mock_getenv, mock_post):
        """When API returns an error (e.g. permission denied), tool should propagate it."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_post.return_value = mock_response

        register_tools(self.mcp, credentials=None)
        tools = self._get_tools()
        result = tools["telegram_delete_message"].fn(chat_id="123", message_id=1)

        assert "error" in result
