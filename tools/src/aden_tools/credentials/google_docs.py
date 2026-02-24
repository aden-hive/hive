"""
Google Docs tool credentials.

Contains credentials for Google Docs API integration.
"""

from .base import CredentialSpec

GOOGLE_DOCS_CREDENTIALS = {
    "google_docs": CredentialSpec(
        env_var="GOOGLE_DOCS_ACCESS_TOKEN",
        tools=[
            "google_docs_create_document",
            "google_docs_get_document",
            "google_docs_insert_text",
            "google_docs_replace_all_text",
            "google_docs_insert_image",
            "google_docs_format_text",
            "google_docs_batch_update",
            "google_docs_create_list",
            "google_docs_add_comment",
            "google_docs_list_comments",
            "google_docs_export_content",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="Google Docs OAuth2 access token",
        # Auth method support
        aden_supported=True,
        aden_provider_name="google",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Google Docs access token:
1. Go to Google Cloud Console: https://console.cloud.google.com/
2. Create a new project or select an existing one
3. Enable the Google Docs API and Google Drive API
4. Go to APIs & Services > Credentials
5. Create OAuth 2.0 credentials (Web application or Desktop app)
6. Use the OAuth 2.0 Playground or your app to get an access token
7. Required scopes:
   - https://www.googleapis.com/auth/documents
   - https://www.googleapis.com/auth/drive.file
   - https://www.googleapis.com/auth/drive (for export/comments)""",
        # Health check configuration
        health_check_endpoint="https://docs.googleapis.com/v1/documents/1",
        health_check_method="GET",
        # Credential store mapping
        credential_id="google_docs",
        credential_key="access_token",
    ),
}
