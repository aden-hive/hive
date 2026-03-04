"""
Reddit credentials.

Contains credentials for Reddit community content monitoring and search.
Requires REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET.
"""

from .base import CredentialSpec

REDDIT_CREDENTIALS = {
    "reddit_client_id": CredentialSpec(
        env_var="REDDIT_CLIENT_ID",
        tools=[
            "reddit_search",
            "reddit_get_posts",
            "reddit_get_comments",
            "reddit_get_user",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.reddit.com/prefs/apps",
        description="Reddit app client ID for OAuth2 authentication",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Reddit API access:
1. Go to https://www.reddit.com/prefs/apps
2. Click 'create another app...' at the bottom
3. Select 'script' as the app type
4. Fill in the name and redirect URI (http://localhost)
5. Copy the client ID (under the app name) and secret
6. Set environment variables:
   export REDDIT_CLIENT_ID=your-client-id
   export REDDIT_CLIENT_SECRET=your-client-secret""",
        health_check_endpoint="",
        credential_id="reddit_client_id",
        credential_key="api_key",
    ),
    "reddit_secret": CredentialSpec(
        env_var="REDDIT_CLIENT_SECRET",
        tools=[
            "reddit_search",
            "reddit_get_posts",
            "reddit_get_comments",
            "reddit_get_user",
        ],
        required=True,
        startup_required=False,
        help_url="https://www.reddit.com/prefs/apps",
        description="Reddit app client secret for OAuth2 authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See REDDIT_CLIENT_ID instructions above.""",
        health_check_endpoint="",
        credential_id="reddit_secret",
        credential_key="api_key",
    ),
}
