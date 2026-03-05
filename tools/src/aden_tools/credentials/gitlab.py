"""
GitLab credentials.

Contains credentials for GitLab projects, issues, and merge requests.
Requires GITLAB_TOKEN. GITLAB_URL is optional (defaults to gitlab.com).
"""

from .base import CredentialSpec

GITLAB_CREDENTIALS = {
    "gitlab_token": CredentialSpec(
        env_var="GITLAB_TOKEN",
        tools=[
            "gitlab_list_projects",
            "gitlab_get_project",
            "gitlab_list_issues",
            "gitlab_get_issue",
            "gitlab_create_issue",
            "gitlab_list_merge_requests",
        ],
        required=True,
        startup_required=False,
        help_url="https://gitlab.com/-/user_settings/personal_access_tokens",
        description="GitLab personal access token",
        direct_api_key_supported=True,
        api_key_instructions="""To set up GitLab API access:
1. Go to https://gitlab.com/-/user_settings/personal_access_tokens
   (or your self-hosted instance equivalent)
2. Create a new token with 'api' scope
3. Set environment variables:
   export GITLAB_TOKEN=your-personal-access-token
   export GITLAB_URL=https://gitlab.com  (optional, defaults to gitlab.com)""",
        health_check_endpoint="https://gitlab.com/api/v4/user",
        credential_id="gitlab_token",
        credential_key="api_key",
    ),
}
