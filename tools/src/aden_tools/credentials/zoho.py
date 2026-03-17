"""
Zoho CRM tool credentials.

Contains credentials for Zoho CRM integration.
"""

from .base import CredentialSpec

ZOHO_CREDENTIALS = {
    "zoho_crm": CredentialSpec(
        env_var="ZOHO_REFRESH_TOKEN",
        tools=[
            "zoho_crm_search",
            "zoho_crm_get_record",
            "zoho_crm_create_record",
            "zoho_crm_update_record",
            "zoho_crm_add_note",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.zoho.com/crm/developer/docs/api/v2/access-refresh.html",
        description="Zoho CRM OAuth2 credentials (client_id, client_secret, refresh_token)",
        aden_supported=True,
        aden_provider_name="zoho_crm",
        direct_api_key_supported=False,
        api_key_instructions="""Zoho CRM uses OAuth2 (not API keys). To get credentials:

1. Go to https://api-console.zoho.com/
2. Create a Server-based client (or Self Client for testing)
3. Copy Client ID and Client Secret
4. Generate refresh token using OAuth flow (see ZOHO_API_KEY_RETRIEVAL.md)
5. Set environment variables:
   - ZOHO_CLIENT_ID=your_client_id
   - ZOHO_CLIENT_SECRET=your_client_secret
   - ZOHO_REFRESH_TOKEN=your_refresh_token
   - ZOHO_REGION=in (valid: in, us, eu, au, jp, uk, sg — exact codes only).
   Or set ZOHO_ACCOUNTS_DOMAIN=https://accounts.zoho.com (or .in, .eu, etc.) instead of ZOHO_REGION.
""",
        health_check_endpoint="https://www.zohoapis.com/crm/v2/users?type=CurrentUser",
        health_check_method="GET",
        credential_id="zoho_crm",
        credential_key="access_token",
        credential_group="",
    ),
}
