"""LLM provider abstraction."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider, LLMResponse
    from framework.llm.stream_events import (
        FinishEvent,
        ReasoningDeltaEvent,
        ReasoningStartEvent,
        StreamErrorEvent,
        StreamEvent,
        TextDeltaEvent,
        TextEndEvent,
        ToolCallEvent,
        ToolResultEvent,
    )

__all__ = [
    "LLMProvider",
    "LLMResponse",
    "StreamEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ReasoningStartEvent",
    "ReasoningDeltaEvent",
    "FinishEvent",
    "StreamErrorEvent",
]

_OPTIONAL_EXPORTS = {
    "AnthropicProvider": ("framework.llm.anthropic", "AnthropicProvider"),
    "LiteLLMProvider": ("framework.llm.litellm", "LiteLLMProvider"),
    "MockLLMProvider": ("framework.llm.mock", "MockLLMProvider"),
}


def __getattr__(name: str) -> Any:
    if name in {"LLMProvider", "LLMResponse"}:
        module = import_module("framework.llm.provider")
        value = getattr(module, name)
        globals()[name] = value
        return value

    if name in {"FinishEvent", "ReasoningDeltaEvent", "ReasoningStartEvent", "StreamErrorEvent", "StreamEvent", "TextDeltaEvent", "TextEndEvent", "ToolCallEvent", "ToolResultEvent"}:
        module = import_module("framework.llm.stream_events")
        value = getattr(module, name)
        globals()[name] = value
        return value

    if name in _OPTIONAL_EXPORTS:
        module_name, attr_name = _OPTIONAL_EXPORTS[name]
        try:
            module = import_module(module_name)
        except ImportError:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
        value = getattr(module, attr_name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
