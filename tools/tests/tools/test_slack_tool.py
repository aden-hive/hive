"""Tests for Slack tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.slack_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def slack_send_message_fn(mcp: FastMCP):
    """Register and return the slack_send_message tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["slack_send_message"].fn


@pytest.fixture
def slack_list_channels_fn(mcp: FastMCP):
    """Register and return the slack_list_channels tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["slack_list_channels"].fn


@pytest.fixture
def slack_get_channel_history_fn(mcp: FastMCP):
    """Register and return the slack_get_channel_history tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["slack_get_channel_history"].fn


@pytest.fixture
def slack_add_reaction_fn(mcp: FastMCP):
    """Register and return the slack_add_reaction tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["slack_add_reaction"].fn


@pytest.fixture
def slack_get_user_info_fn(mcp: FastMCP):
    """Register and return the slack_get_user_info tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["slack_get_user_info"].fn


class TestSlackCredentials:
    """Tests for Slack credential handling."""

    def test_no_credentials_returns_error(self, slack_send_message_fn, monkeypatch):
        """Send without credentials returns helpful error."""
        monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)

        result = slack_send_message_fn(channel="C123", text="Hello")

        assert "error" in result
        assert "Slack credentials not configured" in result["error"]
        assert "help" in result


class TestSlackSendMessage:
    """Tests for slack_send_message tool."""

    def test_send_message_success(self, slack_send_message_fn, monkeypatch):
        """Successful message send returns channel and ts."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": "C123",
                "ts": "1234567890.123456",
                "message": {"text": "Hello"},
            }
            mock_post.return_value = mock_response

            result = slack_send_message_fn(channel="C123", text="Hello")

        assert result["success"] is True
        assert result["channel"] == "C123"
        assert result["ts"] == "1234567890.123456"

    def test_send_message_invalid_auth(self, slack_send_message_fn, monkeypatch):
        """Invalid auth returns appropriate error."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-invalid")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": False, "error": "invalid_auth"}
            mock_post.return_value = mock_response

            result = slack_send_message_fn(channel="C123", text="Hello")

        assert "error" in result
        assert "Invalid Slack bot token" in result["error"]

    def test_send_message_channel_not_found(self, slack_send_message_fn, monkeypatch):
        """Channel not found returns appropriate error."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": False, "error": "channel_not_found"}
            mock_post.return_value = mock_response

            result = slack_send_message_fn(channel="invalid", text="Hello")

        assert "error" in result
        assert "Channel not found" in result["error"]

    def test_send_message_with_thread(self, slack_send_message_fn, monkeypatch):
        """Thread reply includes thread_ts in request."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": "C123",
                "ts": "1234567890.123457",
                "message": {},
            }
            mock_post.return_value = mock_response

            result = slack_send_message_fn(
                channel="C123", text="Reply", thread_ts="1234567890.123456"
            )

        assert result["success"] is True
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["thread_ts"] == "1234567890.123456"


class TestSlackListChannels:
    """Tests for slack_list_channels tool."""

    def test_list_channels_success(self, slack_list_channels_fn, monkeypatch):
        """List channels returns channel list."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channels": [
                    {"id": "C001", "name": "general", "is_private": False, "num_members": 50},
                    {"id": "C002", "name": "random", "is_private": False, "num_members": 30},
                ],
            }
            mock_get.return_value = mock_response

            result = slack_list_channels_fn()

        assert result["success"] is True
        assert result["count"] == 2
        assert result["channels"][0]["name"] == "general"


class TestSlackGetChannelHistory:
    """Tests for slack_get_channel_history tool."""

    def test_get_history_success(self, slack_get_channel_history_fn, monkeypatch):
        """Get history returns messages."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "messages": [
                    {"ts": "1234567890.1", "user": "U001", "text": "Hello", "type": "message"},
                    {"ts": "1234567890.2", "user": "U002", "text": "Hi", "type": "message"},
                ],
            }
            mock_get.return_value = mock_response

            result = slack_get_channel_history_fn(channel="C123")

        assert result["success"] is True
        assert result["count"] == 2
        assert result["messages"][0]["text"] == "Hello"


class TestSlackAddReaction:
    """Tests for slack_add_reaction tool."""

    def test_add_reaction_success(self, slack_add_reaction_fn, monkeypatch):
        """Add reaction returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = slack_add_reaction_fn(
                channel="C123", timestamp="1234567890.123456", emoji="thumbsup"
            )

        assert result["success"] is True

    def test_add_reaction_strips_colons(self, slack_add_reaction_fn, monkeypatch):
        """Emoji colons are stripped."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            slack_add_reaction_fn(
                channel="C123", timestamp="1234567890.123456", emoji=":thumbsup:"
            )

        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"]["name"] == "thumbsup"


class TestSlackGetUserInfo:
    """Tests for slack_get_user_info tool."""

    def test_get_user_info_success(self, slack_get_user_info_fn, monkeypatch):
        """Get user info returns user details."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "user": {
                    "id": "U001",
                    "name": "jdoe",
                    "real_name": "John Doe",
                    "is_admin": False,
                    "is_bot": False,
                    "tz": "America/Los_Angeles",
                    "profile": {"email": "jdoe@example.com", "title": "Engineer"},
                },
            }
            mock_get.return_value = mock_response

            result = slack_get_user_info_fn(user_id="U001")

        assert result["success"] is True
        assert result["user"]["name"] == "jdoe"
        assert result["user"]["email"] == "jdoe@example.com"
