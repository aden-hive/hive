"""
Glue AI tool credentials.

Contains credentials for Glue AI GraphQL API integration.
"""

from .base import CredentialSpec

GLUE_CREDENTIALS = {
    "glue": CredentialSpec(
        env_var="GLUE_ACCESS_TOKEN",
        tools=[
            "glue_send_message",
            "glue_list_groups",
            "glue_list_threads",
            "glue_list_workspaces",
            "glue_get_thread",
            "glue_create_thread",
        ],
        required=True,
        startup_required=False,
        help_url="https://docs.glue.ai/developers/authentication/oauth-2-0-authentication",
        description="OAuth2 access token for Glue AI GraphQL API",
        # Auth method support
        aden_supported=True,
        aden_provider_name="glue",
        direct_api_key_supported=False,
        api_key_instructions="",
        # Health check configuration
        health_check_endpoint="https://api.gluegroups.com/public/graphql",
        health_check_method="POST",
        # Credential store mapping
        credential_id="glue",
        credential_key="access_token",
    ),
}
