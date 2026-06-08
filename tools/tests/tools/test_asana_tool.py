"""Tests for asana_tool - Asana task and project management."""

from unittest.mock import patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.asana_tool.asana_tool import register_tools

ENV = {"ASANA_ACCESS_TOKEN": "test-token"}


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestAsanaListWorkspaces:
    def test_missing_token(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["asana_list_workspaces"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {"data": [{"gid": "ws-1", "name": "My Workspace"}]}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.asana_tool.asana_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["asana_list_workspaces"]()

        assert len(result["workspaces"]) == 1
        assert result["workspaces"][0]["name"] == "My Workspace"


class TestAsanaListProjects:
    def test_missing_workspace(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["asana_list_projects"](workspace_gid="")
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {"data": [{"gid": "proj-1", "name": "Website Redesign", "color": "blue", "archived": False}]}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.asana_tool.asana_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["asana_list_projects"](workspace_gid="ws-1")

        assert len(result["projects"]) == 1
        assert result["projects"][0]["name"] == "Website Redesign"


class TestAsanaListTasks:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["asana_list_tasks"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "gid": "task-1",
                    "name": "Design homepage",
                    "completed": False,
                    "due_on": "2024-06-15",
                    "assignee": {"name": "Alice"},
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.asana_tool.asana_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["asana_list_tasks"](project_gid="proj-1")

        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["name"] == "Design homepage"


class TestAsanaGetTask:
    def test_missing_gid(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["asana_get_task"](task_gid="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        mock_resp = {
            "data": {
                "gid": "task-1",
                "name": "Design homepage",
                "notes": "Create the new homepage design",
                "completed": False,
                "due_on": "2024-06-15",
                "assignee": {"name": "Alice"},
                "projects": [{"name": "Website Redesign"}],
                "tags": [{"name": "urgent"}],
                "created_at": "2024-01-01T00:00:00Z",
                "modified_at": "2024-06-01T00:00:00Z",
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.asana_tool.asana_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["asana_get_task"](task_gid="task-1")

        assert result["name"] == "Design homepage"
        assert result["projects"] == ["Website Redesign"]
        assert result["tags"] == ["urgent"]


class TestAsanaCreateTask:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["asana_create_task"](workspace_gid="ws-1", name="")
        assert "error" in result

    def test_successful_create(self, tool_fns):
        mock_resp = {"data": {"gid": "task-new", "name": "New Task"}}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.asana_tool.asana_tool.httpx.post") as mock_post,
        ):
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = mock_resp
            result = tool_fns["asana_create_task"](workspace_gid="ws-1", name="New Task", due_on="2024-07-01")

        assert result["status"] == "created"
        assert result["gid"] == "task-new"


class TestAsanaSearchTasks:
    def test_missing_params(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["asana_search_tasks"](workspace_gid="", query="")
        assert "error" in result

    def test_successful_search(self, tool_fns):
        mock_resp = {
            "data": [
                {
                    "gid": "task-1",
                    "name": "Design homepage",
                    "completed": False,
                    "due_on": "2024-06-15",
                }
            ]
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.asana_tool.asana_tool.httpx.get") as mock_get,
        ):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = mock_resp
            result = tool_fns["asana_search_tasks"](workspace_gid="ws-1", query="design")

        assert len(result["tasks"]) == 1
