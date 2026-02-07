"""
LLM provider credentials.

Contains credentials for language model providers like Anthropic, OpenAI, etc.
"""

from .base import CredentialSpec

LLM_CREDENTIALS = {
    "anthropic": CredentialSpec(
        env_var="ANTHROPIC_API_KEY",
        tools=[],
        node_types=["llm_generate", "llm_tool_use"],
        required=False,  # Not required - agents can use other providers via LiteLLM
        startup_required=False,  # MCP server doesn't need LLM credentials
        help_url="https://console.anthropic.com/settings/keys",
        description="API key for Anthropic Claude models",
        # Auth method support
        direct_api_key_supported=True,
        api_key_instructions="""To get an Anthropic API key:
1. Go to https://console.anthropic.com/settings/keys
2. Sign in or create an Anthropic account
3. Click "Create Key"
4. Give your key a descriptive name (e.g., "Hive Agent")
5. Copy the API key (starts with sk-ant-)
6. Store it securely - you won't be able to see the full key again!""",
        # Health check configuration
        health_check_endpoint="https://api.anthropic.com/v1/messages",
        health_check_method="POST",
        # Credential store mapping
        credential_id="anthropic",
        credential_key="api_key",
    ),
    # Future LLM providers:
    # "openai": CredentialSpec(
    #     env_var="OPENAI_API_KEY",
    #     tools=[],
    #     node_types=["openai_generate"],
    #     required=False,
    #     startup_required=False,
    #     help_url="https://platform.openai.com/api-keys",
    #     description="API key for OpenAI models",
    # ),
}
