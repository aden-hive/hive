"""Anthropic Claude LLM provider - backward compatible wrapper around LiteLLM."""

import os
from typing import Any

from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.litellm import LiteLLMProvider


def _get_api_key_from_credential_manager() -> str | None:
    """Get API key from CredentialManager or environment.

    Priority:
    1. CredentialManager (supports .env hot-reload)
    2. os.environ fallback
    """
    try:
        from aden_tools.credentials import CredentialManager

        creds = CredentialManager()
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
            api_key: Anthropic API key. If not provided, uses CredentialManager
                     or ANTHROPIC_API_KEY env var.
            model: Model to use (default: claude-haiku-4-5-20251001)
        """
        # Delegate to LiteLLMProvider internally.
        self.api_key = api_key or _get_api_key_from_credential_manager()
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
    ) -> LLMResponse:
        """Generate a completion from Claude (via LiteLLM)."""
        return self._provider.complete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            response_format=response_format,
            json_mode=json_mode,
        )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: callable,
        max_iterations: int = 10,
    ) -> LLMResponse:
        """Run a tool-use loop until Claude produces a final response (via LiteLLM)."""
        return self._provider.complete_with_tools(
            messages=messages,
            system=system,
            tools=tools,
            tool_executor=tool_executor,
            max_iterations=max_iterations,
        )
