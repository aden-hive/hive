"""
Docker Hub credentials.

Contains credentials for Docker Hub repository and image management.
"""

from .base import CredentialSpec

DOCKER_HUB_CREDENTIALS = {
    "docker_hub": CredentialSpec(
        env_var="DOCKER_HUB_TOKEN",
        tools=[
            "docker_hub_search",
            "docker_hub_list_repos",
            "docker_hub_list_tags",
            "docker_hub_get_repo",
            "docker_hub_get_tag_detail",
            "docker_hub_delete_tag",
            "docker_hub_list_webhooks",
        ],
        required=True,
        startup_required=False,
        help_url="https://hub.docker.com/settings/security",
        description=("Docker Hub personal access token (also set DOCKER_HUB_USERNAME for listing own repos)"),
        direct_api_key_supported=True,
        api_key_instructions="""To get a Docker Hub personal access token:
1. Go to https://hub.docker.com/settings/security
2. Click 'New Access Token'
3. Give it a description and select permissions (Read is sufficient for browsing)
4. Copy the token
5. Set environment variables:
   export DOCKER_HUB_TOKEN=your-pat
   export DOCKER_HUB_USERNAME=your-username""",
        health_check_endpoint="https://hub.docker.com/v2/user/login",
        credential_id="docker_hub",
        credential_key="api_key",
    ),
}
