"""
Stripe API credentials for payment processing and billing.
"""

from .base import CredentialSpec

STRIPE_CREDENTIALS = {
    "stripe_api_key": CredentialSpec(
        env_var="STRIPE_API_KEY",
        tools=[
            "stripe_create_customer",
            "stripe_get_customer_by_email",
            "stripe_get_customer_by_id",
            "stripe_update_customer",
            "stripe_list_customers",
            "stripe_delete_customer",
            "stripe_create_subscription",
            "stripe_get_subscription_status",
            "stripe_update_subscription",
            "stripe_cancel_subscription",
            "stripe_pause_subscription",
            "stripe_resume_subscription",
            "stripe_list_subscriptions",
            "stripe_create_invoice",
            "stripe_get_invoice",
            "stripe_list_invoices",
            "stripe_pay_invoice",
            "stripe_void_invoice",
            "stripe_finalize_invoice",
            "stripe_attach_payment_method",
            "stripe_detach_payment_method",
            "stripe_list_payment_methods",
            "stripe_set_default_payment_method",
            "stripe_create_payment_intent",
            "stripe_confirm_payment_intent",
            "stripe_cancel_payment_intent",
            "stripe_capture_payment_intent",
            "stripe_list_payment_intents",
            "stripe_create_checkout_session",
            "stripe_get_checkout_session",
            "stripe_expire_checkout_session",
            "stripe_create_payment_link",
            "stripe_create_product",
            "stripe_get_product",
            "stripe_update_product",
            "stripe_list_products",
            "stripe_archive_product",
            "stripe_create_price",
            "stripe_get_price",
            "stripe_list_prices",
            "stripe_create_refund",
            "stripe_get_refund",
            "stripe_list_refunds",
            "stripe_cancel_refund",
        ],
        help_url="https://dashboard.stripe.com/apikeys",
        description="Stripe secret API key for payment processing (sk_test_... or sk_live_...)",
        credential_id="stripe",
        direct_api_key_supported=True,
        api_key_instructions="""To get your Stripe API key:
1. Go to https://dashboard.stripe.com/apikeys
2. Sign in to your Stripe account
3. For development: Copy the test mode Secret key (starts with sk_test_)
4. For production: Copy the live mode Secret key (starts with sk_live_)
5. Set STRIPE_API_KEY environment variable

⚠️ Use TEST keys for development (no real charges)
⚠️ Use LIVE keys only in production (processes real payments)""",
    ),
    "stripe_webhook_secret": CredentialSpec(
        env_var="STRIPE_WEBHOOK_SECRET",
        tools=["stripe_verify_webhook_signature"],
        help_url="https://dashboard.stripe.com/webhooks",
        description="Stripe webhook signing secret for verifying webhook signatures (whsec_...)",
        credential_id="stripe",
        direct_api_key_supported=True,
        api_key_instructions="""To get your Stripe Webhook Secret (optional):
1. Go to https://dashboard.stripe.com/webhooks
2. Create or select a webhook endpoint
3. Copy the Signing secret (starts with whsec_)
4. Set STRIPE_WEBHOOK_SECRET environment variable

This is only needed if you're using webhooks to receive Stripe events.""",
        required=False,
    ),
}

__all__ = ["STRIPE_CREDENTIALS"]
