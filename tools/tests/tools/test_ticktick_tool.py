"""Tests for TickTick tool with FastMCP."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.ticktick_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-ticktick")


@pytest.fixture
def ticktick_tools(mcp: FastMCP, monkeypatch):
    """Register TickTick tools and return tool functions."""
    monkeypatch.setenv("TICKTICK_ACCESS_TOKEN", "test-access-token")
    register_tools(mcp)
    return {
        "create_task": mcp._tool_manager._tools["ticktick_create_task"].fn,
        "list_tasks": mcp._tool_manager._tools["ticktick_list_tasks"].fn,
        "update_task": mcp._tool_manager._tools["ticktick_update_task"].fn,
        "complete_task": mcp._tool_manager._tools["ticktick_complete_task"].fn,
        "delete_task": mcp._tool_manager._tools["ticktick_delete_task"].fn,
        "list_projects": mcp._tool_manager._tools["ticktick_list_projects"].fn,
        "create_project": mcp._tool_manager._tools["ticktick_create_project"].fn,
        "list_tags": mcp._tool_manager._tools["ticktick_list_tags"].fn,
    }


class TestToolRegistration:
    """Tests for tool registration."""

    def test_all_tools_registered(self, mcp: FastMCP, monkeypatch):
        """All 8 TickTick tools are registered."""
        monkeypatch.setenv("TICKTICK_ACCESS_TOKEN", "test-token")
        register_tools(mcp)

        expected_tools = [
            "ticktick_create_task",
            "ticktick_list_tasks",
            "ticktick_update_task",
            "ticktick_complete_task",
            "ticktick_delete_task",
            "ticktick_list_projects",
            "ticktick_create_project",
            "ticktick_list_tags",
        ]

        for tool_name in expected_tools:
            assert tool_name in mcp._tool_manager._tools


class TestCredentialHandling:
    """Tests for credential handling."""

    def test_no_credentials_returns_error(self, mcp: FastMCP, monkeypatch):
        """Tools without credentials return helpful error."""
        monkeypatch.delenv("TICKTICK_ACCESS_TOKEN", raising=False)
        register_tools(mcp)

        fn = mcp._tool_manager._tools["ticktick_list_projects"].fn
        result = fn()

        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_non_string_credential_returns_error(self, mcp: FastMCP, monkeypatch):
        """Non-string credential returns error dict instead of raising."""
        monkeypatch.delenv("TICKTICK_ACCESS_TOKEN", raising=False)
        creds = MagicMock()
        creds.get.return_value = 12345  # non-string
        register_tools(mcp, credentials=creds)

        fn = mcp._tool_manager._tools["ticktick_list_projects"].fn
        result = fn()

        assert "error" in result
        assert "not configured" in result["error"]

    def test_credentials_from_env(self, mcp: FastMCP, monkeypatch):
        """Tools use credentials from environment variable."""
        monkeypatch.setenv("TICKTICK_ACCESS_TOKEN", "test-token")
        register_tools(mcp)

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'[{"id":"proj1","name":"Inbox"}]'
            mock_response.json.return_value = [
                {"id": "proj1", "name": "Inbox"},
            ]
            mock_get.return_value = mock_response

            fn = mcp._tool_manager._tools["ticktick_list_projects"].fn
            result = fn()

            assert "error" not in result

            # Verify Bearer token is in headers
            call_kwargs = mock_get.call_args
            headers = call_kwargs.kwargs.get("headers", {})
            assert headers.get("Authorization") == "Bearer test-token"

    def test_credentials_from_store(self, mcp: FastMCP, monkeypatch):
        """Tools use credentials from credential store when provided."""
        monkeypatch.delenv("TICKTICK_ACCESS_TOKEN", raising=False)
        creds = MagicMock()
        creds.get.return_value = "store-token"
        register_tools(mcp, credentials=creds)

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"[]"
            mock_response.json.return_value = []
            mock_get.return_value = mock_response

            fn = mcp._tool_manager._tools["ticktick_list_projects"].fn
            result = fn()

            assert "error" not in result
            creds.get.assert_called_with("ticktick")


class TestCreateTask:
    """Tests for ticktick_create_task tool."""

    def test_create_task_success(self, ticktick_tools):
        """Create task returns created task data on success."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"id":"task1","title":"Buy milk","priority":0}'
            mock_response.json.return_value = {
                "id": "task1",
                "title": "Buy milk",
                "priority": 0,
            }
            mock_post.return_value = mock_response

            result = ticktick_tools["create_task"](title="Buy milk")

            assert result["id"] == "task1"
            assert result["title"] == "Buy milk"

    def test_create_task_with_all_params(self, ticktick_tools):
        """Create task passes all optional parameters."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"id":"task2","title":"Meeting"}'
            mock_response.json.return_value = {
                "id": "task2",
                "title": "Meeting",
                "projectId": "proj1",
                "content": "Discuss roadmap",
                "dueDate": "2024-12-31T23:59:00+0000",
                "priority": 5,
            }
            mock_post.return_value = mock_response

            result = ticktick_tools["create_task"](
                title="Meeting",
                project_id="proj1",
                content="Discuss roadmap",
                due_date="2024-12-31T23:59:00+0000",
                priority=5,
            )

            assert result["id"] == "task2"

            # Verify request body
            call_kwargs = mock_post.call_args
            json_data = call_kwargs.kwargs.get("json", {})
            assert json_data["title"] == "Meeting"
            assert json_data["projectId"] == "proj1"
            assert json_data["content"] == "Discuss roadmap"
            assert json_data["dueDate"] == "2024-12-31T23:59:00+0000"
            assert json_data["priority"] == 5

    def test_create_task_empty_title(self, ticktick_tools):
        """Create task returns error for empty title."""
        result = ticktick_tools["create_task"](title="")

        assert "error" in result
        assert "required" in result["error"].lower()


class TestListTasks:
    """Tests for ticktick_list_tasks tool."""

    def test_list_tasks_success(self, ticktick_tools):
        """List tasks returns tasks from project data."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"tasks":[{"id":"t1"},{"id":"t2"}]}'
            mock_response.json.return_value = {
                "id": "proj1",
                "name": "Inbox",
                "tasks": [
                    {"id": "t1", "title": "Task 1", "status": 0},
                    {"id": "t2", "title": "Task 2", "status": 0},
                ],
            }
            mock_get.return_value = mock_response

            result = ticktick_tools["list_tasks"](project_id="proj1")

            assert "tasks" in result
            assert len(result["tasks"]) == 2
            assert result["tasks"][0]["id"] == "t1"

    def test_list_tasks_empty_project(self, ticktick_tools):
        """List tasks returns empty list for project with no tasks."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"id":"proj1","name":"Empty"}'
            mock_response.json.return_value = {
                "id": "proj1",
                "name": "Empty",
            }
            mock_get.return_value = mock_response

            result = ticktick_tools["list_tasks"](project_id="proj1")

            assert result == {"tasks": []}

    def test_list_tasks_missing_project_id(self, ticktick_tools):
        """List tasks returns error for empty project ID."""
        result = ticktick_tools["list_tasks"](project_id="")

        assert "error" in result
        assert "required" in result["error"].lower()


class TestUpdateTask:
    """Tests for ticktick_update_task tool."""

    def test_update_task_success(self, ticktick_tools):
        """Update task returns updated task data."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"id":"t1","title":"Updated title"}'
            mock_response.json.return_value = {
                "id": "t1",
                "title": "Updated title",
                "projectId": "proj1",
            }
            mock_post.return_value = mock_response

            result = ticktick_tools["update_task"](
                task_id="t1",
                project_id="proj1",
                title="Updated title",
            )

            assert result["title"] == "Updated title"

    def test_update_task_missing_task_id(self, ticktick_tools):
        """Update task returns error for empty task ID."""
        result = ticktick_tools["update_task"](task_id="", project_id="proj1")

        assert "error" in result


class TestCompleteTask:
    """Tests for ticktick_complete_task tool."""

    def test_complete_task_success(self, ticktick_tools):
        """Complete task returns success."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b""
            mock_post.return_value = mock_response

            result = ticktick_tools["complete_task"](task_id="t1", project_id="proj1")

            assert result.get("success") is True

    def test_complete_task_not_found(self, ticktick_tools):
        """Complete task returns error for non-existent task."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_post.return_value = mock_response

            result = ticktick_tools["complete_task"](task_id="nonexistent", project_id="proj1")

            assert "error" in result
            assert "not found" in result["error"].lower()

    def test_complete_task_missing_ids(self, ticktick_tools):
        """Complete task returns error for empty IDs."""
        result = ticktick_tools["complete_task"](task_id="", project_id="proj1")
        assert "error" in result

        result = ticktick_tools["complete_task"](task_id="t1", project_id="")
        assert "error" in result


class TestDeleteTask:
    """Tests for ticktick_delete_task tool."""

    def test_delete_task_success(self, ticktick_tools):
        """Delete task returns success."""
        with patch("httpx.delete") as mock_delete:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b""
            mock_delete.return_value = mock_response

            result = ticktick_tools["delete_task"](task_id="t1", project_id="proj1")

            assert result.get("success") is True

            # Verify URL
            call_args = mock_delete.call_args
            url = call_args[0][0]
            assert "/project/proj1/task/t1" in url


class TestListProjects:
    """Tests for ticktick_list_projects tool."""

    def test_list_projects_success(self, ticktick_tools):
        """List projects returns project list."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'[{"id":"p1"},{"id":"p2"}]'
            mock_response.json.return_value = [
                {"id": "p1", "name": "Inbox"},
                {"id": "p2", "name": "Work"},
            ]
            mock_get.return_value = mock_response

            result = ticktick_tools["list_projects"]()

            assert "projects" in result
            assert len(result["projects"]) == 2

    def test_list_projects_empty(self, ticktick_tools):
        """List projects returns empty list when no projects exist."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b"[]"
            mock_response.json.return_value = []
            mock_get.return_value = mock_response

            result = ticktick_tools["list_projects"]()

            assert result == {"projects": []}


class TestCreateProject:
    """Tests for ticktick_create_project tool."""

    def test_create_project_success(self, ticktick_tools):
        """Create project returns created project data."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.content = b'{"id":"p3","name":"New Project"}'
            mock_response.json.return_value = {
                "id": "p3",
                "name": "New Project",
            }
            mock_post.return_value = mock_response

            result = ticktick_tools["create_project"](name="New Project")

            assert result["id"] == "p3"
            assert result["name"] == "New Project"

    def test_create_project_empty_name(self, ticktick_tools):
        """Create project returns error for empty name."""
        result = ticktick_tools["create_project"](name="")

        assert "error" in result
        assert "required" in result["error"].lower()


class TestListTags:
    """Tests for ticktick_list_tags tool."""

    def test_list_tags_not_implemented(self, ticktick_tools):
        """List tags returns not-implemented error."""
        result = ticktick_tools["list_tags"]()

        assert "error" in result
        assert "Not implemented" in result["error"]


class TestErrorHandling:
    """Tests for error handling across tools."""

    def test_401_unauthorized(self, ticktick_tools):
        """401 response returns authentication error."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_get.return_value = mock_response

            result = ticktick_tools["list_projects"]()

            assert "error" in result
            assert "Invalid" in result["error"] or "expired" in result["error"]

    def test_403_forbidden(self, ticktick_tools):
        """403 response returns forbidden error."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 403
            mock_get.return_value = mock_response

            result = ticktick_tools["list_tasks"](project_id="proj1")

            assert "error" in result
            assert "forbidden" in result["error"].lower()

    def test_429_rate_limit(self, ticktick_tools):
        """429 response returns rate limit error."""
        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_get.return_value = mock_response

            result = ticktick_tools["list_projects"]()

            assert "error" in result
            assert "rate limit" in result["error"].lower()

    def test_timeout_error(self, ticktick_tools):
        """Timeout returns appropriate error."""
        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.TimeoutException("Request timed out")

            result = ticktick_tools["list_projects"]()

            assert "error" in result
            assert "timed out" in result["error"].lower()

    def test_network_error(self, ticktick_tools):
        """Network error returns appropriate error."""
        with patch("httpx.post") as mock_post:
            mock_post.side_effect = httpx.RequestError("Connection failed")

            result = ticktick_tools["create_task"](title="Test")

            assert "error" in result
            assert "network" in result["error"].lower()

    def test_missing_credentials_on_create(self, mcp: FastMCP, monkeypatch):
        """Create task without credentials returns helpful error."""
        monkeypatch.delenv("TICKTICK_ACCESS_TOKEN", raising=False)
        register_tools(mcp)

        fn = mcp._tool_manager._tools["ticktick_create_task"].fn
        result = fn(title="Test task")

        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_missing_credentials_on_complete(self, mcp: FastMCP, monkeypatch):
        """Complete task without credentials returns helpful error."""
        monkeypatch.delenv("TICKTICK_ACCESS_TOKEN", raising=False)
        register_tools(mcp)

        fn = mcp._tool_manager._tools["ticktick_complete_task"].fn
        result = fn(task_id="t1", project_id="p1")

        assert "error" in result
        assert "not configured" in result["error"]
        assert "help" in result

    def test_server_error(self, ticktick_tools):
        """5xx response returns API error."""
        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.text = "Internal Server Error"
            mock_response.json.side_effect = Exception("not json")
            mock_post.return_value = mock_response

            result = ticktick_tools["create_task"](title="Test")

            assert "error" in result
            assert "500" in result["error"]
