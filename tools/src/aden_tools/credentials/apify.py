"""
Apify tool credentials.

Contains credentials for Apify (Universal Web Scraping & Automation Marketplace).
"""

from .base import CredentialSpec

APIFY_CREDENTIALS = {
    "apify": CredentialSpec(
        env_var="APIFY_API_TOKEN",
        tools=[
            "apify_run_actor",
            "apify_get_dataset",
            "apify_get_run",
            "apify_search_actors",
        ],
        required=True,
        startup_required=False,
        help_url="https://console.apify.com/account/integrations",
        description="API Token for Apify (Web Scraping & Automation Marketplace)",
        direct_api_key_supported=True,
        api_key_instructions="""To get an Apify API token:
1. Sign up or log in at https://console.apify.com
2. Go to Settings -> Integrations
3. Copy your Personal API token""",
        health_check_endpoint="https://api.apify.com/v2/users/me",
        health_check_method="GET",
        credential_id="apify",
        credential_key="api_token",
    ),
}
