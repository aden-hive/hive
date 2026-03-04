"""Tests for n8n_tool - n8n workflow automation API."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.n8n_tool.n8n_tool import register_tools

ENV = {
    "N8N_API_KEY": "test-api-key-123",
    "N8N_BASE_URL": "https://my-n8n.example.com",
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


class TestN8nListWorkflows:
    def test_missing_credentials(self, tool_fns):
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["n8n_list_workflows"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "wf1",
                    "name": "Email Workflow",
                    "active": True,
                    "createdAt": "2025-01-10T11:00:00Z",
                    "updatedAt": "2025-01-11T12:00:00Z",
                    "tags": [{"name": "production"}],
                    "nodes": [{"name": "Start"}, {"name": "Email"}],
                }
            ],
            "nextCursor": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_list_workflows"]()

        assert result["count"] == 1
        assert result["workflows"][0]["name"] == "Email Workflow"
        assert result["workflows"][0]["active"] is True
        assert result["workflows"][0]["tags"] == ["production"]
        assert result["workflows"][0]["node_count"] == 2

    def test_pagination(self, tool_fns):
        data = {
            "data": [
                {
                    "id": "wf1",
                    "name": "WF1",
                    "active": True,
                    "createdAt": "",
                    "updatedAt": "",
                    "tags": [],
                    "nodes": [],
                }
            ],
            "nextCursor": "cursor123",
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_list_workflows"]()

        assert result["next_cursor"] == "cursor123"


class TestN8nGetWorkflow:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["n8n_get_workflow"](workflow_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": "wf1",
            "name": "Email Workflow",
            "active": True,
            "createdAt": "2025-01-10T11:00:00Z",
            "updatedAt": "2025-01-11T12:00:00Z",
            "tags": [{"name": "production"}],
            "nodes": [
                {"name": "Start", "type": "n8n-nodes-base.start", "position": [100, 200]},
                {"name": "Send Email", "type": "n8n-nodes-base.emailSend", "position": [300, 200]},
            ],
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_get_workflow"](workflow_id="wf1")

        assert result["name"] == "Email Workflow"
        assert result["node_count"] == 2
        assert result["nodes"][1]["type"] == "n8n-nodes-base.emailSend"


class TestN8nActivateWorkflow:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["n8n_activate_workflow"](workflow_id="")
        assert "error" in result

    def test_successful_activate(self, tool_fns):
        data = {"id": "wf1", "name": "Email Workflow", "active": True}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_activate_workflow"](workflow_id="wf1")

        assert result["active"] is True


class TestN8nDeactivateWorkflow:
    def test_successful_deactivate(self, tool_fns):
        data = {"id": "wf1", "name": "Email Workflow", "active": False}
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_deactivate_workflow"](workflow_id="wf1")

        assert result["active"] is False


class TestN8nListExecutions:
    def test_successful_list(self, tool_fns):
        data = {
            "data": [
                {
                    "id": 1000,
                    "workflowId": "wf1",
                    "status": "success",
                    "mode": "webhook",
                    "finished": True,
                    "startedAt": "2025-01-10T11:00:00Z",
                    "stoppedAt": "2025-01-10T11:00:05Z",
                }
            ],
            "nextCursor": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_list_executions"]()

        assert result["count"] == 1
        assert result["executions"][0]["status"] == "success"
        assert result["executions"][0]["workflow_id"] == "wf1"


class TestN8nGetExecution:
    def test_missing_id(self, tool_fns):
        with patch.dict("os.environ", ENV):
            result = tool_fns["n8n_get_execution"](execution_id="")
        assert "error" in result

    def test_successful_get(self, tool_fns):
        data = {
            "id": 1000,
            "workflowId": "wf1",
            "status": "error",
            "mode": "manual",
            "finished": True,
            "startedAt": "2025-01-10T11:00:00Z",
            "stoppedAt": "2025-01-10T11:00:05Z",
            "retryOf": None,
            "retrySuccessId": None,
        }
        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.get", return_value=_mock_resp(data)),
        ):
            result = tool_fns["n8n_get_execution"](execution_id="1000")

        assert result["status"] == "error"
        assert result["mode"] == "manual"
