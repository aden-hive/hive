"""
Intercom tool credentials.

Contains credentials for Intercom customer messaging integration.
"""

from .base import CredentialSpec

INTERCOM_CREDENTIALS = {
    "intercom": CredentialSpec(
        env_var="INTERCOM_ACCESS_TOKEN",
        tools=[
            "intercom_search_conversations",
            "intercom_get_conversation",
            "intercom_get_contact",
            "intercom_search_contacts",
            "intercom_add_note",
            "intercom_add_tag",
            "intercom_assign_conversation",
            "intercom_list_teams",
        ],
        required=True,
        startup_required=False,
        help_url=(
            "https://developers.intercom.com/docs/build-an-integration/learn-more/authentication"
        ),
        description=(
            "Intercom access token (Settings > Integrations"
            " > Developer Hub > Your App > Authentication)"
        ),
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get an Intercom access token:
1. Go to https://app.intercom.com
2. Navigate to Settings > Integrations > Developer Hub
3. Click "New app" (or select an existing app)
4. Go to the "Authentication" tab
5. Copy the access token
6. Required scopes: Read and write conversations, \
Read contacts, Read and write tags, Read admins""",
        # Health check configuration
        health_check_endpoint="https://api.intercom.io/me",
        health_check_method="GET",
        # Credential store mapping
        credential_id="intercom",
        credential_key="access_token",
    ),
}
