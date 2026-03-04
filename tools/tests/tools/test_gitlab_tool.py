"""Tests for gitlab_tool - Projects, issues, and merge requests."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.gitlab_tool.gitlab_tool import register_tools

ENV = {"GITLAB_TOKEN": "test-token"}


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


class TestGitlabListProjects:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["gitlab_list_projects"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        projects = [
            {
                "id": 1,
                "name": "My Project",
                "path_with_namespace": "user/my-project",
                "description": "A project",
                "visibility": "private",
                "default_branch": "main",
                "web_url": "https://gitlab.com/user/my-project",
                "star_count": 5,
                "last_activity_at": "2024-01-01T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.gitlab_tool.gitlab_tool.httpx.get",
                return_value=_mock_resp(projects),
            ),
        ):
            result = tool_fns["gitlab_list_projects"]()

        assert result["count"] == 1
        assert result["projects"][0]["name"] == "My Project"


class TestGitlabGetProject:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gitlab_get_project"](project_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        project = {
            "id": 1,
            "name": "My Project",
            "path_with_namespace": "user/my-project",
            "description": "A project",
            "visibility": "private",
            "default_branch": "main",
            "web_url": "https://gitlab.com/user/my-project",
            "star_count": 5,
            "forks_count": 2,
            "open_issues_count": 3,
            "statistics": {"commit_count": 100},
            "created_at": "2024-01-01T00:00:00Z",
            "last_activity_at": "2024-01-15T00:00:00Z",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.gitlab_tool.gitlab_tool.httpx.get",
                return_value=_mock_resp(project),
            ),
        ):
            result = tool_fns["gitlab_get_project"](project_id="1")

        assert result["name"] == "My Project"
        assert result["commit_count"] == 100


class TestGitlabListIssues:
    def test_missing_project_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gitlab_list_issues"](project_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        issues = [
            {
                "iid": 1,
                "title": "Fix bug",
                "state": "opened",
                "labels": ["bug"],
                "assignees": [{"username": "dev1"}],
                "author": {"username": "reporter"},
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-15T00:00:00Z",
                "web_url": "https://gitlab.com/user/project/-/issues/1",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.gitlab_tool.gitlab_tool.httpx.get",
                return_value=_mock_resp(issues),
            ),
        ):
            result = tool_fns["gitlab_list_issues"](project_id="1")

        assert result["count"] == 1
        assert result["issues"][0]["title"] == "Fix bug"


class TestGitlabGetIssue:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gitlab_get_issue"](project_id="", issue_iid=0)
        assert "error" in result

    def test_successful_get(self, tool_fns):
        issue = {
            "iid": 1,
            "title": "Fix bug",
            "description": "Detailed description",
            "state": "opened",
            "labels": ["bug"],
            "assignees": [{"username": "dev1"}],
            "author": {"username": "reporter"},
            "milestone": {"title": "v1.0"},
            "due_date": "2024-02-01",
            "web_url": "https://gitlab.com/user/project/-/issues/1",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-15T00:00:00Z",
            "closed_at": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.gitlab_tool.gitlab_tool.httpx.get", return_value=_mock_resp(issue)
            ),
        ):
            result = tool_fns["gitlab_get_issue"](project_id="1", issue_iid=1)

        assert result["title"] == "Fix bug"
        assert result["milestone"] == "v1.0"


class TestGitlabCreateIssue:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gitlab_create_issue"](project_id="", title="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        issue = {
            "iid": 2,
            "title": "New issue",
            "web_url": "https://gitlab.com/user/project/-/issues/2",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.gitlab_tool.gitlab_tool.httpx.post",
                return_value=_mock_resp(issue, 201),
            ),
        ):
            result = tool_fns["gitlab_create_issue"](project_id="1", title="New issue")

        assert result["iid"] == 2
        assert result["status"] == "created"


class TestGitlabListMergeRequests:
    def test_missing_project_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["gitlab_list_merge_requests"](project_id="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mrs = [
            {
                "iid": 1,
                "title": "Feature branch",
                "state": "opened",
                "source_branch": "feature",
                "target_branch": "main",
                "author": {"username": "dev1"},
                "web_url": "https://gitlab.com/user/project/-/merge_requests/1",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-15T00:00:00Z",
            }
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.gitlab_tool.gitlab_tool.httpx.get", return_value=_mock_resp(mrs)
            ),
        ):
            result = tool_fns["gitlab_list_merge_requests"](project_id="1")

        assert result["count"] == 1
        assert result["merge_requests"][0]["source_branch"] == "feature"
