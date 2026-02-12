"""
LLM Provider Factory for multi-provider support.

Supports OpenAI, Anthropic (Claude), and Google (Gemini) via LangChain.
Provider selection via environment variable or explicit configuration.

Follows Hive patterns:
- Environment-based configuration
- Type safety
- Non-fatal error handling
"""

import logging
import os
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel

logger = logging.getLogger(__name__)

LLMProvider = Literal["openai", "anthropic", "google"]


def create_llm(
    provider: LLMProvider | None = None,
    model: str | None = None,
    api_key: str | None = None,
    temperature: float = 0.0,
) -> BaseChatModel:
    """
    Create LangChain chat model for specified provider.

    Provider priority:
    1. Explicit provider parameter
    2. HIVE_LLM_PROVIDER environment variable
    3. Auto-detect based on available API keys

    Args:
        provider: LLM provider ("openai", "anthropic", or "google")
        model: Model name (uses provider default if None)
        api_key: API key (uses environment variable if None)
        temperature: Sampling temperature (default 0.0 for deterministic)

    Returns:
        Configured LangChain chat model

    Raises:
        ValueError: If provider is invalid or API key is missing
        ImportError: If required LangChain integration is not installed

    Environment Variables:
        HIVE_LLM_PROVIDER: Default provider (openai|anthropic|google)
        OPENAI_API_KEY: OpenAI API key
        ANTHROPIC_API_KEY: Anthropic API key
        GOOGLE_API_KEY: Google API key

    Example:
        # Auto-detect provider
        llm = create_llm()

        # Explicit provider
        llm = create_llm(provider="openai", model="gpt-4")
        llm = create_llm(provider="anthropic", model="claude-3-5-sonnet-20241022")
        llm = create_llm(provider="google", model="gemini-1.5-pro")
    """
    # Determine provider
    if provider is None:
        provider = _detect_provider()

    # Validate provider
    if provider not in ["openai", "anthropic", "google"]:
        raise ValueError(f"Invalid provider: {provider}. Must be one of: openai, anthropic, google")

    # Create provider-specific LLM
    if provider == "openai":
        return _create_openai(model, api_key, temperature)
    elif provider == "anthropic":
        return _create_anthropic(model, api_key, temperature)
    elif provider == "google":
        return _create_google(model, api_key, temperature)

    raise ValueError(f"Unsupported provider: {provider}")


def _detect_provider() -> LLMProvider:
    """
    Auto-detect LLM provider based on environment.

    Priority:
    1. HIVE_LLM_PROVIDER env var
    2. First available API key (openai -> anthropic -> google)

    Returns:
        Detected provider name

    Raises:
        ValueError: If no provider can be detected
    """
    # Check explicit env var
    env_provider = os.getenv("HIVE_LLM_PROVIDER")
    if env_provider:
        logger.info("Using provider from HIVE_LLM_PROVIDER: %s", env_provider)
        return env_provider.lower()  # type: ignore

    # Auto-detect based on API keys
    if os.getenv("OPENAI_API_KEY"):
        logger.info("Auto-detected OpenAI provider (OPENAI_API_KEY found)")
        return "openai"
    elif os.getenv("ANTHROPIC_API_KEY"):
        logger.info("Auto-detected Anthropic provider (ANTHROPIC_API_KEY found)")
        return "anthropic"
    elif os.getenv("GOOGLE_API_KEY"):
        logger.info("Auto-detected Google provider (GOOGLE_API_KEY found)")
        return "google"

    raise ValueError(
        "No LLM provider configured. Set one of:\n"
        "  - HIVE_LLM_PROVIDER=openai|anthropic|google\n"
        "  - OPENAI_API_KEY=sk-...\n"
        "  - ANTHROPIC_API_KEY=sk-ant-...\n"
        "  - GOOGLE_API_KEY=..."
    )


def _create_openai(model: str | None, api_key: str | None, temperature: float) -> BaseChatModel:
    """Create OpenAI chat model."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as e:
        raise ImportError("OpenAI provider requires: pip install langchain-openai") from e

    # Default model
    if model is None:
        model = "gpt-4"
        logger.debug("Using default OpenAI model: %s", model)

    # Get API key
    final_api_key = api_key or os.getenv("OPENAI_API_KEY")
    if not final_api_key:
        raise ValueError("OpenAI API key required. Set OPENAI_API_KEY environment variable.")

    logger.info("Creating OpenAI chat model: %s", model)
    return ChatOpenAI(model=model, api_key=final_api_key, temperature=temperature)


def _create_anthropic(model: str | None, api_key: str | None, temperature: float) -> BaseChatModel:
    """Create Anthropic chat model."""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise ImportError("Anthropic provider requires: pip install langchain-anthropic") from e

    # Default model
    if model is None:
        model = "claude-3-5-sonnet-20241022"
        logger.debug("Using default Anthropic model: %s", model)

    # Get API key
    final_api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
    if not final_api_key:
        raise ValueError("Anthropic API key required. Set ANTHROPIC_API_KEY environment variable.")

    logger.info("Creating Anthropic chat model: %s", model)
    return ChatAnthropic(model=model, anthropic_api_key=final_api_key, temperature=temperature)


def _create_google(model: str | None, api_key: str | None, temperature: float) -> BaseChatModel:
    """Create Google Gemini chat model."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError as e:
        raise ImportError("Google provider requires: pip install langchain-google-genai") from e

    # Default model
    if model is None:
        model = "gemini-1.5-pro"
        logger.debug("Using default Google model: %s", model)

    # Get API key
    final_api_key = api_key or os.getenv("GOOGLE_API_KEY")
    if not final_api_key:
        raise ValueError("Google API key required. Set GOOGLE_API_KEY environment variable.")

    logger.info("Creating Google chat model: %s", model)
    return ChatGoogleGenerativeAI(
        model=model, google_api_key=final_api_key, temperature=temperature
    )
