"""
Linear credentials.

Contains credentials for Linear issue tracking and project management.
"""

from .base import CredentialSpec

LINEAR_CREDENTIALS = {
    "linear": CredentialSpec(
        env_var="LINEAR_API_KEY",
        tools=[
            "linear_issue_create",
            "linear_issue_get",
            "linear_issue_update",
            "linear_issue_delete",
            "linear_issue_search",
            "linear_issue_add_comment",
            "linear_project_create",
            "linear_project_get",
            "linear_project_update",
            "linear_project_list",
            "linear_teams_list",
            "linear_team_get",
            "linear_workflow_states_get",
            "linear_label_create",
            "linear_labels_list",
            "linear_users_list",
            "linear_user_get",
            "linear_viewer",
            "linear_cycles_list",
            "linear_issue_comments_list",
            "linear_issue_relation_create",
        ],
        required=True,
        startup_required=False,
        help_url="https://linear.app/developers",
        description="Linear API key for issue tracking and project management",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Linear API key:
1. Go to Linear Settings > Account > Security & Access
2. Under 'Personal API Keys', click 'Create key'
3. Choose permissions (Read + Write recommended)
4. Copy the key
5. Set the environment variable:
   export LINEAR_API_KEY=lin_api_your-key""",
        health_check_endpoint="https://api.linear.app/graphql",
        credential_id="linear",
        credential_key="api_key",
    ),
}
