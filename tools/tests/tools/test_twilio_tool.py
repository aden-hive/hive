"""Tests for twilio_tool - SMS and WhatsApp messaging."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.twilio_tool.twilio_tool import register_tools

ENV = {
    "TWILIO_ACCOUNT_SID": "ACtest123",
    "TWILIO_AUTH_TOKEN": "test-token",
}


def _mock_resp(data, status_code=201):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestTwilioSendSms:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["twilio_send_sms"](to="+1234", from_number="+5678", body="Hi")
        assert "error" in result

    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["twilio_send_sms"](to="", from_number="", body="")
        assert "error" in result

    def test_successful_send(self, tool_fns):
        msg = {
            "sid": "SM123",
            "to": "+14155552671",
            "from": "+15017122661",
            "body": "Hello!",
            "status": "queued",
            "direction": "outbound-api",
            "date_sent": None,
            "price": None,
            "error_code": None,
            "error_message": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.twilio_tool.twilio_tool.httpx.post", return_value=_mock_resp(msg)),
        ):
            result = tool_fns["twilio_send_sms"](to="+14155552671", from_number="+15017122661", body="Hello!")

        assert result["sid"] == "SM123"
        assert result["status"] == "queued"


class TestTwilioSendWhatsapp:
    def test_successful_send(self, tool_fns):
        msg = {
            "sid": "SM456",
            "to": "whatsapp:+14155552671",
            "from": "whatsapp:+14155238886",
            "body": "WhatsApp msg",
            "status": "queued",
            "direction": "outbound-api",
            "date_sent": None,
            "price": None,
            "error_code": None,
            "error_message": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.twilio_tool.twilio_tool.httpx.post", return_value=_mock_resp(msg)),
        ):
            result = tool_fns["twilio_send_whatsapp"](
                to="+14155552671", from_number="+14155238886", body="WhatsApp msg"
            )

        assert result["sid"] == "SM456"


class TestTwilioListMessages:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["twilio_list_messages"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "messages": [
                {
                    "sid": "SM123",
                    "to": "+1234",
                    "from": "+5678",
                    "body": "Test",
                    "status": "delivered",
                    "direction": "outbound-api",
                    "date_sent": "2024-01-01",
                    "price": "-0.0075",
                    "error_code": None,
                    "error_message": None,
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.twilio_tool.twilio_tool.httpx.get",
                return_value=_mock_resp(data, 200),
            ),
        ):
            result = tool_fns["twilio_list_messages"]()

        assert result["count"] == 1
        assert result["messages"][0]["status"] == "delivered"


class TestTwilioGetMessage:
    def test_missing_sid(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["twilio_get_message"](message_sid="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        msg = {
            "sid": "SM123",
            "to": "+1234",
            "from": "+5678",
            "body": "Test",
            "status": "delivered",
            "direction": "outbound-api",
            "date_sent": "2024-01-01",
            "price": "-0.0075",
            "error_code": None,
            "error_message": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.twilio_tool.twilio_tool.httpx.get",
                return_value=_mock_resp(msg, 200),
            ),
        ):
            result = tool_fns["twilio_get_message"](message_sid="SM123")

        assert result["sid"] == "SM123"
