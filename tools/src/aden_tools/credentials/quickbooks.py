"""
QuickBooks Online credentials.

Contains credentials for QuickBooks Online Accounting API.
Requires QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID.
"""

from .base import CredentialSpec

QUICKBOOKS_CREDENTIALS = {
    "quickbooks_token": CredentialSpec(
        env_var="QUICKBOOKS_ACCESS_TOKEN",
        tools=[
            "quickbooks_query",
            "quickbooks_get_entity",
            "quickbooks_create_customer",
            "quickbooks_create_invoice",
            "quickbooks_get_company_info",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization",
        description="QuickBooks OAuth 2.0 access token",
        direct_api_key_supported=False,
        api_key_instructions="""To set up QuickBooks API access:
1. Create an app at https://developer.intuit.com
2. Complete OAuth 2.0 authorization flow
3. Set environment variables:
   export QUICKBOOKS_ACCESS_TOKEN=your-oauth-access-token
   export QUICKBOOKS_REALM_ID=your-company-id
   export QUICKBOOKS_SANDBOX=true  # optional, for sandbox""",
        health_check_endpoint="",
        credential_id="quickbooks_token",
        credential_key="api_key",
    ),
    "quickbooks_realm_id": CredentialSpec(
        env_var="QUICKBOOKS_REALM_ID",
        tools=[
            "quickbooks_query",
            "quickbooks_get_entity",
            "quickbooks_create_customer",
            "quickbooks_create_invoice",
            "quickbooks_get_company_info",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization",
        description="QuickBooks company (realm) ID",
        direct_api_key_supported=True,
        api_key_instructions="""See QUICKBOOKS_ACCESS_TOKEN instructions above.""",
        health_check_endpoint="",
        credential_id="quickbooks_realm_id",
        credential_key="api_key",
    ),
}
