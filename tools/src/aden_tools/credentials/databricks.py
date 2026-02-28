"""
Databricks tool credentials.

Contains credentials for Databricks workspace and SQL Warehouse access,
as well as managed MCP server connectivity.
"""

from .base import CredentialSpec

# All tool names that require Databricks credentials
_DATABRICKS_TOOLS = [
    # Custom SQL tools (databricks_tool.py)
    "run_databricks_sql",
    "describe_databricks_table",
    # Managed MCP tools (databricks_mcp_tool.py)
    "databricks_mcp_query_sql",
    "databricks_mcp_query_uc_function",
    "databricks_mcp_vector_search",
    "databricks_mcp_query_genie",
    "databricks_mcp_list_tools",
]

DATABRICKS_CREDENTIALS = {
    "databricks_host": CredentialSpec(
        env_var="DATABRICKS_HOST",
        tools=_DATABRICKS_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://docs.databricks.com/en/workspace/workspace-details.html",
        description="Databricks workspace URL (e.g., https://dbc-a1b2c3d4-e5f6.cloud.databricks.com)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To set up Databricks authentication:

1. Go to your Databricks workspace
2. Copy the workspace URL from your browser (e.g., https://dbc-a1b2c3d4-e5f6.cloud.databricks.com)
3. Set DATABRICKS_HOST=https://your-workspace-hostname

Note: Do not include a trailing slash.""",
        # Credential store mapping
        credential_id="databricks_host",
        credential_key="workspace_url",
    ),
    "databricks_token": CredentialSpec(
        env_var="DATABRICKS_TOKEN",
        tools=_DATABRICKS_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://docs.databricks.com/en/dev-tools/auth/pat.html",
        description="Databricks personal access token for API authentication",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To create a Databricks personal access token:

1. Go to your Databricks workspace
2. Click your username in the top bar > Settings
3. Click 'Developer' in the sidebar
4. Under 'Access tokens', click 'Manage'
5. Click 'Generate new token'
6. Give it a description and set the lifetime
7. Copy the token and set DATABRICKS_TOKEN=dapi...

For service principals, use OAuth machine-to-machine tokens instead.""",
        # Credential store mapping
        credential_id="databricks_token",
        credential_key="access_token",
    ),
    "databricks_warehouse": CredentialSpec(
        env_var="DATABRICKS_WAREHOUSE_ID",
        tools=["run_databricks_sql", "databricks_mcp_query_sql"],
        required=False,
        startup_required=False,
        help_url="https://docs.databricks.com/en/sql/admin/create-sql-warehouse.html",
        description="Default Databricks SQL Warehouse ID for query execution",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To find your SQL Warehouse ID:

1. Go to your Databricks workspace
2. Click 'SQL Warehouses' in the sidebar
3. Click on your warehouse
4. Copy the ID from the URL or the 'Connection details' tab
5. Set DATABRICKS_WAREHOUSE_ID=your_warehouse_id""",
        # Credential store mapping
        credential_id="databricks_warehouse",
        credential_key="warehouse_id",
    ),
}
