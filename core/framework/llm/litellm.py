"""LiteLLM provider for pluggable multi-provider LLM support.

LiteLLM provides a unified, OpenAI-compatible interface that supports
multiple LLM providers including OpenAI, Anthropic, Gemini, Mistral,
Groq, and local models.

See: https://docs.litellm.ai/docs/providers
"""

import asyncio
import json
import logging
import time
import os
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import litellm
    from litellm.exceptions import RateLimitError
except ImportError:
    litellm = None  # type: ignore[assignment]
    RateLimitError = Exception  # type: ignore[assignment, misc]

from framework.config import HIVE_LLM_ENDPOINT as HIVE_API_BASE
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import StreamEvent
from framework.llm.provider_selector import interactive_fallback, quick_provider_check
from framework.config import (
    get_model_api_name_from_config,
    get_provider_from_config,
    get_model_capabilities_from_config,
    get_model_max_tokens
)
from framework.llm.provider_models import get_model_info

logger = logging.getLogger(__name__)


def _patch_litellm_anthropic_oauth() -> None:
    """Patch litellm's Anthropic header construction to fix OAuth token handling."""
    try:
        from litellm.llms.anthropic.common_utils import AnthropicModelInfo
        from litellm.types.llms.anthropic import ANTHROPIC_OAUTH_TOKEN_PREFIX
    except ImportError:
        logger.warning(
            "Could not apply litellm Anthropic OAuth patch — litellm internals may have "
            "changed. Anthropic OAuth tokens (Claude Code subscriptions) may fail with 401. "
            "See BerriAI/litellm#19618. Current litellm version: %s",
            getattr(litellm, "__version__", "unknown"),
        )
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

    patched_count = 0
    for fn_name in ("completion", "acompletion", "responses", "aresponses"):
        original = getattr(litellm, fn_name, None)
        if original is None:
            continue
        patched_count += 1
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

    if patched_count == 0:
        logger.warning(
            "Could not apply litellm metadata=None patch — none of the expected entry "
            "points (completion, acompletion, responses, aresponses) were found. "
            "metadata=None TypeError may occur. Current litellm version: %s",
            getattr(litellm, "__version__", "unknown"),
        )


if litellm is not None:
    _patch_litellm_anthropic_oauth()
    _patch_litellm_metadata_nonetype()

RATE_LIMIT_MAX_RETRIES = 10
RATE_LIMIT_BACKOFF_BASE = 2
RATE_LIMIT_MAX_DELAY = 120
MINIMAX_API_BASE = "https://api.minimax.io/v1"

# Providers that accept cache_control on message content blocks.
# Anthropic: native ephemeral caching. MiniMax & Z-AI/GLM: pass-through to their APIs.
# (OpenAI caches automatically server-side; Groq/Gemini/etc. strip the header.)
_CACHE_CONTROL_PREFIXES = (
    "anthropic/",
    "claude-",
    "minimax/",
    "minimax-",
    "MiniMax-",
    "zai-glm",
    "glm-",
)


def _model_supports_cache_control(model: str) -> bool:
    return any(model.startswith(p) for p in _CACHE_CONTROL_PREFIXES)


# Kimi For Coding uses an Anthropic-compatible endpoint (no /v1 suffix).
# Claude Code integration uses this format; the /v1 OpenAI-compatible endpoint
# enforces a coding-agent whitelist that blocks unknown User-Agents.
KIMI_API_BASE = "https://api.kimi.com/coding"

# Empty-stream retries use a short fixed delay, not the rate-limit backoff.
# Conversation-structure issues are deterministic — long waits don't help.
EMPTY_STREAM_MAX_RETRIES = 3
EMPTY_STREAM_RETRY_DELAY = 1.0

FAILED_REQUESTS_DIR = Path.home() / ".hive" / "failed_requests"

# Maximum number of dump files to retain in ~/.hive/failed_requests/.
# Older files are pruned automatically to prevent unbounded disk growth.
MAX_FAILED_REQUEST_DUMPS = 50


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

def _prune_failed_request_dumps(max_files: int = MAX_FAILED_REQUEST_DUMPS) -> None:
    """Remove oldest dump files when the count exceeds *max_files*.

    Best-effort: never raises — a pruning failure must not break retry logic.
    """
    try:
        all_dumps = sorted(
            FAILED_REQUESTS_DIR.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
        )
        excess = len(all_dumps) - max_files
        if excess > 0:
            for old_file in all_dumps[:excess]:
                old_file.unlink(missing_ok=True)
    except Exception:
        pass  # Best-effort — never block the caller


def _dump_failed_request(
    model: str,
    kwargs: dict[str, Any],
    error_type: str,
    attempt: int,
) -> str:

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

    # Prune old dumps to prevent unbounded disk growth
    _prune_failed_request_dumps()

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
    """
    LiteLLM-based LLM provider for multi-provider support.
    
    Now supports model display names and capability detection.
    """

    def __init__(
    self,
    model: str | None = None,
    api_key: str | None = None,
    api_base: str | None = None,
    provider: str | None = None,
    **kwargs: Any,
):
        """
        Initialize the LiteLLM provider.
        
        Args:
            model: Model identifier (can be API name or display name)
            api_key: API key for the provider
            api_base: Custom API base URL
            provider: Provider name (anthropic, openai, gemini, etc.)
            **kwargs: Additional arguments passed to litellm.completion()
        """

        # DEBUG: Print what's coming in
        print(f"🔍 DEBUG - __init__ called with model={model}, provider={provider}")
        
        # If model not provided, load from config
        if model is None:
            self.model_api_name = get_model_api_name_from_config()
            self.provider = provider or get_provider_from_config()
            print(f"🔍 DEBUG - Loaded from config: model_api_name={self.model_api_name}, provider={self.provider}")
        else:
            # Try to resolve model name
            self.model_api_name = model
            self.provider = provider
            print(f"🔍 DEBUG - Using passed values: model_api_name={self.model_api_name}, provider={self.provider}")
        
        # ========== EMERGENCY PROVIDER DETECTION ==========
        # This catches cases where provider is missing but can be inferred from model name
        if self.provider is None and self.model_api_name:
            model_lower = self.model_api_name.lower()
            
            # Check if model already has provider prefix (e.g., "gemini/gemini-2.5-flash")
            if "/" in self.model_api_name:
                # Extract provider from prefix
                possible_provider = self.model_api_name.split("/")[0].lower()
                if possible_provider in ["gemini", "anthropic", "openai", "groq", "cerebras"]:
                    self.provider = possible_provider
                    logger.info(f"🔍 Extracted provider '{self.provider}' from model prefix")
            else:
                # Try to detect provider from model name
                if "gemini" in model_lower:
                    self.provider = "gemini"
                    # Add the provider prefix to the model for consistency
                    self.model_api_name = f"gemini/{self.model_api_name}"
                    logger.info(f"🔍 Emergency fixed: Using {self.model_api_name} with provider gemini")
                elif "claude" in model_lower:
                    self.provider = "anthropic"
                    self.model_api_name = f"anthropic/{self.model_api_name}"
                    logger.info(f"🔍 Emergency fixed: Using {self.model_api_name} with provider anthropic")
                elif "gpt" in model_lower or "gpt-4" in model_lower or "gpt-3.5" in model_lower:
                    self.provider = "openai"
                    self.model_api_name = f"openai/{self.model_api_name}"
                    logger.info(f"🔍 Emergency fixed: Using {self.model_api_name} with provider openai")
                elif "llama" in model_lower or "mixtral" in model_lower or "gemma" in model_lower:
                    self.provider = "groq"
                    self.model_api_name = f"groq/{self.model_api_name}"
                    logger.info(f"🔍 Emergency fixed: Using {self.model_api_name} with provider groq")
        # =================================================
        
        # Get model info for display name and capabilities
        self.model_info = None
        if self.provider and self.model_api_name:
            # Remove any duplicate provider prefix before looking up in provider_models
            lookup_name = self.model_api_name
            if "/" in lookup_name:
                # Extract just the model name part after the provider/
                lookup_name = lookup_name.split("/")[-1]
            
            # Try to get model info
            try:
                self.model_info = get_model_info(self.provider, lookup_name)
                if self.model_info:
                    logger.debug(f"Found model info for {self.provider}/{lookup_name}")
            except Exception as e:
                logger.debug(f"Could not get model info: {e}")
                self.model_info = None
        
        # Set display name
        if self.model_info:
            self.model_display_name = self.model_info["name"]
        else:
            # Clean up display name by removing provider prefix
            display_name = self.model_api_name or "Unknown"
            if "/" in display_name:
                display_name = display_name.split("/")[-1]
            self.model_display_name = display_name
        
        # CRITICAL FIX: LiteLLM needs provider/model format for ALL providers
        if self.provider and self.model_api_name:
            # If model already has provider prefix, use it as-is
            if "/" in self.model_api_name:
                self.model = self.model_api_name
                logger.info(f"🔍 Using model with existing prefix: {self.model}")
            else:
                # Add provider prefix
                self.model = f"{self.provider}/{self.model_api_name}"
                logger.info(f"🔍 Using model with added prefix: {self.model}")
            
            # Set API key for Gemini
            if self.provider == "gemini" and api_key:
                os.environ["GEMINI_API_KEY"] = api_key
                logger.info(f"🔍 Gemini API key set")
            
            # For OpenAI, set the API key
            if self.provider == "openai" and api_key:
                os.environ["OPENAI_API_KEY"] = api_key
                
            # For Anthropic, set the API key
            if self.provider == "anthropic" and api_key:
                os.environ["ANTHROPIC_API_KEY"] = api_key
                
            # For Groq, set the API key
            if self.provider == "groq" and api_key:
                os.environ["GROQ_API_KEY"] = api_key
                
            # For Cerebras, set the API key
            if self.provider == "cerebras" and api_key:
                os.environ["CEREBRAS_API_KEY"] = api_key
        else:
            self.model = self.model_api_name or "gpt-3.5-turbo"
            logger.warning(f"⚠️ No provider specified, using model: {self.model}")
        
        # Get capabilities
        if self.model_info:
            self.capabilities = {
                "streaming": self.model_info["supports_streaming"],
                "tools": self.model_info["supports_tools"],
                "json_mode": self.model_info["supports_json_mode"]
            }
            logger.debug(f"Loaded capabilities from model info: {self.capabilities}")
        else:
            self.capabilities = get_model_capabilities_from_config()
            logger.debug(f"Loaded capabilities from config: {self.capabilities}")
        
        self.api_key = api_key
        self.api_base = api_base or self._default_api_base_for_model(self.model)

        # Kimi For Coding exposes an Anthropic-compatible endpoint at
        # https://api.kimi.com/coding (the same format Claude Code uses natively).
        # Translate kimi/ prefix to anthropic/ so litellm uses the Anthropic
        # Messages API handler and routes to that endpoint — no special headers needed.
        _original_model = model
        if model.lower().startswith("kimi/"):
            model = "anthropic/" + model[len("kimi/") :]
            # Normalise api_base: litellm's Anthropic handler appends /v1/messages,
            # so the base must be https://api.kimi.com/coding (no /v1 suffix).
            # Strip a trailing /v1 in case the user's saved config has the old value.
            if api_base and api_base.rstrip("/").endswith("/v1"):
                api_base = api_base.rstrip("/")[:-3]
        elif model.lower().startswith("hive/"):
            model = "anthropic/" + model[len("hive/") :]
            if api_base and api_base.rstrip("/").endswith("/v1"):
                api_base = api_base.rstrip("/")[:-3]
        self.model = model
        self.api_key = api_key
        self.api_base = api_base or self._default_api_base_for_model(_original_model)

        self.extra_kwargs = kwargs
        self._codex_backend = bool(
            self.api_base and "chatgpt.com/backend-api/codex" in self.api_base
        )
        
        # Set max tokens from model info if available
        if self.model_info and "max_tokens" not in self.extra_kwargs:
            self.extra_kwargs["max_tokens"] = self.model_info["max_tokens"]
            logger.debug(f"Set max_tokens from model info: {self.model_info['max_tokens']}")
        elif "max_tokens" not in self.extra_kwargs:
            self.extra_kwargs["max_tokens"] = get_model_max_tokens()
            logger.debug(f"Set max_tokens from config: {self.extra_kwargs['max_tokens']}")

        if litellm is None:
            raise ImportError(
                "LiteLLM is not installed. Please install it with: uv pip install litellm"
            )

        # Force Gemini to use API key mode (disable Vertex AI)
        if self.provider == "gemini":
            self._force_gemini_api_mode()

        # Run quick provider check at startup if no config
        asyncio.create_task(self._initial_provider_check())
        
        # Final debug output
        logger.info(f"✅ LiteLLMProvider initialized with model: {self.model}, provider: {self.provider}")
        
    def _force_gemini_api_mode(self):
        """Force Gemini to use API key mode instead of Vertex AI."""
        if self.provider == "gemini":
            # Set environment variables that LiteLLM checks
            if self.api_key:
                os.environ["GEMINI_API_KEY"] = self.api_key
            # Remove any Vertex AI env vars that might interfere
            os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
            os.environ.pop("VERTEXAI_PROJECT", None)
            os.environ.pop("VERTEXAI_LOCATION", None)
            logger.info("✅ Forced Gemini API key mode (disabled Vertex AI)")

    async def _initial_provider_check(self):
        """Check for working providers at startup if none configured."""
        from framework.config import get_hive_config

        config = get_hive_config()
        if not config.get("llm", {}).get("provider"):
            selection = await quick_provider_check()
            if selection:
                self.model_api_name = selection["model"]
                self.provider = selection["provider"]
                if self.provider and self.model_api_name:
                    self.model = f"{self.provider}/{self.model_api_name}"
                self.api_key = selection.get("api_key")

    @staticmethod
    def _default_api_base_for_model(model: str) -> str | None:
        """Return provider-specific default API base when required."""
        model_lower = model.lower()
        if model_lower.startswith("minimax/") or model_lower.startswith("minimax-"):
            return MINIMAX_API_BASE
        if model_lower.startswith("kimi/"):
            return KIMI_API_BASE
        if model_lower.startswith("hive/"):
            return HIVE_API_BASE
        return None

    def get_display_name(self) -> str:
        """Get user-friendly display name for the current model."""
        return self.model_display_name

    def supports_tools(self) -> bool:
        """Check if the current model supports tool calling."""
        return self.capabilities.get("tools", True)

    def supports_json_mode(self) -> bool:
        """Check if the current model supports JSON mode."""
        return self.capabilities.get("json_mode", True)

    def supports_streaming(self) -> bool:
        """Check if the current model supports streaming."""
        return self.capabilities.get("streaming", True)

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
                        self.provider = selection["provider"]
                        self.model_api_name = selection["model"]
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

    def _completion_with_rate_limit_retry(
        self, max_retries: int | None = None, **kwargs: Any
    ) -> Any:
        """Call litellm.completion with retry on 429 rate limit errors and empty responses."""
        model = kwargs.get("model", self.model)
        retries = max_retries if max_retries is not None else RATE_LIMIT_MAX_RETRIES
        for attempt in range(retries + 1):
            try:
                response = litellm.completion(**kwargs)

                content = response.choices[0].message.content if response.choices else None
                has_tool_calls = bool(response.choices and response.choices[0].message.tool_calls)
                if not content and not has_tool_calls:
                    messages = kwargs.get("messages", [])
                    last_role = next(
                        (m["role"] for m in reversed(messages) if m.get("role") != "system"),
                        None,
                    )
                    if last_role == "assistant":
                        logger.debug(
                            "[retry] Empty response after assistant message — "
                            "expected, not retrying."
                        )
                        return response

                    finish_reason = (
                        response.choices[0].finish_reason if response.choices else "unknown"
                    )
                    token_count, token_method = _estimate_tokens(model, messages)
                    dump_path = _dump_failed_request(
                        model=model,
                        kwargs=kwargs,
                        error_type="empty_response",
                        attempt=attempt,
                    )
                    logger.warning(
                        f"[retry] Empty response - {len(messages)} messages, "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )

                    if finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[retry] {model} returned empty content with "
                            f"finish_reason=length (max_tokens={max_tok}). "
                            f"The model exhausted its token budget before "
                            f"producing visible output. Increase max_tokens "
                            f"or use a different model. Not retrying."
                        )
                        return response

                    if attempt == retries:
                        logger.error(
                            f"[retry] GAVE UP on {model} after {retries + 1} "
                            f"attempts — empty response "
                            f"(finish_reason={finish_reason}, "
                            f"choices={len(response.choices) if response.choices else 0})"
                        )
                        return response
                    wait = _compute_retry_delay(attempt)
                    logger.warning(
                        f"[retry] {model} returned empty response "
                        f"(finish_reason={finish_reason}, "
                        f"choices={len(response.choices) if response.choices else 0}) — "
                        f"likely rate limited or quota exceeded. "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{retries})"
                    )
                    time.sleep(wait)
                    continue

                return response
            except RateLimitError as e:
                messages = kwargs.get("messages", [])
                token_count, token_method = _estimate_tokens(model, messages)
                dump_path = _dump_failed_request(
                    model=model,
                    kwargs=kwargs,
                    error_type="rate_limit",
                    attempt=attempt,
                )
                if attempt == retries:
                    logger.error(
                        f"[retry] GAVE UP on {model} after {retries + 1} "
                        f"attempts — rate limit error: {e!s}. "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )
                    raise
                wait = _compute_retry_delay(attempt, exception=e)
                logger.warning(
                    f"[retry] {model} rate limited (429): {e!s}. "
                    f"~{token_count} tokens ({token_method}). "
                    f"Full request dumped to: {dump_path}. "
                    f"Retrying in {wait}s "
                    f"(attempt {attempt + 1}/{retries})"
                )
                time.sleep(wait)
        raise RuntimeError("Exhausted rate limit retries")

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Generate a completion using LiteLLM with capability checks."""
        
        # Check if tools are supported
        if tools and not self.supports_tools():
            logger.warning(f"Model {self.model_display_name} does not support tools. Ignoring tools.")
            tools = None
        
        # Check if JSON mode is supported
        if json_mode and not self.supports_json_mode():
            logger.warning(f"Model {self.model_display_name} does not support JSON mode. Falling back to prompt engineering.")
            # Use prompt engineering instead
            json_mode = False
            if system:
                system += "\n\nPlease respond with a valid JSON object."
            else:
                system = "Please respond with a valid JSON object."
        
        # Check if streaming is supported (for internal use)
        if not self.supports_streaming():
            logger.debug(f"Model {self.model_display_name} does not support streaming.")

        if self._codex_backend:
            return asyncio.run(
                self.acomplete(
                    messages=messages,
                    system=system,
                    tools=tools,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    json_mode=json_mode,
                    max_retries=max_retries,
                )
            )

        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        if json_mode:
            json_instruction = "\n\nPlease respond with a valid JSON object."
            if full_messages and full_messages[0]["role"] == "system":
                full_messages[0]["content"] += json_instruction
            else:
                full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            **self.extra_kwargs,
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        elif "max_tokens" not in kwargs:
            kwargs["max_tokens"] = get_model_max_tokens()

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
        if response_format:
            kwargs["response_format"] = response_format

        response = self._completion_with_rate_limit_retry(max_retries=max_retries, **kwargs)

        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.choices[0].finish_reason or "",
            raw_response=response,
        )

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Async version of complete()."""
        
        # Check if tools are supported
        if tools and not self.supports_tools():
            logger.warning(f"Model {self.model_display_name} does not support tools. Ignoring tools.")
            tools = None
        
        # Check if JSON mode is supported
        if json_mode and not self.supports_json_mode():
            logger.warning(f"Model {self.model_display_name} does not support JSON mode. Falling back to prompt engineering.")
            json_mode = False
            if system:
                system += "\n\nPlease respond with a valid JSON object."
            else:
                system = "Please respond with a valid JSON object."

        if self._codex_backend:
            stream_iter = self.stream(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
            )
            return await self._collect_stream_to_response(stream_iter)

        full_messages = []
        if system:
            sys_msg: dict[str, Any] = {"role": "system", "content": system}
            if _model_supports_cache_control(self.model):
                sys_msg["cache_control"] = {"type": "ephemeral"}
            full_messages.append(sys_msg)
        full_messages.extend(messages)

        if json_mode:
            json_instruction = "\n\nPlease respond with a valid JSON object."
            if full_messages and full_messages[0]["role"] == "system":
                full_messages[0]["content"] += json_instruction
            else:
                full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            **self.extra_kwargs,
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        elif "max_tokens" not in kwargs:
            kwargs["max_tokens"] = get_model_max_tokens()

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
        if response_format:
            kwargs["response_format"] = response_format

        response = await self._acompletion_with_rate_limit_retry(max_retries=max_retries, **kwargs)

        content = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0

        return LLMResponse(
            content=content,
            model=response.model or self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=response.choices[0].finish_reason or "",
            raw_response=response,
        )

    def _tool_to_openai_format(self, tool: Tool) -> dict[str, Any]:
        """Convert Tool to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters.get("properties", {}),
                    "required": tool.parameters.get("required", []),
                },
            },
        }

    def _is_minimax_model(self) -> bool:
        """Return True when the configured model targets MiniMax."""
        model = (self.model or "").lower()
        return model.startswith("minimax/") or model.startswith("minimax-")

    async def _stream_via_nonstream_completion(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool] | None,
        max_tokens: int,
        response_format: dict[str, Any] | None,
        json_mode: bool,
    ) -> AsyncIterator[StreamEvent]:
        """Fallback path: convert non-stream completion to stream events."""
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        try:
            response = await self.acomplete(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
            )
        except Exception as e:
            yield StreamErrorEvent(error=str(e), recoverable=False)
            return

        raw = response.raw_response
        tool_calls = []
        if raw and hasattr(raw, "choices") and raw.choices:
            msg = raw.choices[0].message
            tool_calls = msg.tool_calls or []

        for tc in tool_calls:
            parsed_args: Any
            args = tc.function.arguments if tc.function else ""
            try:
                parsed_args = json.loads(args) if args else {}
            except json.JSONDecodeError:
                parsed_args = {"_raw": args}
            yield ToolCallEvent(
                tool_use_id=getattr(tc, "id", ""),
                tool_name=tc.function.name if tc.function else "",
                tool_input=parsed_args,
            )

        if response.content:
            yield TextDeltaEvent(content=response.content, snapshot=response.content)
            yield TextEndEvent(full_text=response.content)

        yield FinishEvent(
            stop_reason=response.stop_reason or "stop",
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            model=response.model,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion via litellm.acompletion(stream=True)."""
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        if not self.supports_streaming():
            logger.warning(f"Model {self.model_display_name} does not support streaming. Using non-streaming fallback.")
            async for event in self._stream_via_nonstream_completion(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens or get_model_max_tokens(),
                response_format=response_format,
                json_mode=json_mode,
            ):
                yield event
            return

        if self._is_minimax_model():
            async for event in self._stream_via_nonstream_completion(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens or get_model_max_tokens(),
                response_format=response_format,
                json_mode=json_mode,
            ):
                yield event
            return

        full_messages = []
        if system:
            sys_msg: dict[str, Any] = {"role": "system", "content": system}
            if _model_supports_cache_control(self.model):
                sys_msg["cache_control"] = {"type": "ephemeral"}
            full_messages.append(sys_msg)
        full_messages.extend(messages)

        if self._codex_backend and not any(m["role"] == "system" for m in full_messages):
            full_messages.insert(0, {"role": "system", "content": "You are a helpful assistant."})

        if json_mode:
            json_instruction = "\n\nPlease respond with a valid JSON object."
            if full_messages and full_messages[0]["role"] == "system":
                full_messages[0]["content"] += json_instruction
            else:
                full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})

        full_messages = [
            m
            for m in full_messages
            if not (
                m.get("role") == "assistant" and not m.get("content") and not m.get("tool_calls")
            )
        ]

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self.extra_kwargs,
        }

        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        elif "max_tokens" not in kwargs:
            kwargs["max_tokens"] = get_model_max_tokens()

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
        if response_format:
            kwargs["response_format"] = response_format
        if self._codex_backend:
            kwargs.pop("max_tokens", None)
            kwargs.pop("stream_options", None)

        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            tail_events = []
            accumulated_text = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}
            _last_tool_idx = 0
            input_tokens = 0
            output_tokens = 0
            stream_finish_reason: str | None = None

            try:
                response = await litellm.acompletion(**kwargs)

                async for chunk in response:
                    # Capture usage from the trailing usage-only chunk that
                    # stream_options={"include_usage": True} sends with empty choices.
                    if not chunk.choices:
                        usage = getattr(chunk, "usage", None)
                        if usage:
                            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            output_tokens = getattr(usage, "completion_tokens", 0) or 0
                            logger.debug(
                                "[tokens] trailing usage chunk: input=%d output=%d model=%s",
                                input_tokens,
                                output_tokens,
                                self.model,
                            )
                        else:
                            logger.debug(
                                "[tokens] empty-choices chunk with no usage (model=%s)",
                                self.model,
                            )
                        continue
                    choice = chunk.choices[0]

                    delta = choice.delta

                    if delta and delta.content:
                        accumulated_text += delta.content
                        yield TextDeltaEvent(
                            content=delta.content,
                            snapshot=accumulated_text,
                        )

                    if delta and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index if hasattr(tc, "index") and tc.index is not None else 0

                            if tc.id:
                                existing_idx = next(
                                    (k for k, v in tool_calls_acc.items() if v["id"] == tc.id),
                                    None,
                                )
                                if existing_idx is not None:
                                    idx = existing_idx
                                elif idx in tool_calls_acc and tool_calls_acc[idx]["id"] not in (
                                    "",
                                    tc.id,
                                ):
                                    idx = max(tool_calls_acc.keys()) + 1
                                _last_tool_idx = idx
                            else:
                                idx = _last_tool_idx

                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            if tc.id:
                                tool_calls_acc[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    tool_calls_acc[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    tool_calls_acc[idx]["arguments"] += tc.function.arguments

                    if choice.finish_reason:
                        stream_finish_reason = choice.finish_reason
                        for _idx, tc_data in sorted(tool_calls_acc.items()):
                            try:
                                parsed_args = json.loads(tc_data["arguments"])
                            except (json.JSONDecodeError, KeyError):
                                parsed_args = {"_raw": tc_data.get("arguments", "")}
                            tail_events.append(
                                ToolCallEvent(
                                    tool_use_id=tc_data["id"],
                                    tool_name=tc_data["name"],
                                    tool_input=parsed_args,
                                )
                            )

                        if accumulated_text:
                            tail_events.append(TextEndEvent(full_text=accumulated_text))

                        usage = getattr(chunk, "usage", None)
                        logger.debug(
                            "[tokens] finish-chunk raw usage: %r (type=%s)",
                            usage,
                            type(usage).__name__,
                        )
                        cached_tokens = 0
                        if usage:
                            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            output_tokens = getattr(usage, "completion_tokens", 0) or 0
                            _details = getattr(usage, "prompt_tokens_details", None)
                            cached_tokens = (
                                getattr(_details, "cached_tokens", 0) or 0
                                if _details is not None
                                else getattr(usage, "cache_read_input_tokens", 0) or 0
                            )
                            logger.debug(
                                "[tokens] finish-chunk usage: "
                                "input=%d output=%d cached=%d model=%s",
                                input_tokens,
                                output_tokens,
                                cached_tokens,
                                self.model,
                            )

                        logger.debug(
                            "[tokens] finish event: input=%d output=%d cached=%d stop=%s model=%s",
                            input_tokens,
                            output_tokens,
                            cached_tokens,
                            choice.finish_reason,
                            self.model,
                        )
                        tail_events.append(
                            FinishEvent(
                                stop_reason=choice.finish_reason,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                cached_tokens=cached_tokens,
                                model=self.model,
                            )
                        )

                # Fallback: LiteLLM strips usage from yielded chunks before
                # returning them to us, but appends the original chunk (with
                # usage intact) to response.chunks first.  Use LiteLLM's own
                # calculate_total_usage() on that accumulated list.
                if input_tokens == 0 and output_tokens == 0:
                    try:
                        from litellm.litellm_core_utils.streaming_handler import (
                            calculate_total_usage,
                        )

                        _chunks = getattr(response, "chunks", None)
                        if _chunks:
                            _usage = calculate_total_usage(chunks=_chunks)
                            input_tokens = _usage.prompt_tokens or 0
                            output_tokens = _usage.completion_tokens or 0
                            _details = getattr(_usage, "prompt_tokens_details", None)
                            cached_tokens = (
                                getattr(_details, "cached_tokens", 0) or 0
                                if _details is not None
                                else getattr(_usage, "cache_read_input_tokens", 0) or 0
                            )
                            logger.debug(
                                "[tokens] post-loop chunks fallback:"
                                " input=%d output=%d cached=%d model=%s",
                                input_tokens,
                                output_tokens,
                                cached_tokens,
                                self.model,
                            )
                            # Patch the FinishEvent already queued with 0 tokens
                            for _i, _ev in enumerate(tail_events):
                                if isinstance(_ev, FinishEvent) and _ev.input_tokens == 0:
                                    tail_events[_i] = FinishEvent(
                                        stop_reason=_ev.stop_reason,
                                        input_tokens=input_tokens,
                                        output_tokens=output_tokens,
                                        cached_tokens=cached_tokens,
                                        model=_ev.model,
                                    )
                                    break
                    except Exception as _e:
                        logger.debug("[tokens] chunks fallback failed: %s", _e)

                # Check whether the stream produced any real content.
                # (If text deltas were yielded above, has_content is True
                # and we skip the retry path — nothing was yielded in vain.)

                has_content = accumulated_text or tool_calls_acc
                if not has_content:
                    if stream_finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[stream] {self.model} returned empty content "
                            f"with finish_reason=length "
                            f"(max_tokens={max_tok})."
                        )
                        for event in tail_events:
                            yield event
                        return

                    last_role = next(
                        (m["role"] for m in reversed(full_messages) if m.get("role") != "system"),
                        None,
                    )
                    if attempt < EMPTY_STREAM_MAX_RETRIES:
                        token_count, token_method = _estimate_tokens(
                            self.model,
                            full_messages,
                        )
                        dump_path = _dump_failed_request(
                            model=self.model,
                            kwargs=kwargs,
                            error_type="empty_stream",
                            attempt=attempt,
                        )
                        logger.warning(
                            f"[stream-retry] {self.model} returned empty stream "
                            f"after {last_role} message — "
                            f"~{token_count} tokens ({token_method}). "
                            f"Request dumped to: {dump_path}. "
                            f"Retrying in {EMPTY_STREAM_RETRY_DELAY}s "
                            f"(attempt {attempt + 1}/{EMPTY_STREAM_MAX_RETRIES})"
                        )
                        await asyncio.sleep(EMPTY_STREAM_RETRY_DELAY)
                        continue

                    logger.error(
                        f"[stream] {self.model} returned empty stream after "
                        f"{EMPTY_STREAM_MAX_RETRIES} retries "
                        f"(last_role={last_role}). Returning empty result."
                    )

                for event in tail_events:
                    yield event
                return

            except RateLimitError as e:
                if attempt < RATE_LIMIT_MAX_RETRIES:
                    wait = _compute_retry_delay(attempt, exception=e)
                    logger.warning(
                        f"[stream-retry] {self.model} rate limited (429): {e!s}. "
                        f"Retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait)
                    continue
                yield StreamErrorEvent(error=str(e), recoverable=False)
                return

            except Exception as e:
                if _is_stream_transient_error(e) and attempt < RATE_LIMIT_MAX_RETRIES:
                    wait = _compute_retry_delay(attempt, exception=e)
                    logger.warning(
                        f"[stream-retry] {self.model} transient error "
                        f"({type(e).__name__}): {e!s}. "
                        f"Retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait)
                    continue
                recoverable = _is_stream_transient_error(e)
                yield StreamErrorEvent(error=str(e), recoverable=recoverable)
                return

    async def _collect_stream_to_response(
        self,
        stream: AsyncIterator[StreamEvent],
    ) -> LLMResponse:
        """Consume a stream() iterator and collect it into a single LLMResponse."""
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            ToolCallEvent,
        )

        content = ""
        tool_calls: list[dict[str, Any]] = []
        input_tokens = 0
        output_tokens = 0
        stop_reason = ""
        model = self.model

        async for event in stream:
            if isinstance(event, TextDeltaEvent):
                content = event.snapshot
            elif isinstance(event, ToolCallEvent):
                tool_calls.append(
                    {
                        "id": event.tool_use_id,
                        "name": event.tool_name,
                        "input": event.tool_input,
                    }
                )
            elif isinstance(event, FinishEvent):
                input_tokens = event.input_tokens
                output_tokens = event.output_tokens
                stop_reason = event.stop_reason
                if event.model:
                    model = event.model
            elif isinstance(event, StreamErrorEvent):
                if not event.recoverable:
                    raise RuntimeError(f"Stream error: {event.error}")

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            stop_reason=stop_reason,
            raw_response={"tool_calls": tool_calls} if tool_calls else None,
        )