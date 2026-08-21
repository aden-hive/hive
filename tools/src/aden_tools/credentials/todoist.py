"""
Todoist credentials.

Contains credentials for Todoist task management integration.
"""

from .base import CredentialSpec

TODOIST_CREDENTIALS = {
    "todoist": CredentialSpec(
        env_var="TODOIST_API_KEY",
        tools=[
            "todoist_list_tasks",
            "todoist_get_task",
            "todoist_create_task",
            "todoist_update_task",
            "todoist_complete_task",
            "todoist_delete_task",
            "todoist_list_projects",
            "todoist_create_project",
        ],
        required=True,
        startup_required=False,
        help_url="https://todoist.com/app/settings/integrations/developer",
        description="Todoist API token for task and project management",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Todoist API token:
1. Go to https://todoist.com/app/settings/integrations/developer
2. Scroll to the 'API token' section
3. Copy your API token
4. Set the environment variable:
   export TODOIST_API_KEY=your-api-token""",
        health_check_endpoint="https://api.todoist.com/api/v1/projects",
        credential_id="todoist",
        credential_key="api_key",
    ),
}
