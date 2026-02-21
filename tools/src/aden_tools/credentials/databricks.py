"""
Databricks tool credentials.

Contains credentials for Databricks workspace integration.
Supports Databricks on AWS and Azure.
"""

from .base import CredentialSpec

DATABRICKS_CREDENTIALS = {
    "databricks": CredentialSpec(
        env_var="DATABRICKS_TOKEN",
        tools=[
            "run_databricks_sql",
            "trigger_databricks_job",
            "describe_table",
            "list_workspace",
            "databricks_list_jobs",
            "databricks_get_job_status",
            "databricks_list_warehouses",
            "databricks_list_catalogs",
            "databricks_list_schemas",
            "databricks_list_tables",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.databricks.com/en/dev-tools/auth.html",
        description="Databricks Personal Access Token or Service Principal token",
        aden_supported=False,
        aden_provider_name="databricks",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Databricks Personal Access Token:
1. Log in to your Databricks workspace
2. Click on your username in the top right corner
3. Select "Settings" from the dropdown
4. Go to "Developer" tab (or "User Settings" > "Access Tokens")
5. Click "Generate new token"
6. Give your token a comment and lifetime (or leave blank for indefinite)
7. Click "Generate" and copy the token immediately
8. Also set DATABRICKS_HOST to your workspace URL (e.g., https://your-workspace.cloud.databricks.com)

For Service Principal authentication:
1. Create a Service Principal in Azure AD or Databricks
2. Generate a secret for the Service Principal
3. Use the Application ID and Secret as the token""",
        health_check_endpoint="",
        health_check_method="GET",
        credential_id="databricks",
        credential_key="access_token",
        credential_group="databricks",
    ),
    "databricks_host": CredentialSpec(
        env_var="DATABRICKS_HOST",
        tools=[
            "run_databricks_sql",
            "trigger_databricks_job",
            "describe_table",
            "list_workspace",
            "databricks_list_jobs",
            "databricks_get_job_status",
            "databricks_list_warehouses",
            "databricks_list_catalogs",
            "databricks_list_schemas",
            "databricks_list_tables",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.databricks.com/en/workspace/workspace-url.html",
        description="Databricks workspace URL (e.g., https://your-workspace.cloud.databricks.com)",
        aden_supported=False,
        direct_api_key_supported=True,
        credential_id="databricks_host",
        credential_key="host",
        credential_group="databricks",
    ),
}
