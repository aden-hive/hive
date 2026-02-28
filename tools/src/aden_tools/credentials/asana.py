from .base import CredentialSpec

ASANA_TOOLS = [
    "asana_create_task",
    "asana_update_task",
    "asana_get_task",
    "asana_search_tasks",
    "asana_delete_task",
    "asana_add_task_comment",
    "asana_complete_task",
    "asana_add_subtask",
    "asana_create_project",
    "asana_update_project",
    "asana_get_project",
    "asana_list_projects",
    "asana_get_project_tasks",
    "asana_add_task_to_project",
    "asana_get_workspace",
    "asana_list_workspaces",
    "asana_get_user",
    "asana_list_team_members",
    "asana_create_section",
    "asana_list_sections",
    "asana_move_task_to_section",
    "asana_create_tag",
    "asana_add_tag_to_task",
    "asana_list_tags",
    "asana_update_custom_field",
]

ASANA_CREDENTIALS = {
    "asana": CredentialSpec(
        env_var="ASANA_ACCESS_TOKEN",
        tools=ASANA_TOOLS,
        required=True,
        startup_required=False,
        help_url="https://app.asana.com/0/my-apps",
        description="Asana Personal Access Token (PAT)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get an Asana Personal Access Token:
1. Go to https://app.asana.com/0/my-apps
2. Click "+ New access token"
3. Name your token (e.g. "Aden Agent")
4. Copy the token string (starts with "1/...")
5. Store it securely.""",
        # Health check configuration
        health_check_endpoint="https://app.asana.com/api/1.0/users/me",
        health_check_method="GET",
        # Credential store mapping
        credential_id="asana",
        credential_key="access_token",
    ),
}
