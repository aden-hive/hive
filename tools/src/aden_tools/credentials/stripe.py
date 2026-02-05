"""
Stripe credentials definition.
"""
from .base import CredentialSpec

# Must be a Dictionary, not a List
STRIPE_CREDENTIALS = {
    "stripe": CredentialSpec(
        env_var="STRIPE_API_KEY",
        # Explicitly list the functions that need this key
        tools=[
            # Existing
            "get_customer_by_email",
            "get_subscription_status",
            "create_payment_link",
            
            # New: Customer Management
            "create_customer",
            "update_customer",
            "list_customers",
            "get_customer_by_id",
            
            # New: Subscriptions
            "create_subscription",
            "update_subscription",
            "cancel_subscription",
            "list_subscriptions",
            
            # New: Invoices & Payments
            "list_invoices",
            "retrieve_invoice",
            "pay_invoice",
            "list_payment_intents",
            
            # New: Checkout & Webhooks
            "create_checkout_session",
            "verify_webhook_signature"
        ],
        description="Your Stripe Secret Key (starts with sk_live_ or sk_test_).",
        help_url="https://dashboard.stripe.com/apikeys",
        required=True
    )
}