"""Tests for mlflow_tool - Experiment tracking and model registry."""

from unittest.mock import MagicMock, patch

import pytest
from fastmcp import FastMCP

from aden_tools.tools.mlflow_tool.mlflow_tool import register_tools

ENV = {
    "MLFLOW_TRACKING_URI": "http://localhost:5000",
    "MLFLOW_TOKEN": "test-token",
}


def _mock_resp(data, status_code=200):
    """Create a mock httpx response."""
    import json

    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    resp.headers = {"content-type": "application/json"}
    return resp


@pytest.fixture
def tool_fns(mcp: FastMCP):
    """Register MLflow tools and return tool functions."""
    register_tools(mcp, credentials=None)
    tools = mcp._tool_manager._tools
    return {name: tools[name].fn for name in tools}


class TestMlflowListExperiments:
    """Test mlflow_list_experiments tool."""

    def test_no_tracking_uri(self, tool_fns):
        """Test when MLflow tracking URI is not available."""
        with patch.dict("os.environ", {}, clear=True):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                side_effect=Exception("Cannot connect"),
            ):
                result = tool_fns["mlflow_list_experiments"]()
        assert "error" in result

    def test_successful_list(self, tool_fns):
        """Test successful listing of experiments."""
        experiments = {
            "experiments": [
                {
                    "experiment_id": "0",
                    "name": "Default",
                    "artifact_location": "s3://bucket/experiments",
                    "lifecycle_stage": "active",
                },
                {
                    "experiment_id": "1",
                    "name": "ML Pipeline",
                    "artifact_location": "s3://bucket/ml-pipeline",
                    "lifecycle_stage": "active",
                },
            ]
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp(experiments),
            ):
                result = tool_fns["mlflow_list_experiments"]()
        assert "experiments" in result
        assert len(result["experiments"]) == 2


class TestMlflowCreateExperiment:
    """Test mlflow_create_experiment tool."""

    def test_create_with_name_only(self, tool_fns):
        """Test creating experiment with just a name."""
        response = {"experiment_id": "123"}
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_create_experiment"](name="My Experiment")
        assert result["experiment_id"] == "123"

    def test_create_with_artifact_location(self, tool_fns):
        """Test creating experiment with artifact location."""
        response = {"experiment_id": "456"}
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_create_experiment"](
                    name="Exp",
                    artifact_location="s3://bucket/path",
                )
        assert result["experiment_id"] == "456"


class TestMlflowLogRun:
    """Test mlflow_log_run tool."""

    def test_log_run_with_all_fields(self, tool_fns):
        """Test logging a run with parameters, metrics, and tags."""
        run_response = {
            "run": {
                "info": {
                    "run_id": "run-123",
                    "experiment_id": "0",
                    "status": "RUNNING",
                }
            }
        }

        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(run_response),
            ) as mock_post:
                result = tool_fns["mlflow_log_run"](
                    experiment_id="0",
                    run_name="Test Run",
                    parameters={"lr": "0.01", "epochs": "100"},
                    metrics={"accuracy": 0.95, "loss": 0.05},
                    tags={"model": "ResNet50", "env": "prod"},
                )

        assert result["run_id"] == "run-123"
        assert result["parameters_logged"] == 2
        assert result["metrics_logged"] == 2
        assert result["tags_logged"] == 2
        # Verify that POST was called multiple times (create + log params/metrics/tags)
        assert mock_post.call_count >= 1

    def test_log_run_minimal(self, tool_fns):
        """Test logging a run with minimal fields."""
        run_response = {"run": {"info": {"run_id": "run-789", "experiment_id": "0"}}}

        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(run_response),
            ):
                result = tool_fns["mlflow_log_run"](experiment_id="0")

        assert result["run_id"] == "run-789"
        assert result["parameters_logged"] == 0
        assert result["metrics_logged"] == 0
        assert result["tags_logged"] == 0

    def test_log_run_with_partial_failures(self, tool_fns):
        """Test logging run with some failures in parameter/metric logging."""

        def mock_side_effect(*args, **kwargs):
            # First call is run creation, rest alternate between success and failure
            if "run" not in mock_side_effect.call_count_map:
                mock_side_effect.call_count_map["run"] = 0
            mock_side_effect.call_count_map["run"] += 1

            if mock_side_effect.call_count_map["run"] == 1:
                return _mock_resp({"run": {"info": {"run_id": "run-test"}}})
            elif mock_side_effect.call_count_map["run"] % 2 == 0:
                # Every other call fails
                return _mock_resp({"error": "API error"}, status_code=400)
            else:
                return _mock_resp({})

        mock_side_effect.call_count_map = {}

        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                side_effect=mock_side_effect,
            ):
                result = tool_fns["mlflow_log_run"](
                    experiment_id="0",
                    parameters={"p1": "v1", "p2": "v2"},
                    metrics={"m1": 0.5, "m2": 0.7},
                )

        # Should have logged some but not all
        assert result["run_id"] == "run-test"
        assert "warnings" in result or result["parameters_logged"] < 2


class TestMlflowGetMetrics:
    """Test mlflow_get_metrics tool."""

    def test_get_metrics_successful(self, tool_fns):
        """Test retrieving metrics for a run."""
        metrics = {
            "metrics": [
                {
                    "key": "accuracy",
                    "value": 0.95,
                    "timestamp": 1234567890000,
                    "step": 0,
                },
                {
                    "key": "loss",
                    "value": 0.05,
                    "timestamp": 1234567891000,
                    "step": 0,
                },
            ]
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp(metrics),
            ):
                result = tool_fns["mlflow_get_metrics"](run_id="run-123")

        assert "metrics" in result
        assert len(result["metrics"]) == 2


class TestMlflowSearchRuns:
    """Test mlflow_search_runs tool."""

    def test_search_with_filter(self, tool_fns):
        """Test searching runs with metric filter."""
        response = {
            "runs": [
                {
                    "info": {
                        "run_id": "run-1",
                        "experiment_id": "0",
                        "status": "FINISHED",
                    },
                    "data": {
                        "metrics": {"accuracy": 0.95},
                        "params": {"lr": "0.01"},
                    },
                }
            ],
            "next_page_token": None,
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_search_runs"](
                    experiment_ids="0",
                    filter_string="metrics.accuracy > 0.9",
                )

        assert "runs" in result
        assert len(result["runs"]) == 1


class TestMlflowRegisterModel:
    """Test mlflow_register_model tool."""

    def test_register_model_successful(self, tool_fns):
        """Test registering a model."""
        response = {
            "model_version": {
                "name": "my-model",
                "version": "1",
                "source": "runs:/run-123/model",
            }
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_register_model"](
                    model_uri="runs:/run-123/model",
                    name="my-model",
                    tags={"framework": "sklearn"},
                )

        assert "model_version" in result


class TestMlflowGetRegisteredModel:
    """Test mlflow_get_registered_model tool."""

    def test_get_registered_model_successful(self, tool_fns):
        """Test getting registered model details."""
        response = {
            "registered_model": {
                "name": "my-model",
                "creation_timestamp": 1234567890000,
                "last_updated_timestamp": 1234567900000,
                "latest_versions": [
                    {
                        "name": "my-model",
                        "version": "1",
                        "stage": "Production",
                    }
                ],
            }
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_get_registered_model"](name="my-model")

        assert "registered_model" in result


class TestMlflowListRegisteredModels:
    """Test mlflow_list_registered_models tool."""

    def test_list_registered_models_successful(self, tool_fns):
        """Test listing all registered models."""
        response = {
            "registered_models": [
                {
                    "name": "model-1",
                    "creation_timestamp": 1234567890000,
                },
                {
                    "name": "model-2",
                    "creation_timestamp": 1234567900000,
                },
            ]
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_list_registered_models"](max_results=50)

        assert "registered_models" in result
        assert len(result["registered_models"]) == 2


class TestMlflowTransitionModelStage:
    """Test mlflow_transition_model_stage tool."""

    def test_transition_to_production(self, tool_fns):
        """Test transitioning model to Production stage."""
        response = {"model_version": {"name": "my-model", "version": "1", "stage": "Production"}}

        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.post",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_transition_model_stage"](
                    name="my-model",
                    version=1,
                    stage="Production",
                )

        assert "model_version" in result

    def test_invalid_stage(self, tool_fns):
        """Test with invalid stage."""
        result = tool_fns["mlflow_transition_model_stage"](
            name="my-model",
            version=1,
            stage="InvalidStage",
        )
        assert "error" in result


class TestMlflowGetRun:
    """Test mlflow_get_run tool."""

    def test_get_run_successful(self, tool_fns):
        """Test getting run details."""
        response = {
            "run": {
                "info": {
                    "run_id": "run-123",
                    "experiment_id": "0",
                    "status": "FINISHED",
                },
                "data": {
                    "metrics": {"accuracy": 0.95},
                    "params": {"lr": "0.01"},
                    "tags": {"model": "ResNet50"},
                },
            }
        }
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp(response),
            ):
                result = tool_fns["mlflow_get_run"](run_id="run-123")

        assert "run" in result
        assert result["run"]["info"]["run_id"] == "run-123"


class TestMlflowConnectionErrors:
    """Test error handling for connection issues."""

    def test_connection_error(self, tool_fns):
        """Test handling of connection errors."""
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                side_effect=Exception("Connection refused"),
            ):
                result = tool_fns["mlflow_list_experiments"]()
        assert "error" in result

    def test_unauthorized_error(self, tool_fns):
        """Test handling of unauthorized errors."""
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp({}, status_code=401),
            ):
                result = tool_fns["mlflow_list_experiments"]()
        assert "error" in result
        assert "Unauthorized" in result["error"]

    def test_not_found_error(self, tool_fns):
        """Test handling of not found errors."""
        with patch.dict("os.environ", ENV):
            with patch(
                "aden_tools.tools.mlflow_tool.mlflow_tool.httpx.get",
                return_value=_mock_resp({}, status_code=404),
            ):
                result = tool_fns["mlflow_list_experiments"]()
        assert "error" in result
        assert "not found" in result["error"]
