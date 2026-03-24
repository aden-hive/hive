from unittest.mock import MagicMock, patch

from aden_tools.tools.pushover_tool.pushover_tool import register_tools


class TestRegisterTools:
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
        result = self.tools["pushover_send_notification"](message="Hello!", priority=99)
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
