"""Tests for calendly_tool - Scheduling events and invitees."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.calendly_tool.calendly_tool import register_tools

ENV = {"CALENDLY_PAT": "test-pat-token"}

USER_URI = "https://api.calendly.com/users/AAAA"
ORG_URI = "https://api.calendly.com/organizations/BBBB"
EVENT_URI = "https://api.calendly.com/scheduled_events/DDDD"


def _mock_resp(data, status_code=200):
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


class TestCalendlyGetCurrentUser:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["calendly_get_current_user"]()
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "resource": {
                "uri": USER_URI,
                "name": "John Doe",
                "email": "john@example.com",
                "scheduling_url": "https://calendly.com/johndoe",
                "timezone": "America/New_York",
                "current_organization": ORG_URI,
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["calendly_get_current_user"]()

        assert result["name"] == "John Doe"
        assert result["uri"] == USER_URI
        assert result["organization"] == ORG_URI


class TestCalendlyListEventTypes:
    def test_missing_user_uri(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["calendly_list_event_types"](user_uri="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "collection": [
                {
                    "uri": "https://api.calendly.com/event_types/CCCC",
                    "name": "30 Minute Meeting",
                    "slug": "30min",
                    "active": True,
                    "duration": 30,
                    "kind": "solo",
                    "scheduling_url": "https://calendly.com/johndoe/30min",
                    "description_plain": "Quick chat",
                }
            ],
            "pagination": {"next_page_token": None},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["calendly_list_event_types"](user_uri=USER_URI)

        assert result["count"] == 1
        assert result["event_types"][0]["name"] == "30 Minute Meeting"
        assert result["event_types"][0]["duration"] == 30


class TestCalendlyListScheduledEvents:
    def test_missing_user_uri(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["calendly_list_scheduled_events"](user_uri="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "collection": [
                {
                    "uri": EVENT_URI,
                    "name": "30 Minute Meeting",
                    "status": "active",
                    "start_time": "2024-03-15T14:00:00.000000Z",
                    "end_time": "2024-03-15T14:30:00.000000Z",
                    "event_type": "https://api.calendly.com/event_types/CCCC",
                    "location": {"location": "https://zoom.us/j/12345"},
                    "invitees_counter": {"total": 1},
                }
            ],
            "pagination": {"next_page_token": None},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["calendly_list_scheduled_events"](user_uri=USER_URI)

        assert result["count"] == 1
        assert result["events"][0]["name"] == "30 Minute Meeting"
        assert result["events"][0]["invitees_count"] == 1


class TestCalendlyGetScheduledEvent:
    def test_missing_uri(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["calendly_get_scheduled_event"](event_uri="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "resource": {
                "uri": EVENT_URI,
                "name": "30 Minute Meeting",
                "status": "active",
                "start_time": "2024-03-15T14:00:00.000000Z",
                "end_time": "2024-03-15T14:30:00.000000Z",
                "event_type": "https://api.calendly.com/event_types/CCCC",
                "location": {"type": "zoom", "location": "https://zoom.us/j/12345"},
                "invitees_counter": {"total": 1, "active": 1, "limit": 1},
                "event_memberships": [{"user_email": "john@example.com"}],
                "created_at": "2024-03-10T12:00:00.000000Z",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["calendly_get_scheduled_event"](event_uri=EVENT_URI)

        assert result["name"] == "30 Minute Meeting"
        assert result["status"] == "active"


class TestCalendlyListInvitees:
    def test_missing_event_uri(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["calendly_list_invitees"](event_uri="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "collection": [
                {
                    "uri": f"{EVENT_URI}/invitees/EEEE",
                    "name": "Jane Smith",
                    "email": "jane@example.com",
                    "status": "active",
                    "timezone": "America/Chicago",
                    "questions_and_answers": [{"question": "Topic?", "answer": "Product demo"}],
                    "created_at": "2024-03-10T12:00:00.000000Z",
                }
            ],
            "pagination": {"next_page_token": None},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.calendly_tool.calendly_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["calendly_list_invitees"](event_uri=EVENT_URI)

        assert result["count"] == 1
        assert result["invitees"][0]["name"] == "Jane Smith"
        assert result["invitees"][0]["email"] == "jane@example.com"
