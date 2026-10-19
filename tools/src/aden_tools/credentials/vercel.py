"""
Vercel credentials.

Contains credentials for Vercel deployment and hosting management.
"""

from .base import CredentialSpec

VERCEL_CREDENTIALS = {
    "vercel": CredentialSpec(
        env_var="VERCEL_TOKEN",
        tools=[
            "vercel_list_deployments",
            "vercel_get_deployment",
            "vercel_list_projects",
            "vercel_get_project",
            "vercel_list_project_domains",
            "vercel_list_env_vars",
            "vercel_create_env_var",
        ],
        required=True,
        startup_required=False,
        help_url="https://vercel.com/account/tokens",
        description="Vercel access token for deployment and project management",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Vercel access token:
1. Go to https://vercel.com/account/tokens
2. Click 'Create' to generate a new token
3. Give it a name and set the scope (Full Account recommended)
4. Copy the token
5. Set the environment variable:
   export VERCEL_TOKEN=your-token""",
        health_check_endpoint="https://api.vercel.com/v2/user",
        credential_id="vercel",
        credential_key="api_key",
    ),
}
