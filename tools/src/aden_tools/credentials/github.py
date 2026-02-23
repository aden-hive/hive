"""
GitHub tool credentials.

Contains credentials for GitHub API integration.
"""

from .base import CredentialSpec

GITHUB_CREDENTIALS = {
    "github": CredentialSpec(
        env_var="GITHUB_TOKEN",
        tools=[
            "github_list_repos",
            "github_get_repo",
            "github_search_repos",
            "github_list_issues",
            "github_get_issue",
            "github_create_issue",
            "github_update_issue",
            "github_list_pull_requests",
            "github_get_pull_request",
            "github_create_pull_request",
            "github_search_code",
            "github_list_branches",
            "github_get_branch",
            "github_list_stargazers",
            "github_get_user_profile",
            "github_get_user_emails",
        ],
        required=True,
        startup_required=False,
        help_url="https://github.com/settings/tokens",
        description="GitHub Personal Access Token (classic)",
        # Auth method support
        aden_supported=False,
        direct_api_key_supported=True,
        api_key_instructions="""To get a GitHub Personal Access Token:
1. Go to GitHub Settings > Developer settings > Personal access tokens
2. Click "Generate new token" > "Generate new token (classic)"
3. Give your token a descriptive name (e.g., "Hive Agent")
4. Select the following scopes:
   - repo (Full control of private repositories)
   - read:org (Read org and team membership - optional)
   - user (Read user profile data - optional)
5. Click "Generate token" and copy the token (starts with ghp_)
6. Store it securely - you won't be able to see it again!""",
        # Health check configuration
        health_check_endpoint="https://api.github.com/user",
        health_check_method="GET",
        # Credential store mapping
        credential_id="github",
        credential_key="access_token",
    ),
}
