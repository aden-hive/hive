"""LLM Provider abstraction for pluggable LLM backends."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LLMResponse:
    """Response from an LLM call."""

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""
    raw_response: Any = None


@dataclass
class Tool:
    """A tool the LLM can use."""

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)


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
        max_tokens: int = 1024,
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
            max_tokens: Maximum tokens to generate
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

    @abstractmethod
    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[Tool],
        tool_executor: Callable[["ToolUse"], "ToolResult"],
        max_iterations: int = 10,
    ) -> LLMResponse:
        """
        Run a tool-use loop until the LLM produces a final response.

        Args:
            messages: Initial conversation
            system: System prompt
            tools: Available tools
            tool_executor: Function to execute tools: (ToolUse) -> ToolResult
            max_iterations: Max tool calls before stopping

        Returns:
            Final LLMResponse after tool use completes
        """
        pass

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator["StreamEvent"]:
        """
        Stream a completion as an async iterator of StreamEvents.

        Default implementation wraps complete() with synthetic events.
        Subclasses SHOULD override for true streaming.

        Tool orchestration is the CALLER's responsibility:
        - Caller detects ToolCallEvent, executes tool, adds result
          to messages, calls stream() again.
        """
        from framework.llm.stream_events import (
            FinishEvent,
            TextDeltaEvent,
            TextEndEvent,
        )

        response = self.complete(
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens,
        )
        yield TextDeltaEvent(content=response.content, snapshot=response.content)
        yield TextEndEvent(full_text=response.content)
        yield FinishEvent(
            stop_reason=response.stop_reason,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            model=response.model,
        )


# Deferred import target for type annotation
from framework.llm.stream_events import StreamEvent as StreamEvent  # noqa: E402, F401
