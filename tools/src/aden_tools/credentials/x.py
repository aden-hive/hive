"""
X (Twitter) tool credentials.

Contains credentials for X API v2 integration.
Bearer token for read-only operations, OAuth 1.0a keys for write operations.
"""

from .base import CredentialSpec

_X_TOOLS = [
    "x_post_tweet",
    "x_reply_tweet",
    "x_delete_tweet",
    "x_search_tweets",
    "x_get_mentions",
    "x_send_dm",
]

X_CREDENTIALS = {
    "x_bearer_token": CredentialSpec(
        env_var="X_BEARER_TOKEN",
        tools=_X_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://developer.x.com/en/portal/dashboard",
        description="X (Twitter) API v2 Bearer Token for read-only operations",
        direct_api_key_supported=True,
        api_key_instructions="""To get an X API Bearer Token:
1. Go to https://developer.x.com/en/portal/dashboard
2. Create a Project & App (or select existing)
3. Go to Keys & Tokens tab
4. Copy the Bearer Token
5. Set it as X_BEARER_TOKEN environment variable""",
        health_check_endpoint="https://api.x.com/2/users/me",
        health_check_method="GET",
        credential_id="x_bearer_token",
        credential_key="api_key",
        credential_group="x",
    ),
    "x_api_key": CredentialSpec(
        env_var="X_API_KEY",
        tools=_X_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://developer.x.com/en/portal/dashboard",
        description="X (Twitter) API Consumer Key for OAuth 1.0a write operations",
        direct_api_key_supported=True,
        api_key_instructions="""To get your X API Consumer Key:
1. Go to https://developer.x.com/en/portal/dashboard
2. Select your app > Keys and Tokens
3. Under Consumer Keys, copy the API Key""",
        credential_id="x_api_key",
        credential_key="api_key",
        credential_group="x",
    ),
    "x_api_secret": CredentialSpec(
        env_var="X_API_SECRET",
        tools=_X_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://developer.x.com/en/portal/dashboard",
        description="X (Twitter) API Consumer Secret for OAuth 1.0a write operations",
        direct_api_key_supported=True,
        api_key_instructions="""To get your X API Consumer Secret:
1. Go to https://developer.x.com/en/portal/dashboard
2. Select your app > Keys and Tokens
3. Under Consumer Keys, copy the API Secret""",
        credential_id="x_api_secret",
        credential_key="api_key",
        credential_group="x",
    ),
    "x_access_token": CredentialSpec(
        env_var="X_ACCESS_TOKEN",
        tools=_X_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://developer.x.com/en/portal/dashboard",
        description="X (Twitter) User Access Token for OAuth 1.0a write operations",
        direct_api_key_supported=True,
        api_key_instructions="""To get your X Access Token:
1. Go to https://developer.x.com/en/portal/dashboard
2. Select your app > Keys and Tokens
3. Under Authentication Tokens, generate Access Token and Secret
4. Copy the Access Token""",
        credential_id="x_access_token",
        credential_key="api_key",
        credential_group="x",
    ),
    "x_access_token_secret": CredentialSpec(
        env_var="X_ACCESS_TOKEN_SECRET",
        tools=_X_TOOLS,
        required=False,
        startup_required=False,
        help_url="https://developer.x.com/en/portal/dashboard",
        description="X (Twitter) User Access Token Secret for OAuth 1.0a write operations",
        direct_api_key_supported=True,
        api_key_instructions="""To get your X Access Token Secret:
1. Go to https://developer.x.com/en/portal/dashboard
2. Select your app > Keys and Tokens
3. Under Authentication Tokens, generate Access Token and Secret
4. Copy the Access Token Secret""",
        credential_id="x_access_token_secret",
        credential_key="api_key",
        credential_group="x",
    ),
}
