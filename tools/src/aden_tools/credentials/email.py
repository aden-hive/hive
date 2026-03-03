"""
Email tool credentials.

Contains credentials for email providers like Resend, SendGrid, etc.
"""

from .base import CredentialSpec

EMAIL_CREDENTIALS = {
    "resend": CredentialSpec(
        env_var="RESEND_API_KEY",
        tools=["send_email"],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://resend.com/api-keys",
        description="API key for Resend email service",
        # Auth method support
        direct_api_key_supported=True,
        api_key_instructions="""To get a Resend API key:
1. Go to https://resend.com and create an account (or sign in)
2. Navigate to API Keys in the dashboard
3. Click "Create API Key"
4. Give it a name (e.g., "Hive Agent") and choose permissions:
   - "Sending access" is sufficient for most use cases
   - "Full access" if you also need to manage domains
5. Copy the API key (starts with re_)
6. Store it securely - you won't be able to see it again!
7. Note: You'll also need to verify a domain to send emails from custom addresses""",
        # Health check configuration
        health_check_endpoint="https://api.resend.com/domains",
        # Credential store mapping
        credential_id="resend",
        credential_key="api_key",
    ),
    "google": CredentialSpec(
        env_var="GOOGLE_ACCESS_TOKEN",
        tools=[
            # send_email is excluded: it's a multi-provider tool that checks
            # credentials at runtime based on the provider parameter.
            # Gmail tools
            "gmail_reply_email",
            "gmail_list_messages",
            "gmail_get_message",
            "gmail_trash_message",
            "gmail_modify_message",
            "gmail_batch_modify_messages",
            "gmail_batch_get_messages",
            # Google Calendar tools
            "calendar_list_events",
            "calendar_get_event",
            "calendar_create_event",
            "calendar_update_event",
            "calendar_delete_event",
            "calendar_list_calendars",
            "calendar_get_calendar",
            "calendar_check_availability",
            # Google Sheets tools
            "google_sheets_get_spreadsheet",
            "google_sheets_create_spreadsheet",
            "google_sheets_get_values",
            "google_sheets_update_values",
            "google_sheets_append_values",
            "google_sheets_clear_values",
            "google_sheets_batch_update_values",
            "google_sheets_batch_clear_values",
            "google_sheets_add_sheet",
            "google_sheets_delete_sheet",
        ],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://hive.adenhq.com",
        description="Google OAuth2 access token (via Aden) - used for Gmail, Calendar, and Sheets",
        aden_supported=True,
        aden_provider_name="google",
        direct_api_key_supported=False,
        api_key_instructions="Google OAuth requires OAuth2. Connect via hive.adenhq.com",
        health_check_endpoint="https://gmail.googleapis.com/gmail/v1/users/me/profile",
        health_check_method="GET",
        credential_id="google",
        credential_key="access_token",
    ),
}
