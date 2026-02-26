"""
GitLab credential specifications.

Provides credential specifications for GitLab API access.
Supports Personal Access Token (PAT) or Project Access Token authentication.
Allows self-hosted GitLab instances via GITLAB_URL.
"""

from .base import CredentialSpec

GITLAB_CREDENTIALS = {
    "gitlab_access_token": CredentialSpec(
        env_var="GITLAB_ACCESS_TOKEN",
        tools=[
            "gitlab_list_projects",
            "gitlab_list_issues",
            "gitlab_get_merge_request",
            "gitlab_create_issue",
            "gitlab_trigger_pipeline",
        ],
        required=True,
        description=(
            "Personal Access Token or Project Access Token for GitLab API. "
            "Required scope: 'api'. Required for all GitLab operations."
        ),
        help_url="https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html",
    ),
    "gitlab_url": CredentialSpec(
        env_var="GITLAB_URL",
        tools=[
            "gitlab_list_projects",
            "gitlab_list_issues",
            "gitlab_get_merge_request",
            "gitlab_create_issue",
            "gitlab_trigger_pipeline",
        ],
        required=False,
        description=(
            "Base URL for GitLab instance. Defaults to 'https://gitlab.com'. "
            "Set this for self-hosted GitLab instances (e.g., 'https://gitlab.mycompany.com')."
        ),
    ),
}
