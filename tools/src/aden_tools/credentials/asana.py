"""
Asana credentials.

Contains credentials for Asana task and project management.
"""

from .base import CredentialSpec

ASANA_CREDENTIALS = {
    "asana": CredentialSpec(
        env_var="ASANA_ACCESS_TOKEN",
        tools=[
            "asana_list_workspaces",
            "asana_list_projects",
            "asana_list_tasks",
            "asana_get_task",
            "asana_create_task",
            "asana_search_tasks",
            "asana_update_task",
            "asana_add_comment",
            "asana_create_subtask",
        ],
        required=True,
        startup_required=False,
        help_url="https://developers.asana.com/docs/personal-access-token",
        description="Asana personal access token for task and project management",
        direct_api_key_supported=True,
        api_key_instructions="""To get an Asana personal access token:
1. Go to https://app.asana.com/0/my-apps
2. Click 'Create new token'
3. Give it a name and copy the token
4. Set the environment variable:
   export ASANA_ACCESS_TOKEN=your-pat""",
        health_check_endpoint="https://app.asana.com/api/1.0/users/me",
        credential_id="asana",
        credential_key="api_key",
    ),
}
