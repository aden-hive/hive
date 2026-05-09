"""OpenRouter LLM provider — free and open-source model access via openrouter.ai.

Provides OpenRouterProvider, a thin wrapper around LiteLLMProvider that:
  - Pre-configures the OpenRouter endpoint
  - Exposes a free-model alias system (short name -> full model ID)
  - Integrates with the Hive credential store (OPENROUTER_API_KEY)
  - Implements a fallback chain across free models on 429 rate-limit errors

Free models (zero API cost, no credit card):
    openai/gpt-oss-120b:free
    google/gemma-3-12b-it:free
    google/gemma-3-27b-it:free
    meta-llama/llama-3.2-3b-instruct:free
    qwen/qwen3-coder:free

Get a free key at: https://openrouter.ai/keys
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import LLMProvider, LLMResponse, Tool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Free model alias registry
# ---------------------------------------------------------------------------

FREE_MODELS: dict[str, str] = {
    "llama-3.2-3b": "meta-llama/llama-3.2-3b-instruct:free",
    "llama-3.2-1b": "meta-llama/llama-3.2-1b-instruct:free",
    "gemma-3-4b": "google/gemma-3-4b-it:free",
    "gemma-3-12b": "google/gemma-3-12b-it:free",
    "gemma-3-27b": "google/gemma-3-27b-it:free",
    "qwen3-30b": "qwen/qwen3-coder:free",
    "gpt-oss-120b": "openai/gpt-oss-120b:free",
}

# Ordered fallback chain — tried in sequence on 429 rate-limit errors
FALLBACK_CHAIN: list[str] = [
    "openai/gpt-oss-120b:free",
    "google/gemma-3-12b-it:free",
]

DEFAULT_FREE_MODEL = "openai/gpt-oss-120b:free"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"


def _resolve_model(model: str) -> str:
    """Resolve a short alias (e.g. 'gpt-oss-120b') to its full OpenRouter model ID."""
    return FREE_MODELS.get(model, model)


def _get_api_key() -> str | None:
    """Read the OpenRouter API key from the Hive credential store or env.

    Uses is_available() before calling get() so we never raise KeyError
    on an unregistered credential name. All exceptions fall back to the
    OPENROUTER_API_KEY environment variable.
    """
    try:
        from aden_tools.credentials import CredentialStoreAdapter

        creds = CredentialStoreAdapter.default()
        # is_available() checks only the underlying store (not _specs),
        # so it returns False without raising when the spec isn't registered.
        if creds.is_available("openrouter"):
            return creds.get("openrouter")
    except (ImportError, KeyError, Exception):
        # ImportError  — aden_tools not installed (unit test environment)
        # KeyError     — 'openrouter' not in _specs (tools/__init__.py not updated)
        # Exception    — any other store initialisation or retrieval failure
        pass
    return os.environ.get("OPENROUTER_API_KEY")


def _build_litellm(model: str, api_key: str, site_url: str, site_name: str) -> LiteLLMProvider:
    """Build a LiteLLMProvider configured for OpenRouter."""
    litellm_model = f"openrouter/{model}" if not model.startswith("openrouter/") else model
    return LiteLLMProvider(
        model=litellm_model,
        api_key=api_key,
        api_base=OPENROUTER_API_BASE,
        extra_headers={
            "HTTP-Referer": site_url,
            "X-Title": site_name,
        },
    )


class OpenRouterProvider(LLMProvider):
    """
    OpenRouter LLM provider with automatic fallback on rate-limit (429) errors.

    Wraps LiteLLMProvider with:
    - OpenRouter endpoint pre-configured
    - Free-model alias system (e.g. "gpt-oss-120b" -> full ID)
    - Automatic failover through FALLBACK_CHAIN on 429 errors

    Args:
        model:          Full OpenRouter model ID or short alias.
                        Defaults to openai/gpt-oss-120b:free.
        api_key:        OpenRouter API key. Falls back to OPENROUTER_API_KEY env var.
        site_url:       HTTP-Referer header for OpenRouter attribution.
        site_name:      X-Title header for OpenRouter attribution.
        use_fallback:   If True (default), retry with FALLBACK_CHAIN on 429.

    Examples:
        provider = OpenRouterProvider()
        provider = OpenRouterProvider(model="gemma-3-27b")
        provider = OpenRouterProvider(model="openai/gpt-oss-120b:free", api_key="sk-or-...")
    """

    def __init__(
        self,
        model: str = DEFAULT_FREE_MODEL,
        api_key: str | None = None,
        site_url: str = "https://github.com/your-project",
        site_name: str = "Hive Agent",
        use_fallback: bool = True,
    ):
        resolved = _resolve_model(model)
        self.model = resolved
        self.api_key = api_key or _get_api_key()
        self.site_url = site_url
        self.site_name = site_name
        self.use_fallback = use_fallback

        if not self.api_key:
            raise ValueError(
                "OpenRouter API key not found.\n"
                "  1. Get a free key at https://openrouter.ai/keys\n"
                "  2. export OPENROUTER_API_KEY=sk-or-v1-...\n"
                "     OR pass api_key= to OpenRouterProvider()"
            )

        self._provider = _build_litellm(self.model, self.api_key, self.site_url, self.site_name)

    def _fallback_chain(self) -> list[str]:
        """Return fallback models excluding the primary."""
        return [m for m in FALLBACK_CHAIN if m != self.model]

    def _try_fallback(self, exc: Exception, kwargs: dict[str, Any]) -> LLMResponse:
        """Try each fallback model in order on rate-limit errors (sync)."""
        try:
            from litellm.exceptions import RateLimitError
        except ImportError:
            raise exc from None

        if not isinstance(exc, RateLimitError) or not self.use_fallback:
            raise exc

        last_exc = exc
        for fallback_model in self._fallback_chain():
            logger.warning(
                "OpenRouter: %s rate-limited, trying fallback %s",
                self.model,
                fallback_model,
            )
            try:
                provider = _build_litellm(
                    fallback_model, self.api_key, self.site_url, self.site_name
                )
                return provider.complete(**kwargs)
            except RateLimitError as e:
                last_exc = e
                continue
            except Exception as e:
                raise e
        raise last_exc

    async def _try_fallback_async(self, exc: Exception, kwargs: dict[str, Any]) -> LLMResponse:
        """Try each fallback model in order on rate-limit errors (async)."""
        try:
            from litellm.exceptions import RateLimitError
        except ImportError:
            raise exc from None

        if not isinstance(exc, RateLimitError) or not self.use_fallback:
            raise exc

        last_exc = exc
        for fallback_model in self._fallback_chain():
            logger.warning(
                "OpenRouter: %s rate-limited, trying fallback %s",
                self.model,
                fallback_model,
            )
            try:
                provider = _build_litellm(
                    fallback_model, self.api_key, self.site_url, self.site_name
                )
                return await provider.acomplete(**kwargs)
            except RateLimitError as e:
                last_exc = e
                await asyncio.sleep(1)
                continue
            except Exception as e:
                raise e
        raise last_exc

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
        kwargs = {
            "messages": messages,
            "system": system,
            "tools": tools,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "json_mode": json_mode,
            "max_retries": max_retries,
        }
        try:
            return self._provider.complete(**kwargs)
        except Exception as exc:
            return self._try_fallback(exc, kwargs)

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
        kwargs = {
            "messages": messages,
            "system": system,
            "tools": tools,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "json_mode": json_mode,
            "max_retries": max_retries,
        }
        try:
            return await self._provider.acomplete(**kwargs)
        except Exception as exc:
            return await self._try_fallback_async(exc, kwargs)

    def list_free_models(self) -> dict[str, str]:
        """Return all built-in free model aliases and their full OpenRouter IDs."""
        return dict(FREE_MODELS)
