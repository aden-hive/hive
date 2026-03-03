"""Tests for zoom_tool - Zoom meeting management API."""

from unittest.mock import patch, MagicMock

import pytest
from fastmcp import FastMCP

from aden_tools.tools.zoom_tool.zoom_tool import register_tools

ENV = {"ZOOM_ACCESS_TOKEN": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test"}


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


class TestZoomGetUser:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["zoom_get_user"]()
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "abc123",
            "email": "user@example.com",
            "first_name": "Jane",
            "last_name": "Doe",
            "display_name": "Jane Doe",
            "type": 2,
            "timezone": "America/New_York",
            "status": "active",
            "account_id": "acc123",
            "created_at": "2024-01-01T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["zoom_get_user"]()

        assert result["email"] == "user@example.com"
        assert result["display_name"] == "Jane Doe"


class TestZoomListMeetings:
    def test_successful_list(self, tool_fns):
        data = {
            "total_records": 1,
            "next_page_token": "",
            "meetings": [
                {
                    "id": 78475495050,
                    "uuid": "abc123==",
                    "topic": "Weekly Standup",
                    "type": 2,
                    "start_time": "2025-01-21T09:20:00Z",
                    "duration": 30,
                    "timezone": "America/New_York",
                    "join_url": "https://zoom.us/j/78475495050",
                    "created_at": "2025-01-20T09:08:12Z",
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["zoom_list_meetings"]()

        assert result["total_records"] == 1
        assert result["meetings"][0]["topic"] == "Weekly Standup"
        assert result["meetings"][0]["id"] == 78475495050

    def test_pagination(self, tool_fns):
        data = {
            "total_records": 50,
            "next_page_token": "token123",
            "meetings": [{"id": 1, "uuid": "a", "topic": "M1", "type": 2, "start_time": "", "duration": 30, "timezone": "", "join_url": "", "created_at": ""}],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["zoom_list_meetings"]()

        assert result["next_page_token"] == "token123"


class TestZoomGetMeeting:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoom_get_meeting"](meeting_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": 78475495050,
            "uuid": "abc123==",
            "topic": "Project Review",
            "type": 2,
            "start_time": "2025-03-15T14:00:00Z",
            "duration": 60,
            "timezone": "America/New_York",
            "agenda": "Review Q1",
            "join_url": "https://zoom.us/j/78475495050",
            "start_url": "https://zoom.us/s/78475495050",
            "password": "abc123",
            "host_id": "host1",
            "created_at": "2025-03-10T10:00:00Z",
            "settings": {
                "host_video": True,
                "participant_video": True,
                "join_before_host": False,
                "mute_upon_entry": True,
                "waiting_room": True,
                "auto_recording": "cloud",
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["zoom_get_meeting"](meeting_id="78475495050")

        assert result["topic"] == "Project Review"
        assert result["settings"]["waiting_room"] is True


class TestZoomCreateMeeting:
    def test_missing_topic(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoom_create_meeting"](topic="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {
            "id": 78475495050,
            "uuid": "abc123==",
            "topic": "New Meeting",
            "start_time": "2025-03-15T14:00:00Z",
            "duration": 60,
            "join_url": "https://zoom.us/j/78475495050",
            "start_url": "https://zoom.us/s/78475495050",
            "password": "abc123",
            "created_at": "2025-03-10T10:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.post", return_value=_mock_resp(data, 201)),
        ):
            result = tool_fns["zoom_create_meeting"](
                topic="New Meeting",
                start_time="2025-03-15T14:00:00Z",
            )

        assert result["topic"] == "New Meeting"
        assert result["join_url"] == "https://zoom.us/j/78475495050"


class TestZoomDeleteMeeting:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoom_delete_meeting"](meeting_id="")
        assert "error" in result

    def test_successful_delete(self, tool_fns):
        resp = MagicMock()
        resp.status_code = 204
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.delete", return_value=resp),
        ):
            result = tool_fns["zoom_delete_meeting"](meeting_id="78475495050")

        assert result["success"] is True


class TestZoomListRecordings:
    def test_missing_dates(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zoom_list_recordings"](from_date="", to_date="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "total_records": 1,
            "next_page_token": "",
            "meetings": [
                {
                    "id": 78475495050,
                    "topic": "Weekly Standup",
                    "start_time": "2025-01-21T09:20:00Z",
                    "duration": 30,
                    "recording_count": 2,
                    "total_size": 52428800,
                    "recording_files": [
                        {
                            "id": "file1",
                            "file_type": "MP4",
                            "file_size": 41943040,
                            "recording_type": "shared_screen_with_speaker_view",
                            "status": "completed",
                            "play_url": "https://zoom.us/rec/play/test",
                        }
                    ],
                }
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.zoom_tool.zoom_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["zoom_list_recordings"](
                from_date="2025-01-01", to_date="2025-01-31"
            )

        assert result["total_records"] == 1
        assert result["recordings"][0]["recording_count"] == 2
        assert result["recordings"][0]["recording_files"][0]["file_type"] == "MP4"
