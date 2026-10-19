"""Tests for zendesk_tool - Ticket management and search."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.zendesk_tool.zendesk_tool import register_tools

ENV = {
    "ZENDESK_SUBDOMAIN": "test",
    "ZENDESK_EMAIL": "agent@test.com",
    "ZENDESK_API_TOKEN": "test-token",
}


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


TICKET_DATA = {
    "id": 123,
    "subject": "Printer issue",
    "description": "Not printing",
    "status": "open",
    "priority": "high",
    "type": "problem",
    "tags": ["hardware"],
    "requester_id": 100,
    "assignee_id": 200,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-15T00:00:00Z",
}


class TestZendeskListTickets:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["zendesk_list_tickets"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {"tickets": [TICKET_DATA]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.zendesk_tool.zendesk_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["zendesk_list_tickets"]()

        assert result["count"] == 1
        assert result["tickets"][0]["subject"] == "Printer issue"


class TestZendeskGetTicket:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zendesk_get_ticket"](ticket_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {"ticket": TICKET_DATA}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.zendesk_tool.zendesk_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["zendesk_get_ticket"](ticket_id=123)

        assert result["subject"] == "Printer issue"
        assert result["priority"] == "high"


class TestZendeskCreateTicket:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zendesk_create_ticket"](subject="", body="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {"ticket": {"id": 456, "subject": "New ticket", "status": "new"}}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.zendesk_tool.zendesk_tool.httpx.post",
                return_value=_mock_resp(data, 201),
            ),
        ):
            result = tool_fns["zendesk_create_ticket"](subject="New ticket", body="Help needed")

        assert result["result"] == "created"
        assert result["id"] == 456


class TestZendeskUpdateTicket:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zendesk_update_ticket"](ticket_id=0)
        assert "error" in result

    def test_successful_update(self, tool_fns):
        updated = dict(TICKET_DATA)
        updated["status"] = "pending"
        data = {"ticket": updated}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.zendesk_tool.zendesk_tool.httpx.put",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["zendesk_update_ticket"](ticket_id=123, status="pending")

        assert result["status"] == "pending"


class TestZendeskSearchTickets:
    def test_missing_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["zendesk_search_tickets"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "results": [{"id": 123, "subject": "Printer issue", "status": "open", "priority": "high"}],
            "count": 1,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.zendesk_tool.zendesk_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["zendesk_search_tickets"](query="status:open priority:high")

        assert result["count"] == 1
        assert result["results"][0]["subject"] == "Printer issue"
