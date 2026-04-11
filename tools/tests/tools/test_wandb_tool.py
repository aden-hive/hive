"""Tests for wandb_tool - Weights & Biases integration (GraphQL/httpx)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastmcp import FastMCP

from aden_tools.tools.wandb_tool.wandb_tool import register_tools

ENV = {"WANDB_API_KEY": "test-key-abcdefghij"}
_PATCH_POST = "aden_tools.tools.wandb_tool.wandb_tool.httpx.post"


def _mock_resp(data: Any, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = str(data)
    return resp


def _gql_ok(data: dict[str, Any]) -> MagicMock:
    """Wrap data in the GraphQL envelope: {"data": {...}}."""
    return _mock_resp({"data": data})


@pytest.fixture
def tool_fns(mcp: FastMCP) -> dict[str, Any]:
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestWandbTool:
    # --- Credential tests ---

    def test_missing_credentials_returns_error(self, tool_fns: dict[str, Any]) -> None:
        """Missing WANDB_API_KEY must return a descriptive error dict with help."""
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "error" in result
        assert "credentials not configured" in result["error"]
        assert "help" in result

    # --- wandb_list_projects ---

    def test_wandb_list_projects_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_projects returns projects list from GraphQL."""
        gql_data = {
            "projects": {
                "edges": [
                    {
                        "node": {
                            "name": "proj-a",
                            "description": "Desc A",
                            "createdAt": "2024-01-01",
                        }
                    },
                    {
                        "node": {
                            "name": "proj-b",
                            "description": "",
                            "createdAt": "2024-02-01",
                        }
                    },
                ]
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")

        assert result["entity"] == "test-entity"
        assert len(result["projects"]) == 2
        assert result["projects"][0]["name"] == "proj-a"

    def test_wandb_list_projects_http_401(self, tool_fns: dict[str, Any]) -> None:
        """HTTP 401 returns an invalid key error."""
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_mock_resp({}, status_code=401)),
        ):
            result = tool_fns["wandb_list_projects"](entity="e")
        assert result["error"] == "Invalid Weights & Biases API key"

    def test_wandb_list_projects_graphql_error(self, tool_fns: dict[str, Any]) -> None:
        """GraphQL error block is surfaced as an error dict."""
        gql_err = {"errors": [{"message": "entity not found"}]}
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_mock_resp(gql_err)),
        ):
            result = tool_fns["wandb_list_projects"](entity="e")
        assert "error" in result
        assert "entity not found" in result["error"]

    # --- wandb_list_runs ---

    def test_wandb_list_runs_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_runs returns runs list."""
        gql_data = {
            "project": {
                "runs": {
                    "edges": [
                        {
                            "node": {
                                "name": "w854ckuu",
                                "id": "ferengi-directive-1",
                                "state": "finished",
                                "createdAt": "2024-01-01",
                                "config": "{}",
                                "summaryMetrics": "{}",
                            }
                        }
                    ]
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)) as mock_post,
        ):
            result = tool_fns["wandb_list_runs"](
                entity="testentity",
                project="testproject",
                filters='{"key": "value"}',
                per_page=50,
            )

        assert result["project"] == "testproject"
        assert len(result["runs"]) == 1
        assert result["runs"][0]["id"] == "w854ckuu"
        # Verify filters and per_page were forwarded in GraphQL variables
        call_json = mock_post.call_args[1]["json"]
        assert call_json["variables"]["perPage"] == 50
        assert call_json["variables"]["filters"] == {"key": "value"}

    def test_wandb_list_runs_invalid_filters_json(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_runs returns error for invalid JSON filters before any HTTP call."""
        with patch.dict("os.environ", ENV):
            result = tool_fns["wandb_list_runs"](entity="e", project="p", filters="not-json")
        assert "error" in result
        assert "valid JSON" in result["error"]

    # --- wandb_get_run ---

    def test_wandb_get_run_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run returns run details."""
        gql_data = {
            "project": {
                "run": {
                    "name": "run-123",
                    "id": "my-run",
                    "state": "finished",
                    "createdAt": "2024-01-01",
                    "config": '{"lr": 0.001}',
                    "summaryMetrics": '{"accuracy": 0.9}',
                    "tags": ["v1"],
                    "notes": "test",
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)),
        ):
            result = tool_fns["wandb_get_run"](entity="e", project="p", run_id="run-123")

        assert result["id"] == "run-123"
        assert result["config"] == {"lr": 0.001}
        assert result["summary"] == {"accuracy": 0.9}

    def test_wandb_get_run_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run with empty run_id returns error before HTTP call."""
        result = tool_fns["wandb_get_run"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    def test_wandb_get_run_not_found(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run returns not-found error when run is null."""
        gql_data = {"project": {"run": None}}
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)),
        ):
            result = tool_fns["wandb_get_run"](entity="e", project="p", run_id="nope")
        assert "error" in result
        assert "not found" in result["error"]

    # --- wandb_get_run_metrics ---

    def test_wandb_get_run_metrics_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run_metrics returns sampled history."""
        gql_data = {
            "project": {
                "run": {
                    "sampledHistory": [{"loss": 0.5}, {"loss": 0.3}],
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)),
        ):
            result = tool_fns["wandb_get_run_metrics"](
                entity="e", project="p", run_id="r1", metric_keys="loss"
            )

        assert result["run_id"] == "r1"
        assert result["metric_keys"] == ["loss"]
        assert result["history"] == [{"loss": 0.5}, {"loss": 0.3}]

    def test_wandb_get_run_metrics_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run_metrics with empty run_id returns error."""
        with patch.dict("os.environ", ENV):
            result = tool_fns["wandb_get_run_metrics"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    def test_wandb_get_run_metrics_missing_keys(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run_metrics with no metric_keys returns error."""
        with patch.dict("os.environ", ENV):
            result = tool_fns["wandb_get_run_metrics"](entity="e", project="p", run_id="r1")
        assert "error" in result
        assert "metric_keys is required" in result["error"]

    # --- wandb_list_artifacts ---

    def test_wandb_list_artifacts_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_artifacts returns artifact list."""
        gql_data = {
            "project": {
                "run": {
                    "outputArtifacts": {
                        "edges": [
                            {
                                "node": {
                                    "name": "model:v0",
                                    "type": "model",
                                    "description": "",
                                    "createdAt": "2024-01-01",
                                }
                            }
                        ]
                    }
                }
            }
        }
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)),
        ):
            result = tool_fns["wandb_list_artifacts"](entity="e", project="p", run_id="r1")

        assert result["run_id"] == "r1"
        assert result["artifacts"][0]["name"] == "model:v0"

    def test_wandb_list_artifacts_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_artifacts with empty run_id returns error."""
        result = tool_fns["wandb_list_artifacts"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_get_summary ---

    def test_wandb_get_summary_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_summary returns summary filtering out _-prefixed keys."""
        gql_data = {
            "project": {"run": {"summaryMetrics": '{"accuracy": 0.9, "loss": 0.1, "_step": 5}'}}
        }
        with (
            patch.dict("os.environ", ENV),
            patch(_PATCH_POST, return_value=_gql_ok(gql_data)),
        ):
            result = tool_fns["wandb_get_summary"](entity="e", project="p", run_id="r1")

        assert result["run_id"] == "r1"
        assert result["summary"]["accuracy"] == 0.9
        assert "_step" not in result["summary"]

    def test_wandb_get_summary_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_summary with empty run_id returns error."""
        result = tool_fns["wandb_get_summary"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- Network/timeout errors ---

    def test_timeout_returns_error(self, tool_fns: dict[str, Any]) -> None:
        """httpx.TimeoutException is caught and returns a timeout message."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.post",
                side_effect=httpx.TimeoutException("timeout"),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="e")
        assert result["error"] == "Request timed out"

    def test_network_error_returns_error(self, tool_fns: dict[str, Any]) -> None:
        """httpx.RequestError is caught and returns a network error message."""
        with (
            patch.dict("os.environ", ENV),
            patch(
                "aden_tools.tools.wandb_tool.wandb_tool.httpx.post",
                side_effect=httpx.RequestError("Connection refused"),
            ),
        ):
            result = tool_fns["wandb_list_projects"](entity="e")
        assert "Network error" in result["error"]
