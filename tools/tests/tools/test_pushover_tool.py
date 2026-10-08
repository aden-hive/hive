"""Tests for pushover_tool - Pushover push notification integration."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.pushover_tool.pushover_tool import register_tools

ENV = {"PUSHOVER_API_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestPushoverSend:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["pushover_send"](user_key="ukey", message="hi")
        assert "error" in result
        assert "PUSHOVER_API_TOKEN" in result["error"]

    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pushover_send"](user_key="", message="")
        assert "error" in result

    def test_message_too_long(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pushover_send"](user_key="ukey", message="x" * 1025)
        assert "error" in result
        assert "1024" in result["error"]

    def test_invalid_priority(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pushover_send"](user_key="ukey", message="hi", priority=3)
        assert "error" in result

    def test_successful_send(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.json.return_value = {"status": 1, "request": "req-1"}
            result = tool_fns["pushover_send"](user_key="ukey", message="Hello!")

        assert result["status"] == "sent"
        assert result["request"] == "req-1"

    def test_emergency_returns_receipt(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.json.return_value = {
                "status": 1,
                "request": "req-2",
                "receipt": "rcpt-1",
            }
            result = tool_fns["pushover_send"](user_key="ukey", message="URGENT", priority=2)

        assert result["receipt"] == "rcpt-1"

    def test_api_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.json.return_value = {
                "status": 0,
                "errors": ["user key is invalid"],
            }
            mock_post.return_value.text = "error"
            result = tool_fns["pushover_send"](user_key="bad", message="hi")

        assert "error" in result
        assert "user key is invalid" in result["error"]


class TestPushoverValidateUser:
    def test_missing_user_key(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pushover_validate_user"](user_key="")
        assert "error" in result

    def test_valid_user(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.json.return_value = {
                "status": 1,
                "devices": ["iphone", "desktop"],
                "group": 0,
            }
            result = tool_fns["pushover_validate_user"](user_key="ukey")

        assert result["is_valid"] is True
        assert len(result["devices"]) == 2
        assert result["is_group"] is False


class TestPushoverListSounds:
    def test_successful_list(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.json.return_value = {
                "status": 1,
                "sounds": {"pushover": "Pushover (default)", "bike": "Bike"},
            }
            result = tool_fns["pushover_list_sounds"]()

        assert "pushover" in result["sounds"]


class TestPushoverCheckReceipt:
    def test_missing_receipt(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["pushover_check_receipt"](receipt="")
        assert "error" in result

    def test_successful_check(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.pushover_tool.pushover_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.json.return_value = {
                "status": 1,
                "acknowledged": 1,
                "acknowledged_by": "user123",
                "acknowledged_at": 1700000000,
                "last_delivered_at": 1700000000,
                "expired": 0,
                "called_back": 0,
            }
            result = tool_fns["pushover_check_receipt"](receipt="rcpt-1")

        assert result["acknowledged"] is True
        assert result["acknowledged_by"] == "user123"
        assert result["expired"] is False
