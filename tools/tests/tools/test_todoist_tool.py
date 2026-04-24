"""
Tests for Todoist tool.

Covers:
- _TodoistClient methods (list_tasks, get_task, create_task, update_task, complete_task, delete_task, list_projects, create_project)
- Error handling (401, 403, 404, 429, timeout)
- Credential retrieval (CredentialStoreAdapter vs env var)
- All 8 MCP tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from aden_tools.tools.todoist_tool.todoist_tool import (
    MAX_RETRIES,
    _TodoistClient,
    register_tools,
)

# --- _TodoistClient tests ---


class TestTodoistClient:
    def setup_method(self):
        self.client = _TodoistClient("test-api-key")

    def test_headers(self):
        headers = self.client._headers
        assert headers["Content-Type"] == "application/json"
        assert headers["Authorization"] == "Bearer test-api-key"

    def test_handle_response_success(self):
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"id": "123", "content": "Test task"}
        assert self.client._handle_response(response) == {"id": "123", "content": "Test task"}

    def test_handle_response_204(self):
        response = MagicMock()
        response.status_code = 204
        result = self.client._handle_response(response)
        assert result == {"success": True}

    def test_handle_response_rate_limit_429(self):
        response = MagicMock()
        response.status_code = 429
        result = self.client._handle_response(response)
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert result["status_code"] == 429

    @pytest.mark.parametrize(
        "status_code",
        [401, 403, 404, 500],
    )
    def test_handle_response_errors(self, status_code):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = "Test error"
        response.text = "Test error"
        result = self.client._handle_response(response)
        assert "error" in result
        assert str(status_code) in result["error"]

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_list_tasks(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "t1", "content": "Task 1"},
                    {"id": "t2", "content": "Task 2"},
                ]
            ),
        )
        result = self.client.list_tasks()
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "GET"
        assert "tasks" in mock_request.call_args[0][1]
        assert len(result) == 2
        assert result[0]["content"] == "Task 1"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_list_tasks_with_filters(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{"id": "t1", "content": "Task 1"}]),
        )
        result = self.client.list_tasks(project_id="p123", label="work")
        assert mock_request.call_args[1]["params"]["project_id"] == "p123"
        assert mock_request.call_args[1]["params"]["label"] == "work"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_get_task(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": "t1", "content": "Task 1"}),
        )
        result = self.client.get_task("t1")
        mock_request.assert_called_once()
        assert "tasks/t1" in mock_request.call_args[0][1]
        assert result["content"] == "Task 1"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_create_task(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "t123",
                    "content": "New task",
                    "priority": 3,
                }
            ),
        )
        result = self.client.create_task(
            content="New task",
            description="Task description",
            priority=3,
            labels=["work", "urgent"],
        )
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "POST"
        assert "tasks" in mock_request.call_args[0][1]
        assert result["content"] == "New task"
        assert result["priority"] == 3

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_update_task(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": "t1", "content": "Updated task", "priority": 4}),
        )
        result = self.client.update_task("t1", content="Updated task", priority=4)
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "POST"
        assert "tasks/t1" in mock_request.call_args[0][1]
        assert result["content"] == "Updated task"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_complete_task(self, mock_request):
        mock_request.return_value = MagicMock(status_code=204)
        result = self.client.complete_task("t1")
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "POST"
        assert "tasks/t1/close" in mock_request.call_args[0][1]
        assert result["success"] is True

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_delete_task(self, mock_request):
        mock_request.return_value = MagicMock(status_code=204)
        result = self.client.delete_task("t1")
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "DELETE"
        assert "tasks/t1" in mock_request.call_args[0][1]
        assert result["success"] is True

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_list_projects(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "p1", "name": "Project 1"},
                    {"id": "p2", "name": "Project 2"},
                ]
            ),
        )
        result = self.client.list_projects()
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "GET"
        assert "projects" in mock_request.call_args[0][1]
        assert len(result) == 2
        assert result[0]["name"] == "Project 1"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_create_project(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": "p123", "name": "New Project", "color": "blue"}),
        )
        result = self.client.create_project(name="New Project", color="blue", is_favorite=True)
        mock_request.assert_called_once()
        assert mock_request.call_args[0][0] == "POST"
        assert "projects" in mock_request.call_args[0][1]
        assert result["name"] == "New Project"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.time.sleep")
    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_retry_on_429_then_success(self, mock_request, mock_sleep):
        mock_request.side_effect = [
            MagicMock(status_code=429),
            MagicMock(
                status_code=200,
                json=MagicMock(return_value=[{"id": "t1", "content": "Task"}]),
            ),
        ]
        result = self.client.list_tasks()
        assert len(result) == 1
        assert result[0]["content"] == "Task"
        assert mock_request.call_count == 2
        mock_sleep.assert_called_once()

    @patch("aden_tools.tools.todoist_tool.todoist_tool.time.sleep")
    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_retry_exhausted_returns_error(self, mock_request, mock_sleep):
        mock_request.return_value = MagicMock(status_code=429)
        result = self.client.list_tasks()
        assert "error" in result
        assert "rate limit" in result["error"].lower()
        assert mock_request.call_count == MAX_RETRIES + 1


# --- Tool registration tests ---


class TestTodoistListTasksTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_list_tasks_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value=[{"id": "t1", "content": "Test task"}]),
        )
        result = self._fn("todoist_list_tasks")()
        assert result["success"] is True
        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["content"] == "Test task"

    def test_list_tasks_no_credentials(self):
        mcp = MagicMock()
        fns = []
        mcp.tool.return_value = lambda fn: fns.append(fn) or fn
        register_tools(mcp, credentials=None)
        with patch.dict("os.environ", {"TODOIST_API_KEY": ""}, clear=False):
            result = next(f for f in fns if f.__name__ == "todoist_list_tasks")()
        assert "error" in result
        assert "not configured" in result["error"]


class TestTodoistGetTaskTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_get_task_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": "t1", "content": "Test task"}),
        )
        result = self._fn("todoist_get_task")("t1")
        assert result["success"] is True
        assert result["task"]["content"] == "Test task"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_get_task_not_found(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=404,
            json=MagicMock(return_value="Task not found"),
            text="Task not found",
        )
        result = self._fn("todoist_get_task")("bad-id")
        assert "error" in result
        assert "404" in result["error"]



class TestTodoistCreateTaskTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_create_task_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "t123",
                    "content": "New task",
                    "priority": 1,
                }
            ),
        )
        result = self._fn("todoist_create_task")("New task")
        assert result["success"] is True
        assert result["task"]["content"] == "New task"

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_create_task_with_all_params(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value={
                    "id": "t123",
                    "content": "Complex task",
                    "description": "Description",
                    "priority": 4,
                    "labels": ["work", "urgent"],
                }
            ),
        )
        result = self._fn("todoist_create_task")(
            content="Complex task",
            description="Description",
            priority=4,
            labels=["work", "urgent"],
            due_string="tomorrow",
        )
        assert result["success"] is True
        assert result["task"]["priority"] == 4


class TestTodoistUpdateTaskTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_update_task_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": "t1", "content": "Updated", "priority": 4}),
        )
        result = self._fn("todoist_update_task")("t1", content="Updated", priority=4)
        assert result["success"] is True
        assert result["task"]["content"] == "Updated"


class TestTodoistCompleteTaskTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_complete_task_success(self, mock_request):
        mock_request.return_value = MagicMock(status_code=204)
        result = self._fn("todoist_complete_task")("t1")
        assert result["success"] is True
        assert result["completed_task_id"] == "t1"


class TestTodoistDeleteTaskTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_delete_task_success(self, mock_request):
        mock_request.return_value = MagicMock(status_code=204)
        result = self._fn("todoist_delete_task")("t1")
        assert result["success"] is True
        assert result["deleted_task_id"] == "t1"



class TestTodoistListProjectsTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_list_projects_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(
                return_value=[
                    {"id": "p1", "name": "Project 1"},
                    {"id": "p2", "name": "Project 2"},
                ]
            ),
        )
        result = self._fn("todoist_list_projects")()
        assert result["success"] is True
        assert len(result["projects"]) == 2
        assert result["projects"][0]["name"] == "Project 1"


class TestTodoistCreateProjectTool:
    def setup_method(self):
        self.mcp = MagicMock()
        self.fns = []
        self.mcp.tool.return_value = lambda fn: self.fns.append(fn) or fn
        cred = MagicMock()
        cred.get.return_value = "test-api-key"
        register_tools(self.mcp, credentials=cred)

    def _fn(self, name):
        return next(f for f in self.fns if f.__name__ == name)

    @patch("aden_tools.tools.todoist_tool.todoist_tool.httpx.request")
    def test_create_project_success(self, mock_request):
        mock_request.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"id": "p123", "name": "New Project", "color": "blue"}),
        )
        result = self._fn("todoist_create_project")("New Project", color="blue", is_favorite=True)
        assert result["success"] is True
        assert result["project"]["name"] == "New Project"


# --- Credential spec tests ---


class TestCredentialSpec:
    def test_todoist_credential_spec_exists(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        assert "todoist" in CREDENTIAL_SPECS

    def test_todoist_spec_env_var(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["todoist"]
        assert spec.env_var == "TODOIST_API_KEY"

    def test_todoist_spec_tools(self):
        from aden_tools.credentials import CREDENTIAL_SPECS

        spec = CREDENTIAL_SPECS["todoist"]
        assert "todoist_list_tasks" in spec.tools
        assert "todoist_get_task" in spec.tools
        assert "todoist_create_task" in spec.tools
        assert "todoist_update_task" in spec.tools
        assert "todoist_complete_task" in spec.tools
        assert "todoist_delete_task" in spec.tools
        assert "todoist_list_projects" in spec.tools
        assert "todoist_create_project" in spec.tools
        assert len(spec.tools) == 8
