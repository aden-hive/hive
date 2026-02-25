"""
Google Drive tool credentials.
Contains credentials for Google Drive API integration.
"""

from .base import CredentialSpec

GOOGLE_DRIVE_CREDENTIALS = {
    "google_drive": CredentialSpec(
        env_var="GOOGLE_DRIVE_REFRESH_TOKEN",
        tools=[
            "google_drive_create_folder",
            "google_drive_upload_file",
            "google_drive_update_permissions",
            "google_drive_share_file_link",
            "google_drive_list_files",
            "google_drive_move_file",
            "google_drive_empty_trash",
            "google_drive_delete_file",
            "google_drive_download_file",
            "google_drive_search_file"
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="Google Drive OAuth2 access token",
        # Auth method support
        aden_supported=True,
        aden_provider_name="google",
        direct_api_key_supported=False,
        api_key_instructions="""To get a Google Drive access token:
        1. Access the Google Cloud Console.
        2. Create or select a project and Enable the Google Drive API.
        3. Configure your OAuth Consent Screen (internal or external).
        4. Navigate to Credentials > Create Credentials > OAuth client ID.
        5. Set Application Type to Web Application and add your redirect URIs.
        6. Use the resulting Client ID and Secret to perform the initial OAuth
           flow and generate a Refresh Token.
        7. Required scopes:
            - https://www.googleapis.com/auth/drive.file
            - https://www.googleapis.com/auth/drive
            - https://www.googleapis.com/auth/drive.appdata""",
        # Health check configuration
        health_check_endpoint="https://www.googleapis.com/drive/v3/about",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_drive",
        credential_key="access_token",
    ),
}
