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
        required=True,
        startup_required=True,
        help_url="https://console.anthropic.com/settings/keys",
        description="API key for Anthropic Claude models (required for testing)",
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
