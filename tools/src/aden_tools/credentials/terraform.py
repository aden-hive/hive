"""
Terraform Cloud / HCP Terraform credentials.

Contains credentials for the Terraform Cloud REST API v2.
Requires TFC_TOKEN.
"""

from .base import CredentialSpec

TERRAFORM_CREDENTIALS = {
    "tfc_token": CredentialSpec(
        env_var="TFC_TOKEN",
        tools=[
            "terraform_list_workspaces",
            "terraform_get_workspace",
            "terraform_list_runs",
            "terraform_get_run",
            "terraform_create_run",
        ],
        required=True,
        startup_required=False,
        help_url="https://developer.hashicorp.com/terraform/cloud-docs/users-teams-organizations/api-tokens",
        description="Terraform Cloud API token (User or Team token)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Terraform Cloud API access:
1. Go to app.terraform.io > User Settings > Tokens
2. Create a new API token
3. Set environment variable:
   export TFC_TOKEN=your-api-token
   (Optional for Terraform Enterprise: export TFC_URL=https://your-host.example.com)""",
        health_check_endpoint="",
        credential_id="tfc_token",
        credential_key="api_key",
    ),
}
