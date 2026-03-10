"""LiteLLM provider for pluggable multi-provider LLM support."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import litellm
    from litellm.exceptions import RateLimitError
except ImportError:
    litellm = None
    RateLimitError = Exception

from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import StreamEvent
from framework.llm.provider_selector import interactive_fallback, quick_provider_check

logger = logging.getLogger(__name__)


def _patch_litellm_anthropic_oauth() -> None:
    """Patch litellm's Anthropic header construction to fix OAuth token handling."""
    try:
        from litellm.llms.anthropic.common_utils import AnthropicModelInfo
        from litellm.types.llms.anthropic import ANTHROPIC_OAUTH_TOKEN_PREFIX
    except ImportError:
        return

    original = AnthropicModelInfo.validate_environment

    def _patched_validate_environment(
        self, headers, model, messages, optional_params, litellm_params, api_key=None, api_base=None
    ):
        result = original(
            self,
            headers,
            model,
            messages,
            optional_params,
            litellm_params,
            api_key=api_key,
            api_base=api_base,
        )
        auth = result.get("authorization", "")
        if auth.startswith(f"Bearer {ANTHROPIC_OAUTH_TOKEN_PREFIX}"):
            result.pop("x-api-key", None)
        return result

    AnthropicModelInfo.validate_environment = _patched_validate_environment


def _patch_litellm_metadata_nonetype() -> None:
    """Patch litellm entry points to prevent metadata=None TypeError."""
    import functools

    for fn_name in ("completion", "acompletion", "responses", "aresponses"):
        original = getattr(litellm, fn_name, None)
        if original is None:
            continue
        if asyncio.iscoroutinefunction(original):

            @functools.wraps(original)
            async def _async_wrapper(*args, _orig=original, **kwargs):
                if kwargs.get("metadata") is None:
                    kwargs.pop("metadata", None)
                return await _orig(*args, **kwargs)

            setattr(litellm, fn_name, _async_wrapper)
        else:

            @functools.wraps(original)
            def _sync_wrapper(*args, _orig=original, **kwargs):
                if kwargs.get("metadata") is None:
                    kwargs.pop("metadata", None)
                return _orig(*args, **kwargs)

            setattr(litellm, fn_name, _sync_wrapper)


if litellm is not None:
    _patch_litellm_anthropic_oauth()
    _patch_litellm_metadata_nonetype()

RATE_LIMIT_MAX_RETRIES = 10
RATE_LIMIT_BACKOFF_BASE = 2
RATE_LIMIT_MAX_DELAY = 120
MINIMAX_API_BASE = "https://api.minimax.io/v1"

EMPTY_STREAM_MAX_RETRIES = 3
EMPTY_STREAM_RETRY_DELAY = 1.0

FAILED_REQUESTS_DIR = Path.home() / ".hive" / "failed_requests"


def _estimate_tokens(model: str, messages: list[dict]) -> tuple[int, str]:
    """Estimate token count for messages. Returns (token_count, method)."""
    if litellm is not None:
        try:
            count = litellm.token_counter(model=model, messages=messages)
            return count, "litellm"
        except Exception:
            pass

    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return total_chars // 4, "estimate"


def _dump_failed_request(model: str, kwargs: dict[str, Any], error_type: str, attempt: int) -> str:
    """Dump failed request to a file for debugging. Returns the file path."""
    FAILED_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    filename = f"{error_type}_{model.replace('/', '_')}_{timestamp}.json"
    filepath = FAILED_REQUESTS_DIR / filename

    messages = kwargs.get("messages", [])
    dump_data = {
        "timestamp": datetime.now().isoformat(),
        "model": model,
        "error_type": error_type,
        "attempt": attempt,
        "estimated_tokens": _estimate_tokens(model, messages),
        "num_messages": len(messages),
        "messages": messages,
        "tools": kwargs.get("tools"),
        "max_tokens": kwargs.get("max_tokens"),
        "temperature": kwargs.get("temperature"),
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=2, default=str)

    return str(filepath)


def _compute_retry_delay(
    attempt: int,
    exception: BaseException | None = None,
    backoff_base: int = RATE_LIMIT_BACKOFF_BASE,
    max_delay: int = RATE_LIMIT_MAX_DELAY,
) -> float:
    """Compute retry delay, preferring server-provided Retry-After headers."""
    if exception is not None:
        response = getattr(exception, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                retry_after_ms = headers.get("retry-after-ms")
                if retry_after_ms is not None:
                    try:
                        delay = float(retry_after_ms) / 1000.0
                        return min(max(delay, 0), max_delay)
                    except (ValueError, TypeError):
                        pass

                retry_after = headers.get("retry-after")
                if retry_after is not None:
                    try:
                        delay = float(retry_after)
                        return min(max(delay, 0), max_delay)
                    except (ValueError, TypeError):
                        pass

                    try:
                        from email.utils import parsedate_to_datetime

                        retry_date = parsedate_to_datetime(retry_after)
                        now = datetime.now(retry_date.tzinfo)
                        delay = (retry_date - now).total_seconds()
                        return min(max(delay, 0), max_delay)
                    except (ValueError, TypeError, OverflowError):
                        pass

    delay = backoff_base * (2**attempt)
    return min(delay, max_delay)


def _is_stream_transient_error(exc: BaseException) -> bool:
    """Classify whether a streaming exception is transient (recoverable)."""
    try:
        from litellm.exceptions import (
            APIConnectionError,
            BadGatewayError,
            InternalServerError,
            ServiceUnavailableError,
        )

        transient_types: tuple[type[BaseException], ...] = (
            APIConnectionError,
            InternalServerError,
            BadGatewayError,
            ServiceUnavailableError,
            TimeoutError,
            ConnectionError,
            OSError,
        )
    except ImportError:
        transient_types = (TimeoutError, ConnectionError, OSError)

    return isinstance(exc, transient_types)


class LiteLLMProvider(LLMProvider):
    """LiteLLM-based LLM provider for multi-provider support."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ):
        """Initialize the LiteLLM provider."""
        self.model = model
        self.api_key = api_key
        self.api_base = api_base or self._default_api_base_for_model(model)
        self.extra_kwargs = kwargs
        self._codex_backend = bool(
            self.api_base and "chatgpt.com/backend-api/codex" in self.api_base
        )

        if litellm is None:
            raise ImportError(
                "LiteLLM is not installed. Please install it with: uv pip install litellm"
            )

        # Run quick provider check at startup if no config
        asyncio.create_task(self._initial_provider_check())

    async def _initial_provider_check(self):
        """Check for working providers at startup if none configured."""
        from framework.config import get_hive_config

        config = get_hive_config()
        if not config.get("llm", {}).get("provider"):
            selection = await quick_provider_check()
            if selection:
                self.model = selection["model"]
                if selection["provider"] != "gemini":
                    self.model = f"{selection['provider']}/{selection['model']}"
                self.api_key = selection.get("api_key")

    @staticmethod
    def _default_api_base_for_model(model: str) -> str | None:
        """Return provider-specific default API base when required."""
        model_lower = model.lower()
        if model_lower.startswith("minimax/") or model_lower.startswith("minimax-"):
            return MINIMAX_API_BASE
        return None

    async def _acompletion_with_rate_limit_retry(
        self, max_retries: int | None = None, **kwargs: Any
    ) -> Any:
        """Async version with interactive fallback on failure."""
        model = kwargs.get("model", self.model)
        retries = max_retries if max_retries is not None else RATE_LIMIT_MAX_RETRIES

        for attempt in range(retries + 1):
            try:
                return await litellm.acompletion(**kwargs)

            except Exception as e:
                # Check if it's a credit/authentication error
                error_str = str(e).lower()
                is_credit_error = (
                    "credit" in error_str
                    or "balance" in error_str
                    or "invalid" in error_str
                    or "auth" in error_str
                    or "key" in error_str
                    or "permission" in error_str
                )

                # On first attempt with credit error, offer interactive fallback
                if attempt == 0 and is_credit_error:
                    # Get original provider from model string
                    original_provider = model.split("/")[0] if "/" in model else model

                    logger.info(f"Provider {original_provider} failed: {e}")

                    # Show interactive menu
                    selection = await interactive_fallback(original_provider, e)

                    if selection and selection.get("retry"):
                        # User wants to retry with original
                        continue
                    elif selection:
                        # Update kwargs with new provider
                        if selection["provider"] == "gemini":
                            kwargs["model"] = selection["model"]
                        else:
                            kwargs["model"] = f"{selection['provider']}/{selection['model']}"

                        if selection.get("api_key"):
                            kwargs["api_key"] = selection["api_key"]

                        # Update instance for future calls
                        self.model = kwargs["model"]
                        if selection.get("api_key"):
                            self.api_key = selection["api_key"]

                        logger.info(f"Retrying with {selection['name']}...")
                        continue
                    else:
                        # User chose to abort
                        raise

                # Handle rate limits with backoff
                if isinstance(e, RateLimitError) and attempt < retries:
                    wait = _compute_retry_delay(attempt, exception=e)
                    logger.warning(f"Rate limited, retrying in {wait}s...")
                    await asyncio.sleep(wait)
                    continue

                # For other errors or exhausted retries, re-raise
                if attempt == retries:
                    logger.error(f"GAVE UP after {retries + 1} attempts")
                raise

    # Rest of the file remains the same...
    # [The rest of litellm.py methods continue here unchanged]
