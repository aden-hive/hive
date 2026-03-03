"""
Tests for Discord tool.

Covers:
- _DiscordClient methods (list_guilds, list_channels, send_message, get_messages)
- Error handling (401, 403, 404, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 4 MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.discord_tool.discord_tool import (
    MAX_MESSAGE_LENGTH,
    MAX_RETRIES,
    _DiscordClient,
    register_tools,
)

# --- _DiscordClient tests ---


class TestDiscordClient:
    def setup_method(self):
        self.client = _DiscordClient("test-bot-token")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bot test-bot-token"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "123", "username": "test-bot"}
        assert self.client._handle_response(response) == {"id": "123", "username": "test-bot"}

    def test_handle_response_204(self):
        response = MagicMock()
        response.status_code = 204
        result = self.client._handle_response(response)
        assert result == {"success": True}

    def test_handle_response_rate_limit_429(self):
        response = MagicMock()
        response.status_code = 429
        response.json.return_value = {"message": "Rate limit", "retry_after": 2.5}
        response.text = '{"message": "Rate limit", "retry_after": 2.5}'
        result = self.client._handle_response(response)
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert result["retry_after"] == 2.5

    @pytest.mark.parametrize(
        "status_code",
        [401, 403, 404, 500],
    )
    def test_handle_response_errors(self, status_code):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = {"message": "Test error"}
        response.text = "Test error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert str(status_code) in result["error"]

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_guilds(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "g1", "name": "Test Server"},
                    {"id": "g2", "name": "Another Server"},
                ]
            ),
        )
        result = self.client.list_guilds()
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "GET"
        assert "users/@me/guilds" in mock_request.call_args[0][1]
        assert len(result) == 2
        assert result[0]["name"] == "Test Server"

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_channels_text_only_default(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "c1", "name": "general", "type": 0},
                    {"id": "c2", "name": "incidents", "type": 0},
                    {"id": "c3", "name": "voice-chat", "type": 2},
                ]
            ),
        )
        result = self.client.list_channels("guild-123")
        assert len(result) == 2
        assert result[0]["name"] == "general"
        assert result[1]["name"] == "incidents"
        assert not any(c["type"] == 2 for c in result)

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_channels_all_types(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "c1", "name": "general", "type": 0},
                    {"id": "c2", "name": "voice-chat", "type": 2},
                ]
            ),
        )
        result = self.client.list_channels("guild-123", text_only=False)
        assert len(result) == 2
        assert result[0]["type"] == 0
        assert result[1]["type"] == 2

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_send_message(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "m123",
                    "channel_id": "c1",
                    "content": "Hello world",
                }
            ),
        )
        result = self.client.send_message("c1", "Hello world")
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "POST"
        assert "channels/c1/messages" in mock_request.call_args[0][1]
        assert result["content"] == "Hello world"
        assert result["channel_id"] == "c1"

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_get_messages(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "m1", "content": "First"},
                    {"id": "m2", "content": "Second"},
                ]
            ),
        )
        result = self.client.get_messages("c1", limit=10)
        mock_request.assert_called_once()
        assert mock_request.call_args[1]["params"] == {"limit": 10}
        assert len(result) == 2
        assert result[0]["content"] == "First"

    @patch("aden_tools.tools.discord_tool.discord_tool.time.sleep")
    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_retry_on_429_then_success(self, mock_request, mock_sleep):
        mock_request.side_effect = [
            MagicMock(
                status_code=429,
                json=MagicMock(return_value={"retry_after": 0.01}),
                text="{}",
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=[{"id": "g1", "name": "Server"}]),
            ),
        ]
        result = self.client.list_guilds()
        assert len(result) == 1
        assert result[0]["name"] == "Server"
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once_with(0.01)

    @patch("aden_tools.tools.discord_tool.discord_tool.time.sleep")
    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_retry_exhausted_returns_error(self, mock_request, mock_sleep):
        mock_request.return_value = MagicMock(
            status_code=429,
            json=MagicMock(return_value={"retry_after": 0.01}),
            text="{}",
        )
        result = self.client.list_guilds()
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert mock_request.call_count == MAX_RETRIES + 1


# --- Tool registration tests ---


class TestDiscordListGuildsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_guilds_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{"id": "g1", "name": "Test Server"}]),
        )
        result = self._fn("discord_list_guilds")()
        assert result["success"] is True
        assert len(result["guilds"]) == 1
        assert result["guilds"][0]["name"] == "Test Server"

    def test_list_guilds_no_credentials(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        register_tools(mcp, credentials=None)
        with patch.dict("os.environ", {"DISCORD_BOT_TOKEN": ""}, clear=False):
            result = next(f for f in fns if f.__name__ == "discord_list_guilds")()
        assert "error" in result
        assert "not configured" in result["error"]


class TestDiscordListChannelsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_channels_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "c1", "name": "general", "type": 0},
                ]
            ),
        )
        result = self._fn("discord_list_channels")("guild-123")
        assert result["success"] is True
        assert len(result["channels"]) == 1
        assert result["channels"][0]["name"] == "general"

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_channels_text_only_filter(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "c1", "name": "general", "type": 0},
                    {"id": "c2", "name": "voice", "type": 2},
                ]
            ),
        )
        result = self._fn("discord_list_channels")("guild-123", text_only=True)
        assert result["success"] is True
        assert len(result["channels"]) == 1
        assert result["channels"][0]["name"] == "general"

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_list_channels_error(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=404,
            json=MagicMock(return_value={"message": "Unknown Guild"}),
            text="Unknown Guild",
        )
        result = self._fn("discord_list_channels")("bad-guild")
        assert "error" in result
        assert "404" in result["error"]


class TestDiscordSendMessageTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_send_message_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "m123",
                    "channel_id": "c1",
                    "content": "Incident resolved",
                }
            ),
        )
        result = self._fn("discord_send_message")("c1", "Incident resolved")
        assert result["success"] is True
        assert result["message"]["content"] == "Incident resolved"

    def test_send_message_length_validation(self):
        long_content = "x" * (MAX_MESSAGE_LENGTH + 1)
        result = self._fn("discord_send_message")("c1", long_content)
        assert "error" in result
        assert str(MAX_MESSAGE_LENGTH) in result["error"]
        assert result["max_length"] == MAX_MESSAGE_LENGTH
        assert result["provided"] == MAX_MESSAGE_LENGTH + 1

    def test_send_message_exactly_at_limit(self):
        content = "x" * MAX_MESSAGE_LENGTH
        with patch("aden_tools.tools.discord_tool.discord_tool.httpx.request") as mock_request:
            mock_request.return_value = MagicMock(
                status_code=200,
                json=MagicMock(return_value={"id": "m1", "channel_id": "c1", "content": content}),
            )
            result = self._fn("discord_send_message")("c1", content)
        assert result["success"] is True

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_send_message_rate_limit_429_exhausted(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=429,
            json=MagicMock(return_value={"message": "Rate limit", "retry_after": 5}),
            text='{"message": "Rate limit", "retry_after": 5}',
        )
        result = self._fn("discord_send_message")("c1", "Hello")
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert result.get("retry_after") == 5
        assert mock_request.call_count == MAX_RETRIES + 1

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_send_message_rate_limit_then_success(self, mock_request):
        mock_request.side_effect = [
            MagicMock(
                status_code=429,
                json=MagicMock(return_value={"retry_after": 0.01}),
                text="{}",
            ),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value={"id": "m1", "channel_id": "c1", "content": "Hi"}),
            ),
        ]
        result = self._fn("discord_send_message")("c1", "Hi")
        assert result["success"] is True
        assert result["message"]["content"] == "Hi"
        assert mock_request.call_count == 2


class TestDiscordGetMessagesTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-token"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.discord_tool.discord_tool.httpx.request")
    def test_get_messages_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "m1", "content": "First message"},
                ]
            ),
        )
        result = self._fn("discord_get_messages")("c1", limit=10)
        assert result["success"] is True
        assert len(result["messages"]) == 1
        assert result["messages"][0]["content"] == "First message"


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_discord_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "discord" in CREDENTIAL_SPECS

    def test_discord_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["discord"]
        assert spec.env_var == "DISCORD_BOT_TOKEN"

    def test_discord_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["discord"]
        assert "discord_list_guilds" in spec.tools
        assert "discord_list_channels" in spec.tools
        assert "discord_send_message" in spec.tools
        assert "discord_get_messages" in spec.tools
        assert len(spec.tools) == 4
