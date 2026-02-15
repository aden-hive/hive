"""Google Search Console credential specification."""

from __future__ import annotations

from .base import CredentialSpec

GOOGLE_SEARCH_CONSOLE_CREDENTIALS = {
    "google_search_console": CredentialSpec(
        env_var="GOOGLE_APPLICATION_CREDENTIALS",
        tools=[
            "gsc_search_analytics",
            "gsc_get_top_queries",
            "gsc_get_top_pages",
            "gsc_list_sites",
        ],
        required=True,
        help_url="https://developers.google.com/webmaster-tools/v1/how-tos/authorizing",
        description="Path to Google Cloud service account JSON key with Search Console read access",
        direct_api_key_supported=True,
        api_key_instructions="Provide the path to your service account JSON file. Ensure the service account has 'Search Console Viewer' permission.",
    ),
}
