"""
Knowledge base tool credentials.

Contains credentials for knowledge base integrations like Confluence and Notion.
"""

from .base import CredentialSpec

KNOWLEDGE_BASE_CREDENTIALS = {
    "confluence": CredentialSpec(
        env_var="CONFLUENCE_API_TOKEN",
        tools=["confluence_search", "confluence_get_page"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage-profile/security/api-tokens",
        description="API token for Atlassian Confluence access",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Confluence API token:
1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click "Create API token"
3. Give your token a label (e.g., "Hive Agent")
4. Copy the generated token
5. Set CONFLUENCE_API_TOKEN and CONFLUENCE_URL environment variables""",
        health_check_endpoint="https://api.atlassian.com/ex/confluence",
        credential_id="confluence",
        credential_key="api_token",
    ),
    "notion": CredentialSpec(
        env_var="NOTION_API_KEY",
        tools=["notion_search", "notion_get_page"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://www.notion.so/my-integrations",
        description="API key for Notion workspace access",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Notion API key:
1. Go to https://www.notion.so/my-integrations
2. Click "New integration"
3. Give your integration a name (e.g., "Hive Agent")
4. Select the workspace to connect
5. Click "Submit" and copy the "Internal Integration Token"
6. Share pages with your integration from the page settings
7. Set NOTION_API_KEY environment variable""",
        health_check_endpoint="https://api.notion.com/v1/users/me",
        credential_id="notion",
        credential_key="api_key",
    ),
}
