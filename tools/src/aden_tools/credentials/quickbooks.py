"""
QuickBooks credentials.

Setup Instructions:
1. Create a developer account at https://developer.intuit.com/
2. Create a "New App" and select "QuickBooks Online and Payments" 
3. Under "Keys & OAuth", find your "Client ID" and "Client Secret"
4. Add a Redirect URI (e.g. http://localhost)
5. Use the OAuth Playground (https://developer.intuit.com/app/developer/playground) to generate an initial Access Token and Realm ID.
6. Select the scope 'com.intuit.quickbooks.accounting'
7. Copy the Access Token and Realm ID to your .env file as QUICKBOOKS_ACCESS_TOKEN and QUICKBOOKS_REALM_ID.
"""

from .base import CredentialSpec

QUICKBOOK_CREDENTIALS = {
    "quickbooks_access_token": CredentialSpec(
        env_var="QUICKBOOKS_ACCESS_TOKEN",
        tools=[
            "quickbooks_create_invoice",
            "quickbooks_get_invoice",
            "quickbooks_search_customers",
            "quickbooks_create_customer",
            "quickbooks_record_payment",
            "quickbooks_create_expense",
        ],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://developer.intuit.com/app/developer/qbo/docs/develop/authentication-and-authorization",
        description="OAuth 2.0 Access Token for QuickBooks Online API",
    ),
    "quickbooks_realm_id": CredentialSpec(
        env_var="QUICKBOOKS_REALM_ID",
        tools=[
            "quickbooks_create_invoice",
            "quickbooks_get_invoice",
            "quickbooks_search_customers",
            "quickbooks_create_customer",
            "quickbooks_record_payment",
            "quickbooks_create_expense",
        ],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://developer.intuit.com/app/developer/qbo/docs/get-started/get-company-id",
        description="QuickBooks Realm ID (Company ID)",
    ),
}