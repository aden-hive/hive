"""
Tests for the MLflow experiment tracking tool.

Covers:
- Credential retrieval via CredentialStoreAdapter and env var fallback
- HTTP error handling (401, 403, 404, 429, 500)
- Timeout and network error handling
- Empty required parameter validation
- Happy-path response parsing for all 7 tool functions
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from aden_tools.tools.mlflow_tool.mlflow_tool import (
    DEFAULT_TRACKING_URI,
    _get_creds,
    _handle_response,
    _headers,
    register_tools,
)

# ---------------------------------------------------------------------------
# Helper fixtures
# ---------------------------------------------------------------------------

BASE_URI = "http://localhost:5000"


def _mock_resp(status_code: int, json_body: dict | None = None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_body is not None:
        resp.json.return_value = json_body
    else:
        resp.json.side_effect = Exception("no json")
    resp.text = text
    return resp


def _make_mcp_with_tools(credentials=None):
    from fastmcp import FastMCP

    mcp = FastMCP("test-mlflow")
    register_tools(mcp, credentials=credentials)
    return mcp


def _tool(mcp, name: str):
    return mcp._tool_manager._tools[name].fn


# ---------------------------------------------------------------------------
# Unit tests: helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_default_tracking_uri(self):
        assert DEFAULT_TRACKING_URI == "http://localhost:5000"

    def test_get_creds_env_fallback(self, monkeypatch):
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://remote:5000")
        monkeypatch.setenv("MLFLOW_TRACKING_TOKEN", "tok-abc")
        uri, token = _get_creds(None)
        assert uri == "http://remote:5000"
        assert token == "tok-abc"

    def test_get_creds_default_uri_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("MLFLOW_TRACKING_URI", raising=False)
        monkeypatch.delenv("MLFLOW_TRACKING_TOKEN", raising=False)
        uri, token = _get_creds(None)
        assert uri == DEFAULT_TRACKING_URI
        assert token is None

    def test_get_creds_strips_trailing_slash(self, monkeypatch):
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://remote:5000/")
        monkeypatch.delenv("MLFLOW_TRACKING_TOKEN", raising=False)
        uri, _ = _get_creds(None)
        assert not uri.endswith("/")

    def test_get_creds_credential_store(self):
        mock_creds = MagicMock()
        mock_creds.get.side_effect = lambda k: {
            "mlflow_tracking_uri": "http://store-host:5000",
            "mlflow_tracking_token": "store-token",
        }.get(k)
        uri, token = _get_creds(mock_creds)
        assert uri == "http://store-host:5000"
        assert token == "store-token"

    def test_get_creds_store_returns_none_uses_default(self):
        mock_creds = MagicMock()
        mock_creds.get.return_value = None
        uri, token = _get_creds(mock_creds)
        assert uri == DEFAULT_TRACKING_URI
        assert token is None

    def test_headers_no_token(self):
        hdrs = _headers(None)
        assert "Authorization" not in hdrs
        assert hdrs["Content-Type"] == "application/json"

    def test_headers_with_token(self):
        hdrs = _headers("my-token")
        assert hdrs["Authorization"] == "Bearer my-token"

    @pytest.mark.parametrize(
        "status_code,expected_fragment",
        [
            (401, "Invalid or missing"),
            (403, "Insufficient permissions"),
            (404, "not found"),
            (429, "rate limit"),
            (500, "HTTP 500"),
        ],
    )
    def test_handle_response_errors(self, status_code: int, expected_fragment: str):
        resp = _mock_resp(status_code, json_body={"message": "boom"})
        result = _handle_response(resp)
        assert "error" in result
        assert expected_fragment in result["error"]

    def test_handle_response_success(self):
        resp = _mock_resp(200, json_body={"experiments": []})
        result = _handle_response(resp)
        assert result == {"experiments": []}

    def test_handle_response_invalid_json(self):
        resp = _mock_resp(200)  # json.side_effect raises
        result = _handle_response(resp)
        assert "error" in result
        assert "Invalid JSON" in result["error"]


# ---------------------------------------------------------------------------
# Tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_all_seven_tools_registered(self):
        mcp = _make_mcp_with_tools()
        tool_names = list(mcp._tool_manager._tools.keys())
        expected = [
            "mlflow_list_experiments",
            "mlflow_get_experiment",
            "mlflow_list_runs",
            "mlflow_get_run",
            "mlflow_log_metric",
            "mlflow_log_param",
            "mlflow_get_model_version",
        ]
        for name in expected:
            assert name in tool_names, f"Tool '{name}' not registered"


# ---------------------------------------------------------------------------
# Credential path tests
# ---------------------------------------------------------------------------


class TestCredentialPaths:
    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_uses_env_uri_when_no_credential_store(self, mock_post, monkeypatch):
        monkeypatch.setenv("MLFLOW_TRACKING_URI", "http://env-host:5000")
        monkeypatch.delenv("MLFLOW_TRACKING_TOKEN", raising=False)
        mock_post.return_value = _mock_resp(200, {"experiments": []})

        mcp = _make_mcp_with_tools(credentials=None)
        result = _tool(mcp, "mlflow_list_experiments")()

        assert "error" not in result
        call_url = mock_post.call_args[0][0]
        assert "env-host:5000" in call_url

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_uses_credential_store_uri(self, mock_post):
        mock_creds = MagicMock()
        mock_creds.get.side_effect = lambda k: {
            "mlflow_tracking_uri": "http://cred-store-host:5000",
            "mlflow_tracking_token": None,
        }.get(k)
        mock_post.return_value = _mock_resp(200, {"experiments": []})

        mcp = _make_mcp_with_tools(credentials=mock_creds)
        result = _tool(mcp, "mlflow_list_experiments")()

        assert "error" not in result
        call_url = mock_post.call_args[0][0]
        assert "cred-store-host:5000" in call_url

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_bearer_token_sent_in_header(self, mock_post):
        mock_creds = MagicMock()
        mock_creds.get.side_effect = lambda k: {
            "mlflow_tracking_uri": "http://secure-mlflow:5000",
            "mlflow_tracking_token": "secret-bearer",
        }.get(k)
        mock_post.return_value = _mock_resp(200, {"experiments": []})

        mcp = _make_mcp_with_tools(credentials=mock_creds)
        _tool(mcp, "mlflow_list_experiments")()

        sent_headers = mock_post.call_args[1]["headers"]
        assert sent_headers.get("Authorization") == "Bearer secret-bearer"


# ---------------------------------------------------------------------------
# HTTP error parametrize tests (shared across tools)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status_code,expected_fragment",
    [
        (401, "Invalid or missing"),
        (403, "Insufficient permissions"),
        (404, "not found"),
        (429, "rate limit"),
        (500, "HTTP 500"),
    ],
)
class TestHttpErrors:
    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_list_experiments_http_errors(self, mock_post, status_code, expected_fragment):
        mock_post.return_value = _mock_resp(status_code, json_body={"message": "err"})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_experiments")()
        assert "error" in result
        assert expected_fragment in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_get_experiment_http_errors(self, mock_get, status_code, expected_fragment):
        mock_get.return_value = _mock_resp(status_code, json_body={"message": "err"})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_experiment")(experiment_id="0")
        assert "error" in result
        assert expected_fragment in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_list_runs_http_errors(self, mock_post, status_code, expected_fragment):
        mock_post.return_value = _mock_resp(status_code, json_body={"message": "err"})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_runs")(experiment_ids="0")
        assert "error" in result
        assert expected_fragment in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_get_run_http_errors(self, mock_get, status_code, expected_fragment):
        mock_get.return_value = _mock_resp(status_code, json_body={"message": "err"})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_run")(run_id="abc123")
        assert "error" in result
        assert expected_fragment in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_get_model_version_http_errors(self, mock_get, status_code, expected_fragment):
        mock_get.return_value = _mock_resp(status_code, json_body={"message": "err"})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_model_version")(name="my-model", version="1")
        assert "error" in result
        assert expected_fragment in result["error"]


# ---------------------------------------------------------------------------
# Timeout and network error tests
# ---------------------------------------------------------------------------


class TestNetworkErrors:
    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_timeout_list_experiments(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_experiments")()
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_request_error_get_run(self, mock_get):
        mock_get.side_effect = httpx.RequestError("connection refused")
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_run")(run_id="abc")
        assert "error" in result
        assert "Network error" in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_timeout_list_runs(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timed out")
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_runs")(experiment_ids="0")
        assert "error" in result
        assert "timed out" in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_request_error_log_metric(self, mock_post):
        mock_post.side_effect = httpx.RequestError("connection refused")
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_metric")(run_id="r1", key="loss", value=0.5)
        assert "error" in result
        assert "Network error" in result["error"]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_request_error_log_param(self, mock_post):
        mock_post.side_effect = httpx.RequestError("connection refused")
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_param")(run_id="r1", key="lr", value="0.01")
        assert "error" in result
        assert "Network error" in result["error"]


# ---------------------------------------------------------------------------
# Empty required parameter validation
# ---------------------------------------------------------------------------


class TestParameterValidation:
    def test_get_experiment_empty_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_experiment")(experiment_id="")
        assert "error" in result
        assert "experiment_id" in result["error"]

    def test_list_runs_empty_experiment_ids(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_runs")(experiment_ids="")
        assert "error" in result
        assert "experiment_ids" in result["error"]

    def test_list_runs_whitespace_only_ids(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_runs")(experiment_ids="  ,  ")
        assert "error" in result

    def test_get_run_empty_run_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_run")(run_id="")
        assert "error" in result
        assert "run_id" in result["error"]

    def test_log_metric_empty_run_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_metric")(run_id="", key="loss", value=0.5)
        assert "error" in result
        assert "run_id" in result["error"]

    def test_log_metric_empty_key(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_metric")(run_id="r1", key="", value=0.5)
        assert "error" in result
        assert "key" in result["error"]

    def test_log_param_empty_run_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_param")(run_id="", key="lr", value="0.01")
        assert "error" in result
        assert "run_id" in result["error"]

    def test_log_param_empty_key(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_param")(run_id="r1", key="", value="0.01")
        assert "error" in result
        assert "key" in result["error"]

    def test_get_model_version_empty_name(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_model_version")(name="", version="1")
        assert "error" in result
        assert "name" in result["error"]

    def test_get_model_version_empty_version(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_model_version")(name="my-model", version="")
        assert "error" in result
        assert "version" in result["error"]

    def test_get_experiment_whitespace_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_experiment")(experiment_id="   ")
        assert "error" in result
        assert "experiment_id" in result["error"]

    def test_get_run_whitespace_run_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_run")(run_id="  \t  ")
        assert "error" in result
        assert "run_id" in result["error"]

    def test_log_metric_whitespace_run_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_metric")(run_id="   ", key="loss", value=0.5)
        assert "error" in result
        assert "run_id" in result["error"]

    def test_log_metric_whitespace_key(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_metric")(run_id="r1", key="   ", value=0.5)
        assert "error" in result
        assert "key" in result["error"]

    def test_log_param_whitespace_run_id(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_param")(run_id="   ", key="lr", value="0.01")
        assert "error" in result
        assert "run_id" in result["error"]

    def test_log_param_whitespace_key(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_param")(run_id="r1", key="   ", value="0.01")
        assert "error" in result
        assert "key" in result["error"]

    def test_get_model_version_whitespace_name(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_model_version")(name="   ", version="1")
        assert "error" in result
        assert "name" in result["error"]

    def test_get_model_version_whitespace_version(self):
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_model_version")(name="my-model", version="   ")
        assert "error" in result
        assert "version" in result["error"]


# ---------------------------------------------------------------------------
# Happy-path tests — one per tool
# ---------------------------------------------------------------------------


class TestHappyPaths:
    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_list_experiments_happy(self, mock_post):
        mock_post.return_value = _mock_resp(
            200,
            {
                "experiments": [
                    {
                        "experiment_id": "1",
                        "name": "fraud-detection",
                        "artifact_location": "mlflow-artifacts:/1",
                        "lifecycle_stage": "active",
                        "last_update_time": 1700000000,
                        "creation_time": 1699000000,
                    }
                ]
            },
        )
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_experiments")()
        assert "error" not in result
        assert result["count"] == 1
        assert result["experiments"][0]["name"] == "fraud-detection"
        sent_body = mock_post.call_args[1]["json"]
        assert sent_body["view_type"] == "ACTIVE_ONLY"
        assert "experiments/search" in mock_post.call_args[0][0]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_get_experiment_happy(self, mock_get):
        mock_get.return_value = _mock_resp(
            200,
            {
                "experiment": {
                    "experiment_id": "42",
                    "name": "churn-model",
                    "artifact_location": "mlflow-artifacts:/42",
                    "lifecycle_stage": "active",
                    "tags": [{"key": "team", "value": "ml-platform"}],
                }
            },
        )
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_experiment")(experiment_id="42")
        assert "error" not in result
        assert result["name"] == "churn-model"
        assert result["tags"] == [{"key": "team", "value": "ml-platform"}]

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_list_runs_happy(self, mock_post):
        mock_post.return_value = _mock_resp(
            200,
            {
                "runs": [
                    {
                        "info": {
                            "run_id": "run-abc",
                            "run_name": "eager-hawk-42",
                            "experiment_id": "1",
                            "status": "FINISHED",
                            "start_time": 1700000000,
                            "end_time": 1700003600,
                            "artifact_uri": "mlflow-artifacts:/1/run-abc",
                        },
                        "data": {
                            "metrics": [{"key": "accuracy", "value": 0.93}],
                            "params": [{"key": "lr", "value": "0.001"}],
                            "tags": [],
                        },
                    }
                ],
                "next_page_token": "",
            },
        )
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_runs")(experiment_ids="1")
        assert "error" not in result
        assert result["count"] == 1
        run = result["runs"][0]
        assert run["run_id"] == "run-abc"
        assert run["metrics"]["accuracy"] == 0.93
        assert run["params"]["lr"] == "0.001"

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_list_runs_with_filter_and_order(self, mock_post):
        mock_post.return_value = _mock_resp(200, {"runs": [], "next_page_token": ""})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_list_runs")(
            experiment_ids="1,2",
            filter_string="metrics.accuracy > 0.9",
            order_by="metrics.accuracy DESC",
        )
        assert "error" not in result
        sent_body = mock_post.call_args[1]["json"]
        assert sent_body["filter"] == "metrics.accuracy > 0.9"
        assert "metrics.accuracy DESC" in sent_body["order_by"]
        assert set(sent_body["experiment_ids"]) == {"1", "2"}

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_get_run_happy(self, mock_get):
        mock_get.return_value = _mock_resp(
            200,
            {
                "run": {
                    "info": {
                        "run_id": "run-xyz",
                        "run_name": "bold-eagle-7",
                        "experiment_id": "3",
                        "status": "FINISHED",
                        "start_time": 1700000000,
                        "end_time": 1700001800,
                        "artifact_uri": "mlflow-artifacts:/3/run-xyz",
                        "lifecycle_stage": "active",
                    },
                    "data": {
                        "metrics": [
                            {"key": "loss", "value": 0.12},
                            {"key": "accuracy", "value": 0.97},
                        ],
                        "params": [{"key": "epochs", "value": "50"}],
                        "tags": [{"key": "mlflow.user", "value": "alice"}],
                    },
                }
            },
        )
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_run")(run_id="run-xyz")
        assert "error" not in result
        assert result["run_id"] == "run-xyz"
        assert result["metrics"]["accuracy"] == 0.97
        assert result["params"]["epochs"] == "50"

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_log_metric_happy(self, mock_post):
        mock_post.return_value = _mock_resp(200, {})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_metric")(run_id="run-abc", key="val_loss", value=0.25, step=10)
        assert "error" not in result
        assert result["success"] is True
        assert result["key"] == "val_loss"
        assert result["step"] == 10

        sent_body = mock_post.call_args[1]["json"]
        assert sent_body["run_id"] == "run-abc"
        assert sent_body["key"] == "val_loss"
        assert sent_body["value"] == 0.25
        assert sent_body["step"] == 10
        assert "timestamp" in sent_body

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post")
    def test_log_param_happy(self, mock_post):
        mock_post.return_value = _mock_resp(200, {})
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_log_param")(run_id="run-abc", key="lr", value="0.001")
        assert "error" not in result
        assert result["success"] is True
        assert result["key"] == "lr"
        assert result["value"] == "0.001"

    @patch("aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get")
    def test_get_model_version_happy(self, mock_get):
        mock_get.return_value = _mock_resp(
            200,
            {
                "model_version": {
                    "name": "fraud-classifier",
                    "version": "3",
                    "creation_timestamp": 1700000000,
                    "last_updated_timestamp": 1700001000,
                    "current_stage": "Production",
                    "description": "Best model to date",
                    "source": "mlflow-artifacts:/1/run-abc/artifacts/model",
                    "run_id": "run-abc",
                    "status": "READY",
                    "tags": [{"key": "validated", "value": "true"}],
                }
            },
        )
        mcp = _make_mcp_with_tools()
        result = _tool(mcp, "mlflow_get_model_version")(name="fraud-classifier", version="3")
        assert "error" not in result
        assert result["name"] == "fraud-classifier"
        assert result["current_stage"] == "Production"
        assert result["tags"]["validated"] == "true"
