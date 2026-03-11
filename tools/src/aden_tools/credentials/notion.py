"""
Notion credentials.

Contains credentials for Notion pages, databases, and search.
Requires NOTION_API_TOKEN.
"""

from .base import CredentialSpec

NOTION_CREDENTIALS = {
    "notion_token": CredentialSpec(
        env_var="NOTION_API_TOKEN",
        tools=[
            "notion_search",
            "notion_get_page",
            "notion_create_page",
            "notion_query_database",
            "notion_get_database",
            "notion_update_page",
            "notion_archive_page",
            "notion_append_blocks",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.notion.so/my-integrations",
        description="Notion internal integration token",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Notion API access:
1. Go to https://www.notion.so/my-integrations
2. Click 'New integration'
3. Give it a name, select the workspace, and set capabilities
4. Copy the integration token
5. Share target pages/databases with the integration
6. Set environment variable:
   export NOTION_API_TOKEN=your-integration-token""",
        health_check_endpoint="https://api.notion.com/v1/users/me",
        credential_id="notion_token",
        credential_key="api_key",
    ),
}
