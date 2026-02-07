"""
Calendly tool credentials.

Contains credentials for Calendly scheduling integration.
"""

from .base import CredentialSpec

CALENDLY_CREDENTIALS = {
    "calendly": CredentialSpec(
        env_var="CALENDLY_API_TOKEN",
        tools=[
            "calendly_list_event_types",
            "calendly_get_availability",
            "calendly_get_booking_link",
            "calendly_cancel_event",
        ],
        required=True,
        startup_required=False,
        help_url="https://calendly.com/integrations/api_webhooks",
        description="Calendly Personal Access Token",
        direct_api_key_supported=True,
        health_check_endpoint="https://api.calendly.com/users/me",
        health_check_method="GET",
        api_key_instructions="""To get a Calendly API token:
1. Go to https://calendly.com/integrations/api_webhooks
2. Click "Create Token" or "Generate new token"
3. Give it a name and copy the token
4. Set CALENDLY_API_TOKEN environment variable""",
        credential_id="calendly",
        credential_key="access_token",
    ),
}
