"""
Cal.com tool credentials.

Contains credentials for Cal.com scheduling API integration.
"""

from .base import CredentialSpec

CALCOM_CREDENTIALS = {
    "calcom": CredentialSpec(
        env_var="CALCOM_API_KEY",
        tools=[
            "calcom_list_bookings",
            "calcom_get_booking",
            "calcom_create_booking",
            "calcom_cancel_booking",
            "calcom_get_availability",
            "calcom_update_schedule",
            "calcom_list_schedules",
            "calcom_list_event_types",
            "calcom_get_event_type",
        ],
        required=True,
        startup_required=False,
        help_url="https://cal.com/docs/api-reference/v1",
        description="Cal.com API key for scheduling and booking management",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a Cal.com API key:
1. Log in to Cal.com
2. Go to Settings > Developer > API Keys
3. Click "Create new API key"
4. Give it a name and set expiration
5. Copy the key (shown only once)""",
        # Health check configuration
        health_check_endpoint="https://api.cal.com/v1/me",
        health_check_method="GET",
        # Credential store mapping
        credential_id="calcom",
        credential_key="api_key",
    ),
}
