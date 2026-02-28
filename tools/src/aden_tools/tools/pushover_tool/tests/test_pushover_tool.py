"""Tests for Pushover tool."""
from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.pushover_tool.pushover_tool import (
    _PushoverClient,
    register_tools,
)


class TestPushoverClient:
    """Tests for _PushoverClient."""

    def setup_method(self):
        self.client = _PushoverClient(
            token="test_token",
            user_key="test_user_key",
        )

    def _mock_response(self, status_code=200, json_data=None):
        mock = MagicMock()
        mock.status_code = status_code
        mock.json.return_value = json_data or {"status": 1, "request": "abc123"}
        mock.text = "OK"
        return mock

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_send_notification_success(self, mock_post):
        mock_post.return_value = self._mock_response()
        result = self.client.send_notification("Test message", title="Test")
        assert result["status"] == 1
        assert result["request"] == "abc123"

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_send_notification_emergency_priority(self, mock_post):
        mock_post.return_value = self._mock_response()
        result = self.client.send_notification("Emergency!", priority=2)
        call_kwargs = mock_post.call_args[1]["data"]
        assert call_kwargs["retry"] == 30
        assert call_kwargs["expire"] == 3600

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_send_notification_rate_limited(self, mock_post):
        mock_post.return_value = self._mock_response(status_code=429)
        result = self.client.send_notification("Test")
        assert "error" in result
        assert "Rate limit" in result["error"]

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_send_notification_api_error(self, mock_post):
        mock_post.return_value = self._mock_response(
            json_data={"status": 0, "errors": ["invalid token"]}
        )
        result = self.client.send_notification("Test")
        assert "error" in result
        assert "invalid token" in result["error"]

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_send_notification_with_url(self, mock_post):
        mock_post.return_value = self._mock_response()
        result = self.client.send_notification_with_url(
            "Check this out",
            url="https://example.com",
            url_title="Example",
        )
        assert result["status"] == 1

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.get")
    def test_get_sounds(self, mock_get):
        mock_get.return_value = self._mock_response(
            json_data={"status": 1, "sounds": {"pushover": "Pushover (default)"}}
        )
        result = self.client.get_sounds()
        assert "sounds" in result
        assert "pushover" in result["sounds"]

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_validate_user_success(self, mock_post):
        mock_post.return_value = self._mock_response(
            json_data={"status": 1, "devices": ["iphone", "android"]}
        )
        result = self.client.validate_user()
        assert result["status"] == 1
        assert "iphone" in result["devices"]

    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_validate_user_with_device(self, mock_post):
        mock_post.return_value = self._mock_response(
            json_data={"status": 1, "devices": ["iphone"]}
        )
        result = self.client.validate_user(device="iphone")
        call_kwargs = mock_post.call_args[1]["data"]
        assert call_kwargs["device"] == "iphone"


class TestRegisterTools:
    """Tests for register_tools MCP tool functions."""

    def setup_method(self):
        self.mcp = MagicMock()
        self.tools = {}

        def tool_decorator():
            def decorator(func):
                self.tools[func.__name__] = func
                return func
            return decorator

        self.mcp.tool = tool_decorator
        register_tools(self.mcp, credentials=None)

    @patch.dict(
        "os.environ",
        {"PUSHOVER_API_TOKEN": "test_token", "PUSHOVER_USER_KEY": "test_user"},
    )
    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_pushover_send_notification(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": 1, "request": "req123"},
        )
        result = self.tools["pushover_send_notification"](message="Hello!")
        assert result["success"] is True
        assert result["request"] == "req123"

    @patch.dict(
        "os.environ",
        {"PUSHOVER_API_TOKEN": "test_token", "PUSHOVER_USER_KEY": "test_user"},
    )
    def test_pushover_send_notification_invalid_priority(self):
        result = self.tools["pushover_send_notification"](
            message="Hello!", priority=99
        )
        assert "error" in result
        assert "priority" in result["error"]

    def test_pushover_send_notification_no_credentials(self):
        result = self.tools["pushover_send_notification"](message="Hello!")
        assert "error" in result
        assert "credentials" in result["error"]

    @patch.dict(
        "os.environ",
        {"PUSHOVER_API_TOKEN": "test_token", "PUSHOVER_USER_KEY": "test_user"},
    )
    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_pushover_send_notification_with_url(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": 1, "request": "req456"},
        )
        result = self.tools["pushover_send_notification_with_url"](
            message="Check this", url="https://example.com"
        )
        assert result["success"] is True

    @patch.dict(
        "os.environ",
        {"PUSHOVER_API_TOKEN": "test_token", "PUSHOVER_USER_KEY": "test_user"},
    )
    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.get")
    def test_pushover_get_sounds(self, mock_get):
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": 1, "sounds": {"pushover": "Pushover (default)"}},
        )
        result = self.tools["pushover_get_sounds"]()
        assert result["success"] is True
        assert "sounds" in result

    @patch.dict(
        "os.environ",
        {"PUSHOVER_API_TOKEN": "test_token", "PUSHOVER_USER_KEY": "test_user"},
    )
    @patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post")
    def test_pushover_validate_user(self, mock_post):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"status": 1, "devices": ["iphone"]},
        )
        result = self.tools["pushover_validate_user"]()
        assert result["success"] is True
        assert "devices" in result
