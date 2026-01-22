"""
Search tool credentials.

Contains credentials for search providers like Brave Search, Google, Bing, etc.
"""
from .base import CredentialSpec

SEARCH_CREDENTIALS = {
    "brave_search": CredentialSpec(
        env_var="BRAVE_SEARCH_API_KEY",
        tools=["web_search"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://brave.com/search/api/",
        description="API key for Brave Search",
    ),
    # Future search providers:
    # "google_search": CredentialSpec(
    #     env_var="GOOGLE_SEARCH_API_KEY",
    #     tools=["google_search"],
    #     node_types=[],
    #     required=True,
    #     startup_required=False,
    #     help_url="https://developers.google.com/custom-search/v1/overview",
    #     description="API key for Google Custom Search",
    # ),
}
