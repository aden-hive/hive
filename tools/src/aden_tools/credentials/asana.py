from .base import CredentialSpec

ASANA_CREDENTIALS = {
    "asana_access_token": CredentialSpec(
        env_var="ASANA_ACCESS_TOKEN",
        description="Asana Personal Access Token (PAT). Generate at https://app.asana.com/0/my-apps",
    ),
    "asana_workspace_id": CredentialSpec(
        env_var="ASANA_WORKSPACE_ID",
        description="Optional: Default Asana workspace ID",
        required=False,
    ),
}
