"""
Databricks tool credentials.

Contains credentials for Databricks SQL Warehouse and Unity Catalog access.
"""

from .base import CredentialSpec

DATABRICKS_CREDENTIALS = {
    "databricks": CredentialSpec(
        env_var="DATABRICKS_TOKEN",
        tools=["run_databricks_sql", "describe_databricks_table"],
        required=False,
        startup_required=False,
        help_url="https://docs.databricks.com/en/dev-tools/auth/pat.html",
        description="Personal Access Token for Databricks workspace authentication",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To set up Databricks authentication:

1. Log in to your Databricks workspace
2. Click your username in the top right → Settings
3. Navigate to Developer → Access tokens
4. Click "Generate new token"
5. Give it a name (e.g., "Hive Agent") and set an expiration
6. Copy the token and set DATABRICKS_TOKEN=dapi...""",
        # Credential store mapping
        credential_id="databricks",
        credential_key="api_key",
    ),
    "databricks_host": CredentialSpec(
        env_var="DATABRICKS_HOST",
        tools=["run_databricks_sql", "describe_databricks_table"],
        required=False,
        startup_required=False,
        help_url="https://docs.databricks.com/en/workspace/workspace-details.html",
        description="Databricks workspace hostname (e.g., 'adb-12345.6.azuredatabricks.net')",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="Set this to your Databricks workspace hostname without 'https://' "
        "(e.g., 'adb-12345678901234.5.azuredatabricks.net')",
        credential_id="databricks_host",
        credential_key="host",
        credential_group="databricks",
    ),
}
