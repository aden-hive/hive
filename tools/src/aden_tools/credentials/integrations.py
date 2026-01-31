"""
Integration credentials.

Contains credentials for third-party service integrations (HubSpot, Salesforce, etc.).
"""

from .base import CredentialSpec

INTEGRATION_CREDENTIALS = {
    "salesforce": CredentialSpec(
        env_var="SALESFORCE_ACCESS_TOKEN",
        tools=[
            "salesforce_search_leads",
            "salesforce_get_lead",
            "salesforce_create_lead",
            "salesforce_update_lead",
            "salesforce_search_contacts",
            "salesforce_get_contact",
            "salesforce_create_contact",
            "salesforce_update_contact",
            "salesforce_search_accounts",
            "salesforce_get_account",
            "salesforce_create_account",
            "salesforce_update_account",
            "salesforce_search_opportunities",
            "salesforce_get_opportunity",
            "salesforce_create_opportunity",
            "salesforce_update_opportunity",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/",
        description="Salesforce instance URL + access token (Connected App or OAuth2)",
        aden_supported=False,
        aden_provider_name="",
        direct_api_key_supported=True,
        api_key_instructions="""To get Salesforce access:
1. Create a Connected App in Salesforce Setup > App Manager
2. Enable OAuth and set callback URL; request scopes: api, refresh_token
3. Use OAuth2 flow to get access_token and instance_url (e.g. https://yourdomain.my.salesforce.com)
4. Set SALESFORCE_INSTANCE_URL and SALESFORCE_ACCESS_TOKEN""",
        health_check_endpoint="",
        health_check_method="GET",
        credential_id="salesforce",
        credential_key="access_token",
    ),
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
}
