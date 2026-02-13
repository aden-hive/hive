"""
News API credentials.

Includes NewsData.io (primary) and Finlight.me (optional sentiment).
"""

from .base import CredentialSpec

NEWS_CREDENTIALS = {
    "newsdata": CredentialSpec(
        env_var="NEWSDATA_API_KEY",
        tools=["news_search", "news_headlines", "news_by_company"],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://newsdata.io/",
        description="API key for NewsData.io news search",
        direct_api_key_supported=True,
        api_key_instructions="""To get a NewsData.io API key:
1. Go to https://newsdata.io/
2. Create an account (free tier available)
3. Open your dashboard and find the API key section
4. Copy the API key and store it securely""",
        health_check_endpoint="https://newsdata.io/api/1/news",
        credential_id="newsdata",
        credential_key="api_key",
    ),
    "finlight": CredentialSpec(
        env_var="FINLIGHT_API_KEY",
        tools=["news_sentiment"],
        node_types=[],
        required=False,
        startup_required=False,
        help_url="https://finlight.me/",
        description="API key for Finlight news sentiment analysis",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Finlight API key:
1. Go to https://finlight.me/
2. Create an account (free tier available)
3. Open your dashboard and generate an API key
4. Copy the API key and store it securely""",
        health_check_endpoint="https://api.finlight.me/v1/news",
        credential_id="finlight",
        credential_key="api_key",
    ),
}
