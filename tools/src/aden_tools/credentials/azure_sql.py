"""
Azure SQL Database management credentials.

Contains credentials for the Azure SQL REST API (management plane).
Requires AZURE_SQL_ACCESS_TOKEN and AZURE_SUBSCRIPTION_ID.
"""

from .base import CredentialSpec

AZURE_SQL_CREDENTIALS = {
    "azure_sql_token": CredentialSpec(
        env_var="AZURE_SQL_ACCESS_TOKEN",
        tools=[
            "azure_sql_list_servers",
            "azure_sql_get_server",
            "azure_sql_list_databases",
            "azure_sql_get_database",
            "azure_sql_list_firewall_rules",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/rest/api/sql/",
        description="Azure Bearer token for SQL management API (scope: management.azure.com)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Azure SQL management API access:
1. Register an app in Azure AD (Entra ID)
2. Assign SQL DB Contributor or Reader role
3. Obtain a token via client credentials flow (scope: https://management.azure.com/.default)
4. Set environment variables:
   export AZURE_SQL_ACCESS_TOKEN=your-bearer-token
   export AZURE_SUBSCRIPTION_ID=your-subscription-id""",
        health_check_endpoint="",
        credential_id="azure_sql_token",
        credential_key="api_key",
    ),
    "azure_subscription_id": CredentialSpec(
        env_var="AZURE_SUBSCRIPTION_ID",
        tools=[
            "azure_sql_list_servers",
            "azure_sql_get_server",
            "azure_sql_list_databases",
            "azure_sql_get_database",
            "azure_sql_list_firewall_rules",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/azure/azure-portal/get-subscription-tenant-id",
        description="Azure subscription ID for resource management",
        direct_api_key_supported=True,
        api_key_instructions="""See AZURE_SQL_ACCESS_TOKEN instructions above.""",
        health_check_endpoint="",
        credential_id="azure_subscription_id",
        credential_key="api_key",
    ),
}
