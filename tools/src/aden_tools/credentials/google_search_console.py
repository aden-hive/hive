"""
Google Search Console credentials.

Contains credentials for Search Console analytics, sitemaps, and URL inspection.
"""

from .base import CredentialSpec

GOOGLE_SEARCH_CONSOLE_CREDENTIALS = {
    "google_search_console": CredentialSpec(
        env_var="GOOGLE_SEARCH_CONSOLE_TOKEN",
        tools=[
            "gsc_search_analytics",
            "gsc_list_sites",
            "gsc_list_sitemaps",
            "gsc_inspect_url",
            "gsc_submit_sitemap",
            "gsc_top_queries",
            "gsc_top_pages",
            "gsc_delete_sitemap",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.google.com/webmaster-tools/v1/prereqs",
        description="Google OAuth2 access token with Search Console scope",
        direct_api_key_supported=False,
        api_key_instructions="""To get a Google Search Console access token:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create an OAuth2 client (type: Desktop app or Web app)
3. Enable the Search Console API in your project
4. Generate an access token with scope: https://www.googleapis.com/auth/webmasters.readonly
5. Set the environment variable:
   export GOOGLE_SEARCH_CONSOLE_TOKEN=your-access-token""",
        health_check_endpoint="https://www.googleapis.com/webmasters/v3/sites",
        credential_id="google_search_console",
        credential_key="api_key",
    ),
}
