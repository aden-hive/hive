"""Tests for todoist_tool — tasks and projects (FastMCP)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.todoist_tool.todoist_tool import register_tools

ENV = {"TODOIST_API_TOKEN": "test-token"}
PATCH_BASE = "aden_tools.tools.todoist_tool.todoist_tool"


def _mock_resp(data, status_code=200, text=""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    if status_code == 204:
        resp.json.side_effect = ValueError("no json")
    else:
        resp.json.return_value = data
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


# ---------------------------------------------------------------------------
# Shared HTTP / auth errors
# ---------------------------------------------------------------------------


class TestTodoistRequestErrors:
    @pytest.mark.parametrize(
        ("status_code", "fragment"),
        [
            (401, "Invalid or expired"),
            (403, "forbidden"),
            (404, "not found"),
            (429, "Rate limit"),
        ],
    )
    def test_get_tasks_http_errors(self, tool_fns, status_code, fragment):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.get",
                return_value=_mock_resp({}, status_code),
            ),
        ):
            result = tool_fns["todoist_get_tasks"]()
        assert "error" in result
        assert fragment.lower() in result["error"].lower()

    def test_get_tasks_timeout(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.get",
                side_effect=httpx.TimeoutException("timed out"),
            ),
        ):
            result = tool_fns["todoist_get_tasks"]()
        assert "error" in result
        assert "timed out" in result["error"].lower()

    def test_get_tasks_generic_exception(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.get",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = tool_fns["todoist_get_tasks"]()
        assert "error" in result
        assert "boom" in result["error"]


class TestCredentialStoreAdapter:
    def test_credential_store_used_when_provided(self, mcp: FastMCP):
        mock_creds = MagicMock()
        mock_creds.get.return_value = "store-token"
        register_tools(mcp, credentials=mock_creds)
        tools = mcp._tool_manager._tools
        fn = tools["todoist_get_tasks"].fn

        with patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp([])) as mock_get:
            fn()

        mock_creds.get.assert_called_with("todoist_token")
        hdrs = mock_get.call_args.kwargs.get("headers", {})
        assert hdrs.get("Authorization") == "Bearer store-token"


# ---------------------------------------------------------------------------
# todoist_get_tasks
# ---------------------------------------------------------------------------


class TestTodoistGetTasks:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["todoist_get_tasks"]()
        assert "error" in result

    def test_invalid_priority(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["todoist_get_tasks"](priority=99)
        assert "error" in result
        assert "priority" in result["error"].lower()

    def test_success_and_filters(self, tool_fns):
        payload = [
            {"id": "1", "content": "A", "priority": 1},
            {"id": "2", "content": "B", "priority": 4},
        ]
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(payload)) as mock_get,
        ):
            result = tool_fns["todoist_get_tasks"](
                project_id="2203306141",
                label_ids="123,456",
                priority=4,
            )

        assert result["count"] == 1
        assert result["tasks"][0]["id"] == "2"
        assert mock_get.call_args[0][0].endswith("/tasks")
        params = mock_get.call_args.kwargs.get("params") or {}
        assert params.get("project_id") == "2203306141"
        assert params.get("label_ids") == "123,456"


# ---------------------------------------------------------------------------
# todoist_create_task
# ---------------------------------------------------------------------------


class TestTodoistCreateTask:
    def test_missing_content(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["todoist_create_task"](content="   ")
        assert "error" in result

    def test_invalid_priority(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["todoist_create_task"](content="Buy milk", priority=9)
        assert "error" in result

    def test_success(self, tool_fns):
        created = {
            "id": "task-1",
            "content": "Buy milk",
            "priority": 4,
            "project_id": "2203306141",
        }
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(created)) as mock_post,
        ):
            result = tool_fns["todoist_create_task"](
                content="Buy milk",
                due_string="tomorrow",
                priority=4,
                project_id="2203306141",
            )

        assert result["id"] == "task-1"
        body = mock_post.call_args.kwargs["json"]
        assert body["content"] == "Buy milk"
        assert body["due_string"] == "tomorrow"
        assert body["priority"] == 4
        assert body["project_id"] == "2203306141"


# ---------------------------------------------------------------------------
# todoist_complete_task
# ---------------------------------------------------------------------------


class TestTodoistCompleteTask:
    def test_missing_task_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["todoist_complete_task"](task_id="")
        assert "error" in result

    def test_success_204(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.post",
                return_value=_mock_resp({}, status_code=204),
            ),
        ):
            result = tool_fns["todoist_complete_task"](task_id="task-99")

        assert result["status"] == "completed"
        assert result["id"] == "task-99"


# ---------------------------------------------------------------------------
# todoist_get_projects
# ---------------------------------------------------------------------------


class TestTodoistGetProjects:
    def test_success(self, tool_fns):
        plist = [{"id": "p1", "name": "Inbox"}]
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.get", return_value=_mock_resp(plist)),
        ):
            result = tool_fns["todoist_get_projects"]()

        assert result["count"] == 1
        assert result["projects"][0]["name"] == "Inbox"


# ---------------------------------------------------------------------------
# todoist_create_project
# ---------------------------------------------------------------------------


class TestTodoistCreateProject:
    def test_missing_name(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["todoist_create_project"](name="")
        assert "error" in result

    def test_success(self, tool_fns):
        proj = {"id": "proj-1", "name": "Work", "color": "30"}
        with (
            patch.dict("os.environ", ENV),
            patch(f"{PATCH_BASE}.httpx.post", return_value=_mock_resp(proj)) as mock_post,
        ):
            result = tool_fns["todoist_create_project"](name="Work", color="30")

        assert result["name"] == "Work"
        assert mock_post.call_args.kwargs["json"] == {"name": "Work", "color": "30"}


# ---------------------------------------------------------------------------
# todoist_delete_task
# ---------------------------------------------------------------------------


class TestTodoistDeleteTask:
    def test_missing_task_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["todoist_delete_task"](task_id="")
        assert "error" in result

    def test_success_204(self, tool_fns):
        with (
            patch.dict("os.environ", ENV),
            patch(
                f"{PATCH_BASE}.httpx.delete",
                return_value=_mock_resp({}, status_code=204),
            ),
        ):
            result = tool_fns["todoist_delete_task"](task_id="task-del")

        assert result["status"] == "deleted"
        assert result["id"] == "task-del"
