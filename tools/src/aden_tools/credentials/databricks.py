"""
Databricks credentials.

Contains credentials for Databricks workspace, SQL, and job management.
"""

from .base import CredentialSpec

DATABRICKS_CREDENTIALS = {
    "databricks": CredentialSpec(
        env_var="DATABRICKS_TOKEN",
        tools=[
            "databricks_sql_query",
            "databricks_list_jobs",
            "databricks_run_job",
            "databricks_get_run",
            "databricks_list_clusters",
            "databricks_start_cluster",
            "databricks_terminate_cluster",
            "databricks_list_workspace",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.databricks.com/dev-tools/auth/pat.html",
        description="Databricks personal access token (also requires DATABRICKS_HOST env var)",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Databricks personal access token:
1. Go to your Databricks workspace URL
2. Click your username in the top-right → Settings
3. Go to Developer → Access tokens
4. Click Generate new token
5. Set both environment variables:
   export DATABRICKS_TOKEN=dapi...
   export DATABRICKS_HOST=https://your-workspace.cloud.databricks.com""",
        health_check_endpoint="",
        credential_id="databricks",
        credential_key="api_key",
    ),
}
