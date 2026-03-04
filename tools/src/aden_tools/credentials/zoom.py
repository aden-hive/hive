"""
Zoom meeting management credentials.

Contains credentials for the Zoom REST API v2.
Requires ZOOM_ACCESS_TOKEN (Server-to-Server OAuth Bearer token).
"""

from .base import CredentialSpec

ZOOM_CREDENTIALS = {
    "zoom": CredentialSpec(
        env_var="ZOOM_ACCESS_TOKEN",
        tools=[
            "zoom_get_user",
            "zoom_list_meetings",
            "zoom_get_meeting",
            "zoom_create_meeting",
            "zoom_delete_meeting",
            "zoom_list_recordings",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.zoom.us/docs/internal-apps/s2s-oauth/",
        description="Zoom Server-to-Server OAuth access token",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Zoom API access:
1. Go to Zoom App Marketplace and create a Server-to-Server OAuth app
2. Add required scopes: user:read, meeting:read, meeting:write, recording:read
3. Generate a token using account_credentials grant type
4. Set environment variable:
   export ZOOM_ACCESS_TOKEN=your-bearer-token""",
        health_check_endpoint="",
        credential_id="zoom",
        credential_key="api_key",
    ),
}
