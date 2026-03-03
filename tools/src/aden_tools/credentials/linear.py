"""
Linear credentials.

Contains credentials for Linear issue tracking and project management.
"""

from .base import CredentialSpec

LINEAR_CREDENTIALS = {
    "linear": CredentialSpec(
        env_var="LINEAR_API_KEY",
        tools=[
            "linear_list_issues",
            "linear_get_issue",
            "linear_create_issue",
            "linear_list_teams",
            "linear_list_projects",
            "linear_search_issues",
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
