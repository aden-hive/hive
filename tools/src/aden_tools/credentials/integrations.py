"""
Integration credentials.

Contains credentials for third-party service integrations (HubSpot, etc.).
"""

from .base import CredentialSpec

INTEGRATION_CREDENTIALS = {
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
    "trello_api_key": CredentialSpec(
        env_var="TRELLO_API_KEY",
        tools=[
            "trello_list_boards",
            "trello_get_member",
            "trello_list_lists",
            "trello_list_cards",
            "trello_create_card",
            "trello_move_card",
            "trello_update_card",
            "trello_add_comment",
            "trello_add_attachment",
        ],
        required=True,
        startup_required=False,
        help_url="https://trello.com/power-ups/admin",
        description="Trello API key",
        direct_api_key_supported=True,
        api_key_instructions=(
            "To get a Trello API key:\n"
            "1. Go to https://trello.com/power-ups/admin\n"
            "2. Create or open a Power-Up\n"
            "3. Copy the API key shown in the Power-Up admin page\n"
        ),
        credential_id="trello_api_key",
        credential_key="api_key",
    ),
    "trello_api_token": CredentialSpec(
        env_var="TRELLO_API_TOKEN",
        tools=[
            "trello_list_boards",
            "trello_get_member",
            "trello_list_lists",
            "trello_list_cards",
            "trello_create_card",
            "trello_move_card",
            "trello_update_card",
            "trello_add_comment",
            "trello_add_attachment",
        ],
        required=True,
        startup_required=False,
        help_url="https://trello.com/1/authorize",
        description="Trello API token",
        direct_api_key_supported=True,
        api_key_instructions=(
            "To get a Trello API token:\n"
            "1. Ensure you have a Trello API key\n"
            "2. Go to the recently created Power-Up\n"
            "3. Click on API key section\n"
            "4. Click on Token button\n"
            "5. Authorize and copy the token returned by Trello\n"
        ),
        credential_id="trello_api_token",
        credential_key="token",
    ),
}
