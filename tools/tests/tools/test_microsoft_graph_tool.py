"""Tests for microsoft_graph_tool - Microsoft Graph API integration."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool import register_tools


@pytest.fixture
def tool_fns(mcp: FastMCP):
    """Register and return all Microsoft Graph tool functions."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestOutlookListMessages:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["outlook_list_messages"]()
        assert "error" in result
        assert "MICROSOFT_GRAPH_ACCESS_TOKEN" in result["error"]

    def test_successful_list(self, tool_fns):
        mock_response = {
            "value": [
                {
                    "id": "msg-1",
                    "subject": "Hello",
                    "from": {"emailAddress": {"name": "Alice", "address": "alice@example.com"}},
                    "receivedDateTime": "2024-01-01T00:00:00Z",
                    "isRead": False,
                    "hasAttachments": False,
                    "bodyPreview": "Hi there",
                }
            ]
        }
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.get"
            ) as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["outlook_list_messages"]()

        assert result["folder"] == "inbox"
        assert len(result["messages"]) == 1
        assert result["messages"][0]["subject"] == "Hello"
        assert result["messages"][0]["from_email"] == "alice@example.com"


class TestOutlookGetMessage:
    def test_missing_message_id(self, tool_fns):
        with patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}):
            result = tool_fns["outlook_get_message"](message_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_response = {
            "id": "msg-1",
            "subject": "Test Email",
            "from": {"emailAddress": {"name": "Bob", "address": "bob@example.com"}},
            "toRecipients": [{"emailAddress": {"name": "Alice", "address": "alice@example.com"}}],
            "body": {"content": "<p>Hello</p>", "contentType": "html"},
            "receivedDateTime": "2024-01-01T00:00:00Z",
            "hasAttachments": False,
            "importance": "normal",
            "categories": [],
            "isRead": True,
        }
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.get"
            ) as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["outlook_get_message"](message_id="msg-1")

        assert result["subject"] == "Test Email"
        assert result["from_email"] == "bob@example.com"
        assert len(result["to"]) == 1


class TestOutlookSendMail:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}):
            result = tool_fns["outlook_send_mail"](to="", subject="", body="test")
        assert "error" in result

    def test_successful_send(self, tool_fns):
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.post"
            ) as mock_post,
        ):
            mock_post.return_value.status_code = 202
            mock_post.return_value.json.return_value = {}
            mock_post.return_value.text = ""
            result = tool_fns["outlook_send_mail"](
                to="alice@example.com", subject="Test", body="Hello"
            )

        assert result["status"] == "sent"
        assert result["to"] == "alice@example.com"


class TestTeamsListTeams:
    def test_successful_list(self, tool_fns):
        mock_response = {
            "value": [{"id": "team-1", "displayName": "Engineering", "description": "Dev team"}]
        }
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.get"
            ) as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["teams_list_teams"]()

        assert len(result["teams"]) == 1
        assert result["teams"][0]["displayName"] == "Engineering"


class TestTeamsListChannels:
    def test_missing_team_id(self, tool_fns):
        with patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}):
            result = tool_fns["teams_list_channels"](team_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_response = {
            "value": [
                {
                    "id": "ch-1",
                    "displayName": "General",
                    "description": "General channel",
                    "membershipType": "standard",
                }
            ]
        }
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.get"
            ) as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["teams_list_channels"](team_id="team-1")

        assert result["team_id"] == "team-1"
        assert len(result["channels"]) == 1


class TestTeamsSendChannelMessage:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}):
            result = tool_fns["teams_send_channel_message"](team_id="", channel_id="", message="")
        assert "error" in result

    def test_successful_send(self, tool_fns):
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.post"
            ) as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {"id": "msg-123"}
            mock_post.return_value.text = '{"id": "msg-123"}'
            result = tool_fns["teams_send_channel_message"](
                team_id="team-1", channel_id="ch-1", message="Hello team!"
            )

        assert result["status"] == "sent"
        assert result["messageId"] == "msg-123"


class TestOneDriveSearchFiles:
    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}):
            result = tool_fns["onedrive_search_files"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_response = {
            "value": [
                {
                    "id": "file-1",
                    "name": "report.pdf",
                    "size": 1024,
                    "lastModifiedDateTime": "2024-01-01T00:00:00Z",
                    "webUrl": "https://onedrive.live.com/report.pdf",
                    "file": {"mimeType": "application/pdf"},
                    "parentReference": {"path": "/drive/root:/Documents"},
                }
            ]
        }
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.get"
            ) as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_response
            result = tool_fns["onedrive_search_files"](query="report")

        assert result["query"] == "report"
        assert len(result["files"]) == 1
        assert result["files"][0]["name"] == "report.pdf"


class TestOneDriveUploadFile:
    def test_missing_fields(self, tool_fns):
        with patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}):
            result = tool_fns["onedrive_upload_file"](file_path="", content="")
        assert "error" in result

    def test_successful_upload(self, tool_fns):
        with (
            patch.dict("os.environ", {"MICROSOFT_GRAPH_ACCESS_TOKEN": "test-token"}),
            patch(
                "aden_tools.tools.microsoft_graph_tool.microsoft_graph_tool.httpx.put"
            ) as mock_put,
        ):
            mock_put.return_value.status_code = 201
            mock_put.return_value.json.return_value = {
                "name": "notes.txt",
                "id": "file-2",
                "size": 100,
                "webUrl": "https://onedrive.live.com/notes.txt",
            }
            result = tool_fns["onedrive_upload_file"](
                file_path="Documents/notes.txt", content="Hello world"
            )

        assert result["status"] == "uploaded"
        assert result["name"] == "notes.txt"
