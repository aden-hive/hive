"""Tests for wandb_tool - Weights & Biases integration."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.wandb_tool.wandb_tool import register_tools

ENV = {
    "WANDB_API_KEY": "test-key",
}


def _mock_resp(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = "Internal Server Error" if status_code == 500 else ""
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestWandbTool:
    # --- Credential tests ---

    def test_missing_credentials_returns_error(self, tool_fns):
        """Missing WANDB_API_KEY must return a descriptive error dict."""
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "error" in result
        assert "credentials not configured" in result["error"]
        assert "help" in result

    # --- wandb_list_projects ---

    def test_wandb_list_projects_success(self, tool_fns):
        """wandb_list_projects returns projects from API."""
        data = {"projects": [{"name": "project1"}, {"name": "project2"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ) as mock_get,
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")

        assert result == data
        # Verify entity was passed either in URL or as a query param
        actual_params = mock_get.call_args[1].get("params", {})
        assert actual_params.get("entity") == "test-entity"

    # --- wandb_get_runs ---

    def test_wandb_get_runs_success(self, tool_fns):
        """wandb_get_runs returns runs list with per_page param."""
        data = {"runs": [{"id": "abc123", "name": "run1"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ) as mock_get,
        ):
            result = tool_fns["wandb_get_runs"](
                entity="test-entity", project="test-project", per_page=25
            )

        assert result == data
        params = mock_get.call_args[1]["params"]
        assert params["per_page"] == 25

    def test_wandb_get_runs_with_filters(self, tool_fns):
        """wandb_get_runs passes filters param to API."""
        data = {"runs": []}
        filters = '{"state": "finished"}'
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ) as mock_get,
        ):
            result = tool_fns["wandb_get_runs"](
                entity="test-entity", project="test-project", filters=filters
            )

        assert result == data
        params = mock_get.call_args[1]["params"]
        assert params["filters"] == filters

    # --- wandb_get_run ---

    def test_wandb_get_run_success(self, tool_fns):
        """wandb_get_run with valid run_id returns run details."""
        data = {"id": "run-123", "state": "finished", "config": {"lr": 0.001}}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["wandb_get_run"](
                entity="test-entity", project="test-project", run_id="run-123"
            )

        assert result["id"] == "run-123"
        assert result["config"]["lr"] == 0.001

    def test_wandb_get_run_missing_id(self, tool_fns):
        """wandb_get_run with empty run_id returns error immediately."""
        result = tool_fns["wandb_get_run"](entity="test-entity", project="test-project", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_get_run_metrics ---

    def test_wandb_get_run_metrics_success(self, tool_fns):
        """wandb_get_run_metrics returns metric history."""
        data = {"history": [{"loss": 0.5, "_step": 0}, {"loss": 0.3, "_step": 1}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["wandb_get_run_metrics"](
                entity="test-entity", project="test-project", run_id="run-123"
            )

        assert result == data

    def test_wandb_get_run_metrics_with_keys(self, tool_fns):
        """wandb_get_run_metrics passes metric_keys param."""
        data = {"history": [{"loss": 0.5}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ) as mock_get,
        ):
            result = tool_fns["wandb_get_run_metrics"](
                entity="test-entity",
                project="test-project",
                run_id="run-123",
                metric_keys="loss,accuracy",
            )

        assert result == data
        params = mock_get.call_args[1]["params"]
        assert params["keys"] == "loss,accuracy"

    def test_wandb_get_run_metrics_missing_id(self, tool_fns):
        """wandb_get_run_metrics with empty run_id returns error."""
        result = tool_fns["wandb_get_run_metrics"](
            entity="test-entity", project="test-project", run_id=""
        )
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_get_artifacts ---

    def test_wandb_get_artifacts_success(self, tool_fns):
        """wandb_get_artifacts returns artifacts for a run."""
        data = {"artifacts": [{"name": "model", "type": "model", "version": "v0"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["wandb_get_artifacts"](
                entity="test-entity", project="test-project", run_id="run-123"
            )

        assert result == data
        assert result["artifacts"][0]["name"] == "model"

    def test_wandb_get_artifacts_missing_id(self, tool_fns):
        """wandb_get_artifacts with empty run_id returns error."""
        result = tool_fns["wandb_get_artifacts"](
            entity="test-entity", project="test-project", run_id=""
        )
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_get_summary ---

    def test_wandb_get_summary_success(self, tool_fns):
        """wandb_get_summary returns final summary metrics."""
        data = {"loss": 0.15, "accuracy": 0.95, "_runtime": 300}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["wandb_get_summary"](
                entity="test-entity", project="test-project", run_id="run-123"
            )

        assert result["accuracy"] == 0.95
        assert result["loss"] == 0.15

    def test_wandb_get_summary_missing_id(self, tool_fns):
        """wandb_get_summary with empty run_id returns error."""
        result = tool_fns["wandb_get_summary"](
            entity="test-entity", project="test-project", run_id=""
        )
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- HTTP error handling ---

    def test_http_401_returns_invalid_key_error(self, tool_fns):
        """HTTP 401 is mapped to a clear 'Invalid API key' message."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp({}, status_code=401),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert result["error"] == "Invalid Weights & Biases API key"

    def test_http_403_returns_permissions_error(self, tool_fns):
        """HTTP 403 is mapped to a permissions error."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp({}, status_code=403),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "Insufficient permissions" in result["error"]

    def test_http_404_returns_not_found_error(self, tool_fns):
        """HTTP 404 is mapped to a not-found error."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp({}, status_code=404),
            ),
        ):
            result = tool_fns["wandb_get_run"](
                entity="test-entity", project="test-project", run_id="nonexistent"
            )
        assert result["error"] == "Weights & Biases resource not found"

    def test_http_429_returns_rate_limit_error(self, tool_fns):
        """HTTP 429 is mapped to a rate-limit message."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp({}, status_code=429),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "rate limit exceeded" in result["error"]

    def test_http_500_returns_api_error(self, tool_fns):
        """HTTP 500 with non-JSON body is handled gracefully."""
        mock_r = _mock_resp({}, status_code=500)
        mock_r.json.side_effect = ValueError("Not JSON")
        mock_r.text = "Internal Server Error"
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=mock_r,
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "API error (HTTP 500)" in result["error"]
        assert "Internal Server Error" in result["error"]

    def test_timeout_returns_error(self, tool_fns):
        """httpx.TimeoutException is caught and returns a timeout message."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                side_effect=httpx.TimeoutException("timeout"),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert result["error"] == "Request timed out"

    def test_network_error_returns_error(self, tool_fns):
        """httpx.RequestError is caught and returns a network error message."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                side_effect=httpx.RequestError("Connection refused"),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "Network error" in result["error"]
        assert "Connection refused" in result["error"]
