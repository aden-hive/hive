"""
MLflow Experiment Tracking and Model Registry Tool.

Supports:
- MLflow Tracking Server (local or remote)
- Experiment management (list, create, get)
- Run logging and tracking (log metrics, params, artifacts)
- Model registry (register, get, transition stage)
- Metrics and artifacts retrieval

API Reference: https://mlflow.org/docs/latest/rest-api.html
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def _get_tracking_uri(credentials: CredentialStoreAdapter | None) -> str:
    """Get MLflow tracking URI from credentials or environment."""
    if credentials is not None:
        try:
            uri = credentials.get("mlflow_tracking_uri")
            if uri:
                return uri
        except (KeyError, AttributeError):
            pass
    return os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")


def _get_token(credentials: CredentialStoreAdapter | None) -> str | None:
    """Get MLflow token from credentials or environment."""
    if credentials is not None:
        try:
            return credentials.get("mlflow_token")
        except (KeyError, AttributeError):
            pass
    return os.getenv("MLFLOW_TOKEN")


def _make_request(
    method: str,
    uri: str,
    endpoint: str,
    token: str | None = None,
    json_data: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Make HTTP request to MLflow API."""
    url = f"{uri.rstrip('/')}/api/2.0{endpoint}"
    headers: dict[str, str] = {}

    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        if method.upper() == "GET":
            resp = httpx.get(url, headers=headers, params=params, timeout=30.0)
        elif method.upper() == "POST":
            resp = httpx.post(url, headers=headers, json=json_data, params=params, timeout=30.0)
        elif method.upper() == "PATCH":
            resp = httpx.patch(url, headers=headers, json=json_data, timeout=30.0)
        else:
            return {"error": f"Unsupported HTTP method: {method}"}

        if resp.status_code == 401:
            return {"error": "Unauthorized. Check MLFLOW_TOKEN or MLflow server access."}
        if resp.status_code == 404:
            return {"error": f"MLflow resource not found at {endpoint}"}
        if resp.status_code >= 400:
            try:
                body = resp.json()
                message = body.get("message", resp.text)
            except Exception:
                message = resp.text
            return {"error": f"MLflow API error (HTTP {resp.status_code}): {message}"}

        return resp.json() if resp.text else {"success": True}
    except httpx.ConnectError:
        return {
            "error": f"Cannot connect to MLflow server at {uri}. Is it running?",
            "help": "Start MLflow server with: mlflow server --host 0.0.0.0 --port 5000",
        }
    except httpx.TimeoutException:
        return {"error": "Request to MLflow server timed out"}
    except Exception as e:
        return {"error": f"MLflow request failed: {e!s}"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register MLflow experiment tracking and model registry tools."""

    tracking_uri = _get_tracking_uri(credentials)
    token = _get_token(credentials)

    @mcp.tool()
    def mlflow_list_experiments() -> dict:
        """
        List all MLflow experiments.

        Returns:
            Dict with experiments list and metadata.
        """
        return _make_request("GET", tracking_uri, "/mlflow/experiments/list", token=token)

    @mcp.tool()
    def mlflow_get_experiment(experiment_id: str) -> dict:
        """
        Get details of a specific MLflow experiment.

        Args:
            experiment_id: The experiment ID.

        Returns:
            Dict with experiment details.
        """
        return _make_request(
            "GET",
            tracking_uri,
            "/mlflow/experiments/get",
            token=token,
            params={"experiment_id": experiment_id},
        )

    @mcp.tool()
    def mlflow_create_experiment(name: str, artifact_location: str = "") -> dict:
        """
        Create a new MLflow experiment.

        Args:
            name: Experiment name.
            artifact_location: Optional artifact storage location.

        Returns:
            Dict with created experiment ID.
        """
        payload = {"name": name}
        if artifact_location:
            payload["artifact_location"] = artifact_location
        return _make_request(
            "POST",
            tracking_uri,
            "/mlflow/experiments/create",
            token=token,
            json_data=payload,
        )

    @mcp.tool()
    def mlflow_log_run(
        experiment_id: str,
        run_name: str = "",
        parameters: dict[str, str] | None = None,
        metrics: dict[str, float] | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict:
        """
        Log a run to MLflow with parameters, metrics, and tags.

        Args:
            experiment_id: The experiment ID.
            run_name: Optional run name.
            parameters: Dict of parameter names to values.
            metrics: Dict of metric names to numeric values.
            tags: Dict of tag names to values.

        Returns:
            Dict with run ID and status.
        """
        # Create run
        run_payload = {"experiment_id": experiment_id}
        if run_name:
            run_payload["tags"] = [{"key": "mlflow.runName", "value": run_name}]

        run_response = _make_request(
            "POST",
            tracking_uri,
            "/mlflow/runs/create",
            token=token,
            json_data=run_payload,
        )

        if "error" in run_response:
            return run_response

        run_id = run_response.get("run", {}).get("info", {}).get("run_id")
        if not run_id:
            return {"error": "Failed to create run"}

        # Track successful logging counts
        params_logged = 0
        metrics_logged = 0
        tags_logged = 0
        errors = []

        # Log parameters
        if parameters:
            for param_name, param_value in parameters.items():
                resp = _make_request(
                    "POST",
                    tracking_uri,
                    "/mlflow/runs/log-parameter",
                    token=token,
                    json_data={
                        "run_id": run_id,
                        "key": param_name,
                        "value": str(param_value),
                    },
                )
                if "error" not in resp:
                    params_logged += 1
                else:
                    errors.append(f"Failed to log parameter {param_name}: {resp['error']}")

        # Log metrics
        if metrics:
            for metric_name, metric_value in metrics.items():
                resp = _make_request(
                    "POST",
                    tracking_uri,
                    "/mlflow/runs/log-metric",
                    token=token,
                    json_data={
                        "run_id": run_id,
                        "key": metric_name,
                        "value": float(metric_value),
                        "timestamp": int(__import__("time").time() * 1000),
                    },
                )
                if "error" not in resp:
                    metrics_logged += 1
                else:
                    errors.append(f"Failed to log metric {metric_name}: {resp['error']}")

        # Log tags
        if tags:
            for tag_name, tag_value in tags.items():
                resp = _make_request(
                    "POST",
                    tracking_uri,
                    "/mlflow/runs/set-tag",
                    token=token,
                    json_data={
                        "run_id": run_id,
                        "key": tag_name,
                        "value": str(tag_value),
                    },
                )
                if "error" not in resp:
                    tags_logged += 1
                else:
                    errors.append(f"Failed to log tag {tag_name}: {resp['error']}")

        result = {
            "run_id": run_id,
            "experiment_id": experiment_id,
            "status": "created",
            "parameters_logged": params_logged,
            "metrics_logged": metrics_logged,
            "tags_logged": tags_logged,
        }
        if errors:
            result["warnings"] = errors
        return result

    @mcp.tool()
    def mlflow_get_metrics(run_id: str) -> dict:
        """
        Get all metrics for a specific run.

        Args:
            run_id: The run ID.

        Returns:
            Dict with metrics data.
        """
        return _make_request(
            "GET",
            tracking_uri,
            "/mlflow/metrics/get-history",
            token=token,
            params={"run_id": run_id},
        )

    @mcp.tool()
    def mlflow_search_runs(
        experiment_ids: str = "",
        filter_string: str = "",
        max_results: int = 100,
    ) -> dict:
        """
        Search MLflow runs with optional filtering.

        Args:
            experiment_ids: Comma-separated experiment IDs to search.
            filter_string: Filter expression (e.g., "metrics.accuracy > 0.9").
            max_results: Maximum number of results to return.

        Returns:
            Dict with matching runs.
        """
        payload: dict[str, Any] = {"max_results": max_results}

        if experiment_ids:
            payload["experiment_ids"] = experiment_ids.split(",")
        if filter_string:
            payload["filter"] = filter_string

        return _make_request(
            "POST",
            tracking_uri,
            "/mlflow/runs/search",
            token=token,
            json_data=payload,
        )

    @mcp.tool()
    def mlflow_register_model(
        model_uri: str,
        name: str,
        tags: dict[str, str] | None = None,
    ) -> dict:
        """
        Register a model to MLflow Model Registry.

        Args:
            model_uri: Model URI (e.g., "runs:/run_id/model").
            name: Model name.
            tags: Optional dict of tags.

        Returns:
            Dict with registered model version details.
        """
        payload = {
            "source": model_uri,
            "name": name,
        }
        if tags:
            payload["tags"] = tags

        return _make_request(
            "POST",
            tracking_uri,
            "/mlflow/model-versions/create",
            token=token,
            json_data=payload,
        )

    @mcp.tool()
    def mlflow_get_registered_model(name: str) -> dict:
        """
        Get details of a registered model.

        Args:
            name: Registered model name.

        Returns:
            Dict with model details and versions.
        """
        return _make_request(
            "GET",
            tracking_uri,
            "/mlflow/registered-models/get",
            token=token,
            params={"name": name},
        )

    @mcp.tool()
    def mlflow_list_registered_models(max_results: int = 100) -> dict:
        """
        List all registered models in the Model Registry.

        Args:
            max_results: Maximum number of models to return.

        Returns:
            Dict with registered models list.
        """
        return _make_request(
            "GET",
            tracking_uri,
            "/mlflow/registered-models/list",
            token=token,
            params={"max_results": max_results},
        )

    @mcp.tool()
    def mlflow_transition_model_stage(
        name: str,
        version: int,
        stage: str,
    ) -> dict:
        """
        Transition a model version to a new stage (Staging, Production, Archived).

        Args:
            name: Registered model name.
            version: Model version number.
            stage: Target stage (Staging, Production, or Archived).

        Returns:
            Dict with transition status.
        """
        if stage not in ["Staging", "Production", "Archived", "None"]:
            return {
                "error": f"Invalid stage '{stage}'. Must be one of: Staging, Production, Archived, None"
            }

        return _make_request(
            "POST",
            tracking_uri,
            "/mlflow/model-versions/transition-stage",
            token=token,
            json_data={
                "name": name,
                "version": version,
                "stage": stage,
            },
        )

    @mcp.tool()
    def mlflow_get_run(run_id: str) -> dict:
        """
        Get details of a specific run.

        Args:
            run_id: The run ID.

        Returns:
            Dict with run details, metrics, params, and tags.
        """
        return _make_request(
            "GET",
            tracking_uri,
            "/mlflow/runs/get",
            token=token,
            params={"run_id": run_id},
        )
