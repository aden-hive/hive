"""
Freshdesk credentials.

Contains credentials for Freshdesk API v2 (tickets, contacts, agents, groups).
Requires FRESHDESK_API_KEY and FRESHDESK_DOMAIN (or credential store equivalents).
"""

from .base import CredentialSpec

# Shared tool coverage for both Freshdesk credentials.
_FRESHDESK_TOOLS = [
    "freshdesk_list_tickets",
    "freshdesk_filter_tickets",
    "freshdesk_list_ticket_conversations",
    "freshdesk_get_ticket",
    "freshdesk_create_ticket",
    "freshdesk_update_ticket",
    "freshdesk_add_ticket_reply",
    "freshdesk_list_contacts",
    "freshdesk_get_contact",
    "freshdesk_create_contact",
    "freshdesk_update_contact",
    "freshdesk_list_agents",
    "freshdesk_get_agent",
    "freshdesk_list_groups",
    "freshdesk_get_group",
    "freshdesk_list_companies",
    "freshdesk_get_company",
]

# Credential specs for Freshdesk API key and domain.
FRESHDESK_CREDENTIALS = {
    # API key used as Basic auth username (`api_key:X`).
    "freshdesk": CredentialSpec(
        env_var="FRESHDESK_API_KEY",
        tools=_FRESHDESK_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://support.freshdesk.com/en/support/solutions/articles/215517-how-to-find-your-api-key",
        description="Freshdesk API key for ticket, contact, agent, and group management",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Freshdesk API key:
1. Log in to Freshdesk
2. Click your profile avatar (top-right) and select Profile Settings
3. Copy the value under 'Your API Key'
4. Set the environment variable:
   export FRESHDESK_API_KEY=your-api-key""",
        health_check_endpoint="",
        credential_id="freshdesk",
        credential_key="api_key",
    ),
    # Freshdesk tenant hostname used to build API base URLs.
    "freshdesk_domain": CredentialSpec(
        env_var="FRESHDESK_DOMAIN",
        tools=_FRESHDESK_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://developers.freshdesk.com/api/#introduction",
        description="Freshdesk hostname (e.g. acme.freshdesk.com). Required with API key.",
        direct_api_key_supported=True,
        api_key_instructions="""Set your Freshdesk hostname:
   export FRESHDESK_DOMAIN=acme.freshdesk.com""",
        health_check_endpoint="",
        credential_id="freshdesk_domain",
        credential_key="domain",
    ),
}
