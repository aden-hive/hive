"""Anthropic Claude LLM provider - DEPRECATED.

This provider is deprecated and will be removed in a future version.
Please use LiteLLMProvider via get_llm_provider() instead, which respects
your configuration and supports all providers.

The get_llm_provider() function automatically returns the correct provider
based on your ~/.hive/configuration.json settings.
"""

import logging
import os
import warnings
from typing import Any

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse, Tool

logger = logging.getLogger(__name__)

# Show deprecation warning when module is imported
warnings.warn(
    "AnthropicProvider is deprecated and will be removed in a future version. "
    "Use framework.llm.get_llm_provider() instead which respects your configuration.",
    DeprecationWarning,
    stacklevel=2
)

logger.warning(
    " AnthropicProvider is deprecated. Please update your code to use "
    "get_llm_provider() from framework.llm which automatically selects "
    "the correct provider based on your configuration."
)


def _check_configuration() -> tuple[bool, str]:
    """Check if Anthropic is actually configured in user settings.
    
    Returns:
        Tuple of (is_configured, message)
    """
    try:
        from framework.config import get_hive_config
        
        config = get_hive_config()
        llm_config = config.get("llm", {})
        provider = llm_config.get("provider", "").lower()
        
        if provider and provider not in ["anthropic", "claude"]:
            return False, f"Your LLM provider is set to '{provider}' not Anthropic"
        
        return True, "Anthropic configured"
    except ImportError:
        # If config module not available, assume it might be configured
        return True, "Configuration check skipped"


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
    """
    Anthropic Claude LLM provider - DEPRECATED.
    
    This class is maintained for backward compatibility but will be removed.
    Please migrate to using get_llm_provider() from framework.llm instead.
    
    The new provider system:
    - Automatically uses your configured provider (Gemini, Groq, etc.)
    - Shows interactive menu if your selected provider fails
    - Persists your choice for future sessions
    - Supports all providers through LiteLLM
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        """Initialize Anthropic provider with configuration check.
        
        Args:
            api_key: Anthropic API key (optional, will check env/config if not provided)
            model: Model name (optional, will use config if not provided)
            
        Raises:
            ValueError: If Anthropic is not the configured provider or API key missing
        """
        # Check if user actually wants Anthropic
        is_configured, config_message = _check_configuration()
        if not is_configured:
            raise ValueError(
                f" AnthropicProvider used but {config_message}.\n\n"
                f"This usually means code is forcing Anthropic when it shouldn't.\n"
                f"To fix this:\n"
                f"1. Run './quickstart.sh' to reconfigure your LLM provider\n"
                f"2. Use get_llm_provider() instead of directly instantiating AnthropicProvider\n"
                f"3. If you see this error in Hive core code, please report it on GitHub"
            )
        
        # Get API key
        self.api_key = api_key or _get_api_key_from_credential_store()
        
        # Get model from config or parameter
        if model is None:
            try:
                from framework.config import get_hive_config
                config = get_hive_config().get("llm", {})
                self.model = config.get("model", "claude-3-haiku-20240307")
            except ImportError:
                self.model = "claude-3-haiku-20240307"
        else:
            self.model = model
        
        # Log deprecation with context
        logger.info(
            f" AnthropicProvider is deprecated - use get_llm_provider() instead. "
            f"Model: {self.model}"
        )
        
        # Use LiteLLM internally
        self._provider = LiteLLMProvider(
            model=f"anthropic/{self.model}",
            api_key=self.api_key,
        )

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