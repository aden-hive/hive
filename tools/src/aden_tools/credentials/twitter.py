"""
Twitter/X credentials.

Contains credentials for X API v2.
Requires X_BEARER_TOKEN for read-only access.
"""

from .base import CredentialSpec

TWITTER_CREDENTIALS = {
    "x_bearer_token": CredentialSpec(
        env_var="X_BEARER_TOKEN",
        tools=[
            "twitter_search_tweets",
            "twitter_get_user",
            "twitter_get_user_tweets",
            "twitter_get_tweet",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.x.com/en/portal/dashboard",
        description="X/Twitter API v2 Bearer Token (app-only, read access)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up X/Twitter API access:
1. Go to https://developer.x.com/en/portal/dashboard
2. Create a Project and App
3. Copy the Bearer Token from the Keys and Tokens tab
4. Set environment variable:
   export X_BEARER_TOKEN=your-bearer-token""",
        health_check_endpoint="",
        credential_id="x_bearer_token",
        credential_key="api_key",
    ),
}
