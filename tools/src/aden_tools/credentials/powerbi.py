"""
Power BI credentials.

Contains credentials for the Microsoft Power BI REST API.
Requires POWERBI_ACCESS_TOKEN (OAuth2 Bearer token).
"""

from .base import CredentialSpec

POWERBI_CREDENTIALS = {
    "powerbi_token": CredentialSpec(
        env_var="POWERBI_ACCESS_TOKEN",
        tools=[
            "powerbi_list_workspaces",
            "powerbi_list_datasets",
            "powerbi_list_reports",
            "powerbi_refresh_dataset",
            "powerbi_get_refresh_history",
        ],
        required=True,
        startup_required=False,
        help_url="https://learn.microsoft.com/en-us/rest/api/power-bi/",
        description="Power BI OAuth2 access token for API access",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Power BI API access:
1. Register an app in Azure AD (Entra ID)
2. Grant Power BI API permissions (Workspace.Read.All, Dataset.ReadWrite.All, Report.Read.All)
3. Obtain an access token via client credentials or authorization code flow
4. Set environment variable:
   export POWERBI_ACCESS_TOKEN=your-oauth-access-token""",
        health_check_endpoint="",
        credential_id="powerbi_token",
        credential_key="api_key",
    ),
}
