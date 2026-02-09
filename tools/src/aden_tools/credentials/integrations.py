"""
Integration credentials.

Contains credentials for third-party service integrations (HubSpot, etc.).
"""

from .base import CredentialSpec

INTEGRATION_CREDENTIALS = {
    "github": CredentialSpec(
        env_var="GITHUB_TOKEN",
        tools=[
            "github_list_repos",
            "github_get_repo",
            "github_search_repos",
            "github_list_issues",
            "github_get_issue",
            "github_create_issue",
            "github_update_issue",
            "github_list_pull_requests",
            "github_get_pull_request",
            "github_create_pull_request",
            "github_search_code",
            "github_list_branches",
            "github_get_branch",
        ],
        required=True,
        startup_required=False,
        help_url="https://github.com/settings/tokens",
        description="GitHub Personal Access Token (classic)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a GitHub Personal Access Token:
1. Go to GitHub Settings > Developer settings > Personal access tokens
2. Click "Generate new token" > "Generate new token (classic)"
3. Give your token a descriptive name (e.g., "Hive Agent")
4. Select the following scopes:
   - repo (Full control of private repositories)
   - read:org (Read org and team membership - optional)
   - user (Read user profile data - optional)
5. Click "Generate token" and copy the token (starts with ghp_)
6. Store it securely - you won't be able to see it again!""",
        # Health check configuration
        health_check_endpoint="https://api.github.com/user",
        health_check_method="GET",
        # Credential store mapping
        credential_id="github",
        credential_key="access_token",
    ),
    "hubspot": CredentialSpec(
        env_var="HUBSPOT_ACCESS_TOKEN",
        tools=[
            "hubspot_search_contacts",
            "hubspot_get_contact",
            "hubspot_create_contact",
            "hubspot_update_contact",
            "hubspot_search_companies",
            "hubspot_get_company",
            "hubspot_create_company",
            "hubspot_update_company",
            "hubspot_search_deals",
            "hubspot_get_deal",
            "hubspot_create_deal",
            "hubspot_update_deal",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.hubspot.com/docs/api/private-apps",
        description="HubSpot access token (Private App or OAuth2)",
        # Auth method support
        aden_supported=True,
        aden_provider_name="hubspot",
        direct_api_key_supported=True,
        api_key_instructions="""To get a HubSpot Private App token:
1. Go to HubSpot Settings > Integrations > Private Apps
2. Click "Create a private app"
3. Name your app (e.g., "Hive Agent")
4. Go to the "Scopes" tab and enable:
   - crm.objects.contacts.read
   - crm.objects.contacts.write
   - crm.objects.companies.read
   - crm.objects.companies.write
   - crm.objects.deals.read
   - crm.objects.deals.write
5. Click "Create app" and copy the access token""",
        # Health check configuration
        health_check_endpoint="https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
        health_check_method="GET",
        # Credential store mapping
        credential_id="hubspot",
        credential_key="access_token",
    ),
    "mssql_server": CredentialSpec(
        env_var="MSSQL_SERVER",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/sql/connect/odbc/download-odbc-driver-for-sql-server",
        description="MSSQL Server instance name (e.g., 'localhost' or 'SERVER\\INSTANCE')",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To connect to MSSQL Server:
1. Ensure SQL Server is installed and running
2. Note your server instance name (e.g., 'localhost\\SQLEXPRESS')
3. Set the connection details as environment variables:
   - MSSQL_SERVER: Server address (e.g., 'localhost\\SQLEXPRESS')
   - MSSQL_DATABASE: Database name (e.g., 'AdenTestDB')
   - MSSQL_USERNAME: SQL Server username (e.g., 'sa')
   - MSSQL_PASSWORD: SQL Server password
4. Ensure ODBC Driver 17 for SQL Server is installed""",
        # Credential store mapping
        credential_id="mssql",
        credential_key="server",
    ),
    "mssql_database": CredentialSpec(
        env_var="MSSQL_DATABASE",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/sql/t-sql/statements/create-database-transact-sql",
        description="MSSQL Database name to connect to",
        aden_supported=False,
        direct_api_key_supported=True,
        credential_id="mssql",
        credential_key="database",
    ),
    "mssql_username": CredentialSpec(
        env_var="MSSQL_USERNAME",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=False,  # Optional - can use Windows Auth
        startup_required=False,
        description="MSSQL Server username (not required for Windows Authentication)",
        aden_supported=False,
        direct_api_key_supported=True,
        credential_id="mssql",
        credential_key="username",
    ),
    "mssql_password": CredentialSpec(
        env_var="MSSQL_PASSWORD",
        tools=[
            "mssql_execute_query",
            "mssql_execute_update",
            "mssql_get_schema",
            "mssql_execute_procedure",
        ],
        required=False,  # Optional - can use Windows Auth
        startup_required=False,
        description="MSSQL Server password (not required for Windows Authentication)",
        aden_supported=False,
        direct_api_key_supported=True,
        credential_id="mssql",
        credential_key="password",
    ),
}
