"""
Google Calendar tool credentials.

Contains credentials for Google Calendar integration.
"""

from .base import CredentialSpec

GOOGLE_CALENDAR_CREDENTIALS = {
    "google_calendar_oauth": CredentialSpec(
        env_var="GOOGLE_CALENDAR_ACCESS_TOKEN",
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
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://hive.adenhq.com",
        description="Google Calendar OAuth2 access token (via Aden) - used for Google Calendar",
        # Auth method support
        aden_supported=True,
        aden_provider_name="google-calendar",
        direct_api_key_supported=False,
        api_key_instructions="Google Calendar OAuth requires OAuth2. Connect via hive.adenhq.com",
        # Health check configuration
        health_check_endpoint="https://www.googleapis.com/calendar/v3/users/me/calendarList",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_calendar_oauth",
        credential_key="access_token",
    ),
}
