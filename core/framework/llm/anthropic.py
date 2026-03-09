"""Anthropic Claude LLM provider - backward compatible wrapper around LiteLLM."""

import os
from typing import Any

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse, Tool


def _get_api_key_from_credential_store() -> str | None:
    """Get API key from CredentialStoreAdapter or environment.

    Priority:
    1. CredentialStoreAdapter (supports encrypted storage + env vars)
    2. os.environ fallback
    """
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
    Anthropic Claude LLM provider.

    This is a backward-compatible wrapper that internally uses LiteLLMProvider.
    Existing code using AnthropicProvider will continue to work unchanged,
    while benefiting from LiteLLM's unified interface and features.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-haiku-4-5-20251001",
    ):
        """
        Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key. If not provided, uses CredentialStoreAdapter
                     or ANTHROPIC_API_KEY env var.
            model: Model to use (default: claude-haiku-4-5-20251001)
        """
        # Delegate to LiteLLMProvider internally.
        self.api_key = api_key or _get_api_key_from_credential_store()
        if not self.api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY env var or pass api_key."
            )

        self.model = model

        self._provider = LiteLLMProvider(
            model=model,
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
