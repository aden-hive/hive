"""
Confluence credentials.

Contains credentials for Confluence wiki & knowledge management.
Requires CONFLUENCE_DOMAIN, CONFLUENCE_EMAIL, and CONFLUENCE_API_TOKEN.
"""

from .base import CredentialSpec

CONFLUENCE_CREDENTIALS = {
    "confluence_domain": CredentialSpec(
        env_var="CONFLUENCE_DOMAIN",
        tools=[
            "confluence_list_spaces",
            "confluence_list_pages",
            "confluence_get_page",
            "confluence_create_page",
            "confluence_search",
        ],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage/api-tokens",
        description="Confluence domain (e.g. your-org.atlassian.net)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Confluence access:
1. Go to https://id.atlassian.com/manage/api-tokens
2. Click 'Create API token'
3. Set environment variables:
   export CONFLUENCE_DOMAIN=your-org.atlassian.net
   export CONFLUENCE_EMAIL=your-email@example.com
   export CONFLUENCE_API_TOKEN=your-api-token""",
        health_check_endpoint="",
        credential_id="confluence_domain",
        credential_key="api_key",
    ),
    "confluence_email": CredentialSpec(
        env_var="CONFLUENCE_EMAIL",
        tools=[
            "confluence_list_spaces",
            "confluence_list_pages",
            "confluence_get_page",
            "confluence_create_page",
            "confluence_search",
        ],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage/api-tokens",
        description="Atlassian account email for Confluence authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See CONFLUENCE_DOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="confluence_email",
        credential_key="api_key",
    ),
    "confluence_token": CredentialSpec(
        env_var="CONFLUENCE_API_TOKEN",
        tools=[
            "confluence_list_spaces",
            "confluence_list_pages",
            "confluence_get_page",
            "confluence_create_page",
            "confluence_search",
        ],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage/api-tokens",
        description="Atlassian API token for Confluence authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See CONFLUENCE_DOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="confluence_token",
        credential_key="api_key",
    ),
}
