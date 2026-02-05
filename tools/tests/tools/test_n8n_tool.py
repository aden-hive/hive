"""Tests for n8n workflow automation tool with FastMCP."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.n8n_tool import register_tools


@pytest.fixture
def mcp():
    """Create a FastMCP instance for testing."""
    return FastMCP("test-server")


@pytest.fixture
def n8n_execute_workflow_fn(mcp: FastMCP):
    """Register and return the n8n_execute_workflow tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_execute_workflow"].fn


@pytest.fixture
def n8n_trigger_webhook_fn(mcp: FastMCP):
    """Register and return the n8n_trigger_webhook tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_trigger_webhook"].fn


@pytest.fixture
def n8n_get_execution_status_fn(mcp: FastMCP):
    """Register and return the n8n_get_execution_status tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_get_execution_status"].fn


@pytest.fixture
def n8n_list_executions_fn(mcp: FastMCP):
    """Register and return the n8n_list_executions tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_list_executions"].fn


@pytest.fixture
def n8n_list_workflows_fn(mcp: FastMCP):
    """Register and return the n8n_list_workflows tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_list_workflows"].fn


@pytest.fixture
def n8n_get_workflow_fn(mcp: FastMCP):
    """Register and return the n8n_get_workflow tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_get_workflow"].fn


@pytest.fixture
def n8n_activate_workflow_fn(mcp: FastMCP):
    """Register and return the n8n_activate_workflow tool function."""
    register_tools(mcp)
    return mcp._tool_manager._tools["n8n_activate_workflow"].fn


class TestN8nCredentials:
    """Tests for n8n credential handling."""

    def test_no_url_returns_error(self, n8n_execute_workflow_fn, monkeypatch):
        """Execute without API URL returns helpful error."""
        monkeypatch.delenv("N8N_API_URL", raising=False)
        monkeypatch.delenv("N8N_URL", raising=False)
        monkeypatch.setenv("N8N_API_KEY", "test-key")

        result = n8n_execute_workflow_fn(workflow_id="123")

        assert "error" in result
        assert "n8n API URL not configured" in result["error"]
        assert "help" in result

    def test_no_api_key_returns_error(self, n8n_execute_workflow_fn, monkeypatch):
        """Execute without API key returns helpful error."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.delenv("N8N_API_KEY", raising=False)

        result = n8n_execute_workflow_fn(workflow_id="123")

        assert "error" in result
        assert "n8n API key not configured" in result["error"]
        assert "help" in result


class TestN8nExecuteWorkflow:
    """Tests for n8n_execute_workflow tool."""

    def test_execute_workflow_success(self, n8n_execute_workflow_fn, monkeypatch):
        """Successful workflow execution returns execution details."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "exec-123",
                "status": "success",
                "data": {"result": "completed"},
            }
            mock_post.return_value = mock_response

            result = n8n_execute_workflow_fn(workflow_id="wf-456")

        assert result["success"] is True
        assert result["execution_id"] == "exec-123"
        assert result["status"] == "success"

    def test_execute_workflow_with_data(self, n8n_execute_workflow_fn, monkeypatch):
        """Workflow execution with input data passes data correctly."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"id": "exec-789", "status": "success"}
            mock_post.return_value = mock_response

            result = n8n_execute_workflow_fn(
                workflow_id="wf-123", data={"input": "value"}
            )

        assert result["success"] is True
        # Verify the data was passed in the request body
        call_kwargs = mock_post.call_args
        assert call_kwargs[1]["json"] == {"input": "value"}

    def test_execute_workflow_not_found(self, n8n_execute_workflow_fn, monkeypatch):
        """Workflow not found returns appropriate error."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 404
            mock_response.json.return_value = {"message": "Workflow not found"}
            mock_post.return_value = mock_response

            result = n8n_execute_workflow_fn(workflow_id="nonexistent")

        assert "error" in result


class TestN8nTriggerWebhook:
    """Tests for n8n_trigger_webhook tool."""

    def test_trigger_webhook_success(self, n8n_trigger_webhook_fn, monkeypatch):
        """Successful webhook trigger returns response data."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"received": True, "processed": "ok"}
            mock_post.return_value = mock_response

            result = n8n_trigger_webhook_fn(
                webhook_path="my-webhook", data={"event": "test"}
            )

        assert result["success"] is True
        assert result["data"]["received"] is True

    def test_trigger_webhook_full_url(self, n8n_trigger_webhook_fn, monkeypatch):
        """Webhook with full URL uses URL directly."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"ok": True}
            mock_post.return_value = mock_response

            result = n8n_trigger_webhook_fn(
                webhook_path="https://other-n8n.com/webhook/custom"
            )

        assert result["success"] is True
        call_args = mock_post.call_args
        assert "https://other-n8n.com/webhook/custom" in str(call_args)

    def test_trigger_webhook_get_method(self, n8n_trigger_webhook_fn, monkeypatch):
        """Webhook with GET method uses httpx.get."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}
            mock_get.return_value = mock_response

            result = n8n_trigger_webhook_fn(webhook_path="my-webhook", method="GET")

        assert result["success"] is True
        mock_get.assert_called_once()


class TestN8nGetExecutionStatus:
    """Tests for n8n_get_execution_status tool."""

    def test_get_execution_status_success(
        self, n8n_get_execution_status_fn, monkeypatch
    ):
        """Get execution status returns full execution details."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "exec-123",
                "status": "success",
                "mode": "manual",
                "startedAt": "2024-01-15T10:00:00Z",
                "stoppedAt": "2024-01-15T10:00:05Z",
                "workflowId": "wf-456",
                "finished": True,
                "data": {"output": "result"},
            }
            mock_get.return_value = mock_response

            result = n8n_get_execution_status_fn(execution_id="exec-123")

        assert result["success"] is True
        assert result["execution"]["id"] == "exec-123"
        assert result["execution"]["status"] == "success"
        assert result["execution"]["finished"] is True

    def test_get_execution_status_running(
        self, n8n_get_execution_status_fn, monkeypatch
    ):
        """Get execution status for running workflow."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "exec-789",
                "status": "running",
                "startedAt": "2024-01-15T10:00:00Z",
                "finished": False,
            }
            mock_get.return_value = mock_response

            result = n8n_get_execution_status_fn(execution_id="exec-789")

        assert result["success"] is True
        assert result["execution"]["status"] == "running"
        assert result["execution"]["finished"] is False


class TestN8nListExecutions:
    """Tests for n8n_list_executions tool."""

    def test_list_executions_success(self, n8n_list_executions_fn, monkeypatch):
        """List executions returns execution list."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {
                        "id": "exec-1",
                        "status": "success",
                        "workflowId": "wf-1",
                        "finished": True,
                    },
                    {
                        "id": "exec-2",
                        "status": "error",
                        "workflowId": "wf-2",
                        "finished": True,
                    },
                ]
            }
            mock_get.return_value = mock_response

            result = n8n_list_executions_fn()

        assert result["success"] is True
        assert result["count"] == 2
        assert len(result["executions"]) == 2

    def test_list_executions_with_filters(self, n8n_list_executions_fn, monkeypatch):
        """List executions with workflow_id and status filters."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": []}
            mock_get.return_value = mock_response

            result = n8n_list_executions_fn(
                workflow_id="wf-123", status="error", limit=10
            )

        assert result["success"] is True
        # Verify filters were passed
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["workflowId"] == "wf-123"
        assert params["status"] == "error"
        assert params["limit"] == 10


class TestN8nListWorkflows:
    """Tests for n8n_list_workflows tool."""

    def test_list_workflows_success(self, n8n_list_workflows_fn, monkeypatch):
        """List workflows returns workflow list."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {
                        "id": "wf-1",
                        "name": "My Workflow",
                        "active": True,
                        "createdAt": "2024-01-01T00:00:00Z",
                    },
                    {
                        "id": "wf-2",
                        "name": "Another Workflow",
                        "active": False,
                        "createdAt": "2024-01-02T00:00:00Z",
                    },
                ]
            }
            mock_get.return_value = mock_response

            result = n8n_list_workflows_fn()

        assert result["success"] is True
        assert result["count"] == 2
        assert result["workflows"][0]["name"] == "My Workflow"
        assert result["workflows"][0]["active"] is True

    def test_list_workflows_active_only(self, n8n_list_workflows_fn, monkeypatch):
        """List workflows with active_only filter."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": []}
            mock_get.return_value = mock_response

            result = n8n_list_workflows_fn(active_only=True)

        assert result["success"] is True
        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["active"] == "true"


class TestN8nGetWorkflow:
    """Tests for n8n_get_workflow tool."""

    def test_get_workflow_success(self, n8n_get_workflow_fn, monkeypatch):
        """Get workflow returns workflow details."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "wf-123",
                "name": "Test Workflow",
                "active": True,
                "nodes": [
                    {"name": "Start", "type": "n8n-nodes-base.manualTrigger"},
                    {"name": "HTTP Request", "type": "n8n-nodes-base.httpRequest"},
                ],
            }
            mock_get.return_value = mock_response

            result = n8n_get_workflow_fn(workflow_id="wf-123")

        assert result["success"] is True
        assert result["workflow"]["id"] == "wf-123"
        assert result["workflow"]["name"] == "Test Workflow"
        assert len(result["workflow"]["nodes"]) == 2


class TestN8nActivateWorkflow:
    """Tests for n8n_activate_workflow tool."""

    def test_activate_workflow_success(self, n8n_activate_workflow_fn, monkeypatch):
        """Activate workflow returns updated status."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.patch") as mock_patch:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "wf-123",
                "name": "Test Workflow",
                "active": True,
            }
            mock_patch.return_value = mock_response

            result = n8n_activate_workflow_fn(workflow_id="wf-123", active=True)

        assert result["success"] is True
        assert result["workflow"]["active"] is True

    def test_deactivate_workflow_success(self, n8n_activate_workflow_fn, monkeypatch):
        """Deactivate workflow returns updated status."""
        monkeypatch.setenv("N8N_API_URL", "https://n8n.example.com")
        monkeypatch.setenv("N8N_API_KEY", "test-api-key")

        with patch("httpx.patch") as mock_patch:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "id": "wf-123",
                "name": "Test Workflow",
                "active": False,
            }
            mock_patch.return_value = mock_response

            result = n8n_activate_workflow_fn(workflow_id="wf-123", active=False)

        assert result["success"] is True
        assert result["workflow"]["active"] is False
        # Verify the active=False was passed
        call_kwargs = mock_patch.call_args
        assert call_kwargs[1]["json"]["active"] is False
