"""
Langfuse LLM observability credentials.

Contains credentials for the Langfuse REST API and SDK.
Requires LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_HOST.
"""

from .base import CredentialSpec

LANGFUSE_CREDENTIALS = {
    "langfuse": CredentialSpec(
        env_var="LANGFUSE_PUBLIC_KEY",
        tools=[
            "start_agent_trace",
            "log_node_span",
            "score_agent_run",
            "langfuse_list_traces",
            "langfuse_get_trace",
            "langfuse_list_scores",
            "langfuse_create_score",
            "langfuse_list_prompts",
            "langfuse_get_prompt",
        ],
        required=True,
        startup_required=False,
        help_url="https://cloud.langfuse.com/",
        description="Langfuse public key (starts with pk-lf-)",
        direct_api_key_supported=True,
        api_key_instructions=\"\"\"To set up Langfuse access:
1. Go to https://cloud.langfuse.com/ and create a free account
2. Create a new Project
3. Go to Settings → API Keys
4. Click Create new API key
5. Copy the Public Key (starts with pk-lf-) and Secret Key (starts with sk-lf-)
6. Set environment variables:
   export LANGFUSE_PUBLIC_KEY=pk-lf-your-public-key
   export LANGFUSE_SECRET_KEY=sk-lf-your-secret-key
   export LANGFUSE_HOST=https://cloud.langfuse.com (or your self-hosted URL)\"\"\",
        health_check_endpoint="https://cloud.langfuse.com/api/public/projects",
        credential_id="langfuse",
        credential_key="public_key",
        credential_group="langfuse",
    ),
    "langfuse_secret": CredentialSpec(
        env_var="LANGFUSE_SECRET_KEY",
        tools=[
            "start_agent_trace",
            "log_node_span",
            "score_agent_run",
            "langfuse_list_traces",
            "langfuse_get_trace",
            "langfuse_list_scores",
            "langfuse_create_score",
            "langfuse_list_prompts",
            "langfuse_get_prompt",
        ],
        required=True,
        startup_required=False,
        help_url="https://cloud.langfuse.com/",
        description="Langfuse secret key (starts with sk-lf-)",
        direct_api_key_supported=True,
        api_key_instructions="See LANGFUSE_PUBLIC_KEY instructions above.",
        health_check_endpoint="https://cloud.langfuse.com/api/public/projects",
        credential_id="langfuse",
        credential_key="secret_key",
        credential_group="langfuse",
    ),
    "langfuse_host": CredentialSpec(
        env_var="LANGFUSE_HOST",
        tools=[
            "start_agent_trace",
            "log_node_span",
            "score_agent_run",
            "langfuse_list_traces",
            "langfuse_get_trace",
            "langfuse_list_scores",
            "langfuse_create_score",
            "langfuse_list_prompts",
            "langfuse_get_prompt",
        ],
        required=True,
        startup_required=False,
        help_url="https://cloud.langfuse.com/",
        description="Langfuse server URL (cloud or self-hosted)",
        direct_api_key_supported=True,
        api_key_instructions="See LANGFUSE_PUBLIC_KEY instructions above.",
        health_check_endpoint="https://cloud.langfuse.com/api/public/projects",
        credential_id="langfuse",
        credential_key="host",
        credential_group="langfuse",
    ),
}
