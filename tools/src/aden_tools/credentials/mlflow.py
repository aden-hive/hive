"""
MLflow experiment tracking credentials.

Contains credentials for the MLflow REST API v2.

MLFLOW_TRACKING_URI is optional and defaults to http://localhost:5000.
MLFLOW_TRACKING_TOKEN is only required when the server has authentication enabled
(e.g., Databricks-managed MLflow or self-hosted deployments with auth).
"""

from __future__ import annotations

from .base import CredentialSpec

MLFLOW_CREDENTIALS = {
    "mlflow_tracking_uri": CredentialSpec(
        env_var="MLFLOW_TRACKING_URI",
        tools=[
            "mlflow_list_experiments",
            "mlflow_get_experiment",
            "mlflow_list_runs",
            "mlflow_get_run",
            "mlflow_log_metric",
            "mlflow_log_param",
            "mlflow_get_model_version",
        ],
        required=False,
        startup_required=False,
        help_url="https://mlflow.org/docs/latest/tracking.html",
        description="MLflow Tracking Server URI (default: http://localhost:5000)",
        direct_api_key_supported=True,
        api_key_instructions="""To configure MLflow tracking:
1. Start a local tracking server: mlflow server --host 0.0.0.0 --port 5000
2. Or point to a remote server:
   export MLFLOW_TRACKING_URI=https://your-mlflow-server.example.com
3. If authentication is enabled, also set MLFLOW_TRACKING_TOKEN.""",
        health_check_endpoint="",
        credential_id="mlflow_tracking_uri",
        credential_key="api_key",
    ),
    "mlflow_tracking_token": CredentialSpec(
        env_var="MLFLOW_TRACKING_TOKEN",
        tools=[
            "mlflow_list_experiments",
            "mlflow_get_experiment",
            "mlflow_list_runs",
            "mlflow_get_run",
            "mlflow_log_metric",
            "mlflow_log_param",
            "mlflow_get_model_version",
        ],
        required=False,
        startup_required=False,
        help_url="https://mlflow.org/docs/latest/auth/index.html",
        description="MLflow Bearer token for authenticated deployments (optional)",
        direct_api_key_supported=True,
        api_key_instructions="""To obtain an MLflow token:
- Databricks-hosted MLflow: use a Databricks personal access token.
- Self-hosted with auth enabled: create a token via mlflow.server.auth APIs.
  export MLFLOW_TRACKING_TOKEN=your-token""",
        health_check_endpoint="",
        credential_id="mlflow_tracking_token",
        credential_key="api_key",
    ),
}
