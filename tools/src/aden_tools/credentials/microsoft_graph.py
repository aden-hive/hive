"""
Microsoft Graph API credentials.

Contains credentials for Microsoft 365 services (Outlook, Teams, OneDrive).
"""

from .base import CredentialSpec

MICROSOFT_GRAPH_CREDENTIALS = {
    "microsoft_graph": CredentialSpec(
        env_var="MICROSOFT_GRAPH_ACCESS_TOKEN",
        tools=[
            # Outlook mail (from microsoft_graph_tool)
            "outlook_list_messages",
            "outlook_get_message",
            "outlook_send_mail",
            # Outlook-specific features (categories, focused inbox, drafts, batch)
            "outlook_list_categories",
            "outlook_set_category",
            "outlook_create_category",
            "outlook_get_focused_inbox",
            "outlook_create_draft",
            "outlook_batch_get_messages",
            # Teams
            "teams_list_teams",
            "teams_list_channels",
            "teams_send_channel_message",
            "teams_get_channel_messages",
            # OneDrive
            "onedrive_search_files",
            "onedrive_list_files",
            "onedrive_download_file",
            "onedrive_upload_file",
        ],
        required=True,
        startup_required=False,
        help_url="https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade",
        description="Microsoft Graph OAuth 2.0 access token for Outlook, Teams, and OneDrive",
        aden_supported=True,
        aden_provider_name="microsoft",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Microsoft Graph access token:
1. Go to https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade
2. Register a new application (or select existing)
3. Under API Permissions, add Microsoft Graph permissions:
   - Mail.Read, Mail.Send (for Outlook)
   - ChannelMessage.Read.All, ChannelMessage.Send (for Teams)
   - Files.ReadWrite (for OneDrive)
4. Configure Authentication with redirect URI
5. Get client ID and client secret from Certificates & Secrets
6. Use OAuth 2.0 authorization code flow to obtain access token
7. For quick testing, use https://developer.microsoft.com/en-us/graph/graph-explorer""",
        health_check_endpoint="https://graph.microsoft.com/v1.0/me",
        credential_id="microsoft_graph",
        credential_key="access_token",
    ),
}
