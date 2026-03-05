"""Tests for intercom_tool - customer messaging and conversations."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.intercom_tool.intercom_tool import register_tools

ENV = {"INTERCOM_ACCESS_TOKEN": "test-token-123"}


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


class TestIntercomMissingCredentials:
    def test_search_conversations_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["intercom_search_conversations"]()
        assert "error" in result

    def test_get_conversation_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["intercom_get_conversation"](conversation_id="123")
        assert "error" in result

    def test_list_teams_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["intercom_list_teams"]()
        assert "error" in result

    def test_search_contacts_no_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["intercom_search_contacts"](query="Alice")
        assert "error" in result


class TestIntercomSearchConversations:
    def test_successful_search(self, tool_fns):
        data = {
            "conversations": [
                {"id": "c1", "state": "open", "created_at": 1700000000},
                {"id": "c2", "state": "open", "created_at": 1700000001},
            ],
            "total_count": 2,
            "pages": {"total_pages": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["intercom_search_conversations"]()
        assert result["total_count"] == 2
        assert len(result["conversations"]) == 2

    def test_invalid_token_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.post",
                return_value=_mock_resp({}, 401),
            ),
        ):
            result = tool_fns["intercom_search_conversations"]()
        assert "error" in result


class TestIntercomGetConversation:
    def test_successful_get(self, tool_fns):
        data = {"id": "c1", "state": "open", "created_at": 1700000000}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["intercom_get_conversation"](conversation_id="c1")
        assert result["id"] == "c1"

    def test_not_found_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.get",
                return_value=_mock_resp({}, 404),
            ),
        ):
            result = tool_fns["intercom_get_conversation"](conversation_id="missing")
        assert "error" in result


class TestIntercomSearchContacts:
    def test_successful_search(self, tool_fns):
        data = {
            "data": [{"id": "u1", "email": "alice@example.com", "name": "Alice"}],
            "total_count": 1,
            "pages": {"total_pages": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.post",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["intercom_search_contacts"](query="alice")
        assert result["total_count"] == 1

    def test_rate_limit_returns_error(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.post",
                return_value=_mock_resp({}, 429),
            ),
        ):
            result = tool_fns["intercom_search_contacts"](query="alice")
        assert "error" in result


class TestIntercomListTeams:
    def test_successful_list(self, tool_fns):
        data = {"teams": [{"id": "t1", "name": "Support"}, {"id": "t2", "name": "Sales"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.intercom_tool.intercom_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["intercom_list_teams"]()
        assert len(result["teams"]) == 2
        assert result["teams"][0]["name"] == "Support"
