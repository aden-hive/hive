import pytest
from unittest.mock import MagicMock, patch
from fastmcp import FastMCP
from aden_tools.tools.asana_tool.tool import register_tools
from aden_tools.credentials import CredentialStoreAdapter

@pytest.fixture
def mock_credentials():
    return CredentialStoreAdapter.for_testing({
        "asana_access_token": "test-token"
    })

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
        
        # Setup specific return values
        
        # Tasks
        mock_tasks.create_task.return_value = {"gid": "123", "name": "Task", "data": {"gid": "123"}}
        mock_tasks.update_task.return_value = {"gid": "123", "name": "Task Updated"}
        mock_tasks.get_task.return_value = {"gid": "123", "name": "Task"}
        # Search returns iterable
        mock_tasks.search_tasks_for_workspace.return_value = [{"gid": "123", "name": "Found Task"}]
        mock_tasks.delete_task.return_value = {}
        mock_tasks.create_subtask_for_task.return_value = {"gid": "sub1", "name": "Subtask"}
        mock_tasks.add_project_for_task.return_value = {}
        mock_tasks.add_tag_for_task.return_value = {}
        
        # Workspaces
        mock_workspaces.get_workspaces.return_value = [{"gid": "ws1", "name": "Workspace 1"}]
        mock_workspaces.get_workspace.return_value = {"gid": "ws1", "name": "Workspace 1"}
        
        # Projects
        mock_projects.create_project.return_value = {"gid": "p1", "name": "Project"}
        mock_projects.get_projects.return_value = [{"gid": "p1", "name": "Project 1"}]
        
        # Users
        mock_users.get_user.return_value = {"gid": "u1", "name": "User"}
        mock_users.get_users.return_value = [{"gid": "u1", "name": "User"}]
        
        # Sections
        mock_sections.create_section_for_project.return_value = {"gid": "sec1", "name": "Section"}
        mock_sections.get_sections_for_project.return_value = [{"gid": "sec1", "name": "Section"}]
        
        # Stories
        mock_stories.create_story_for_task.return_value = {"gid": "story1", "text": "Comment"}
        
        # Tags
        mock_tags.create_tag.return_value = {"gid": "tag1", "name": "Tag"}
        mock_tags.get_tags.return_value = [{"gid": "tag1", "name": "Tag"}]
        
        yield {
            "tasks": mock_tasks,
            "projects": mock_projects,
            "workspaces": mock_workspaces,
            "users": mock_users,
            "stories": mock_stories,
            "sections": mock_sections,
            "tags": mock_tags
        }

def get_tool_fn(mcp, name):
    if hasattr(mcp, "_tool_manager"):
        return mcp._tool_manager._tools[name].fn
    return mcp._tools[name]

def test_create_task(mock_apis, mock_credentials):
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = get_tool_fn(mcp, "asana_create_task")
    
    result = tool(name="New Task", workspace="ws1")
    
    # Check result simply
    assert result["gid"] == "123"
    
    args = mock_apis["tasks"].create_task.call_args[0][0]
    assert args["data"]["name"] == "New Task"
    assert args["data"]["workspace"] == "ws1"

def test_update_task(mock_apis, mock_credentials):
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = get_tool_fn(mcp, "asana_update_task")
    
    tool(task_gid="123", completed=True)
    
    args = mock_apis["tasks"].update_task.call_args[0][0]
    assert args["data"]["completed"] is True
    assert mock_apis["tasks"].update_task.call_args[0][1] == "123"

def test_search_tasks(mock_apis, mock_credentials):
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = get_tool_fn(mcp, "asana_search_tasks")
    
    result = tool(text="hello", workspace="ws1")
    
    assert len(result) == 1
    call_args = mock_apis["tasks"].search_tasks_for_workspace.call_args
    assert call_args[0][0] == "ws1" # arg 1
    assert call_args[1]["text"] == "hello" # kwarg

def test_create_project(mock_apis, mock_credentials):
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = get_tool_fn(mcp, "asana_create_project")
    
    tool(name="My Project", workspace="ws1")
    
    args = mock_apis["projects"].create_project.call_args[0][0]
    assert args["data"]["name"] == "My Project"
    assert args["data"]["workspace"] == "ws1"

def test_add_comment(mock_apis, mock_credentials):
    mcp = FastMCP("test")
    register_tools(mcp, credentials=mock_credentials)
    tool = get_tool_fn(mcp, "asana_add_task_comment")
    
    tool(task_gid="123", text="Hello")
    
    args = mock_apis["stories"].create_story_for_task.call_args[0][0]
    assert args["data"]["text"] == "Hello"
    assert mock_apis["stories"].create_story_for_task.call_args[0][1] == "123"
