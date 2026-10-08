"""
Pipedrive CRM credentials.

Contains credentials for Pipedrive deal, contact, and pipeline management.
"""

from .base import CredentialSpec

PIPEDRIVE_CREDENTIALS = {
    "pipedrive": CredentialSpec(
        env_var="PIPEDRIVE_API_TOKEN",
        tools=[
            "pipedrive_list_deals",
            "pipedrive_get_deal",
            "pipedrive_create_deal",
            "pipedrive_list_persons",
            "pipedrive_search_persons",
            "pipedrive_list_organizations",
            "pipedrive_list_activities",
            "pipedrive_list_pipelines",
            "pipedrive_list_stages",
            "pipedrive_add_note",
            "pipedrive_update_deal",
            "pipedrive_create_person",
            "pipedrive_create_activity",
        ],
        required=True,
        startup_required=False,
        help_url="https://pipedrive.readme.io/docs/core-api-concepts-about-pipedrive-api",
        description=("Pipedrive API token for CRM management (also set PIPEDRIVE_DOMAIN for custom domains)"),
        direct_api_key_supported=True,
        api_key_instructions="""To get a Pipedrive API token:
1. Log in to your Pipedrive account
2. Go to Settings > Personal preferences > API
3. Copy your personal API token
4. Set environment variables:
   export PIPEDRIVE_API_TOKEN=your-api-token
   export PIPEDRIVE_DOMAIN=your-company.pipedrive.com""",
        health_check_endpoint="https://api.pipedrive.com/v1/users/me",
        credential_id="pipedrive",
        credential_key="api_key",
    ),
}
