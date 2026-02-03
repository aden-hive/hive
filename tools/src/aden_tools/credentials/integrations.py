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
    "slack": CredentialSpec(
        env_var="SLACK_BOT_TOKEN",
        tools=[
            "slack_send_message",
            "slack_list_channels",
            "slack_get_channel_history",
            "slack_list_users",
            "slack_get_user",
        ],
        required=True,
        startup_required=False,
        help_url="https://api.slack.com/apps",
        description="Slack Bot User OAuth Token",
        # Auth method support
        aden_supported=True,
        aden_provider_name="slack",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Slack Bot Token:
1. Go to https://api.slack.com/apps
2. Create a new app (or select existing)
3. Go to "OAuth & Permissions"
4. Add the following Bot Token Scopes:
   - chat:write
   - channels:read
   - channels:history
   - users:read
5. Install the app to your workspace
6. Copy the "Bot User OAuth Token" (starts with xoxb-)""",
        # Health check configuration
        health_check_endpoint="https://slack.com/api/auth.test",
        health_check_method="POST",
        # Credential store mapping
        credential_id="slack",
        credential_key="bot_token",
    ),
}
