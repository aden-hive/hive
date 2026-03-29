"""Anthropic Claude LLM provider - DEPRECATED.

This provider is deprecated and will be removed in a future version.
Please use LiteLLMProvider via get_llm_provider() instead, which respects
your configuration and supports all providers.
"""

import logging
import os
import warnings
from typing import Any
import json
import logging
import warnings
from pathlib import Path
from typing import Any
from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse, Tool

logger = logging.getLogger(__name__)

# Show deprecation warning when module is imported
warnings.warn(
    "AnthropicProvider is deprecated and will be removed in a future version. "
    "Use framework.llm.get_llm_provider() instead which respects your configuration.",
    DeprecationWarning,
    stacklevel=2,
)

logger.warning(
    "AnthropicProvider is deprecated. Please update your code to use "
    "get_llm_provider() from framework.llm which automatically selects "
    "the correct provider based on your configuration."
)


def _get_llm_config():
    """Get current LLM configuration from ~/.hive/config.json."""
    config_path = Path.home() / ".hive" / "configuration.json"
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
                return config.get("llm", {})
        except Exception as e:
            logger.debug(f"Failed to read config: {e}")

    # Fallback to environment
    return {
        "provider": os.environ.get("MODEL_PROVIDER", "").lower(),
        "model": os.environ.get("LITELLM_MODEL", ""),
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    }


def _get_api_key_from_credential_store() -> str | None:
    """Get API key from CredentialStoreAdapter or environment."""
    try:
        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.default()
        if creds.is_available("anthropic"):
            return creds.get("anthropic")
    except ImportError:
        pass
    return os.environ.get("ANTHROPIC_API_KEY")


class AnthropicProvider(LLMProvider):
    """Anthropic Claude LLM provider - DEPRECATED.

    This class is maintained for backward compatibility but will be removed.
    Please migrate to using get_llm_provider() from framework.llm instead.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        """Initialize Anthropic provider with configuration check.

        Args:
            api_key: Anthropic API key (optional, will check env/config if not provided)
            model: Model name (optional, will use config if not provided)

        Raises:
            ValueError: If Anthropic is not the configured provider or API key missing
        """
        # Check if user actually wants Anthropic
        config = _get_llm_config()
        selected_provider = config.get("provider", "").lower()

        # Check if user actually wants Anthropic
        if selected_provider and selected_provider not in ["anthropic", "claude"]:
            raise ValueError(
                f"AnthropicProvider used but your LLM provider is set to '{selected_provider}'. "
                "This usually means a bug in the code is forcing Anthropic when it shouldn't.\n\n"
                "To fix this:\n"
                "1. Run './quickstart.sh' again\n"
                "2. Select your desired provider (Gemini, Groq, etc.)\n"
                "3. If the error persists, please report this issue."
            )

        # For Anthropic users, get the API key
        self.api_key = api_key or _get_api_key_from_credential_store()
        if not self.api_key and selected_provider == "anthropic":
            raise ValueError(
                "Anthropic API key required but not found. "
                "Please set ANTHROPIC_API_KEY environment variable or configure it in quickstart."
            )

        # Use model from config, or passed model, or fallback
        self.model = (
            model
            or config.get("model")
            or os.environ.get("LITELLM_MODEL")
            or "claude-3-haiku-20240307"  # Safe fallback
        )

        logger.info(f"Initializing AnthropicProvider with model: {self.model}")

        self._provider = LiteLLMProvider(model=self.model, api_key=self.api_key)

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Generate a completion (deprecated)."""
        return self._provider.complete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
            max_retries=max_retries,
        )

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Async completion (deprecated)."""
        return await self._provider.acomplete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
            max_retries=max_retries,
        )
