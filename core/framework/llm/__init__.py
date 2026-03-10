"""LLM provider abstraction."""

import logging

from framework.llm.provider import LLMProvider, LLMResponse
from framework.llm.stream_events import (
    FinishEvent,
    ReasoningDeltaEvent,
    ReasoningStartEvent,
    StreamErrorEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
    ToolResultEvent,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "StreamEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ReasoningStartEvent",
    "ReasoningDeltaEvent",
    "FinishEvent",
    "StreamErrorEvent",
    "get_llm_provider",
    "get_available_providers",
    "interactive_fallback",
]

# Export the new provider selector functions
try:
    from framework.llm.provider_selector import interactive_fallback

    __all__.append("interactive_fallback")
except ImportError:
    logger.debug("provider_selector not available")

# Export LiteLLM provider
try:
    from framework.llm.litellm import LiteLLMProvider

    __all__.append("LiteLLMProvider")
except ImportError:
    pass

# Export Mock provider
try:
    from framework.llm.mock import MockLLMProvider

    __all__.append("MockLLMProvider")
except ImportError:
    pass

# Don't auto-export AnthropicProvider - use get_llm_provider instead
try:
    from framework.llm.anthropic import AnthropicProvider

    # Explicitly NOT adding to __all__ to prevent accidental use
    logger.warning(
        "AnthropicProvider is deprecated. Use get_llm_provider() or LiteLLMProvider directly."
    )
except ImportError:
    pass


def get_llm_provider(config: dict | None = None) -> LLMProvider:
    """Get the appropriate LLM provider based on user configuration.

    Args:
        config: Optional config dict. If None, loads from ~/.hive/configuration.json

    Returns:
        LLMProvider instance configured for the user's selected provider
    """
    if config is None:
        from framework.config import get_hive_config

        config = get_hive_config().get("llm", {})

    provider_name = config.get("provider", "").lower()
    model = config.get("model", "")
    api_key = config.get("api_key_env_var")
    api_base = config.get("api_base")

    # Get API key if specified
    if api_key:
        import os

        api_key = os.environ.get(api_key)

    logger.info(f"Creating LLM provider for: {provider_name} with model: {model}")

    # Always use LiteLLM - it supports everything
    from framework.llm.litellm import LiteLLMProvider

    # Format model correctly
    if provider_name and model:
        if provider_name == "gemini":
            full_model = model
        else:
            full_model = f"{provider_name}/{model}"
    else:
        full_model = model or "gemini-3-flash-preview"

    return LiteLLMProvider(model=full_model, api_key=api_key, api_base=api_base)


def get_available_providers() -> dict:
    """Get all available LLM providers based on environment variables."""
    from framework.config import get_available_providers as _get_providers

    return _get_providers()
