"""
Stripe API credentials for payment processing and billing.
"""

from .base import CredentialSpec

STRIPE_CREDENTIALS = {
    "stripe_api_key": CredentialSpec(
        env_var="STRIPE_API_KEY",
    ),
    "stripe_webhook_secret": CredentialSpec(
        env_var="STRIPE_WEBHOOK_SECRET",
    ),
}

__all__ = ["STRIPE_CREDENTIALS"]
