"""
Google Drive tool credentials.

OAuth 2.0 credentials (access token + refresh token) for Google Drive API.
Enables agents to list, read, upload, download, search, and manage files
in a user's Google Drive.
"""

from .base import CredentialSpec

GOOGLE_DRIVE_CREDENTIALS = {
    "google_drive": CredentialSpec(
        env_var="GOOGLE_DRIVE_ACCESS_TOKEN",
        tools=[
            "drive_list_files",
            "drive_get_file",
            "drive_upload_file",
            "drive_download_file",
            "drive_search_files",
            "drive_create_folder",
            "drive_delete_file",
            "drive_share_file",
            "drive_get_file_metadata",
            "drive_copy_file",
            "drive_move_file",
        ],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="OAuth 2.0 credentials (access token + refresh token) for Google Drive API",
        # Auth method support
        aden_supported=True,
        aden_provider_name="google-drive",
        direct_api_key_supported=False,
        api_key_instructions="""Google Drive requires OAuth 2.0. API keys only work for publicly
shared Drive data; private files require OAuth 2.0. Connect via hive.adenhq.com or:
1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Create a new project or select an existing one
3. Enable the Google Drive API: APIs & Services → Library → "Google Drive API" → Enable
4. Configure OAuth consent screen: APIs & Services → OAuth consent screen
5. Create OAuth 2.0 credentials: APIs & Services → Credentials → OAuth client ID
6. Run the OAuth 2.0 flow to obtain access token and refresh token
7. Set GOOGLE_DRIVE_ACCESS_TOKEN, GOOGLE_DRIVE_REFRESH_TOKEN (and optionally
   GOOGLE_DRIVE_CLIENT_ID, GOOGLE_DRIVE_CLIENT_SECRET for token refresh)""",
        # Health check configuration
        health_check_endpoint="https://www.googleapis.com/drive/v3/about?fields=user",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_drive",
        credential_key="access_token",
    ),
}
