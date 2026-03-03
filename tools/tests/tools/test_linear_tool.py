"""Tests for linear_tool - Linear issue tracking and project management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.linear_tool.linear_tool import register_tools

ENV = {"LINEAR_API_KEY": "lin_api_test"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestLinearListIssues:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["linear_list_issues"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": {
                "issues": {
                    "nodes": [
                        {
                            "id": "issue-1",
                            "identifier": "ENG-123",
                            "title": "Fix login bug",
                            "state": {"name": "In Progress"},
                            "priority": 2,
                            "assignee": {"displayName": "Alice"},
                            "createdAt": "2024-01-01T00:00:00Z",
                        }
                    ]
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["linear_list_issues"]()

        assert len(result["issues"]) == 1
        assert result["issues"][0]["identifier"] == "ENG-123"


class TestLinearGetIssue:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["linear_get_issue"](issue_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "data": {
                "issue": {
                    "id": "issue-1",
                    "identifier": "ENG-123",
                    "title": "Fix login bug",
                    "description": "The login page crashes on submit",
                    "state": {"name": "In Progress"},
                    "priority": 2,
                    "assignee": {"displayName": "Alice"},
                    "project": {"name": "Q1 Sprint"},
                    "labels": {"nodes": [{"name": "bug"}]},
                    "estimate": 3,
                    "dueDate": "2024-06-15",
                    "createdAt": "2024-01-01T00:00:00Z",
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["linear_get_issue"](issue_id="ENG-123")

        assert result["title"] == "Fix login bug"
        assert result["labels"] == ["bug"]


class TestLinearCreateIssue:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["linear_create_issue"](team_id="", title="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = {
            "data": {
                "issueCreate": {
                    "success": True,
                    "issue": {
                        "id": "issue-new",
                        "identifier": "ENG-124",
                        "title": "Add dark mode",
                    },
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["linear_create_issue"](team_id="team-1", title="Add dark mode")

        assert result["status"] == "created"
        assert result["identifier"] == "ENG-124"


class TestLinearListTeams:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": {
                "teams": {
                    "nodes": [
                        {"id": "team-1", "name": "Engineering", "key": "ENG", "description": "Core eng"}
                    ]
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["linear_list_teams"]()

        assert len(result["teams"]) == 1
        assert result["teams"][0]["key"] == "ENG"


class TestLinearListProjects:
    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": {
                "projects": {
                    "nodes": [
                        {
                            "id": "proj-1",
                            "name": "Q1 Sprint",
                            "state": "started",
                            "progress": 0.65,
                            "lead": {"displayName": "Bob"},
                            "targetDate": "2024-03-31",
                        }
                    ]
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["linear_list_projects"]()

        assert len(result["projects"]) == 1
        assert result["projects"][0]["progress"] == 0.65


class TestLinearSearchIssues:
    def test_empty_query(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["linear_search_issues"](query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = {
            "data": {
                "searchIssues": {
                    "nodes": [
                        {
                            "id": "issue-1",
                            "identifier": "ENG-123",
                            "title": "Fix login bug",
                            "state": {"name": "In Progress"},
                            "assignee": {"displayName": "Alice"},
                        }
                    ]
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.linear_tool.linear_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 200
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["linear_search_issues"](query="login")

        assert len(result["results"]) == 1
