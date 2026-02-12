"""
Salesforce tool credentials.

Contains credentials for Salesforce CRM integration.
"""

from .base import CredentialSpec

SALESFORCE_CREDENTIALS = {
    "salesforce": CredentialSpec(
        env_var="SALESFORCE_ACCESS_TOKEN",
        tools=[
            "salesforce_search_objects",
            "salesforce_get_object",
            "salesforce_create_object",
            "salesforce_update_object",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/intro_what_is_rest_api.htm",
        description="Salesforce access token and instance URL",
        # Auth method support
        aden_supported=True,
        aden_provider_name="salesforce",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Salesforce Access Token:
1. Log in to Salesforce
2. Go to Setup > Apps > App Manager
3. Create a "New Connected App"
4. Enable OAuth Settings and add required scopes (e.g., api, refresh_token)
5. Use the Client ID and Secret to generate an access token via OAuth2 flow.
6. Alternatively, use a personal security token or session ID for testing.""",
        # Health check configuration (requires instance URL which is handled in the tool)
        health_check_endpoint="https://login.salesforce.com/services/oauth2/token",
        health_check_method="POST",
        # Credential store mapping
        credential_id="salesforce",
        credential_key="access_token",
    ),
}
