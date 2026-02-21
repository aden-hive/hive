"""
Stripe tool credentials.
Contains credentials for Stripe payments integration.
"""

from .base import CredentialSpec

STRIPE_CREDENTIALS = {
    "stripe": CredentialSpec(
        env_var="STRIPE_API_KEY",
        tools=[
            "stripe_create_customer",
            "stripe_get_customer",
            "stripe_get_customer_by_email",
            "stripe_update_customer",
            "stripe_list_customers",
            "stripe_get_subscription",
            "stripe_get_subscription_status",
            "stripe_list_subscriptions",
            "stripe_create_subscription",
            "stripe_update_subscription",
            "stripe_cancel_subscription",
            "stripe_create_payment_intent",
            "stripe_get_payment_intent",
            "stripe_confirm_payment_intent",
            "stripe_cancel_payment_intent",
            "stripe_list_payment_intents",
            "stripe_list_charges",
            "stripe_get_charge",
            "stripe_capture_charge",
            "stripe_create_refund",
            "stripe_get_refund",
            "stripe_list_refunds",
            "stripe_list_invoices",
            "stripe_get_invoice",
            "stripe_create_invoice",
            "stripe_finalize_invoice",
            "stripe_pay_invoice",
            "stripe_void_invoice",
            "stripe_create_invoice_item",
            "stripe_list_invoice_items",
            "stripe_delete_invoice_item",
            "stripe_create_product",
            "stripe_get_product",
            "stripe_list_products",
            "stripe_update_product",
            "stripe_create_price",
            "stripe_get_price",
            "stripe_list_prices",
            "stripe_update_price",
            "stripe_create_payment_link",
            "stripe_get_payment_link",
            "stripe_list_payment_links",
            "stripe_create_coupon",
            "stripe_list_coupons",
            "stripe_delete_coupon",
            "stripe_get_balance",
            "stripe_list_balance_transactions",
            "stripe_list_webhook_endpoints",
            "stripe_list_payment_methods",
            "stripe_get_payment_method",
            "stripe_detach_payment_method",
        ],
        required=True,
        startup_required=False,
        help_url="https://stripe.com/docs/keys",
        description="Stripe Secret API Key for authenticating all API requests",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get your Stripe API key:
1. Log in to the Stripe Dashboard at https://dashboard.stripe.com
2. Navigate to Developers -> API keys
3. Copy the Secret key (starts with sk_test_ for test mode or sk_live_ for live mode)
Note: Use test keys (sk_test_*) for development to avoid real charges""",
        # Health check configuration
        health_check_endpoint="https://api.stripe.com/v1/balance",
        health_check_method="GET",
        # Credential store mapping
        credential_id="stripe",
        credential_key="api_key",
        credential_group="",
    ),
}
