"""
Langfuse LLM observability credentials.

Contains credentials for the Langfuse REST API.
Requires LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY.
Optional LANGFUSE_HOST for self-hosted instances.
"""

from .base import CredentialSpec

LANGFUSE_CREDENTIALS = {
    "langfuse_public_key": CredentialSpec(
        env_var="LANGFUSE_PUBLIC_KEY",
        tools=[
            "langfuse_list_traces",
            "langfuse_get_trace",
            "langfuse_list_scores",
            "langfuse_create_score",
            "langfuse_list_prompts",
            "langfuse_get_prompt",
        ],
        required=True,
        startup_required=False,
        help_url="https://langfuse.com/docs/api-and-data-platform/features/public-api",
        description="Langfuse public key (starts with pk-lf-)",
        direct_api_key_supported=True,
        api_key_instructions="""To set up Langfuse API access:
1. Create a Langfuse account at https://cloud.langfuse.com
2. Go to Project > Settings > API Keys
3. Create a new key pair
4. Set environment variables:
   export LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
   export LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
   export LANGFUSE_HOST=https://cloud.langfuse.com (optional, for self-hosted)""",
        health_check_endpoint="",
        credential_id="langfuse_public_key",
        credential_key="api_key",
    ),
    "langfuse_secret_key": CredentialSpec(
        env_var="LANGFUSE_SECRET_KEY",
        tools=[
            "langfuse_list_traces",
            "langfuse_get_trace",
            "langfuse_list_scores",
            "langfuse_create_score",
            "langfuse_list_prompts",
            "langfuse_get_prompt",
        ],
        required=True,
        startup_required=False,
        help_url="https://langfuse.com/docs/api-and-data-platform/features/public-api",
        description="Langfuse secret key (starts with sk-lf-)",
        direct_api_key_supported=True,
        api_key_instructions="""See LANGFUSE_PUBLIC_KEY instructions above.""",
        health_check_endpoint="",
        credential_id="langfuse_secret_key",
        credential_key="api_key",
    ),
}
