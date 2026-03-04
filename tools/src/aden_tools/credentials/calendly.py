"""
Calendly credentials.

Contains credentials for the Calendly API v2.
Requires CALENDLY_PAT (Personal Access Token).
"""

from .base import CredentialSpec

CALENDLY_CREDENTIALS = {
    "calendly_pat": CredentialSpec(
        env_var="CALENDLY_PAT",
        tools=[
            "calendly_get_current_user",
            "calendly_list_event_types",
            "calendly_list_scheduled_events",
            "calendly_get_scheduled_event",
            "calendly_list_invitees",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.calendly.com/how-to-authenticate-with-personal-access-tokens",
        description="Calendly Personal Access Token",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Calendly API access:
1. Go to https://calendly.com/integrations/api_webhooks
2. Generate a Personal Access Token
3. Set environment variable:
   export CALENDLY_PAT=your-personal-access-token""",
        health_check_endpoint="https://api.calendly.com/users/me",
        credential_id="calendly_pat",
        credential_key="api_key",
    ),
}
