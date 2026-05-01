"""
MLflow ML experiment tracking tool.

Uses the MLflow REST API v2 via httpx — no SDK dependency.

Authentication: Optional Bearer token (MLFLOW_TRACKING_TOKEN).
REST API base: {MLFLOW_TRACKING_URI}/api/2.0/mlflow

For local deployments no token is required; set MLFLOW_TRACKING_URI to point
at a remote server and MLFLOW_TRACKING_TOKEN when auth is enabled.

API Reference: https://mlflow.org/docs/latest/rest-api.html
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter

DEFAULT_TRACKING_URI = "http://localhost:5000"


def _get_creds(
    credentials: CredentialStoreAdapter | None,
) -> tuple[str, str | None]:
    """Return (tracking_uri, token_or_none).

    Both values are optional — a local MLflow server needs neither.
    The tracking URI falls back to http://localhost:5000 when unset.
    """
    if credentials is not None:
        uri = credentials.get("mlflow_tracking_uri") or DEFAULT_TRACKING_URI
        token = credentials.get("mlflow_tracking_token")
    else:
        uri = os.getenv("MLFLOW_TRACKING_URI", DEFAULT_TRACKING_URI)
        token = os.getenv("MLFLOW_TRACKING_TOKEN")

    return uri.rstrip("/"), token or None


def _headers(token: str | None) -> dict[str, str]:
    """Build request headers, adding Authorization when a token is present."""
    hdrs: dict[str, str] = {"Content-Type": "application/json"}
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    return hdrs


def _handle_response(resp: httpx.Response) -> dict[str, Any]:
    """Parse an MLflow REST response, normalizing HTTP error cases to error dicts."""
    if resp.status_code == 401:
        return {"error": "Invalid or missing MLflow authentication token"}
    if resp.status_code == 403:
        return {"error": "Insufficient permissions for this MLflow resource"}
    if resp.status_code == 404:
        return {"error": "MLflow resource not found"}
    if resp.status_code == 429:
        return {"error": "MLflow rate limit exceeded. Try again later."}
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("message", body.get("error_code", resp.text))
        except Exception:
            detail = resp.text
        return {"error": f"MLflow API error (HTTP {resp.status_code}): {detail}"}
    try:
        return resp.json()
    except Exception:
        return {"error": f"Invalid JSON response from MLflow (HTTP {resp.status_code})"}


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register MLflow experiment tracking tools with the MCP server."""

    @mcp.tool()
    def mlflow_list_experiments(
        view_type: str = "ACTIVE_ONLY",
        max_results: int = 100,
    ) -> dict:
        """
        List experiments in the MLflow tracking server.

        Args:
            view_type: Filter by lifecycle state. One of "ACTIVE_ONLY",
                "DELETED_ONLY", or "ALL" (default: "ACTIVE_ONLY").
            max_results: Maximum number of experiments to return (default 100).

        Returns:
            Dict with an "experiments" list and a "count" of returned items.
        """
        uri, token = _get_creds(credentials)
        try:
            resp = httpx.get(
                f"{uri}/api/2.0/mlflow/experiments/list",
                headers=_headers(token),
                params={"view_type": view_type, "max_results": max_results},
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data

        experiments = [
            {
                "experiment_id": exp.get("experiment_id"),
                "name": exp.get("name"),
                "artifact_location": exp.get("artifact_location"),
                "lifecycle_stage": exp.get("lifecycle_stage"),
                "last_update_time": exp.get("last_update_time"),
                "creation_time": exp.get("creation_time"),
            }
            for exp in data.get("experiments", [])
        ]
        return {"experiments": experiments, "count": len(experiments)}

    @mcp.tool()
    def mlflow_get_experiment(experiment_id: str) -> dict:
        """
        Get details of a specific MLflow experiment.

        Args:
            experiment_id: The experiment ID (e.g., "0" for the default experiment).

        Returns:
            Dict with experiment metadata including name, artifact location, and tags.
        """
        if not experiment_id:
            return {"error": "experiment_id is required"}

        uri, token = _get_creds(credentials)
        try:
            resp = httpx.get(
                f"{uri}/api/2.0/mlflow/experiments/get",
                headers=_headers(token),
                params={"experiment_id": experiment_id},
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data

        exp = data.get("experiment", {})
        return {
            "experiment_id": exp.get("experiment_id"),
            "name": exp.get("name"),
            "artifact_location": exp.get("artifact_location"),
            "lifecycle_stage": exp.get("lifecycle_stage"),
            "last_update_time": exp.get("last_update_time"),
            "creation_time": exp.get("creation_time"),
            "tags": exp.get("tags", []),
        }

    @mcp.tool()
    def mlflow_list_runs(
        experiment_ids: str,
        filter_string: str = "",
        max_results: int = 100,
        order_by: str = "",
    ) -> dict:
        """
        Search for runs in one or more MLflow experiments.

        Args:
            experiment_ids: Comma-separated experiment IDs to search (e.g., "0,1,2").
            filter_string: MLflow filter expression to narrow results
                (e.g., "metrics.accuracy > 0.9" or "params.lr = '0.01'").
            max_results: Maximum number of runs to return (default 100).
            order_by: Comma-separated sort columns
                (e.g., "metrics.accuracy DESC,start_time ASC").

        Returns:
            Dict with a "runs" list, each containing info, metrics, params, and tags.
        """
        if not experiment_ids:
            return {"error": "experiment_ids is required"}

        ids = [eid.strip() for eid in experiment_ids.split(",") if eid.strip()]
        if not ids:
            return {"error": "experiment_ids must contain at least one non-empty ID"}

        uri, token = _get_creds(credentials)
        body: dict[str, Any] = {"experiment_ids": ids, "max_results": max_results}
        if filter_string:
            body["filter"] = filter_string
        if order_by:
            body["order_by"] = [col.strip() for col in order_by.split(",") if col.strip()]

        try:
            resp = httpx.post(
                f"{uri}/api/2.0/mlflow/runs/search",
                headers=_headers(token),
                json=body,
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data

        runs = []
        for run in data.get("runs", []):
            info = run.get("info", {})
            run_data = run.get("data", {})
            runs.append(
                {
                    "run_id": info.get("run_id"),
                    "run_name": info.get("run_name"),
                    "experiment_id": info.get("experiment_id"),
                    "status": info.get("status"),
                    "start_time": info.get("start_time"),
                    "end_time": info.get("end_time"),
                    "artifact_uri": info.get("artifact_uri"),
                    "metrics": {m["key"]: m["value"] for m in run_data.get("metrics", [])},
                    "params": {p["key"]: p["value"] for p in run_data.get("params", [])},
                    "tags": {t["key"]: t["value"] for t in run_data.get("tags", [])},
                }
            )
        return {
            "runs": runs,
            "count": len(runs),
            "next_page_token": data.get("next_page_token", ""),
        }

    @mcp.tool()
    def mlflow_get_run(run_id: str) -> dict:
        """
        Get full details of a specific MLflow run.

        Args:
            run_id: The run ID to retrieve.

        Returns:
            Dict with run info, final metrics, params, and tags.
        """
        if not run_id:
            return {"error": "run_id is required"}

        uri, token = _get_creds(credentials)
        try:
            resp = httpx.get(
                f"{uri}/api/2.0/mlflow/runs/get",
                headers=_headers(token),
                params={"run_id": run_id},
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data

        run = data.get("run", {})
        info = run.get("info", {})
        run_data = run.get("data", {})
        return {
            "run_id": info.get("run_id"),
            "run_name": info.get("run_name"),
            "experiment_id": info.get("experiment_id"),
            "status": info.get("status"),
            "start_time": info.get("start_time"),
            "end_time": info.get("end_time"),
            "artifact_uri": info.get("artifact_uri"),
            "lifecycle_stage": info.get("lifecycle_stage"),
            "metrics": {m["key"]: m["value"] for m in run_data.get("metrics", [])},
            "params": {p["key"]: p["value"] for p in run_data.get("params", [])},
            "tags": {t["key"]: t["value"] for t in run_data.get("tags", [])},
        }

    @mcp.tool()
    def mlflow_log_metric(
        run_id: str,
        key: str,
        value: float,
        step: int = 0,
    ) -> dict:
        """
        Log a metric value to an active MLflow run.

        Args:
            run_id: The active run ID to log to.
            key: Metric name (e.g., "accuracy", "loss").
            value: Numeric metric value.
            step: Training step or epoch number (default 0).

        Returns:
            Dict with success confirmation or an error message.
        """
        if not run_id:
            return {"error": "run_id is required"}
        if not key:
            return {"error": "key is required"}

        uri, token = _get_creds(credentials)
        body: dict[str, Any] = {
            "run_id": run_id,
            "key": key,
            "value": value,
            "timestamp": int(time.time() * 1000),
            "step": step,
        }
        try:
            resp = httpx.post(
                f"{uri}/api/2.0/mlflow/runs/log-metric",
                headers=_headers(token),
                json=body,
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data
        return {"success": True, "run_id": run_id, "key": key, "value": value, "step": step}

    @mcp.tool()
    def mlflow_log_param(run_id: str, key: str, value: str) -> dict:
        """
        Log a parameter to an active MLflow run.

        Args:
            run_id: The active run ID to log to.
            key: Parameter name (e.g., "learning_rate", "batch_size").
            value: Parameter value (always stored as a string).

        Returns:
            Dict with success confirmation or an error message.
        """
        if not run_id:
            return {"error": "run_id is required"}
        if not key:
            return {"error": "key is required"}

        uri, token = _get_creds(credentials)
        body: dict[str, Any] = {"run_id": run_id, "key": key, "value": value}
        try:
            resp = httpx.post(
                f"{uri}/api/2.0/mlflow/runs/log-parameter",
                headers=_headers(token),
                json=body,
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data
        return {"success": True, "run_id": run_id, "key": key, "value": value}

    @mcp.tool()
    def mlflow_get_model_version(name: str, version: str) -> dict:
        """
        Get details of a specific MLflow registered model version.

        Args:
            name: The registered model name.
            version: The model version number as a string (e.g., "1", "2").

        Returns:
            Dict with model version metadata including stage, source, and run ID.
        """
        if not name:
            return {"error": "name is required"}
        if not version:
            return {"error": "version is required"}

        uri, token = _get_creds(credentials)
        try:
            resp = httpx.get(
                f"{uri}/api/2.0/mlflow/model-versions/get",
                headers=_headers(token),
                params={"name": name, "version": version},
                timeout=30.0,
            )
        except httpx.TimeoutException:
            return {"error": "Request timed out"}
        except httpx.RequestError as exc:
            return {"error": f"Network error: {exc}"}

        data = _handle_response(resp)
        if "error" in data:
            return data

        mv = data.get("model_version", {})
        return {
            "name": mv.get("name"),
            "version": mv.get("version"),
            "creation_timestamp": mv.get("creation_timestamp"),
            "last_updated_timestamp": mv.get("last_updated_timestamp"),
            "current_stage": mv.get("current_stage"),
            "description": mv.get("description", ""),
            "source": mv.get("source"),
            "run_id": mv.get("run_id"),
            "status": mv.get("status"),
            "tags": {t["key"]: t["value"] for t in mv.get("tags", [])},
        }
