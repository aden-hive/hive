"""
Zendesk credentials.

Contains credentials for Zendesk Support ticket management.
Requires ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN.
"""

from .base import CredentialSpec

ZENDESK_CREDENTIALS = {
    "zendesk_subdomain": CredentialSpec(
        env_var="ZENDESK_SUBDOMAIN",
        tools=[
            "zendesk_list_tickets",
            "zendesk_get_ticket",
            "zendesk_create_ticket",
            "zendesk_update_ticket",
            "zendesk_search_tickets",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.zendesk.com/api-reference/introduction/security-and-auth/",
        description="Zendesk subdomain (e.g. 'acme' from acme.zendesk.com)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Zendesk API access:
1. Go to Zendesk Admin > Apps and integrations > APIs > Zendesk API
2. Enable Token Access and create an API token
3. Set environment variables:
   export ZENDESK_SUBDOMAIN=your-subdomain
   export ZENDESK_EMAIL=your-email@example.com
   export ZENDESK_API_TOKEN=your-api-token""",
        health_check_endpoint="",
        credential_id="zendesk_subdomain",
        credential_key="api_key",
    ),
    "zendesk_email": CredentialSpec(
        env_var="ZENDESK_EMAIL",
        tools=[
            "zendesk_list_tickets",
            "zendesk_get_ticket",
            "zendesk_create_ticket",
            "zendesk_update_ticket",
            "zendesk_search_tickets",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.zendesk.com/api-reference/introduction/security-and-auth/",
        description="Zendesk agent email for API authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See ZENDESK_SUBDOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="zendesk_email",
        credential_key="api_key",
    ),
    "zendesk_token": CredentialSpec(
        env_var="ZENDESK_API_TOKEN",
        tools=[
            "zendesk_list_tickets",
            "zendesk_get_ticket",
            "zendesk_create_ticket",
            "zendesk_update_ticket",
            "zendesk_search_tickets",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.zendesk.com/api-reference/introduction/security-and-auth/",
        description="Zendesk API token for authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See ZENDESK_SUBDOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="zendesk_token",
        credential_key="api_key",
    ),
}
