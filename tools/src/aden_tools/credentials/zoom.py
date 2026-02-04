"""
Zoom credentials definition.
"""
from .base import CredentialSpec

ZOOM_CREDENTIALS = {
    "zoom_account_id": CredentialSpec(
        env_var="ZOOM_ACCOUNT_ID",
        tools=["create_meeting", "list_meetings", "get_meeting_details"],
        description="Zoom Account ID (from App Marketplace)",
        required=True
    ),
    "zoom_client_id": CredentialSpec(
        env_var="ZOOM_CLIENT_ID",
        tools=["create_meeting", "list_meetings", "get_meeting_details"],
        description="Zoom Client ID (from App Marketplace)",
        required=True
    ),
    "zoom_client_secret": CredentialSpec(
        env_var="ZOOM_CLIENT_SECRET",
        tools=["create_meeting", "list_meetings", "get_meeting_details"],
        description="Zoom Client Secret",
        required=True
    )
}