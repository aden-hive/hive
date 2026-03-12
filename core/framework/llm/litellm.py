<<<<<<< HEAD
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
RATE_LIMIT_BACKOFF_BASE = 2  # seconds
RATE_LIMIT_MAX_DELAY = 120  # seconds - cap to prevent absurd waits
MINIMAX_API_BASE = "https://api.minimax.io/v1"
# Kimi For Coding uses an Anthropic-compatible endpoint (no /v1 suffix).
# Claude Code integration uses this format; the /v1 OpenAI-compatible endpoint
# enforces a coding-agent whitelist that blocks unknown User-Agents.
KIMI_API_BASE = "https://api.kimi.com/coding"

# Empty-stream retries use a short fixed delay, not the rate-limit backoff.
EMPTY_STREAM_MAX_RETRIES = 3
EMPTY_STREAM_RETRY_DELAY = 1.0  # seconds

# Directory for dumping failed requests
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

    Supports any model that LiteLLM supports, including:
    - OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, gpt-3.5-turbo
    - Anthropic: claude-3-opus, claude-3-sonnet, claude-3-haiku
    - Google: gemini-pro, gemini-1.5-pro, gemini-1.5-flash
    - DeepSeek: deepseek-chat, deepseek-coder, deepseek-reasoner
    - Mistral: mistral-large, mistral-medium, mistral-small
    - Groq: llama3-70b, mixtral-8x7b
    - Local: ollama/llama3, ollama/mistral
    - And many more...
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
            api_key: API key for the provider.
            api_base: Custom API base URL (for proxies or local deployments)
            **kwargs: Additional arguments passed to litellm.completion()
        """
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
        self.model = model
        self.api_key = api_key
        self.api_base = api_base or self._default_api_base_for_model(_original_model)
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
        if model_lower.startswith("kimi/"):
            return KIMI_API_BASE
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
                    "credit" in error_str or 
                    "balance" in error_str or 
                    "invalid" in error_str or
                    "auth" in error_str or
                    "key" in error_str or
                    "permission" in error_str
                )
                
                # On first attempt with credit error, offer interactive fallback
                if attempt == 0 and is_credit_error:
                    # Get original provider from model string
                    original_provider = model.split('/')[0] if '/' in model else model
                    
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

    # ------------------------------------------------------------------
    # Rest of the file remains exactly the same - only the async method above changed
    # All the methods below are unchanged from your original litellm.py
    # ------------------------------------------------------------------

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
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Generate a completion using LiteLLM."""
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
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
    ) -> LLMResponse:
        """Async version of complete()."""
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
        max_tokens: int = 4096,
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

        if self._is_minimax_model():
            async for event in self._stream_via_nonstream_completion(
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
            ):
                yield event
            return

        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
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
                    choice = chunk.choices[0] if chunk.choices else None
                    if not choice:
                        continue

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
=======
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
>>>>>>> b3daa379bd2f7ddad5520b8ef9d232e3fbb47e05
