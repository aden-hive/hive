"""
Google Calendar tool credentials.

Contains credentials for Google Calendar integration.
"""

from .base import CredentialSpec

GOOGLE_CALENDAR_CREDENTIALS = {
    "google_calendar_oauth": CredentialSpec(
        env_var="GOOGLE_CALENDAR_OAUTH_TOKEN",
        tools=[
            "calendar_list_events",
            "calendar_get_event",
            "calendar_create_event",
            "calendar_update_event",
            "calendar_delete_event",
            "calendar_list_calendars",
            "calendar_get_calendar",
            "calendar_check_availability",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="Google Calendar OAuth2 credentials (via Aden or direct setup)",
        # Auth method support
        aden_supported=True,
        aden_provider_name="google-calendar",
        direct_api_key_supported=False,
        api_key_instructions=(
            "To set up Google Calendar credentials directly:\n"
            "1. Go to https://developers.google.com/oauthplayground/\n"
            "2. Select 'Google Calendar API v3' scopes\n"
            "3. Authorize and get an access token\n"
            "4. Set GOOGLE_CALENDAR_OAUTH_TOKEN environment variable\n"
            "Note: Tokens expire after ~1 hour. Use Aden OAuth for auto-refresh."
        ),
        # Credential store mapping
        credential_id="google_calendar_oauth",
        credential_key="access_token",
    ),
}
