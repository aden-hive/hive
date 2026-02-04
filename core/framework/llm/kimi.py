import logging
import os
from collections.abc import Callable
from typing import Any

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse

logger = logging.getLogger(__name__)


def _get_api_key_from_credential_manager() -> str | None:
    """Get API key from CredentialManager or environment.

    Priority:
    1. CredentialManager (supports .env hot-reload)
    2. os.environ fallback
    """
    try:
        from aden_tools.credentials import CredentialManager

        creds = CredentialManager()
        if creds.is_available("kimi"):
            return creds.get("kimi")
        if creds.is_available("moonshot"):
            return creds.get("moonshot")
    except ImportError:
        pass
    return os.environ.get("KIMI_API_KEY") or os.environ.get("MOONSHOT_API_KEY")


class KimiProvider(LLMProvider):
    """
    Kimi (Moonshot AI) LLM provider.

    Kimi K2.5 features a "Thinking Mode" which produces a reasoning_content field.
    This provider ensures that reasoning_content is captured and accessible.
    
    Kimi is OpenAI-compatible, so we use LiteLLMProvider internally.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "moonshot-v1-8k",
        api_base: str = "https://api.moonshot.cn/v1",
        **kwargs: Any,
    ):
        """
        Initialize the Kimi provider.

        Args:
            api_key: Kimi/Moonshot API key. If not provided, uses CredentialManager
                     or KIMI_API_KEY/MOONSHOT_API_KEY env var.
            model: Model to use (default: moonshot-v1-8k).
                   For K2.5, use appropriate model name.
            api_base: API base URL (default: Moonshot's official endpoint).
            **kwargs: Additional arguments passed to litellm.completion()
        """
        self.api_key = api_key or _get_api_key_from_credential_manager()
        if not self.api_key:
            raise ValueError(
                "Kimi/Moonshot API key required. Set KIMI_API_KEY or MOONSHOT_API_KEY env var."
            )

        self.model = model
        self.api_base = api_base

        # Kimi is often called via 'moonshot/' prefix in LiteLLM if not using custom base.
        # If api_base is provided, litellm will use it.
        self._provider = LiteLLMProvider(
            model=model,
            api_key=self.api_key,
            api_base=self.api_base,
            **kwargs
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
        """Generate a completion from Kimi (via LiteLLM)."""
        try:
            return self._provider.complete(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
            )
        except Exception as e:
            logger.error(f"Kimi completion error: {str(e)}")
            raise RuntimeError(f"Kimi generation failed: {str(e)}") from e

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable[[ToolUse], ToolResult],
        max_iterations: int = 10,
    ) -> LLMResponse:
        """Run a tool-use loop until Kimi produces a final response (via LiteLLM)."""
        try:
            return self._provider.complete_with_tools(
                messages=messages,
                system=system,
                tools=tools,
                tool_executor=tool_executor,
                max_iterations=max_iterations,
            )
        except Exception as e:
            logger.error(f"Kimi tool completion error: {str(e)}")
            raise RuntimeError(f"Kimi tool generation failed: {str(e)}") from e
