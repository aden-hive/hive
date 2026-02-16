from .base import CredentialSpec

SHORTCUT_CREDENTIALS = {
    "shortcut_api": CredentialSpec(
        env_var="SHORTCUT_API_TOKEN",
        tools=["create_shortcut_story", "search_shortcut_stories"],
        required=True,
        help_url="https://help.shortcut.com/hc/en-us/articles/205701199-Shortcut-API-Tokens",
        description="API Token for Shortcut",
        credential_id="shortcut_api",
        credential_key="api_token",
    ),
}
