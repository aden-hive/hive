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
            "get_customer_by_email",
            "get_subscription_status",
            "create_payment_link"
        ],
        description="Your Stripe Secret Key (starts with sk_live_ or sk_test_).",
        help_url="https://dashboard.stripe.com/apikeys",
        required=True
    )
}