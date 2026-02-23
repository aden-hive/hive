"""
TickTick tool credentials.

Contains credentials for TickTick task management integration.
"""

from .base import CredentialSpec

TICKTICK_CREDENTIALS = {
    "ticktick": CredentialSpec(
        env_var="TICKTICK_ACCESS_TOKEN",
        tools=[
            "ticktick_create_task",
            "ticktick_list_tasks",
            "ticktick_update_task",
            "ticktick_complete_task",
            "ticktick_delete_task",
            "ticktick_list_projects",
            "ticktick_create_project",
            "ticktick_list_tags",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.ticktick.com/docs",
        description="TickTick OAuth2 access token for task management",
        # Auth method support
        aden_supported=True,
        aden_provider_name="ticktick",
        direct_api_key_supported=True,
        api_key_instructions="""To get a TickTick access token:
1. Go to https://developer.ticktick.com/manage
2. Create a new app (register as a developer if needed)
3. Set a redirect URL for your app
4. Use the OAuth2 flow to obtain an access token
5. Set the token as TICKTICK_ACCESS_TOKEN""",
        # Health check configuration
        health_check_endpoint="https://api.ticktick.com/open/v1/user/profile",
        health_check_method="GET",
        # Credential store mapping
        credential_id="ticktick",
        credential_key="access_token",
    ),
}
