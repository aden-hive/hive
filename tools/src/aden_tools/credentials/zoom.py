from .base import CredentialSpec

ZOOM_CREDENTIALS = {
    "ZOOM_ACCOUNT_ID": CredentialSpec(
        env_var="ZOOM_ACCOUNT_ID",
        description="Zoom Account ID (Server-to-Server OAuth)",
        required=True,
        tools=["create_meeting", "list_upcoming_meetings", "get_meeting_details", "update_meeting", "delete_meeting", "get_meeting_transcript"],
    ),
    "ZOOM_CLIENT_ID": CredentialSpec(
        env_var="ZOOM_CLIENT_ID",
        description="Zoom App Client ID",
        required=True,
        tools=["create_meeting", "list_upcoming_meetings", "get_meeting_details", "update_meeting", "delete_meeting", "get_meeting_transcript"],
    ),
    "ZOOM_CLIENT_SECRET": CredentialSpec(
        env_var="ZOOM_CLIENT_SECRET",
        description="Zoom App Client Secret",
        required=True,
        # 'sensitive' field does not exist in base.py, handled by env var nature
        tools=["create_meeting", "list_upcoming_meetings", "get_meeting_details", "update_meeting", "delete_meeting", "get_meeting_transcript"],
    ),
    "ZOOM_USER_EMAIL": CredentialSpec(
        env_var="ZOOM_USER_EMAIL",
        description="Default host email for scheduling meetings",
        required=False,
        tools=["create_meeting", "list_upcoming_meetings", "get_meeting_details", "update_meeting", "delete_meeting", "get_meeting_transcript"],
    ),
}