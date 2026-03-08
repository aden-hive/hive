"""
HuggingFace credentials.

Contains credentials for HuggingFace Hub API and Inference API access.
"""

from .base import CredentialSpec

HUGGINGFACE_CREDENTIALS = {
    "huggingface": CredentialSpec(
        env_var="HUGGINGFACE_TOKEN",
        tools=[
            "huggingface_search_models",
            "huggingface_get_model",
            "huggingface_search_datasets",
            "huggingface_get_dataset",
            "huggingface_search_spaces",
            "huggingface_whoami",
            "huggingface_run_inference",
            "huggingface_run_embedding",
            "huggingface_list_inference_endpoints",
        ],
        required=True,
        startup_required=False,
        help_url="https://huggingface.co/settings/tokens",
        description="HuggingFace API token for Hub access (models, datasets, spaces) and Inference API",
        direct_api_key_supported=True,
        api_key_instructions="""To get a HuggingFace token:
1. Go to https://huggingface.co/settings/tokens
2. Click 'New token'
3. Choose 'Read' access (or 'Write' for repo management)
4. Copy the token
5. Set the environment variable:
   export HUGGINGFACE_TOKEN=hf_your-token""",
        health_check_endpoint="https://huggingface.co/api/whoami-v2",
        credential_id="huggingface",
        credential_key="api_key",
    ),
}

