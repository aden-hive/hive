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
        startup_required=False,  # MCP servers don't require LLM credentials at startup
        help_url="https://console.anthropic.com/settings/keys",
        description="API key for Anthropic Claude models",
        direct_api_key_supported=True,
        api_key_instructions="""To get an Anthropic API key:
1. Go to https://console.anthropic.com/settings/keys
2. Sign in or create an Anthropic account
3. Click "Create Key"
4. Give your key a descriptive name (e.g., "Hive Agent")
5. Copy the API key (starts with sk-ant-)
6. Store it securely - you won't be able to see the full key again!""",
        health_check_endpoint="https://api.anthropic.com/v1/messages",
        health_check_method="POST",
        credential_id="anthropic",
        credential_key="api_key",
    ),
    "openai": CredentialSpec(
        env_var="OPENAI_API_KEY",
        tools=[],
        node_types=["llm_generate", "llm_tool_use"],
        required=False,
        startup_required=False,
        help_url="https://platform.openai.com/api-keys",
        description="API key for OpenAI models (used via LiteLLM)",
        direct_api_key_supported=True,
        api_key_instructions="""To get an OpenAI API key:
1. Go to https://platform.openai.com/api-keys
2. Sign in or create an OpenAI account
3. Click "Create new secret key"
4. Copy the key (starts with sk-)
5. Store it securely - you won't be able to see the full key again!""",
        health_check_endpoint="https://api.openai.com/v1/models",
        health_check_method="GET",
        credential_id="openai",
        credential_key="api_key",
    ),
    "cerebras": CredentialSpec(
        env_var="CEREBRAS_API_KEY",
        tools=[],
        node_types=["llm_generate", "llm_tool_use"],
        required=False,
        startup_required=False,
        help_url="https://cloud.cerebras.ai/",
        description="API key for Cerebras models (often used for fast/cheap inference via LiteLLM)",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Cerebras API key:
1. Go to https://cloud.cerebras.ai/
2. Sign in or create an account
3. Create an API key in your account settings
4. Copy the key and store it securely""",
        health_check_endpoint="https://api.cerebras.ai/v1/models",
        health_check_method="GET",
        credential_id="cerebras",
        credential_key="api_key",
    ),
    "groq": CredentialSpec(
        env_var="GROQ_API_KEY",
        tools=[],
        node_types=["llm_generate", "llm_tool_use"],
        required=False,
        startup_required=False,
        help_url="https://console.groq.com/keys",
        description="API key for Groq models (fast inference via LiteLLM)",
        direct_api_key_supported=True,
        api_key_instructions="""To get a Groq API key:
1. Go to https://console.groq.com/keys
2. Sign in or create an account
3. Create a new API key
4. Copy the key and store it securely""",
        health_check_endpoint="https://api.groq.com/openai/v1/models",
        health_check_method="GET",
        credential_id="groq",
        credential_key="api_key",
    ),
}
