"""Tests for wandb_tool - Weights & Biases integration (SDK-based)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.wandb_tool.wandb_tool import register_tools

ENV = {
    "WANDB_API_KEY": "test-key",
}


def _mock_project(name: str = "my-project") -> MagicMock:
    p = MagicMock()
    p.name = name
    p.id = f"id-{name}"
    p.description = ""
    p.url = f"https://wandb.ai/entity/{name}"
    return p


def _mock_run(
    run_id: str = "abc123",
    name: str = "test-run",
    state: str = "finished",
) -> MagicMock:
    r = MagicMock()
    r.id = run_id
    r.name = name
    r.state = state
    r.url = f"https://wandb.ai/entity/project/runs/{run_id}"
    r.created_at = "2024-01-01T00:00:00"
    r.config = {"lr": 0.001}
    r.tags = ["v1"]
    r.notes = "test notes"
    # summary mock with items()
    summary_mock = MagicMock()
    summary_mock.items.return_value = [("accuracy", 0.9), ("loss", 0.1), ("_step", 5)]
    r.summary = summary_mock
    return r


def _mock_history(*rows: dict[str, Any]) -> MagicMock:
    """Return a mock DataFrame-like object for run.history()."""
    df = MagicMock()
    df.to_dict.return_value = list(rows)
    return df


def _mock_artifact(name: str = "model:v0", atype: str = "model") -> MagicMock:
    a = MagicMock()
    a.name = name
    a.type = atype
    a.version = "v0"
    a.size = 1024
    return a


@pytest.fixture
def tool_fns(mcp: FastMCP) -> dict[str, Any]:
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestWandbTool:
    # --- Credential tests ---

    def test_missing_credentials_returns_error(self, tool_fns: dict[str, Any]) -> None:
        """Missing WANDB_API_KEY must return a descriptive error dict."""
        with patch.dict("os.environ", {}, clear=True):
            result = tool_fns["wandb_list_projects"](entity="test-entity")
        assert "error" in result
        assert "credentials not configured" in result["error"]
        assert "help" in result

    # --- wandb_list_projects ---

    def test_wandb_list_projects_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_projects returns projects list from the SDK."""
        mock_api = MagicMock()
        mock_api.projects.return_value = [_mock_project("proj-a"), _mock_project("proj-b")]

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")

        assert result["entity"] == "test-entity"
        assert len(result["projects"]) == 2
        assert result["projects"][0]["name"] == "proj-a"
        mock_api.projects.assert_called_once_with(entity="test-entity")

    def test_wandb_list_projects_sdk_error(self, tool_fns: dict[str, Any]) -> None:
        """SDK exceptions are caught and returned as error dicts."""
        mock_api = MagicMock()
        mock_api.projects.side_effect = Exception("network failure")

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_list_projects"](entity="test-entity")

        assert "error" in result
        assert "network failure" in result["error"]

    # --- wandb_list_runs ---

    def test_wandb_list_runs_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_runs returns runs list."""
        mock_api = MagicMock()
        mock_api.runs.return_value = [_mock_run("r1", "run-one"), _mock_run("r2", "run-two")]

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_list_runs"](
                entity="test-entity", project="test-project", per_page=25
            )

        assert result["project"] == "test-project"
        assert len(result["runs"]) == 2
        assert result["runs"][0]["id"] == "r1"
        mock_api.runs.assert_called_once_with(path="test-entity/test-project", per_page=25)

    def test_wandb_list_runs_with_valid_filters(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_runs passes parsed filters dict to SDK."""
        mock_api = MagicMock()
        mock_api.runs.return_value = []

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_list_runs"](
                entity="e", project="p", filters='{"state": "finished"}'
            )

        mock_api.runs.assert_called_once_with(
            path="e/p", per_page=50, filters={"state": "finished"}
        )
        assert "runs" in result

    def test_wandb_list_runs_invalid_filters_json(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_runs returns error for invalid JSON filters."""
        with patch.dict("os.environ", ENV):
            result = tool_fns["wandb_list_runs"](entity="e", project="p", filters="not-json")
        assert "error" in result
        assert "valid JSON" in result["error"]

    # --- wandb_get_run ---

    def test_wandb_get_run_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run returns full run details."""
        mock_api = MagicMock()
        mock_api.run.return_value = _mock_run("run-123", "my-run")

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_get_run"](entity="e", project="p", run_id="run-123")

        assert result["id"] == "run-123"
        assert result["name"] == "my-run"
        assert result["config"] == {"lr": 0.001}
        mock_api.run.assert_called_once_with("e/p/run-123")

    def test_wandb_get_run_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run with empty run_id returns error before any API call."""
        result = tool_fns["wandb_get_run"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_get_run_metrics ---

    def test_wandb_get_run_metrics_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run_metrics returns history steps."""
        mock_api = MagicMock()
        run = _mock_run()
        run.history.return_value = _mock_history(
            {"loss": 0.5, "_step": 0}, {"loss": 0.3, "_step": 1}
        )
        mock_api.run.return_value = run

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_get_run_metrics"](entity="e", project="p", run_id="abc123")

        assert result["run_id"] == "abc123"
        assert len(result["steps"]) == 2
        assert result["steps"][0]["loss"] == 0.5

    def test_wandb_get_run_metrics_with_keys(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run_metrics passes parsed keys list to history()."""
        mock_api = MagicMock()
        run = _mock_run()
        run.history.return_value = _mock_history({"loss": 0.5})
        mock_api.run.return_value = run

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            tool_fns["wandb_get_run_metrics"](
                entity="e", project="p", run_id="abc123", metric_keys="loss,accuracy"
            )

        run.history.assert_called_once_with(samples=500, keys=["loss", "accuracy"])

    def test_wandb_get_run_metrics_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_run_metrics with empty run_id returns error."""
        result = tool_fns["wandb_get_run_metrics"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_list_artifacts ---

    def test_wandb_list_artifacts_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_artifacts returns artifact list."""
        mock_api = MagicMock()
        run = _mock_run()
        run.logged_artifacts.return_value = [
            _mock_artifact("model:v0", "model"),
            _mock_artifact("dataset:v1", "dataset"),
        ]
        mock_api.run.return_value = run

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_list_artifacts"](entity="e", project="p", run_id="abc123")

        assert result["run_id"] == "abc123"
        assert len(result["artifacts"]) == 2
        assert result["artifacts"][0]["name"] == "model:v0"
        assert result["artifacts"][0]["type"] == "model"

    def test_wandb_list_artifacts_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_list_artifacts with empty run_id returns error."""
        result = tool_fns["wandb_list_artifacts"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"

    # --- wandb_get_summary ---

    def test_wandb_get_summary_success(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_summary returns non-internal summary keys."""
        mock_api = MagicMock()
        mock_api.run.return_value = _mock_run()

        with (
            patch.dict("os.environ", ENV),
            patch("aden_tools.tools.wandb_tool.wandb_tool._make_api", return_value=mock_api),
        ):
            result = tool_fns["wandb_get_summary"](entity="e", project="p", run_id="abc123")

        assert result["run_id"] == "abc123"
        # Internal keys (_step) should be filtered out
        assert "_step" not in result["summary"]
        assert result["summary"]["accuracy"] == 0.9
        assert result["summary"]["loss"] == 0.1

    def test_wandb_get_summary_missing_id(self, tool_fns: dict[str, Any]) -> None:
        """wandb_get_summary with empty run_id returns error."""
        result = tool_fns["wandb_get_summary"](entity="e", project="p", run_id="")
        assert "error" in result
        assert result["error"] == "run_id is required"
