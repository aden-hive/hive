"""Agent loop -- the core agent execution primitive."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.agent_loop.agent_loop import (
        AgentLoop,
        JudgeProtocol,
        JudgeVerdict,
        LoopConfig,
        OutputAccumulator,
    )
    from framework.agent_loop.conversation import ConversationStore, Message, NodeConversation
    from framework.agent_loop.types import AgentContext, AgentProtocol, AgentResult, AgentSpec

__all__ = [
    "AgentContext",
    "AgentProtocol",
    "AgentResult",
    "AgentSpec",
    "ConversationStore",
    "Message",
    "NodeConversation",
    "AgentLoop",
    "JudgeProtocol",
    "JudgeVerdict",
    "LoopConfig",
    "OutputAccumulator",
]

_EXPORTS = {
    "AgentContext": ("framework.agent_loop.types", "AgentContext"),
    "AgentProtocol": ("framework.agent_loop.types", "AgentProtocol"),
    "AgentResult": ("framework.agent_loop.types", "AgentResult"),
    "AgentSpec": ("framework.agent_loop.types", "AgentSpec"),
    "ConversationStore": ("framework.agent_loop.conversation", "ConversationStore"),
    "Message": ("framework.agent_loop.conversation", "Message"),
    "NodeConversation": ("framework.agent_loop.conversation", "NodeConversation"),
    "AgentLoop": ("framework.agent_loop.agent_loop", "AgentLoop"),
    "JudgeProtocol": ("framework.agent_loop.agent_loop", "JudgeProtocol"),
    "JudgeVerdict": ("framework.agent_loop.agent_loop", "JudgeVerdict"),
    "LoopConfig": ("framework.agent_loop.agent_loop", "LoopConfig"),
    "OutputAccumulator": ("framework.agent_loop.agent_loop", "OutputAccumulator"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
