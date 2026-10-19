"""LLM Provider abstraction for pluggable LLM backends."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from functools import partial
from typing import Any


@dataclass
class LLMResponse:
    """Response from an LLM call.

    ``cached_tokens`` and ``cache_creation_tokens`` are subsets of
    ``input_tokens`` (providers report them inside ``prompt_tokens``).
    Surface them for visibility; do not add to a total.

    ``cost_usd`` is the per-call USD cost when the provider / pricing table
    can produce one (Anthropic, OpenAI, OpenRouter are supported). 0.0 when
    unknown or unpriced — treat as "unreported", not "free".

    ``credits`` is the per-request Hive credit cost when the response came
    through a Hive-aliased model (the proxy puts it on ``usage.credits``).
    ``None`` means the field was absent — not zero. Direct provider models
    never set this.
    """

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    credits: float | None = None
    stop_reason: str = ""
    raw_response: Any = None


@dataclass
class Tool:
    """A tool the LLM can use."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    # If True, the tool may return ImageContent in its result. Text-only models
    # (e.g. glm-5, deepseek-chat) have this hidden from their schema entirely.
    produces_image: bool = False
    # If True, this tool performs no filesystem/process/network writes and is
    # safe to run concurrently with other safe-flagged tools inside the same
    # assistant turn. Unsafe tools (writes, shell, browser actions) are always
    # serialized after the safe batch. Default False - the conservative choice
    # when a tool's behavior isn't explicitly vetted.
    concurrency_safe: bool = False


@dataclass
class ToolUse:
    """A tool call requested by the LLM."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    """Result of executing a tool."""

    tool_use_id: str
    content: str
    is_error: bool = False
    image_content: list[dict[str, Any]] | None = None
    is_skill_content: bool = False  # AS-10: marks activated skill body, protected from pruning
    # Absolute path to the on-disk spill file holding this result's full content
    # (set by truncate_tool_result whenever a spillover dir is configured — for
    # BOTH large-preview and small-inline results). Carried out-of-band, never in
    # the LLM-visible message, so compaction can cite a recovery path when it
    # clears the result without re-priming the "saved to path" poison pattern.
    spillover_path: str | None = None


class LLMProvider(ABC):
    """
    Abstract LLM provider - plug in any LLM backend.

    Implementations should handle:
    - API authentication
    - Request/response formatting
    - Token counting
    - Error handling
    """

    @abstractmethod
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
        """
        Generate a completion from the LLM.

        Args:
            messages: Conversation history [{role: "user"|"assistant", content: str}]
            system: System prompt
            tools: Available tools for the LLM to use
            max_tokens: Maximum tokens to generate. ``None`` resolves to the
                configured default (``llm.aux_max_tokens`` for completions,
                ``llm.max_tokens`` for streams) in the concrete provider.
            response_format: Optional structured output format. Use:
                - {"type": "json_object"} for basic JSON mode
                - {"type": "json_schema", "json_schema": {"name": "...", "schema": {...}}}
                  for strict JSON schema enforcement
            json_mode: If True, request structured JSON output from the LLM
            max_retries: Override retry count for rate-limit/empty-response retries.
                None uses the provider default.

        Returns:
            LLMResponse with content and metadata
        """
        pass

    async def acomplete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list["Tool"] | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
        max_retries: int | None = None,
        system_dynamic_suffix: str | None = None,
    ) -> "LLMResponse":
        """Async version of complete(). Non-blocking on the event loop.

        Default implementation offloads the sync complete() to a thread pool.
        Subclasses SHOULD override for native async I/O.

        ``system_dynamic_suffix`` is an optional per-turn tail for providers
        that honor ``cache_control`` (see LiteLLMProvider for semantics).
        The default implementation concatenates it onto ``system`` since the
        sync ``complete()`` path does not support the split.
        """
        combined_system = system
        if system_dynamic_suffix:
            combined_system = f"{system}\n\n{system_dynamic_suffix}" if system else system_dynamic_suffix
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(
                self.complete,
                messages=messages,
                system=combined_system,
                tools=tools,
                max_tokens=max_tokens,
                response_format=response_format,
                json_mode=json_mode,
                max_retries=max_retries,
            ),
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int | None = None,
        system_dynamic_suffix: str | None = None,
    ) -> AsyncIterator["StreamEvent"]:
        """
        Stream a completion as an async iterator of StreamEvents.

        Default implementation wraps complete() with synthetic events.
        Subclasses SHOULD override for true streaming.

        Tool orchestration is the CALLER's responsibility:
        - Caller detects ToolCallEvent, executes tool, adds result
          to messages, calls stream() again.

        ``system_dynamic_suffix`` is forwarded to ``acomplete``; see its
        docstring for the two-block split semantics.
        """
        from framework.llm.stream_events import (
            FinishEvent,
            TextDeltaEvent,
            TextEndEvent,
        )

        # Resolve here, not in acomplete: a stream's None contract is the
        # MAIN budget (llm.max_tokens), while acomplete's is the aux budget.
        if max_tokens is None:
            from framework.config import get_max_tokens

            max_tokens = get_max_tokens()

        response = await self.acomplete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
            system_dynamic_suffix=system_dynamic_suffix,
        )
        yield TextDeltaEvent(content=response.content, snapshot=response.content)
        yield TextEndEvent(full_text=response.content)
        yield FinishEvent(
            stop_reason=response.stop_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cache_creation_tokens=response.cache_creation_tokens,
            cost_usd=response.cost_usd,
            credits=response.credits,
            model=response.model,
        )


# Deferred import target for type annotation
from framework.llm.stream_events import StreamEvent as StreamEvent  # noqa: E402, F401
