"""Tests for tines_tool - Security automation stories and actions."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.tines_tool.tines_tool import register_tools

ENV = {
    "TINES_DOMAIN": "test-tenant.tines.com",
    "TINES_API_KEY": "test-api-key",
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


class TestTinesListStories:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["tines_list_stories"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "stories": [
                {
                    "id": 123,
                    "name": "Alert Triage",
                    "description": "Auto-triage security alerts",
                    "disabled": False,
                    "mode": "LIVE",
                    "team_id": 1,
                    "tags": ["security"],
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-15T00:00:00Z",
                }
            ],
            "meta": {"count": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.tines_tool.tines_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["tines_list_stories"]()

        assert result["count"] == 1
        assert result["stories"][0]["name"] == "Alert Triage"


class TestTinesGetStory:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["tines_get_story"](story_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": 123,
            "name": "Alert Triage",
            "description": "Auto-triage",
            "disabled": False,
            "mode": "LIVE",
            "team_id": 1,
            "folder_id": 5,
            "tags": ["security"],
            "send_to_story_enabled": True,
            "entry_agent_id": 456,
            "exit_agents": [789],
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-15T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.tines_tool.tines_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["tines_get_story"](story_id=123)

        assert result["name"] == "Alert Triage"
        assert result["entry_agent_id"] == 456


class TestTinesListActions:
    def test_successful_list(self, tool_fns):
        data = {
            "agents": [
                {
                    "id": 456,
                    "name": "Enrich IOC",
                    "type": "Agents::HTTPRequestAgent",
                    "story_id": 123,
                    "disabled": False,
                    "created_at": "2024-01-01T00:00:00Z",
                    "updated_at": "2024-01-15T00:00:00Z",
                }
            ],
            "meta": {"count": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.tines_tool.tines_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["tines_list_actions"](story_id=123)

        assert result["count"] == 1
        assert result["actions"][0]["name"] == "Enrich IOC"
        assert result["actions"][0]["type"] == "Agents::HTTPRequestAgent"


class TestTinesGetAction:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["tines_get_action"](action_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": 456,
            "name": "Enrich IOC",
            "type": "Agents::HTTPRequestAgent",
            "description": "Sends HTTP request to threat intel API",
            "story_id": 123,
            "disabled": False,
            "sources": [111],
            "receivers": [222],
            "options": {"url": "https://api.example.com"},
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-15T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.tines_tool.tines_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["tines_get_action"](action_id=456)

        assert result["name"] == "Enrich IOC"
        assert result["sources"] == [111]


class TestTinesGetActionLogs:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["tines_get_action_logs"](action_id=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "action_logs": [
                {
                    "id": 789,
                    "level": 3,
                    "message": "Successfully sent HTTP request",
                    "created_at": "2024-01-15T12:00:00Z",
                }
            ],
            "meta": {"count": 1},
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.tines_tool.tines_tool.httpx.get", return_value=_mock_resp(data)
            ),
        ):
            result = tool_fns["tines_get_action_logs"](action_id=456)

        assert result["count"] == 1
        assert result["logs"][0]["message"] == "Successfully sent HTTP request"
