"""
Tests for Asana tools.
"""

import pytest
from unittest.mock import MagicMock, patch
from fastmcp import FastMCP
from aden_tools.tools.asana_tool.tool import register_tools
from aden_tools.credentials import CredentialStoreAdapter
import os

# Try to import ApiException for side_effect, or create a mock exception
try:
    from asana.rest import ApiException
except ImportError:

    class ApiException(Exception):
        def __init__(self, status=None, reason=None, http_resp=None):
            self.status = status
            self.reason = reason
            self.body = http_resp


@pytest.fixture
def mock_credentials():
    return CredentialStoreAdapter.for_testing({"asana": "test-token"})


@pytest.fixture
def mock_apis():
    with patch("aden_tools.tools.asana_tool.tool.asana") as mock_asana:
        # Mock Configuration and ApiClient
        mock_asana.Configuration.return_value = MagicMock()
        mock_asana.ApiClient.return_value = MagicMock()

        # Mock API classes
        mock_tasks = MagicMock()
        mock_asana.TasksApi.return_value = mock_tasks

        mock_projects = MagicMock()
        mock_asana.ProjectsApi.return_value = mock_projects

        mock_workspaces = MagicMock()
        mock_asana.WorkspacesApi.return_value = mock_workspaces

        mock_users = MagicMock()
        mock_asana.UsersApi.return_value = mock_users

        mock_stories = MagicMock()
        mock_asana.StoriesApi.return_value = mock_stories

        mock_sections = MagicMock()
        mock_asana.SectionsApi.return_value = mock_sections

        mock_tags = MagicMock()
        mock_asana.TagsApi.return_value = mock_tags

        # Setup specific return values matches typical Asana response structure

        # Tasks
        # Need to return objects that have .to_dict or are dicts
        # Our tool implementation handles both but let's be consistent
        t1 = MagicMock()
        t1.to_dict.return_value = {"gid": "123", "name": "Task"}
        mock_tasks.create_task.return_value = t1
        mock_tasks.update_task.return_value = t1
        mock_tasks.get_task.return_value = t1

        # Search returns iterable
        t2 = MagicMock()
        t2.to_dict.return_value = {"gid": "123", "name": "Found Task"}
        # search_tasks_for_workspace returns request response which is iterable or has data
        search_res = MagicMock()
        search_res.data = [t2]
        search_res.__iter__.return_value = [t2]
        mock_tasks.search_tasks_for_workspace.return_value = search_res

        mock_tasks.delete_task.return_value = {}
        mock_tasks.create_subtask_for_task.return_value = {
            "gid": "sub1",
            "name": "Subtask",
        }

        # Projects
        p1 = MagicMock()
        p1.to_dict.return_value = {"gid": "p1", "name": "Project"}
        mock_projects.create_project.return_value = p1
        mock_projects.get_projects.return_value = [p1]

        # Workspaces (default for get_workspace_gid)
        # Note: workspace resolution expects an iterable of dict-like objects or objects with .gid
        ws1 = MagicMock()
        ws1.gid = "ws1"
        ws1.name = "Workspace 1"
        # Ensure __getitem__ works for dict-like access if needed
        ws1.__getitem__ = (
            lambda name: "ws1"
            if name == "gid"
            else "Workspace 1"
            if name == "name"
            else None
        )

        ws_res = MagicMock()
        ws_res.data = [ws1]
        ws_res.__iter__.return_value = [ws1]
        mock_workspaces.get_workspaces.return_value = ws_res

        mock_workspaces.get_workspace.return_value = {
            "gid": "ws1",
            "name": "Workspace 1",
        }

        # Stories
        story = MagicMock()
        story.to_dict.return_value = {"gid": "story1", "text": "Comment"}
        mock_stories.create_story_for_task.return_value = story

        yield {
            "tasks": mock_tasks,
            "projects": mock_projects,
            "workspaces": mock_workspaces,
            "stories": mock_stories,
            "asana_module": mock_asana,
        }


def test_missing_credentials():
    """Test that missing credentials return an error dict with help."""
    mcp = FastMCP("test")
    # Empty credentials and ensure env var is unset
    creds = CredentialStoreAdapter.for_testing({})
    with patch.dict(os.environ, {}, clear=True):
        register_tools(mcp, credentials=creds)

        # Access tool directly via _tool_manager
        tool = mcp._tool_manager._tools["asana_create_task"].fn
        result = tool(name="Task")

        assert isinstance(result, dict)
        assert "error" in result
        assert "Asana credentials not configured" in result["error"]
        assert "help" in result


def test_invalid_credential_type():
    """Test that non-string credential value is handled safely."""
    mcp = FastMCP("test")
    creds = CredentialStoreAdapter.for_testing({})
    # Mock get to return an object (non-string)
    with patch.object(creds, "get", return_value=123):
        register_tools(mcp, credentials=creds)
        tool = mcp._tool_manager._tools["asana_create_task"].fn
        result = tool(name="Task")

        assert isinstance(result, dict)
        assert "error" in result  # Should fallback to missing creds error path


def test_api_error_handling(mock_apis, mock_credentials):
    """Test standard API error handling."""
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = mcp._tool_manager._tools["asana_create_task"].fn

    # Mock exception
    mock_apis["tasks"].create_task.side_effect = ApiException(
        status=400, reason="Bad Request"
    )

    result = tool(name="Fail Task", workspace="ws1")
    assert "error" in result
    assert "Bad Request" in str(result["error"])


def test_create_task(mock_apis, mock_credentials):
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = mcp._tool_manager._tools["asana_create_task"].fn

    result = tool(name="New Task", workspace="ws1")

    assert result["gid"] == "123"

    # Check args
    call_args = mock_apis["tasks"].create_task.call_args[0][0]
    assert call_args["data"]["name"] == "New Task"
    assert call_args["data"]["workspace"] == "ws1"


def test_search_tasks_format(mock_apis, mock_credentials):
    """Test that list results are wrapped in a dict."""
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = mcp._tool_manager._tools["asana_search_tasks"].fn

    result = tool(text="hello", workspace="ws1")

    # Expect dict wrapper {"data": [...]}
    assert isinstance(result, dict)
    assert "data" in result
    assert isinstance(result["data"], list)
    assert len(result["data"]) == 1
    assert result["data"][0]["gid"] == "123"


def test_workspace_resolution(mock_apis, mock_credentials):
    """Test workspace resolution logic."""
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = mcp._tool_manager._tools["asana_create_task"].fn

    # 1. By Name (Workspace 1 -> ws1)
    tool(name="T1", workspace="Workspace 1")
    args1 = mock_apis["tasks"].create_task.call_args[0][0]["data"]["workspace"]
    assert args1 == "ws1"

    # 2. By GID (explicit)
    # If not found in list, fallback to using it as GID because it's digits
    tool(name="T2", workspace="999")
    args2 = mock_apis["tasks"].create_task.call_args[0][0]["data"]["workspace"]
    assert args2 == "999"


def test_registration_completeness(mock_credentials):
    """Verify all 25 tools are registered."""
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)

    expected_tools = [
        "asana_create_task",
        "asana_update_task",
        "asana_get_task",
        "asana_search_tasks",
        "asana_delete_task",
        "asana_add_task_comment",
        "asana_complete_task",
        "asana_add_subtask",
        "asana_create_project",
        "asana_update_project",
        "asana_get_project",
        "asana_list_projects",
        "asana_get_project_tasks",
        "asana_add_task_to_project",
        "asana_get_workspace",
        "asana_list_workspaces",
        "asana_get_user",
        "asana_list_team_members",
        "asana_create_section",
        "asana_list_sections",
        "asana_move_task_to_section",
        "asana_create_tag",
        "asana_add_tag_to_task",
        "asana_list_tags",
        "asana_update_custom_field",
    ]

    registered = mcp._tool_manager._tools.keys()
    for t in expected_tools:
        assert t in registered, f"Tool {t} not registered"
