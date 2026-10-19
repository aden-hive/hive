"""
Zoho CRM credentials.

Contains credentials for Zoho CRM module management.
"""

from .base import CredentialSpec

ZOHO_CRM_CREDENTIALS = {
    "zoho_crm": CredentialSpec(
        env_var="ZOHO_CRM_ACCESS_TOKEN",
        tools=[
            "zoho_crm_list_records",
            "zoho_crm_get_record",
            "zoho_crm_create_record",
            "zoho_crm_search_records",
            "zoho_crm_list_modules",
            "zoho_crm_add_note",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.zoho.com/crm/developer/docs/api/v7/",
        description="Zoho CRM OAuth access token (also set ZOHO_CRM_DOMAIN for non-US regions)",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Zoho CRM access token:
1. Go to https://api-console.zoho.com/
2. Create a Self Client
3. Generate an access token with scope: ZohoCRM.modules.ALL
4. Set environment variables:
   export ZOHO_CRM_ACCESS_TOKEN=your-access-token
   export ZOHO_CRM_DOMAIN=www.zohoapis.com  (or .eu, .in, .com.au, .jp)""",
        health_check_endpoint="https://www.zohoapis.com/crm/v7/users?type=CurrentUser",
        credential_id="zoho_crm",
        credential_key="api_key",
    ),
}
