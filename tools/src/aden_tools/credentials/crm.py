"""
CRM-related credential specifications.
"""

from .base import CredentialSpec

CRM_CREDENTIALS = {
    "hubspot": CredentialSpec(
        env_var="HUBSPOT_ACCESS_TOKEN",
        tools=[
            "hubspot_health_check",
            "hubspot_webhook_verify",
            "hubspot_webhook_receive",
            "hubspot_register_webhook_subscription",
            "hubspot_list_webhook_subscriptions",
        ],
        description="HubSpot Private App Access Token or OAuth2 Access Token",
        help_url="https://developers.hubspot.com/docs/api/private-apps",
    ),
    "hubspot_webhook_secret": CredentialSpec(
        env_var="HUBSPOT_WEBHOOK_SIGNING_SECRET",
        tools=["hubspot_webhook_verify"],
        required=True,
        description="HubSpot Webhook Signing Secret for payload verification",
        help_url="https://developers.hubspot.com/docs/api/webhooks/validating-requests",
    ),
}
