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

            slack_add_reaction_fn(channel="C123", timestamp="1234567890.123456", emoji=":thumbsup:")

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


# ============================================================================
# Additional Tool Tests (v2 - 15 tools)
# ============================================================================


@pytest.fixture
def get_tool_fn(mcp: FastMCP):
    """Factory fixture to get any tool function by name."""
    register_tools(mcp)

    def _get(name: str):
        return mcp._tool_manager._tools[name].fn

    return _get


class TestSlackUpdateMessage:
    """Tests for slack_update_message tool."""

    def test_update_message_success(self, get_tool_fn, monkeypatch):
        """Update message returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_update_message")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": "C123",
                "ts": "1234567890.123456",
                "text": "Updated text",
            }
            mock_post.return_value = mock_response

            result = fn(channel="C123", ts="1234567890.123456", text="Updated text")

        assert result["success"] is True
        assert result["ts"] == "1234567890.123456"


class TestSlackDeleteMessage:
    """Tests for slack_delete_message tool."""

    def test_delete_message_success(self, get_tool_fn, monkeypatch):
        """Delete message returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_delete_message")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": "C123",
                "ts": "1234567890.123456",
            }
            mock_post.return_value = mock_response

            result = fn(channel="C123", ts="1234567890.123456")

        assert result["success"] is True


class TestSlackScheduleMessage:
    """Tests for slack_schedule_message tool."""

    def test_schedule_message_success(self, get_tool_fn, monkeypatch):
        """Schedule message returns scheduled_message_id."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_schedule_message")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": "C123",
                "scheduled_message_id": "Q123ABC",
                "post_at": 1769865600,
            }
            mock_post.return_value = mock_response

            result = fn(channel="C123", text="Scheduled!", post_at=1769865600)

        assert result["success"] is True
        assert result["scheduled_message_id"] == "Q123ABC"


class TestSlackCreateChannel:
    """Tests for slack_create_channel tool."""

    def test_create_channel_success(self, get_tool_fn, monkeypatch):
        """Create channel returns channel details."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_create_channel")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": {"id": "C999", "name": "new-channel", "is_private": False},
            }
            mock_post.return_value = mock_response

            result = fn(name="new-channel")

        assert result["success"] is True
        assert result["channel"]["id"] == "C999"


class TestSlackArchiveChannel:
    """Tests for slack_archive_channel tool."""

    def test_archive_channel_success(self, get_tool_fn, monkeypatch):
        """Archive channel returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_archive_channel")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(channel="C123")

        assert result["success"] is True


class TestSlackInviteToChannel:
    """Tests for slack_invite_to_channel tool."""

    def test_invite_to_channel_success(self, get_tool_fn, monkeypatch):
        """Invite to channel returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_invite_to_channel")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True, "channel": {"id": "C123"}}
            mock_post.return_value = mock_response

            result = fn(channel="C123", user_ids="U001,U002")

        assert result["success"] is True


class TestSlackSetChannelTopic:
    """Tests for slack_set_channel_topic tool."""

    def test_set_topic_success(self, get_tool_fn, monkeypatch):
        """Set channel topic returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_set_channel_topic")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True, "topic": "New topic"}
            mock_post.return_value = mock_response

            result = fn(channel="C123", topic="New topic")

        assert result["success"] is True


class TestSlackRemoveReaction:
    """Tests for slack_remove_reaction tool."""

    def test_remove_reaction_success(self, get_tool_fn, monkeypatch):
        """Remove reaction returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_remove_reaction")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(channel="C123", timestamp="1234567890.123456", emoji="thumbsup")

        assert result["success"] is True


class TestSlackListUsers:
    """Tests for slack_list_users tool."""

    def test_list_users_success(self, get_tool_fn, monkeypatch):
        """List users returns user list."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_list_users")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "members": [
                    {
                        "id": "U001",
                        "name": "alice",
                        "real_name": "Alice",
                        "is_bot": False,
                        "deleted": False,
                    },
                    {
                        "id": "U002",
                        "name": "bob",
                        "real_name": "Bob",
                        "is_bot": False,
                        "deleted": False,
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn()

        assert result["success"] is True
        assert result["count"] == 2


class TestSlackUploadFile:
    """Tests for slack_upload_file tool."""

    def test_upload_file_success(self, get_tool_fn, monkeypatch):
        """Upload file returns file details."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_upload_file")

        with patch("httpx.get") as mock_get, patch("httpx.post") as mock_post:
            # Mock getUploadURLExternal
            mock_url_response = MagicMock()
            mock_url_response.status_code = 200
            mock_url_response.json.return_value = {
                "ok": True,
                "upload_url": "https://files.slack.com/upload/v1/...",
                "file_id": "F123",
            }
            mock_get.return_value = mock_url_response

            # Mock upload and complete
            mock_upload_response = MagicMock()
            mock_upload_response.status_code = 200

            mock_complete_response = MagicMock()
            mock_complete_response.status_code = 200
            mock_complete_response.json.return_value = {
                "ok": True,
                "files": [
                    {"id": "F123", "name": "test.csv", "title": "Test", "permalink": "https://..."}
                ],
            }
            mock_post.side_effect = [mock_upload_response, mock_complete_response]

            result = fn(channel="C123", content="a,b,c", filename="test.csv")

        assert result["success"] is True
        assert result["file"]["id"] == "F123"


# ============================================================================
# Advanced Tool Tests (v3 - 11 new tools)
# ============================================================================


class TestSlackSearchMessages:
    """Tests for slack_search_messages tool."""

    def test_search_messages_success(self, get_tool_fn, monkeypatch):
        """Search messages returns results."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_search_messages")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "messages": {
                    "total": 2,
                    "matches": [
                        {
                            "text": "Hello world",
                            "user": "U001",
                            "ts": "123.456",
                            "channel": {"name": "general"},
                            "permalink": "https://...",
                        },
                        {
                            "text": "Hello there",
                            "user": "U002",
                            "ts": "123.457",
                            "channel": {"name": "random"},
                            "permalink": "https://...",
                        },
                    ],
                },
            }
            mock_get.return_value = mock_response

            result = fn(query="Hello")

        assert result["success"] is True
        assert result["total"] == 2
        assert len(result["messages"]) == 2


class TestSlackGetThreadReplies:
    """Tests for slack_get_thread_replies tool."""

    def test_get_thread_replies_success(self, get_tool_fn, monkeypatch):
        """Get thread replies returns messages."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_get_thread_replies")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "messages": [
                    {"ts": "123.456", "user": "U001", "text": "Parent message"},
                    {"ts": "123.457", "user": "U002", "text": "Reply 1"},
                    {"ts": "123.458", "user": "U003", "text": "Reply 2"},
                ],
            }
            mock_get.return_value = mock_response

            result = fn(channel="C123", thread_ts="123.456")

        assert result["success"] is True
        assert result["count"] == 3


class TestSlackPinMessage:
    """Tests for slack_pin_message tool."""

    def test_pin_message_success(self, get_tool_fn, monkeypatch):
        """Pin message returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_pin_message")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(channel="C123", timestamp="123.456")

        assert result["success"] is True


class TestSlackUnpinMessage:
    """Tests for slack_unpin_message tool."""

    def test_unpin_message_success(self, get_tool_fn, monkeypatch):
        """Unpin message returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_unpin_message")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(channel="C123", timestamp="123.456")

        assert result["success"] is True


class TestSlackListPins:
    """Tests for slack_list_pins tool."""

    def test_list_pins_success(self, get_tool_fn, monkeypatch):
        """List pins returns pinned items."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_list_pins")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "items": [
                    {
                        "type": "message",
                        "created": 1234567890,
                        "message": {"text": "Important msg"},
                    },
                ],
            }
            mock_get.return_value = mock_response

            result = fn(channel="C123")

        assert result["success"] is True
        assert result["count"] == 1


class TestSlackAddBookmark:
    """Tests for slack_add_bookmark tool."""

    def test_add_bookmark_success(self, get_tool_fn, monkeypatch):
        """Add bookmark returns bookmark details."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_add_bookmark")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "bookmark": {"id": "Bk123", "title": "Docs", "link": "https://docs.example.com"},
            }
            mock_post.return_value = mock_response

            result = fn(channel="C123", title="Docs", link="https://docs.example.com")

        assert result["success"] is True
        assert result["bookmark"]["id"] == "Bk123"


class TestSlackListScheduledMessages:
    """Tests for slack_list_scheduled_messages tool."""

    def test_list_scheduled_success(self, get_tool_fn, monkeypatch):
        """List scheduled messages returns pending messages."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_list_scheduled_messages")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "scheduled_messages": [
                    {"id": "Q1", "channel_id": "C123", "post_at": 1769865600, "text": "Reminder"},
                ],
            }
            mock_post.return_value = mock_response

            result = fn()

        assert result["success"] is True
        assert result["count"] == 1


class TestSlackDeleteScheduledMessage:
    """Tests for slack_delete_scheduled_message tool."""

    def test_delete_scheduled_success(self, get_tool_fn, monkeypatch):
        """Delete scheduled message returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_delete_scheduled_message")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(channel="C123", scheduled_message_id="Q1")

        assert result["success"] is True


class TestSlackSendDM:
    """Tests for slack_send_dm tool."""

    def test_send_dm_success(self, get_tool_fn, monkeypatch):
        """Send DM opens channel and sends message."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_send_dm")

        with patch("httpx.post") as mock_post:
            # Mock open DM then send message
            mock_open_response = MagicMock()
            mock_open_response.status_code = 200
            mock_open_response.json.return_value = {"ok": True, "channel": {"id": "D123"}}

            mock_send_response = MagicMock()
            mock_send_response.status_code = 200
            mock_send_response.json.return_value = {"ok": True, "channel": "D123", "ts": "123.456"}

            mock_post.side_effect = [mock_open_response, mock_send_response]

            result = fn(user_id="U001", text="Hello privately!")

        assert result["success"] is True
        assert result["channel"] == "D123"


class TestSlackGetPermalink:
    """Tests for slack_get_permalink tool."""

    def test_get_permalink_success(self, get_tool_fn, monkeypatch):
        """Get permalink returns link."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_get_permalink")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "permalink": "https://workspace.slack.com/archives/C123/p1234567890123456",
            }
            mock_get.return_value = mock_response

            result = fn(channel="C123", message_ts="123.456")

        assert result["success"] is True
        assert "slack.com" in result["permalink"]


class TestSlackSendEphemeral:
    """Tests for slack_send_ephemeral tool."""

    def test_send_ephemeral_success(self, get_tool_fn, monkeypatch):
        """Send ephemeral returns message_ts."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_send_ephemeral")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True, "message_ts": "123.456"}
            mock_post.return_value = mock_response

            result = fn(channel="C123", user_id="U001", text="Only you can see this")

        assert result["success"] is True
        assert result["message_ts"] == "123.456"


# ============================================================================
# Block Kit & Views Tests (v3 - 29 tools)
# ============================================================================


class TestSlackPostBlocks:
    """Tests for slack_post_blocks tool."""

    def test_post_blocks_success(self, get_tool_fn, monkeypatch):
        """Post blocks message returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_post_blocks")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "channel": "C123",
                "ts": "1234567890.123456",
            }
            mock_post.return_value = mock_response

            blocks_json = '[{"type": "section", "text": {"type": "mrkdwn", "text": "*Hello*"}}]'
            result = fn(channel="C123", blocks=blocks_json, text="Fallback")

        assert result["success"] is True
        assert result["ts"] == "1234567890.123456"

    def test_post_blocks_invalid_json(self, get_tool_fn, monkeypatch):
        """Post blocks with invalid JSON returns error."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_post_blocks")

        result = fn(channel="C123", blocks="not valid json", text="Fallback")

        assert "error" in result
        assert "Invalid blocks JSON" in result["error"]


class TestSlackOpenModal:
    """Tests for slack_open_modal tool."""

    def test_open_modal_success(self, get_tool_fn, monkeypatch):
        """Open modal returns view_id."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_open_modal")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "view": {"id": "V123ABC"},
            }
            mock_post.return_value = mock_response

            blocks_json = (
                '[{"type": "input", "element": {"type": "plain_text_input"},'
                ' "label": {"type": "plain_text", "text": "Name"}}]'
            )
            result = fn(trigger_id="12345.67890.abcdef", title="My Modal", blocks=blocks_json)

        assert result["success"] is True
        assert result["view_id"] == "V123ABC"

    def test_open_modal_invalid_json(self, get_tool_fn, monkeypatch):
        """Open modal with invalid blocks JSON returns error."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_open_modal")

        result = fn(trigger_id="123.456", title="Test", blocks="not json")

        assert "error" in result
        assert "Invalid blocks JSON" in result["error"]


class TestSlackUpdateHomeTab:
    """Tests for slack_update_home_tab tool."""

    def test_update_home_tab_success(self, get_tool_fn, monkeypatch):
        """Update home tab returns view_id."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_update_home_tab")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "view": {"id": "V456DEF"},
            }
            mock_post.return_value = mock_response

            blocks_json = '[{"type": "section", "text": {"type": "mrkdwn", "text": "Welcome!"}}]'
            result = fn(user_id="U001", blocks=blocks_json)

        assert result["success"] is True
        assert result["view_id"] == "V456DEF"

    def test_update_home_tab_invalid_json(self, get_tool_fn, monkeypatch):
        """Update home tab with invalid blocks returns error."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_update_home_tab")

        result = fn(user_id="U001", blocks="invalid")

        assert "error" in result
        assert "Invalid blocks JSON" in result["error"]


# =============================================================================
# Phase 3: Critical Power Tools Tests
# =============================================================================


class TestSlackGetConversationContext:
    """Tests for slack_get_conversation_context tool."""

    def test_get_conversation_context_success(self, get_tool_fn, monkeypatch):
        """Get conversation context returns messages with user names."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_get_conversation_context")

        with patch("httpx.get") as mock_get:
            # Mock history response first, then user info responses
            def mock_get_response(url, **kwargs):
                mock_response = MagicMock()
                mock_response.status_code = 200
                if "conversations.history" in url:
                    mock_response.json.return_value = {
                        "ok": True,
                        "messages": [
                            {"ts": "1234.1", "user": "U001", "text": "Hello"},
                            {"ts": "1234.2", "user": "U002", "text": "Hi there"},
                        ],
                    }
                elif "users.info" in url:
                    user_id = kwargs.get("params", {}).get("user", "U001")
                    name = "Alice" if user_id == "U001" else "Bob"
                    mock_response.json.return_value = {
                        "ok": True,
                        "user": {"id": user_id, "real_name": name},
                    }
                return mock_response

            mock_get.side_effect = mock_get_response

            result = fn(channel="C123", limit=10, include_user_info=True)

        assert result["channel"] == "C123"
        assert result["message_count"] == 2
        assert len(result["users_in_conversation"]) > 0


class TestSlackFindUserByEmail:
    """Tests for slack_find_user_by_email tool."""

    def test_find_user_by_email_success(self, get_tool_fn, monkeypatch):
        """Find user by email returns user info."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_find_user_by_email")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": True,
                "user": {
                    "id": "U001",
                    "name": "john.doe",
                    "real_name": "John Doe",
                    "profile": {"email": "john.doe@example.com"},
                },
            }
            mock_get.return_value = mock_response

            result = fn(email="john.doe@example.com")

        assert result["ok"] is True
        assert result["user"]["id"] == "U001"
        assert result["user"]["name"] == "john.doe"

    def test_find_user_by_email_not_found(self, get_tool_fn, monkeypatch):
        """Find user by email returns error when not found."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_find_user_by_email")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "ok": False,
                "error": "users_not_found",
            }
            mock_get.return_value = mock_response

            result = fn(email="nonexistent@example.com")

        assert "error" in result


class TestSlackKickUserFromChannel:
    """Tests for slack_kick_user_from_channel tool."""

    def test_kick_user_success(self, get_tool_fn, monkeypatch):
        """Kick user returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_kick_user_from_channel")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(channel="C123", user="U456")

        assert result["ok"] is True


class TestSlackDeleteFile:
    """Tests for slack_delete_file tool."""

    def test_delete_file_success(self, get_tool_fn, monkeypatch):
        """Delete file returns success."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_delete_file")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = fn(file_id="F123ABC")

        assert result["ok"] is True


class TestSlackGetTeamStats:
    """Tests for slack_get_team_stats tool."""

    def test_get_team_stats_success(self, get_tool_fn, monkeypatch):
        """Get team stats returns team info."""
        monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test-token")
        fn = get_tool_fn("slack_get_team_stats")

        with patch("httpx.get") as mock_get:

            def mock_response(url, **kwargs):
                response = MagicMock()
                response.status_code = 200
                if "team.info" in url:
                    response.json.return_value = {
                        "ok": True,
                        "team": {
                            "id": "T123",
                            "name": "My Workspace",
                            "domain": "myworkspace",
                        },
                    }
                elif "users.list" in url:
                    response.json.return_value = {
                        "ok": True,
                        "members": [{"id": "U001"}, {"id": "U002"}],
                    }
                return response

            mock_get.side_effect = mock_response

            result = fn()

        assert result["team_name"] == "My Workspace"
        assert result["team_domain"] == "myworkspace"
        assert result["team_id"] == "T123"
