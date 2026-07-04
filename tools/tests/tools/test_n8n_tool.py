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


# ---------------------------------------------------------------------------
# n8n_trigger_webhook tests
# ---------------------------------------------------------------------------

WEBHOOK_URL = "https://my-n8n.example.com/webhook/abc123"


class TestN8nTriggerWebhook:
    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def test_missing_webhook_url(self, tool_fns):
        result = tool_fns["n8n_trigger_webhook"](webhook_url="")
        assert "error" in result
        assert result["error"] == "webhook_url is required"

    def test_invalid_method(self, tool_fns):
        result = tool_fns["n8n_trigger_webhook"](
            webhook_url=WEBHOOK_URL,
            method="DELETE",
        )
        assert "error" in result
        assert "method" in result["error"].lower()

    # ------------------------------------------------------------------
    # Successful POST
    # ------------------------------------------------------------------

    def test_post_json_response(self, tool_fns):
        response_data = {"executionId": "exec-42", "status": "running"}
        with patch(
            "aden_tools.tools.n8n_tool.n8n_tool.httpx.post",
            return_value=_mock_resp(response_data, status_code=200),
        ):
            result = tool_fns["n8n_trigger_webhook"](
                webhook_url=WEBHOOK_URL,
                payload={"order_id": "ORD-1"},
            )

        assert result["triggered"] is True
        assert result["status_code"] == 200
        assert result["response"]["executionId"] == "exec-42"

    def test_post_plain_text_response(self, tool_fns):
        """Webhook that returns plain text (not JSON) should still succeed."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("not json")
        resp.text = "Workflow executed"

        with patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", return_value=resp):
            result = tool_fns["n8n_trigger_webhook"](
                webhook_url=WEBHOOK_URL,
                payload={"ping": True},
            )

        assert result["triggered"] is True
        assert result["response"] == "Workflow executed"

    def test_post_204_no_content(self, tool_fns):
        """HTTP 204 means the webhook triggered but returned no body."""
        resp = MagicMock()
        resp.status_code = 204

        with patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", return_value=resp):
            result = tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL)

        assert result["triggered"] is True
        assert result["status_code"] == 204
        assert result["response"] == {}

    # ------------------------------------------------------------------
    # Successful GET
    # ------------------------------------------------------------------

    def test_get_request(self, tool_fns):
        response_data = {"pong": True}
        with patch(
            "aden_tools.tools.n8n_tool.n8n_tool.httpx.get",
            return_value=_mock_resp(response_data, status_code=200),
        ):
            result = tool_fns["n8n_trigger_webhook"](
                webhook_url=WEBHOOK_URL,
                method="GET",
                payload={"check": "health"},
            )

        assert result["triggered"] is True
        assert result["status_code"] == 200

    # ------------------------------------------------------------------
    # Custom headers
    # ------------------------------------------------------------------

    def test_custom_headers_forwarded(self, tool_fns):
        """Extra headers supplied by the caller should reach the HTTP layer."""
        response_data = {"ok": True}
        captured: dict = {}

        def fake_post(url, json, headers, timeout):
            captured["headers"] = headers
            return _mock_resp(response_data)

        with patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", side_effect=fake_post):
            tool_fns["n8n_trigger_webhook"](
                webhook_url=WEBHOOK_URL,
                headers={"X-Source": "hive-agent"},
            )

        assert captured["headers"].get("X-Source") == "hive-agent"
        # Default Content-Type should still be present
        assert "Content-Type" in captured["headers"]

    # ------------------------------------------------------------------
    # Timeout clamping
    # ------------------------------------------------------------------

    def test_timeout_clamped_to_max(self, tool_fns):
        """Timeout values above 120 should be clamped to 120."""
        captured: dict = {}

        def fake_post(url, json, headers, timeout):
            captured["timeout"] = timeout
            return _mock_resp({"ok": True})

        with patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", side_effect=fake_post):
            tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL, timeout=9999)

        assert captured["timeout"] == 120.0

    def test_timeout_clamped_to_min(self, tool_fns):
        """Timeout values below 1 should be clamped to 1."""
        captured: dict = {}

        def fake_post(url, json, headers, timeout):
            captured["timeout"] = timeout
            return _mock_resp({"ok": True})

        with patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", side_effect=fake_post):
            tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL, timeout=0)

        assert captured["timeout"] == 1.0

    # ------------------------------------------------------------------
    # HTTP error responses
    # ------------------------------------------------------------------

    def test_http_404_returns_error(self, tool_fns):
        error_body = {"message": "Workflow not found"}
        with patch(
            "aden_tools.tools.n8n_tool.n8n_tool.httpx.post",
            return_value=_mock_resp(error_body, status_code=404),
        ):
            result = tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL)

        assert result["triggered"] is False
        assert "404" in result["error"]

    def test_http_500_returns_error(self, tool_fns):
        error_body = {"message": "Internal server error"}
        with patch(
            "aden_tools.tools.n8n_tool.n8n_tool.httpx.post",
            return_value=_mock_resp(error_body, status_code=500),
        ):
            result = tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL)

        assert result["triggered"] is False
        assert "500" in result["error"]

    # ------------------------------------------------------------------
    # Network-level errors
    # ------------------------------------------------------------------

    def test_timeout_exception(self, tool_fns):
        import httpx as _httpx

        with patch(
            "aden_tools.tools.n8n_tool.n8n_tool.httpx.post",
            side_effect=_httpx.TimeoutException("timed out"),
        ):
            result = tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL)

        assert result["triggered"] is False
        assert "timed out" in result["error"].lower()

    def test_network_error(self, tool_fns):
        import httpx as _httpx

        with patch(
            "aden_tools.tools.n8n_tool.n8n_tool.httpx.post",
            side_effect=_httpx.RequestError("connection refused"),
        ):
            result = tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL)

        assert result["triggered"] is False
        assert "network error" in result["error"].lower()

    # ------------------------------------------------------------------
    # Empty / None payload defaults to empty dict
    # ------------------------------------------------------------------

    def test_none_payload_defaults_to_empty_dict(self, tool_fns):
        captured: dict = {}

        def fake_post(url, json, headers, timeout):
            captured["json"] = json
            return _mock_resp({"ok": True})

        with patch("aden_tools.tools.n8n_tool.n8n_tool.httpx.post", side_effect=fake_post):
            tool_fns["n8n_trigger_webhook"](webhook_url=WEBHOOK_URL, payload=None)

        assert captured["json"] == {}
