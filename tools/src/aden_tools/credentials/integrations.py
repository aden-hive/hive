"""
Integration credentials.

Contains credentials for third-party service integrations (HubSpot, etc.).
"""

from .base import CredentialSpec

INTEGRATION_CREDENTIALS = {
    "hubspot": CredentialSpec(
        env_var="HUBSPOT_ACCESS_TOKEN",
        tools=[
            "hubspot_search_contacts",
            "hubspot_get_contact",
            "hubspot_create_contact",
            "hubspot_update_contact",
            "hubspot_search_companies",
            "hubspot_get_company",
            "hubspot_create_company",
            "hubspot_update_company",
            "hubspot_search_deals",
            "hubspot_get_deal",
            "hubspot_create_deal",
            "hubspot_update_deal",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.hubspot.com/docs/api/private-apps",
        description="HubSpot access token (Private App or OAuth2)",
        # Auth method support
        aden_supported=True,
        aden_provider_name="hubspot",
        direct_api_key_supported=True,
        api_key_instructions="""To get a HubSpot Private App token:
1. Go to HubSpot Settings > Integrations > Private Apps
2. Click "Create a private app"
3. Name your app (e.g., "Hive Agent")
4. Go to the "Scopes" tab and enable:
   - crm.objects.contacts.read
   - crm.objects.contacts.write
   - crm.objects.companies.read
   - crm.objects.companies.write
   - crm.objects.deals.read
   - crm.objects.deals.write
5. Click "Create app" and copy the access token""",
        # Health check configuration
        health_check_endpoint="https://api.hubapi.com/crm/v3/objects/contacts?limit=1",
        health_check_method="GET",
        # Credential store mapping
        credential_id="hubspot",
        credential_key="access_token",
    ),
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
