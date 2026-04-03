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
    def test_missing_credentials(self, tool_fns):
        """Test that missing credentials returns an error dict."""
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "error" in result
        assert "credentials not configured" in result["error"]

    def test_wandb_list_projects_success(self, tool_fns):
        """Test wandb_list_projects returns projects list."""
        data = {"projects": [{"name": "project1"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert result == data

    def test_wandb_list_runs_success(self, tool_fns):
        """Test wandb_list_runs returns runs list."""
        data = {"runs": [{"name": "run1"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ) as mock_get,
        ):
            result = tool_fns["wandb_list_runs"](
                entity="test-entity", project="test-project", per_page=50
            )
        assert result == data
        assert mock_get.call_args[1]["params"] == {"per_page": 50}

    def test_wandb_list_runs_invalid_per_page(self, tool_fns):
        """Test wandb_list_runs with invalid per_page."""
        result = tool_fns["wandb_list_runs"](
            entity="test-entity", project="test-project", per_page=1001
        )
        assert "error" in result
        assert "per_page must be between 1 and 1000" in result["error"]

    def test_wandb_get_run_success(self, tool_fns):
        """Test wandb_get_run with valid run_id."""
        data = {"id": "run-123", "status": "finished"}
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

    def test_wandb_get_run_missing_id(self, tool_fns):
        """Test wandb_get_run with missing run_id."""
        result = tool_fns["wandb_get_run"](entity="test-entity", project="test-project", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    def test_wandb_get_run_metrics_success(self, tool_fns):
        """Test wandb_get_run_metrics returns history."""
        data = [{"loss": 0.5}, {"loss": 0.4}]
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
        assert len(result) == 2
        assert result[1]["loss"] == 0.4

    def test_wandb_list_artifacts_success(self, tool_fns):
        """Test wandb_list_artifacts returns artifacts."""
        data = {"artifacts": [{"name": "model:v0"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp(data),
            ),
        ):
            result = tool_fns["wandb_list_artifacts"](entity="test-entity", project="test-project")
        assert result["artifacts"][0]["name"] == "model:v0"

    def test_http_401_handled(self, tool_fns):
        """Test HTTP 401 handled gracefully."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp({}, status_code=401),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert result["error"] == "Invalid Weights & Biases API key"

    def test_http_429_handled(self, tool_fns):
        """Test HTTP 429 handled gracefully."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                return_value=_mock_resp({}, status_code=429),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert result["error"] == "Weights & Biases rate limit exceeded. Try again later."

    def test_http_500_handled(self, tool_fns):
        """Test HTTP 500 handled gracefully."""
        mock_r = _mock_resp({}, status_code=500)
        mock_r.json.side_effect = ValueError("Not JSON")
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

    def test_timeout_handled(self, tool_fns):
        """Test that httpx.TimeoutException is handled correctly."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                side_effect=httpx.TimeoutException("Timeout"),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert result["error"] == "Request timed out"

    def test_network_error_handled(self, tool_fns):
        """Test that httpx.RequestError is handled correctly."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.get",
                side_effect=httpx.RequestError("Network error"),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "Network error" in result["error"]
