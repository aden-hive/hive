"""
Integration credentials.

Contains credentials for third-party service integrations (HubSpot, Linear, etc.).
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
    "linear": CredentialSpec(
        env_var="LINEAR_API_KEY",
        tools=[
            "linear_issue_create",
            "linear_issue_get",
            "linear_issue_update",
            "linear_issue_delete",
            "linear_issue_search",
            "linear_issue_add_comment",
            "linear_project_create",
            "linear_project_get",
            "linear_project_update",
            "linear_project_list",
            "linear_teams_list",
            "linear_team_get",
            "linear_workflow_states_get",
            "linear_label_create",
            "linear_labels_list",
            "linear_users_list",
            "linear_user_get",
            "linear_viewer",
        ],
        required=True,
        startup_required=False,
        help_url="https://linear.app/settings/api",
        description="Linear API key or OAuth2 token for project management integration",
        # Auth method support
        aden_supported=True,
        aden_provider_name="linear",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Linear API key:
1. Go to Linear Settings > API (https://linear.app/settings/api)
2. Click "Create key" under "Personal API keys"
3. Give your key a descriptive label (e.g., "Hive Agent")
4. Copy the generated key (starts with 'lin_api_')
5. Store it securely - you won't be able to see it again!

Note: Personal API keys have the same permissions as your user account.

To create an OAuth application (for automatic token refresh via Aden):
1. Go to Linear Settings > API (https://linear.app/settings/api)
2. Click "New OAuth application"
3. Fill in the required information:
   - Application name (e.g., "Hive Agent")
   - Developer name
   - Other required fields
4. Click "Create"
5. Copy your client ID and client secret""",
        # Health check configuration
        health_check_endpoint="https://api.linear.app/graphql",
        health_check_method="POST",
        # Credential store mapping
        credential_id="linear",
        credential_key="api_key",
    ),
}
