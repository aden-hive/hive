"""Tests for jira_tool - Issue tracking and project management."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.jira_tool.jira_tool import register_tools

ENV = {
    "JIRA_DOMAIN": "test.atlassian.net",
    "JIRA_EMAIL": "user@test.com",
    "JIRA_API_TOKEN": "test-token",
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


class TestJiraSearchIssues:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["jira_search_issues"](jql="project = TEST")
        assert "error" in result

    def test_missing_jql(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["jira_search_issues"](jql="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        data = {
            "issues": [
                {
                    "key": "TEST-1",
                    "fields": {
                        "summary": "Fix login bug",
                        "status": {"name": "In Progress"},
                        "assignee": {"displayName": "John Doe"},
                        "priority": {"name": "High"},
                        "issuetype": {"name": "Bug"},
                    },
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.jira_tool.jira_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["jira_search_issues"](jql="project = TEST")

        assert result["count"] == 1
        assert result["issues"][0]["key"] == "TEST-1"
        assert result["issues"][0]["status"] == "In Progress"


class TestJiraGetIssue:
    def test_missing_issue_key(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["jira_get_issue"](issue_key="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "key": "TEST-1",
            "fields": {
                "summary": "Fix login bug",
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Login fails"}]}
                    ],
                },
                "status": {"name": "In Progress"},
                "assignee": {"displayName": "John"},
                "reporter": {"displayName": "Jane"},
                "priority": {"name": "High"},
                "issuetype": {"name": "Bug"},
                "project": {"name": "Test Project"},
                "labels": ["backend"],
                "created": "2024-01-01T00:00:00Z",
                "updated": "2024-01-15T00:00:00Z",
            },
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.jira_tool.jira_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["jira_get_issue"](issue_key="TEST-1")

        assert result["summary"] == "Fix login bug"
        assert result["description"] == "Login fails"


class TestJiraCreateIssue:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["jira_create_issue"](project_key="", summary="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        data = {
            "key": "TEST-2",
            "id": "10002",
            "self": "https://test.atlassian.net/rest/api/3/issue/10002",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.jira_tool.jira_tool.httpx.post",
                return_value=_mock_resp(data, 201),
            ),
        ):
            result = tool_fns["jira_create_issue"](project_key="TEST", summary="New task")

        assert result["key"] == "TEST-2"
        assert result["status"] == "created"


class TestJiraListProjects:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["jira_list_projects"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "values": [
                {"key": "TEST", "name": "Test Project", "id": "10000", "projectTypeKey": "software"}
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.jira_tool.jira_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["jira_list_projects"]()

        assert result["count"] == 1
        assert result["projects"][0]["key"] == "TEST"


class TestJiraGetProject:
    def test_missing_key(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["jira_get_project"](project_key="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "key": "TEST",
            "name": "Test Project",
            "id": "10000",
            "description": "A test project",
            "lead": {"displayName": "Jane"},
            "projectTypeKey": "software",
            "issueTypes": [
                {"name": "Bug", "subtask": False},
                {"name": "Task", "subtask": False},
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.jira_tool.jira_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["jira_get_project"](project_key="TEST")

        assert result["name"] == "Test Project"
        assert result["lead"] == "Jane"


class TestJiraAddComment:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["jira_add_comment"](issue_key="", body="")
        assert "error" in result

    def test_successful_add(self, tool_fns):
        data = {
            "id": "100",
            "author": {"displayName": "John"},
            "created": "2024-01-15T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.jira_tool.jira_tool.httpx.post",
                return_value=_mock_resp(data, 201),
            ),
        ):
            result = tool_fns["jira_add_comment"](issue_key="TEST-1", body="Great work!")

        assert result["status"] == "created"
        assert result["author"] == "John"
