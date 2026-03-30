"""Anthropic Claude LLM provider - DEPRECATED.

This provider is deprecated and will be removed in a future version.
Please use LiteLLMProvider via get_llm_provider() instead, which respects
your configuration and supports all providers.
"""

from __future__ import annotations

import json
import logging
import os
import warnings
from pathlib import Path
from typing import Any

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.provider_models import get_model_info
from framework.config import get_hive_config

logger = logging.getLogger(__name__)


def _get_llm_config() -> dict[str, Any]:
    """Get current LLM configuration from shared config loader."""
    config = get_hive_config()
    llm_config = config.get("llm", {})

    # Fallback to environment for missing keys
    if not llm_config.get("provider"):
        llm_config["provider"] = os.environ.get("MODEL_PROVIDER", "").lower()
    if not llm_config.get("model"):
        llm_config["model"] = os.environ.get("LITELLM_MODEL", "")
    if not llm_config.get("api_key"):
        llm_config["api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")

    return llm_config


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
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        """Initialize Anthropic provider with configuration check.

        Args:
            api_key: Anthropic API key (optional, will check env/config if not provided)
            model: Model name (optional, will use config if not provided)

        Raises:
            ValueError: If Anthropic is not the configured provider or API key missing
        """
        # Emit deprecation warning only when class is instantiated
        warnings.warn(
            "AnthropicProvider is deprecated and will be removed in a future version. "
            "Use framework.llm.get_llm_provider() instead which respects your configuration.",
            DeprecationWarning,
            stacklevel=3,
        )
        logger.warning(
            "AnthropicProvider is deprecated. Please update your code to use "
            "get_llm_provider() from framework.llm which automatically selects "
            "the correct provider based on your configuration."
        )

        # Check if user actually wants Anthropic
        config = _get_llm_config()
        selected_provider = config.get("provider", "").lower()

        # Only block when provider is set to something else AND no explicit params
        if (
            selected_provider
            and selected_provider not in ["anthropic", "claude"]
            and api_key is None
            and model is None
        ):
            raise ValueError(
                f"AnthropicProvider used but your LLM provider is set to '{selected_provider}'. "
                f"This usually means a bug in the code is forcing Anthropic when it shouldn't.\n\n"
                f"To fix this:\n"
                f"1. Run './quickstart.sh' again\n"
                f"2. Select your desired provider (Gemini, Groq, etc.)\n"
                f"3. If the error persists, please report this issue."
            )

        # For Anthropic users, get the API key
        self.api_key = api_key or _get_api_key_from_credential_store()
        if not self.api_key and selected_provider in {"anthropic", "claude"}:
            raise ValueError(
                "Anthropic API key required but not found. "
                "Please set ANTHROPIC_API_KEY environment variable or configure it in quickstart."
            )

        # Use model from config, or passed model, or fallback
        self.model = (
            model
            or config.get("model")
            or os.environ.get("LITELLM_MODEL")
            or "claude-haiku-4-5-20251001"  # Original default - maintain compatibility
        )

        logger.info(f"Initializing AnthropicProvider with model: {self.model}")

        self._provider = LiteLLMProvider(
            model=self.model,
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
        """Generate a completion from Claude (via LiteLLM)."""
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
        """Async completion via LiteLLM."""
        return await self._provider.acomplete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
            max_retries=max_retries,
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ):
        """Stream responses from Claude."""
        return self._provider.stream(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
        )

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using Claude's tokenizer."""
        return self._provider.count_tokens(text)

    def get_model_info(self) -> dict[str, Any]:
        """Get accurate information about the current model."""
        # Delegate to the wrapped provider for accurate metadata
        wrapped_info = self._provider.get_model_info() if hasattr(self._provider, "get_model_info") else {}

        # Get model info from registry for the specific model
        model_info = get_model_info("anthropic", self.model) if self.model else None

        # Merge sources, preferring registry info for accuracy
        if model_info:
            return {
                "provider": "anthropic",
                "model": self.model,
                "max_tokens": model_info.get("max_tokens", 200000),
                "supports_tools": model_info.get("supports_tools", True),
                "supports_streaming": model_info.get("supports_streaming", True),
                "supports_json_mode": model_info.get("supports_json_mode", True),
                **wrapped_info,
            }

        # Fallback to wrapped provider info
        return {
            "provider": "anthropic",
            "model": self.model,
            "max_tokens": wrapped_info.get("max_tokens", 200000),
            "supports_tools": wrapped_info.get("supports_tools", True),
            "supports_streaming": wrapped_info.get("supports_streaming", True),
            "supports_json_mode": wrapped_info.get("supports_json_mode", True),
        }

    def validate_api_key(self) -> bool:
        """Validate that the API key is working."""
        return self._provider.validate_api_key()

    def get_remaining_quota(self) -> dict[str, Any] | None:
        """Get remaining quota information if available."""
        return self._provider.get_remaining_quota()

    def __repr__(self) -> str:
        return f"AnthropicProvider(model={self.model})"

    def __str__(self) -> str:
        return f"Anthropic Claude ({self.model})"
