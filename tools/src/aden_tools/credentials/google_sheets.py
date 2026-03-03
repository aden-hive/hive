"""
Google Sheets credentials.

Contains credentials for Google Sheets spreadsheet access.
Requires GOOGLE_SHEETS_API_KEY for read-only access to public sheets.
"""

from .base import CredentialSpec

GOOGLE_SHEETS_CREDENTIALS = {
    "google_sheets_key": CredentialSpec(
        env_var="GOOGLE_SHEETS_API_KEY",
        tools=[
            "sheets_get_spreadsheet",
            "sheets_read_range",
            "sheets_batch_read",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.cloud.google.com/apis/credentials",
        description="Google API key for reading public Google Sheets",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Google Sheets API access:
1. Go to https://console.cloud.google.com/apis/credentials
2. Click 'Create Credentials' > 'API Key'
3. Enable the Google Sheets API in APIs & Services > Library
4. Target spreadsheets must be shared as 'Anyone with the link'
5. Set environment variable:
   export GOOGLE_SHEETS_API_KEY=your-api-key""",
        health_check_endpoint="",
        credential_id="google_sheets_key",
        credential_key="api_key",
    ),
}
