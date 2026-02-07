"""
Notion tool credentials.

Contains credentials for Notion workspace integration.
"""

from .base import CredentialSpec

NOTION_CREDENTIALS = {
    "notion": CredentialSpec(
        env_var="NOTION_API_KEY",
        tools=[
            "notion_search",
            "notion_get_page",
            "notion_create_page",
            "notion_append_text",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.notion.com/docs/create-a-notion-integration",
        description="Notion Integration Token (starts with secret_)",
        # Auth method support
        aden_supported=False,  # Notion doesn't support OAuth2 via Aden yet
        aden_provider_name="",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Notion Integration Token:
1. Go to https://www.notion.so/my-integrations
2. Click "+ New integration"
3. Give your integration a name (e.g., "Hive Agent")
4. Select the workspace where you want to use the integration
5. Click "Submit" to create the integration
6. Copy the "Internal Integration Token" (starts with secret_)
7. Important: Share your Notion pages/databases with this integration:
   - Open the page/database in Notion
   - Click "..." menu > "Connections" (or "+ Add connections")
   - Search for your integration name and select it

Note: The integration can only access pages/databases that are explicitly shared with it.""",
        # Health check configuration
        health_check_endpoint="https://api.notion.com/v1/users/me",
        health_check_method="GET",
        # Credential store mapping
        credential_id="notion",
        credential_key="api_key",
    ),
}
