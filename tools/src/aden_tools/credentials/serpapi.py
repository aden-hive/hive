"""
SerpAPI tool credentials.

Contains credentials for SerpAPI (Google Scholar & Patents search).
"""

from .base import CredentialSpec

SERPAPI_CREDENTIALS = {
    "serpapi": CredentialSpec(
        env_var="SERPAPI_API_KEY",
        tools=[
            "scholar_search",
            "scholar_get_citations",
            "scholar_get_author",
            "patents_search",
            "patents_get_details",
        ],
        required=True,
        startup_required=False,
        help_url="https://serpapi.com/manage-api-key",
        description="API key for SerpAPI (Google Scholar & Patents)",
        direct_api_key_supported=True,
        api_key_instructions="""To get a SerpAPI API key:
1. Go to https://serpapi.com/users/sign_up
2. Create an account (free tier: 100 searches/month)
3. Go to https://serpapi.com/manage-api-key
4. Copy your API key""",
        health_check_endpoint="https://serpapi.com/account.json",
        credential_id="serpapi",
        credential_key="api_key",
    ),
}
