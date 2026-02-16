"""
Stripe API credentials for payment processing and billing.
"""
from .base import CredentialSpec

STRIPE_CREDENTIALS = {
    "stripe_api_key": CredentialSpec(
        env_var="STRIPE_API_KEY",
        credential_id="stripe_api_key",
        credential_key="api_key",
        description="Stripe Secret API Key (starts with sk_...)",
        help_url="https://dashboard.stripe.com/apikeys",
        api_key_instructions=(
            "1. Log in to your Stripe Dashboard.\n"
            "2. Go to Developers > API keys.\n"
            "3. Copy the Secret key (sk_test_... or sk_live_...)."
        ),
        direct_api_key_supported=True,
        tools=[
            "stripe_create_customer",
            "stripe_get_customer_by_email",
            "stripe_get_customer_by_id",
            "stripe_update_customer",
            "stripe_list_customers",
            "stripe_create_subscription",
            "stripe_get_subscription_status",
            "stripe_cancel_subscription",
            "stripe_list_subscriptions",
            "stripe_create_invoice",
            "stripe_list_invoices",
            "stripe_pay_invoice",
            "stripe_create_payment_link",
            "stripe_create_checkout_session",
            "stripe_create_product",
            "stripe_create_price",
            "stripe_list_products",
            "stripe_create_refund",
        ],
    ),
    "stripe_webhook_secret": CredentialSpec(
        env_var="STRIPE_WEBHOOK_SECRET",
        credential_id="stripe_webhook_secret",
        credential_key="webhook_secret",
        description="Stripe Webhook Signing Secret (starts with whsec_...)",
        help_url="https://dashboard.stripe.com/webhooks",
        api_key_instructions=(
            "1. Go to Developers > Webhooks in Stripe Dashboard.\n"
            "2. Click 'Add endpoint' or select an existing one.\n"
            "3. Click 'Reveal' under Signing secret."
        ),
        direct_api_key_supported=True,
        tools=[
            "stripe_verify_webhook_signature"
        ],
    ),
}

__all__ = ["STRIPE_CREDENTIALS"]