"""
Jira credentials.

Contains credentials for Jira Cloud issue tracking.
Requires JIRA_DOMAIN, JIRA_EMAIL, and JIRA_API_TOKEN.
"""

from .base import CredentialSpec

JIRA_CREDENTIALS = {
    "jira_domain": CredentialSpec(
        env_var="JIRA_DOMAIN",
        tools=[
            "jira_search_issues",
            "jira_get_issue",
            "jira_create_issue",
            "jira_list_projects",
            "jira_get_project",
            "jira_add_comment",
            "jira_update_issue",
            "jira_list_transitions",
            "jira_transition_issue",
        ],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage/api-tokens",
        description="Jira Cloud domain (e.g. your-org.atlassian.net)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Jira API access:
1. Go to https://id.atlassian.com/manage/api-tokens
2. Click 'Create API token'
3. Set environment variables:
   export JIRA_DOMAIN=your-org.atlassian.net
   export JIRA_EMAIL=your-email@example.com
   export JIRA_API_TOKEN=your-api-token""",
        health_check_endpoint="",
        credential_id="jira_domain",
        credential_key="api_key",
    ),
    "jira_email": CredentialSpec(
        env_var="JIRA_EMAIL",
        tools=[
            "jira_search_issues",
            "jira_get_issue",
            "jira_create_issue",
            "jira_list_projects",
            "jira_get_project",
            "jira_add_comment",
            "jira_update_issue",
            "jira_list_transitions",
            "jira_transition_issue",
        ],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage/api-tokens",
        description="Atlassian account email for Jira authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See JIRA_DOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="jira_email",
        credential_key="api_key",
    ),
    "jira_token": CredentialSpec(
        env_var="JIRA_API_TOKEN",
        tools=[
            "jira_search_issues",
            "jira_get_issue",
            "jira_create_issue",
            "jira_list_projects",
            "jira_get_project",
            "jira_add_comment",
            "jira_update_issue",
            "jira_list_transitions",
            "jira_transition_issue",
        ],
        required=True,
        startup_required=False,
        help_url="https://id.atlassian.com/manage/api-tokens",
        description="Atlassian API token for Jira authentication",
        direct_api_key_supported=True,
        api_key_instructions="""See JIRA_DOMAIN instructions above.""",
        health_check_endpoint="",
        credential_id="jira_token",
        credential_key="api_key",
    ),
}
