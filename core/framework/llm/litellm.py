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

from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import StreamEvent

logger = logging.getLogger(__name__)


def _patch_litellm_anthropic_oauth() -> None:
    """Patch litellm's Anthropic header construction to fix OAuth token handling.

    litellm bug: validate_environment() puts the OAuth token into x-api-key,
    but Anthropic's API rejects OAuth tokens in x-api-key. They must be sent
    via Authorization: Bearer only, with x-api-key omitted entirely.

    This patch wraps validate_environment to remove x-api-key when the
    Authorization header carries an OAuth token (sk-ant-oat prefix).

    See: https://github.com/BerriAI/litellm/issues/19618
    """
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
    """Patch litellm entry points to prevent metadata=None TypeError.

    litellm bug: the @client decorator in utils.py has four places that do
        "model_group" in kwargs.get("metadata", {})
    but kwargs["metadata"] can be explicitly None (set internally by
    litellm_params), causing:
        TypeError: argument of type 'NoneType' is not iterable
    This masks the real API error with a confusing APIConnectionError.

    Fix: wrap the four litellm entry points (completion, acompletion,
    responses, aresponses) to pop metadata=None before the @client
    decorator's error handler can crash on it.
    """
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
RATE_LIMIT_BACKOFF_BASE = 2  # seconds
RATE_LIMIT_MAX_DELAY = 120  # seconds - cap to prevent absurd waits

# Directory for dumping failed requests
FAILED_REQUESTS_DIR = Path.home() / ".hive" / "failed_requests"


def _estimate_tokens(model: str, messages: list[dict]) -> tuple[int, str]:
    """Estimate token count for messages. Returns (token_count, method)."""
    # Try litellm's token counter first
    if litellm is not None:
        try:
            count = litellm.token_counter(model=model, messages=messages)
            return count, "litellm"
        except Exception:
            pass

    # Fallback: rough estimate based on character count (~4 chars per token)
    total_chars = sum(len(str(m.get("content", ""))) for m in messages)
    return total_chars // 4, "estimate"


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

    # Build dump data
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

    with open(filepath, "w") as f:
        json.dump(dump_data, f, indent=2, default=str)

    return str(filepath)


def _compute_retry_delay(
    attempt: int,
    exception: BaseException | None = None,
    backoff_base: int = RATE_LIMIT_BACKOFF_BASE,
    max_delay: int = RATE_LIMIT_MAX_DELAY,
) -> float:
    """Compute retry delay, preferring server-provided Retry-After headers.

    Priority:
    1. retry-after-ms header (milliseconds, float)
    2. retry-after header as seconds (float)
    3. retry-after header as HTTP-date (RFC 7231)
    4. Exponential backoff: backoff_base * 2^attempt

    All values are capped at max_delay seconds.
    """
    if exception is not None:
        response = getattr(exception, "response", None)
        if response is not None:
            headers = getattr(response, "headers", None)
            if headers is not None:
                # Priority 1: retry-after-ms (milliseconds)
                retry_after_ms = headers.get("retry-after-ms")
                if retry_after_ms is not None:
                    try:
                        delay = float(retry_after_ms) / 1000.0
                        return min(max(delay, 0), max_delay)
                    except (ValueError, TypeError):
                        pass

                # Priority 2: retry-after (seconds or HTTP-date)
                retry_after = headers.get("retry-after")
                if retry_after is not None:
                    # Try as seconds (float)
                    try:
                        delay = float(retry_after)
                        return min(max(delay, 0), max_delay)
                    except (ValueError, TypeError):
                        pass

                    # Try as HTTP-date (e.g., "Fri, 31 Dec 2025 23:59:59 GMT")
                    try:
                        from email.utils import parsedate_to_datetime

                        retry_date = parsedate_to_datetime(retry_after)
                        now = datetime.now(retry_date.tzinfo)
                        delay = (retry_date - now).total_seconds()
                        return min(max(delay, 0), max_delay)
                    except (ValueError, TypeError, OverflowError):
                        pass

    # Fallback: exponential backoff
    delay = backoff_base * (2**attempt)
    return min(delay, max_delay)


def _is_stream_transient_error(exc: BaseException) -> bool:
    """Classify whether a streaming exception is transient (recoverable).

    Transient errors (recoverable=True): network issues, server errors, timeouts.
    Permanent errors (recoverable=False): auth, bad request, context window, etc.
    """
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

    Supports any model that LiteLLM supports, including:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
    - Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
    - Google: gemini-pro, gemini-1.5-pro, gemini-1.5-flash
    - DeepSeek: deepseek-chat, deepseek-coder, deepseek-reasoner
    - Mistral: mistral-large, mistral-medium, mistral-small
    - Groq: llama3-70b, mixtral-8x7b
    - Local: ollama/llama3, ollama/mistral
    - And many more...

    Usage:
        # OpenAI
        provider = LiteLLMProvider(model="gpt-4o-mini")

        # Anthropic
        provider = LiteLLMProvider(model="claude-3-haiku-20240307")

        # Google Gemini
        provider = LiteLLMProvider(model="gemini/gemini-1.5-flash")

        # DeepSeek
        provider = LiteLLMProvider(model="deepseek/deepseek-chat")

        # Local Ollama
        provider = LiteLLMProvider(model="ollama/llama3")

        # With custom API base
        provider = LiteLLMProvider(
            model="gpt-4o-mini",
            api_base="https://my-proxy.com/v1"
        )
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ):
        """
        Initialize the LiteLLM provider.

        Args:
            model: Model identifier (e.g., "gpt-4o-mini", "claude-3-haiku-20240307")
                   LiteLLM auto-detects the provider from the model name.
            api_key: API key for the provider. If not provided, LiteLLM will
                     look for the appropriate env var (OPENAI_API_KEY,
                     ANTHROPIC_API_KEY, etc.)
            api_base: Custom API base URL (for proxies or local deployments)
            **kwargs: Additional arguments passed to litellm.completion()
        """
        self.model = model
        self.api_key = api_key
        self.api_base = api_base
        self.extra_kwargs = kwargs
        # The Codex ChatGPT backend (chatgpt.com/backend-api/codex) rejects
        # several standard OpenAI params: max_output_tokens, stream_options.
        self._codex_backend = bool(api_base and "chatgpt.com/backend-api/codex" in api_base)

        if litellm is None:
            raise ImportError(
                "LiteLLM is not installed. Please install it with: uv pip install litellm"
            )

        # Note: The Codex ChatGPT backend is a Responses API endpoint at
        # chatgpt.com/backend-api/codex/responses.  LiteLLM's model registry
        # correctly marks codex models with mode="responses", so we do NOT
        # override the mode.  The responses_api_bridge in litellm handles
        # converting Chat Completions requests to Responses API format.

    def _completion_with_rate_limit_retry(
        self, max_retries: int | None = None, **kwargs: Any
    ) -> Any:
        """Call litellm.completion with retry on 429 rate limit errors and empty responses."""
        model = kwargs.get("model", self.model)
        retries = max_retries if max_retries is not None else RATE_LIMIT_MAX_RETRIES
        for attempt in range(retries + 1):
            try:
                response = litellm.completion(**kwargs)  # type: ignore[union-attr]

                # Some providers (e.g. Gemini) return 200 with empty content on
                # rate limit / quota exhaustion instead of a proper 429.  Treat
                # empty responses the same as a rate-limit error and retry.
                content = response.choices[0].message.content if response.choices else None
                has_tool_calls = bool(response.choices and response.choices[0].message.tool_calls)
                if not content and not has_tool_calls:
                    # If the conversation ends with an assistant message,
                    # an empty response is expected — don't retry.
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
                    # Dump full request to file for debugging
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

                    # finish_reason=length means the model exhausted max_tokens
                    # before producing content. Retrying with the same max_tokens
                    # will never help — return immediately instead of looping.
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
                # Dump full request to file for debugging
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
        # unreachable, but satisfies type checker
        raise RuntimeError("Exhausted rate limit retries")

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
        """Generate a completion using LiteLLM."""
        # Codex ChatGPT backend requires streaming — delegate to the unified
        # async streaming path which properly handles tool calls.
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

        # Prepare messages with system prompt
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        # Add JSON mode via prompt engineering (works across all providers)
        if json_mode:
            json_instruction = "\n\nPlease respond with a valid JSON object."
            # Append to system message if present, otherwise add as system message
            if full_messages and full_messages[0]["role"] == "system":
                full_messages[0]["content"] += json_instruction
            else:
                full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})

        # Build kwargs
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            **self.extra_kwargs,
        }

        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base

        # Add tools if provided
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]

        # Add response_format for structured output
        # LiteLLM passes this through to the underlying provider
        if response_format:
            kwargs["response_format"] = response_format

        # Make the call
        response = self._completion_with_rate_limit_retry(max_retries=max_retries, **kwargs)

        # Extract content
        content = response.choices[0].message.content or ""

        # Get usage info.
        # NOTE: completion_tokens includes reasoning/thinking tokens for models
        # that use them (o1, gpt-5-mini, etc.). LiteLLM does not reliably expose
        # usage.completion_tokens_details.reasoning_tokens across all providers.
        # This means output_tokens may be inflated for reasoning models.
        # Compaction is unaffected — it uses prompt_tokens (input-side only).
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

    # ------------------------------------------------------------------
    # Async variants — non-blocking on the event loop
    # ------------------------------------------------------------------

    async def _acompletion_with_rate_limit_retry(
        self, max_retries: int | None = None, **kwargs: Any
    ) -> Any:
        """Async version of _completion_with_rate_limit_retry.

        Uses litellm.acompletion and asyncio.sleep instead of blocking calls.
        """
        model = kwargs.get("model", self.model)
        retries = max_retries if max_retries is not None else RATE_LIMIT_MAX_RETRIES
        for attempt in range(retries + 1):
            try:
                response = await litellm.acompletion(**kwargs)  # type: ignore[union-attr]

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
                            "[async-retry] Empty response after assistant message — "
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
                        f"[async-retry] Empty response - {len(messages)} messages, "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )

                    # finish_reason=length means the model exhausted max_tokens
                    # before producing content. Retrying with the same max_tokens
                    # will never help — return immediately instead of looping.
                    if finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[async-retry] {model} returned empty content with "
                            f"finish_reason=length (max_tokens={max_tok}). "
                            f"The model exhausted its token budget before "
                            f"producing visible output. Increase max_tokens "
                            f"or use a different model. Not retrying."
                        )
                        return response

                    if attempt == retries:
                        logger.error(
                            f"[async-retry] GAVE UP on {model} after {retries + 1} "
                            f"attempts — empty response "
                            f"(finish_reason={finish_reason}, "
                            f"choices={len(response.choices) if response.choices else 0})"
                        )
                        return response
                    wait = _compute_retry_delay(attempt)
                    logger.warning(
                        f"[async-retry] {model} returned empty response "
                        f"(finish_reason={finish_reason}, "
                        f"choices={len(response.choices) if response.choices else 0}) — "
                        f"likely rate limited or quota exceeded. "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{retries})"
                    )
                    await asyncio.sleep(wait)
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
                        f"[async-retry] GAVE UP on {model} after {retries + 1} "
                        f"attempts — rate limit error: {e!s}. "
                        f"~{token_count} tokens ({token_method}). "
                        f"Full request dumped to: {dump_path}"
                    )
                    raise
                wait = _compute_retry_delay(attempt, exception=e)
                logger.warning(
                    f"[async-retry] {model} rate limited (429): {e!s}. "
                    f"~{token_count} tokens ({token_method}). "
                    f"Full request dumped to: {dump_path}. "
                    f"Retrying in {wait}s "
                    f"(attempt {attempt + 1}/{retries})"
                )
                await asyncio.sleep(wait)
        raise RuntimeError("Exhausted rate limit retries")

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
        """Async version of complete(). Uses litellm.acompletion — non-blocking."""
        # Codex ChatGPT backend requires streaming — route through stream() which
        # already handles Codex quirks and has proper tool call accumulation.
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

        full_messages: list[dict[str, Any]] = []
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
            "max_tokens": max_tokens,
            **self.extra_kwargs,
        }

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

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> AsyncIterator[StreamEvent]:
        """Stream a completion via litellm.acompletion(stream=True).

        Yields StreamEvent objects as chunks arrive from the provider.
        Tool call arguments are accumulated across chunks and yielded as
        a single ToolCallEvent with fully parsed JSON when complete.

        Empty responses (e.g. Gemini stealth rate-limits that return 200
        with no content) are retried with exponential backoff, mirroring
        the retry behaviour of ``_completion_with_rate_limit_retry``.
        """
        from framework.llm.stream_events import (
            FinishEvent,
            StreamErrorEvent,
            TextDeltaEvent,
            TextEndEvent,
            ToolCallEvent,
        )

        full_messages: list[dict[str, Any]] = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        # Codex Responses API requires an `instructions` field (system prompt).
        # Inject a minimal one when callers don't provide a system message.
        if self._codex_backend and not any(m["role"] == "system" for m in full_messages):
            full_messages.insert(0, {"role": "system", "content": "You are a helpful assistant."})

        # Add JSON mode via prompt engineering (works across all providers)
        if json_mode:
            json_instruction = "\n\nPlease respond with a valid JSON object."
            if full_messages and full_messages[0]["role"] == "system":
                full_messages[0]["content"] += json_instruction
            else:
                full_messages.insert(0, {"role": "system", "content": json_instruction.strip()})

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self.extra_kwargs,
        }
        if self.api_key:
            kwargs["api_key"] = self.api_key
        if self.api_base:
            kwargs["api_base"] = self.api_base
        if tools:
            kwargs["tools"] = [self._tool_to_openai_format(t) for t in tools]
        if response_format:
            kwargs["response_format"] = response_format
        # The Codex ChatGPT backend (Responses API) rejects several params.
        if self._codex_backend:
            kwargs.pop("max_tokens", None)
            kwargs.pop("stream_options", None)

        for attempt in range(RATE_LIMIT_MAX_RETRIES + 1):
            # Post-stream events (ToolCall, TextEnd, Finish) are buffered
            # because they depend on the full stream.  TextDeltaEvents are
            # yielded immediately so callers see tokens in real time.
            tail_events: list[StreamEvent] = []
            accumulated_text = ""
            tool_calls_acc: dict[int, dict[str, str]] = {}
            _last_tool_idx = 0  # tracks most recently opened tool call slot
            input_tokens = 0
            output_tokens = 0
            stream_finish_reason: str | None = None

            try:
                response = await litellm.acompletion(**kwargs)  # type: ignore[union-attr]

                async for chunk in response:
                    choice = chunk.choices[0] if chunk.choices else None
                    if not choice:
                        continue

                    delta = choice.delta

                    # --- Text content — yield immediately for real-time streaming ---
                    if delta and delta.content:
                        accumulated_text += delta.content
                        yield TextDeltaEvent(
                            content=delta.content,
                            snapshot=accumulated_text,
                        )

                    # --- Tool calls (accumulate across chunks) ---
                    # The Codex/Responses API bridge (litellm bug) hardcodes
                    # index=0 on every ChatCompletionToolCallChunk, even for
                    # parallel tool calls.  We work around this by using tc.id
                    # (set on output_item.added events) as a "new tool call"
                    # signal and tracking the most recently opened slot for
                    # argument deltas that arrive with id=None.
                    if delta and delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index if hasattr(tc, "index") and tc.index is not None else 0

                            if tc.id:
                                # New tool call announced (or done event re-sent).
                                # Check if this id already has a slot.
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
                                    # Slot taken by a different call — assign new index
                                    idx = max(tool_calls_acc.keys()) + 1
                                _last_tool_idx = idx
                            else:
                                # Argument delta with no id — route to last opened slot
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

                    # --- Finish ---
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
                        if usage:
                            input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                            output_tokens = getattr(usage, "completion_tokens", 0) or 0

                        tail_events.append(
                            FinishEvent(
                                stop_reason=choice.finish_reason,
                                input_tokens=input_tokens,
                                output_tokens=output_tokens,
                                model=self.model,
                            )
                        )

                # Check whether the stream produced any real content.
                # (If text deltas were yielded above, has_content is True
                # and we skip the retry path — nothing was yielded in vain.)
                has_content = accumulated_text or tool_calls_acc
                if not has_content and attempt < RATE_LIMIT_MAX_RETRIES:
                    # If the conversation ends with an assistant or tool
                    # message, an empty stream is expected — the LLM has
                    # nothing new to say.  Don't burn retries on this;
                    # let the caller (EventLoopNode) decide what to do.
                    # Typical case: client_facing node where the LLM set
                    # all outputs via set_output tool calls, and the tool
                    # results are the last messages.
                    last_role = next(
                        (m["role"] for m in reversed(full_messages) if m.get("role") != "system"),
                        None,
                    )
                    if last_role in ("assistant", "tool"):
                        logger.debug(
                            "[stream] Empty response after %s message — expected, not retrying.",
                            last_role,
                        )
                        for event in tail_events:
                            yield event
                        return

                    # finish_reason=length means the model exhausted
                    # max_tokens before producing content. Retrying with
                    # the same max_tokens will never help.
                    if stream_finish_reason == "length":
                        max_tok = kwargs.get("max_tokens", "unset")
                        logger.error(
                            f"[stream] {self.model} returned empty content "
                            f"with finish_reason=length "
                            f"(max_tokens={max_tok}). The model exhausted "
                            f"its token budget before producing visible "
                            f"output. Increase max_tokens or use a "
                            f"different model. Not retrying."
                        )
                        for event in tail_events:
                            yield event
                        return

                    wait = _compute_retry_delay(attempt)
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
                        f"[stream-retry] {self.model} returned empty stream — "
                        f"~{token_count} tokens ({token_method}). "
                        f"Request dumped to: {dump_path}. "
                        f"Retrying in {wait}s "
                        f"(attempt {attempt + 1}/{RATE_LIMIT_MAX_RETRIES})"
                    )
                    await asyncio.sleep(wait)
                    continue

                # Success (or final attempt) — flush remaining events.
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
        """Consume a stream() iterator and collect it into a single LLMResponse.

        Used by acomplete() to route through the unified streaming path so that
        all backends (including Codex) get proper tool call handling.
        """
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
                content = event.snapshot  # snapshot is the accumulated text
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
