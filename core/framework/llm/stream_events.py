"""Stream event types for LLM streaming responses.

Defines a discriminated union of frozen dataclasses representing every event
a streaming LLM call can produce. These types form the contract between the
LLM provider layer, EventLoopNode, event bus, persistence, and monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class TextDeltaEvent:
    """A chunk of text produced by the LLM."""

    type: Literal["text_delta"] = "text_delta"
    content: str = ""  # this chunk's text
    snapshot: str = ""  # accumulated text so far


@dataclass(frozen=True)
class TextEndEvent:
    """Signals that text generation is complete."""

    type: Literal["text_end"] = "text_end"
    full_text: str = ""


@dataclass(frozen=True)
class ToolCallEvent:
    """The LLM has requested a tool call."""

    type: Literal["tool_call"] = "tool_call"
    tool_use_id: str = ""
    tool_name: str = ""
    tool_input: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResultEvent:
    """Result of executing a tool call."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str = ""
    content: str = ""
    is_error: bool = False


@dataclass(frozen=True)
class ReasoningStartEvent:
    """The LLM has started a reasoning/thinking block."""

    type: Literal["reasoning_start"] = "reasoning_start"


@dataclass(frozen=True)
class ReasoningDeltaEvent:
    """A chunk of reasoning/thinking content."""

    type: Literal["reasoning_delta"] = "reasoning_delta"
    content: str = ""


@dataclass(frozen=True)
class FinishEvent:
    """The LLM has finished generating."""

    type: Literal["finish"] = "finish"
    stop_reason: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""


@dataclass(frozen=True)
class StreamErrorEvent:
    """An error occurred during streaming."""

    type: Literal["error"] = "error"
    error: str = ""
    recoverable: bool = False


# Discriminated union of all stream event types
StreamEvent = (
    TextDeltaEvent
    | TextEndEvent
    | ToolCallEvent
    | ToolResultEvent
    | ReasoningStartEvent
    | ReasoningDeltaEvent
    | FinishEvent
    | StreamErrorEvent
)
