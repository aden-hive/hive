"""Model provider registry for LLM configuration.

Contains metadata for supported LLM providers and their available models.
Used by the model configuration TUI to present options to users.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelInfo:
    """Information about a specific model."""

    id: str  # Full model identifier for LiteLLM (e.g., "groq/llama3-8b-8192")
    name: str  # Display name
    context_window: int  # Max context window in tokens
    description: str  # Human-readable description
    recommended: bool = False  # Whether this is a recommended option


@dataclass
class ProviderInfo:
    """Information about an LLM provider."""

    id: str  # Provider identifier (e.g., "groq")
    name: str  # Display name (e.g., "Groq")
    env_var: str  # Environment variable for API key
    models: list[ModelInfo]  # Available models
    description: str  # Provider description
    api_key_url: str  # URL to get API key
    requires_prefix: bool = True  # Whether model IDs need provider prefix


# Provider configurations
PROVIDERS = {
    "anthropic": ProviderInfo(
        id="anthropic",
        name="Anthropic (Claude)",
        env_var="ANTHROPIC_API_KEY",
        description="Claude models - advanced reasoning and code generation",
        api_key_url="https://console.anthropic.com/settings/keys",
        requires_prefix=False,  # Anthropic models don't need prefix
        models=[
            ModelInfo(
                id="claude-opus-4-20250514",
                name="Claude Opus 4",
                context_window=200000,
                description="Most capable model - complex reasoning",
                recommended=False,
            ),
            ModelInfo(
                id="claude-sonnet-4-20250514",
                name="Claude Sonnet 4",
                context_window=200000,
                description="Balanced performance and speed",
                recommended=True,
            ),
            ModelInfo(
                id="claude-haiku-4-5-20251001",
                name="Claude Haiku 4.5",
                context_window=200000,
                description="Fast and efficient",
                recommended=False,
            ),
            ModelInfo(
                id="claude-3-5-sonnet-20241022",
                name="Claude 3.5 Sonnet",
                context_window=200000,
                description="Previous generation, still excellent",
                recommended=False,
            ),
        ],
    ),
    "groq": ProviderInfo(
        id="groq",
        name="Groq",
        env_var="GROQ_API_KEY",
        description="Ultra-fast inference with open models",
        api_key_url="https://console.groq.com/keys",
        requires_prefix=True,
        models=[
            ModelInfo(
                id="groq/llama-3.3-70b-versatile",
                name="Llama 3.3 70B",
                context_window=8192,
                description="Most capable Llama model",
                recommended=True,
            ),
            ModelInfo(
                id="groq/llama3-70b-8192",
                name="Llama 3 70B",
                context_window=8192,
                description="Previous generation, very fast",
                recommended=False,
            ),
            ModelInfo(
                id="groq/llama3-8b-8192",
                name="Llama 3 8B",
                context_window=8192,
                description="Fastest, good for simple tasks",
                recommended=False,
            ),
            ModelInfo(
                id="groq/mixtral-8x7b-32768",
                name="Mixtral 8x7B",
                context_window=32768,
                description="32K context, good for long documents",
                recommended=False,
            ),
            ModelInfo(
                id="groq/gemma2-9b-it",
                name="Gemma 2 9B",
                context_window=8192,
                description="Google's open model",
                recommended=False,
            ),
        ],
    ),
    "openai": ProviderInfo(
        id="openai",
        name="OpenAI (GPT)",
        env_var="OPENAI_API_KEY",
        description="GPT models - industry standard",
        api_key_url="https://platform.openai.com/api-keys",
        requires_prefix=False,
        models=[
            ModelInfo(
                id="gpt-4o",
                name="GPT-4o",
                context_window=128000,
                description="Latest multimodal model",
                recommended=True,
            ),
            ModelInfo(
                id="gpt-4o-mini",
                name="GPT-4o Mini",
                context_window=128000,
                description="Fast and cost-effective",
                recommended=True,
            ),
            ModelInfo(
                id="gpt-4-turbo",
                name="GPT-4 Turbo",
                context_window=128000,
                description="Previous generation",
                recommended=False,
            ),
            ModelInfo(
                id="gpt-3.5-turbo",
                name="GPT-3.5 Turbo",
                context_window=16385,
                description="Legacy model, very fast",
                recommended=False,
            ),
        ],
    ),
    "google": ProviderInfo(
        id="google",
        name="Google (Gemini)",
        env_var="GEMINI_API_KEY",
        description="Gemini models - multimodal capabilities",
        api_key_url="https://makersuite.google.com/app/apikey",
        requires_prefix=True,
        models=[
            ModelInfo(
                id="gemini/gemini-2.0-flash-exp",
                name="Gemini 2.0 Flash",
                context_window=1000000,
                description="1M context, experimental",
                recommended=True,
            ),
            ModelInfo(
                id="gemini/gemini-1.5-pro",
                name="Gemini 1.5 Pro",
                context_window=2000000,
                description="2M context, most capable",
                recommended=False,
            ),
            ModelInfo(
                id="gemini/gemini-1.5-flash",
                name="Gemini 1.5 Flash",
                context_window=1000000,
                description="1M context, fast",
                recommended=False,
            ),
        ],
    ),
    "cerebras": ProviderInfo(
        id="cerebras",
        name="Cerebras",
        env_var="CEREBRAS_API_KEY",
        description="Extremely fast inference on custom hardware",
        api_key_url="https://cloud.cerebras.ai/",
        requires_prefix=True,
        models=[
            ModelInfo(
                id="cerebras/llama-3.3-70b",
                name="Llama 3.3 70B",
                context_window=8192,
                description="Ultra-fast Llama inference",
                recommended=True,
            ),
            ModelInfo(
                id="cerebras/llama3.1-8b",
                name="Llama 3.1 8B",
                context_window=8192,
                description="Fastest option",
                recommended=False,
            ),
        ],
    ),
    "deepseek": ProviderInfo(
        id="deepseek",
        name="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        description="Cost-effective Chinese models",
        api_key_url="https://platform.deepseek.com/api_keys",
        requires_prefix=True,
        models=[
            ModelInfo(
                id="deepseek/deepseek-chat",
                name="DeepSeek Chat",
                context_window=64000,
                description="General purpose chat model",
                recommended=True,
            ),
            ModelInfo(
                id="deepseek/deepseek-coder",
                name="DeepSeek Coder",
                context_window=64000,
                description="Specialized for coding",
                recommended=False,
            ),
        ],
    ),
}


def get_provider_by_id(provider_id: str) -> ProviderInfo | None:
    """Get provider info by ID."""
    return PROVIDERS.get(provider_id)


def get_provider_for_model(model_id: str) -> ProviderInfo | None:
    """Determine which provider a model belongs to based on its ID."""
    # Check for explicit prefix (e.g., "groq/llama3-8b-8192")
    if "/" in model_id:
        prefix = model_id.split("/")[0]
        if prefix in PROVIDERS:
            return PROVIDERS[prefix]

    # Check if it matches any provider's models (for providers without prefix)
    for provider in PROVIDERS.values():
        for model in provider.models:
            if model.id == model_id:
                return provider

    return None


def validate_model_provider_match(model_id: str, provider_id: str) -> bool:
    """Validate that a model ID is compatible with a provider."""
    provider = get_provider_by_id(provider_id)
    if not provider:
        return False

    # Check if model exists in provider's model list
    for model in provider.models:
        if model.id == model_id:
            return True

    return False


def get_model_info(model_id: str) -> ModelInfo | None:
    """Get model info by ID."""
    for provider in PROVIDERS.values():
        for model in provider.models:
            if model.id == model_id:
                return model
    return None
