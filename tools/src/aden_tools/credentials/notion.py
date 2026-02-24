"""
Notion tool credentials.
Contains credentials for Notion workspace integration.
"""

from .base import CredentialSpec

NOTION_CREDENTIALS = {
    "notion": CredentialSpec(
        env_var="NOTION_API_KEY",
        tools=[
            "notion_create_page",
            "notion_get_page",
            "notion_update_page",
            "notion_archive_page",
            "notion_query_database",
            "notion_get_database",
            "notion_create_database",
            "notion_update_database",
            "notion_get_block",
            "notion_get_block_children",
            "notion_append_block_children",
            "notion_delete_block",
            "notion_search",
            "notion_list_users",
            "notion_get_user",
            "notion_create_comment",
            "notion_list_comments",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.notion.so/my-integrations",
        description="Notion Internal Integration Secret for authenticating all API requests",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get your Notion API key:
1. Go to https://www.notion.so/my-integrations
2. Click "New integration"
3. Name it and select a workspace
4. Copy the Internal Integration Secret (starts with ntn_ or secret_)
5. Share target pages/databases with the integration via the "..." menu -> "Add connections"
Note: The integration can only access pages explicitly shared with it""",
        # Health check configuration
        health_check_endpoint="https://api.notion.com/v1/users/me",
        health_check_method="GET",
        # Credential store mapping
        credential_id="notion",
        credential_key="api_key",
        credential_group="",
    ),
}
