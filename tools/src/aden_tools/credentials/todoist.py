"""
Todoist REST API credentials.

Requires a personal API token (Bearer).
"""

from .base import CredentialSpec

TODOIST_CREDENTIALS = {
    "todoist_token": CredentialSpec(
        env_var="TODOIST_API_TOKEN",
        tools=[
            "todoist_get_tasks",
            "todoist_create_task",
            "todoist_complete_task",
            "todoist_get_projects",
            "todoist_create_project",
            "todoist_delete_task",
        ],
        node_types=[],
        required=True,
        startup_required=False,
        help_url="https://todoist.com/app/settings/integrations",
        description="Todoist personal API token",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Todoist API token:
1. Open https://todoist.com/app/settings/integrations
2. Under 'Developer', copy your API token or create a new app token
3. Set environment variable:
   export TODOIST_API_TOKEN=your-token""",
        health_check_endpoint="https://api.todoist.com/rest/v2/projects",
        credential_id="todoist_token",
        credential_key="api_key",
    ),
}
