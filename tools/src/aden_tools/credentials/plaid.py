"""
Plaid credentials.

Contains credentials for Plaid banking & financial data operations.
Plaid requires both PLAID_CLIENT_ID and PLAID_SECRET.
"""

from .base import CredentialSpec

PLAID_CREDENTIALS = {
    "plaid_client_id": CredentialSpec(
        env_var="PLAID_CLIENT_ID",
        tools=[
            "plaid_get_accounts",
            "plaid_get_balance",
            "plaid_sync_transactions",
            "plaid_get_transactions",
            "plaid_get_institution",
            "plaid_search_institutions",
        ],
        required=True,
        startup_required=False,
        help_url="https://dashboard.plaid.com/developers/keys",
        description=(
            "Plaid client ID for banking data access"
            " (also set PLAID_SECRET and optionally PLAID_ENV)"
        ),
        direct_api_key_supported=True,
        api_key_instructions="""To get Plaid credentials:
1. Sign up at https://dashboard.plaid.com/
2. Go to Developers > Keys
3. Copy your client_id and secret
4. Set environment variables:
   export PLAID_CLIENT_ID=your-client-id
   export PLAID_SECRET=your-secret
   export PLAID_ENV=sandbox  (or development, production)""",
        health_check_endpoint="https://sandbox.plaid.com/institutions/search",
        credential_id="plaid_client_id",
        credential_key="api_key",
    ),
    "plaid_secret": CredentialSpec(
        env_var="PLAID_SECRET",
        tools=[
            "plaid_get_accounts",
            "plaid_get_balance",
            "plaid_sync_transactions",
            "plaid_get_transactions",
            "plaid_get_institution",
            "plaid_search_institutions",
        ],
        required=True,
        startup_required=False,
        help_url="https://dashboard.plaid.com/developers/keys",
        description="Plaid API secret for banking data access",
        direct_api_key_supported=True,
        api_key_instructions="""See PLAID_CLIENT_ID instructions above.""",
        health_check_endpoint="https://sandbox.plaid.com/institutions/search",
        credential_id="plaid_secret",
        credential_key="api_key",
    ),
}
