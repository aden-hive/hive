"""
Razorpay tool credentials.

Contains credentials for Razorpay payments integration.
"""

from .base import CredentialSpec

RAZORPAY_CREDENTIALS = {
    "razorpay": CredentialSpec(
        env_var="RAZORPAY_API_KEY",
        tools=[
            "razorpay_list_payments",
            "razorpay_get_payment",
            "razorpay_create_payment_link",
            "razorpay_list_invoices",
            "razorpay_get_invoice",
            "razorpay_create_refund",
        ],
        required=True,
        startup_required=False,
        help_url="https://razorpay.com/docs/api/authentication",
        description="Razorpay API Key ID (used with API Secret for HTTP Basic auth)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get Razorpay API credentials:
1. Log in to the Razorpay Dashboard at https://dashboard.razorpay.com
2. Navigate to Settings → API Keys
3. Click "Generate Key" (or use existing test/live key)
4. Copy the Key ID and Key Secret

Note: Use test keys (rzp_test_*) for development""",
        # Health check configuration
        health_check_endpoint="https://api.razorpay.com/v1/payments?count=1",
        health_check_method="GET",
        # Credential store mapping
        credential_id="razorpay",
        credential_key="api_key",
        credential_group="razorpay",
    ),
    "razorpay_secret": CredentialSpec(
        env_var="RAZORPAY_API_SECRET",
        tools=[
            "razorpay_list_payments",
            "razorpay_get_payment",
            "razorpay_create_payment_link",
            "razorpay_list_invoices",
            "razorpay_get_invoice",
            "razorpay_create_refund",
        ],
        required=True,
        startup_required=False,
        help_url="https://razorpay.com/docs/api/authentication",
        description="Razorpay API Secret (used with API Key for HTTP Basic auth)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get Razorpay API credentials:
1. Log in to the Razorpay Dashboard at https://dashboard.razorpay.com
2. Navigate to Settings → API Keys
3. Click "Generate Key" (or use existing test/live key)
4. Copy the Key ID and Key Secret

Note: Use test keys (rzp_test_*) for development""",
        # Health check configuration
        health_check_endpoint="https://api.razorpay.com/v1/payments?count=1",
        health_check_method="GET",
        # Credential store mapping
        credential_id="razorpay_secret",
        credential_key="api_secret",
        credential_group="razorpay",
    ),
}
