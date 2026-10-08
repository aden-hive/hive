"""
Mattermost tool credentials.

Contains credentials for Mattermost server integration.
"""

from .base import CredentialSpec

MATTERMOST_CREDENTIALS = {
    "mattermost": CredentialSpec(
        env_var="MATTERMOST_ACCESS_TOKEN",
        tools=[
            "mattermost_list_teams",
            "mattermost_list_channels",
            "mattermost_get_channel",
            "mattermost_send_message",
            "mattermost_get_posts",
            "mattermost_create_reaction",
            "mattermost_delete_post",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.mattermost.com/integrate/reference/personal-access-token/",
        description="Mattermost Personal Access Token",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Mattermost Personal Access Token:
1. Log in to your Mattermost server
2. Go to Profile > Security > Personal Access Tokens
3. Click "Create Token"
4. Give it a description and click "Save"
5. Copy the token (it won't be shown again)

Note: Personal access tokens must be enabled by your System Admin.
Also set MATTERMOST_URL to your server URL (e.g. https://mattermost.example.com)""",
        health_check_endpoint=None,
        health_check_method="GET",
        credential_id="mattermost",
        credential_key="access_token",
    ),
    "mattermost_url": CredentialSpec(
        env_var="MATTERMOST_URL",
        tools=[
            "mattermost_list_teams",
            "mattermost_list_channels",
            "mattermost_get_channel",
            "mattermost_send_message",
            "mattermost_get_posts",
            "mattermost_create_reaction",
            "mattermost_delete_post",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.mattermost.com/integrate/reference/personal-access-token/",
        description="Mattermost Server URL (e.g. https://mattermost.example.com)",
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""Set this to your Mattermost server URL, e.g. https://mattermost.example.com
Do not include /api/v4 — it will be added automatically.""",
        health_check_endpoint=None,
        health_check_method="GET",
        credential_id="mattermost_url",
        credential_key="url",
    ),
}
