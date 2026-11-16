"""Hive's primitives, for projects built on Hive.

    from hive import AgentLoop, AgentContext, AgentSpec, LiteLLMProvider, Tool, ToolResult

    loop = AgentLoop(tool_executor=run_tool, on_report=keep)
    result = await loop.execute(AgentContext(runtime=None, agent_id="a1", agent_spec=spec, llm=llm))

Each name is imported when first used, so ``import hive`` is cheap and a project pays only for
the parts it touches. ``SSEResponse`` needs the ``server`` extra (aiohttp), so ``from hive import *``
leaves it out; colonies and Hive's own tools need the ``tools`` extra. Everything else in Hive stays importable under ``framework``.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.agent_loop.agent_loop import AgentLoop
    from framework.agent_loop.conversation import ConversationStore, Message
    from framework.agent_loop.internals.types import JudgeProtocol, JudgeVerdict, LoopConfig
    from framework.agent_loop.types import AgentContext, AgentProtocol, AgentReport, AgentResult, AgentSpec
    from framework.config import (
        HIVE_HOME,
        RuntimeConfig,
        get_api_base,
        get_api_key,
        get_hive_config,
        get_preferred_model,
    )
    from framework.host.colony_runtime import ColonyConfig, ColonyRuntime
    from framework.host.event_bus import AgentEvent, EventBus, EventType
    from framework.host.worker import Worker
    from framework.llm.anthropic import AnthropicProvider
    from framework.llm.litellm import LiteLLMProvider
    from framework.llm.mock import MockLLMProvider
    from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
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
    from framework.loader.agent_loader import AgentLoader
    from framework.server.channels import Channel, ChannelError, ChannelHost, QueenOutput
    from framework.server.sse import SSEResponse as SSEResponse  # not in __all__: it needs the server extra
    from framework.server.turn_context import TurnContext, TurnContextHost
    from framework.storage.conversation_store import FileConversationStore
    from framework.tracker.decision_tracker import DecisionTracker

try:
    __version__ = version("aden-hive")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0+unknown"

_EXPORTS: dict[str, str] = {
    # The agent loop: one agent's turns, its tools, and what it reports.
    "AgentLoop": "framework.agent_loop.agent_loop",
    "LoopConfig": "framework.agent_loop.internals.types",
    "JudgeProtocol": "framework.agent_loop.internals.types",
    "JudgeVerdict": "framework.agent_loop.internals.types",
    "AgentContext": "framework.agent_loop.types",
    "AgentProtocol": "framework.agent_loop.types",
    "AgentReport": "framework.agent_loop.types",
    "AgentResult": "framework.agent_loop.types",
    "AgentSpec": "framework.agent_loop.types",
    "ConversationStore": "framework.agent_loop.conversation",
    "Message": "framework.agent_loop.conversation",
    "FileConversationStore": "framework.storage.conversation_store",
    # Models.
    "LLMProvider": "framework.llm.provider",
    "LLMResponse": "framework.llm.provider",
    "Tool": "framework.llm.provider",
    "ToolUse": "framework.llm.provider",
    "ToolResult": "framework.llm.provider",
    "LiteLLMProvider": "framework.llm.litellm",
    "AnthropicProvider": "framework.llm.anthropic",
    "MockLLMProvider": "framework.llm.mock",
    "StreamEvent": "framework.llm.stream_events",
    "TextDeltaEvent": "framework.llm.stream_events",
    "TextEndEvent": "framework.llm.stream_events",
    "ToolCallEvent": "framework.llm.stream_events",
    "ToolResultEvent": "framework.llm.stream_events",
    "ReasoningStartEvent": "framework.llm.stream_events",
    "ReasoningDeltaEvent": "framework.llm.stream_events",
    "FinishEvent": "framework.llm.stream_events",
    "StreamErrorEvent": "framework.llm.stream_events",
    # Events.
    "EventBus": "framework.host.event_bus",
    "AgentEvent": "framework.host.event_bus",
    "EventType": "framework.host.event_bus",
    # Hosting many agents (colonies need the ``tools`` extra to run workers).
    "ColonyRuntime": "framework.host.colony_runtime",
    "ColonyConfig": "framework.host.colony_runtime",
    "Worker": "framework.host.worker",
    "AgentLoader": "framework.loader.agent_loader",
    "DecisionTracker": "framework.tracker.decision_tracker",
    # The user's Hive configuration: home, model and keys.
    "HIVE_HOME": "framework.config",
    "RuntimeConfig": "framework.config",
    "get_hive_config": "framework.config",
    "get_preferred_model": "framework.config",
    "get_api_key": "framework.config",
    "get_api_base": "framework.config",
    # Serving (needs the ``server`` extra).
    "SSEResponse": "framework.server.sse",
    # Channels: chat apps that reach queens from inside ``hive serve`` (see framework.server.channels).
    "Channel": "framework.server.channels",
    "ChannelError": "framework.server.channels",
    "ChannelHost": "framework.server.channels",
    "QueenOutput": "framework.server.channels",
    # Turn context: what installed packages put in front of a queen before her turn (see framework.server.turn_context).
    "TurnContext": "framework.server.turn_context",
    "TurnContextHost": "framework.server.turn_context",
}

__all__ = [
    "__version__",
    "AgentContext",
    "AgentEvent",
    "AgentLoader",
    "AgentLoop",
    "AgentProtocol",
    "AgentReport",
    "AgentResult",
    "AgentSpec",
    "AnthropicProvider",
    "Channel",
    "ChannelError",
    "ChannelHost",
    "ColonyConfig",
    "ColonyRuntime",
    "ConversationStore",
    "DecisionTracker",
    "EventBus",
    "EventType",
    "FileConversationStore",
    "FinishEvent",
    "HIVE_HOME",
    "JudgeProtocol",
    "JudgeVerdict",
    "LLMProvider",
    "LLMResponse",
    "LiteLLMProvider",
    "LoopConfig",
    "Message",
    "MockLLMProvider",
    "QueenOutput",
    "ReasoningDeltaEvent",
    "ReasoningStartEvent",
    "RuntimeConfig",
    "StreamErrorEvent",
    "StreamEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "Tool",
    "ToolCallEvent",
    "ToolResult",
    "ToolResultEvent",
    "ToolUse",
    "TurnContext",
    "TurnContextHost",
    "Worker",
    "get_api_base",
    "get_api_key",
    "get_hive_config",
    "get_preferred_model",
]


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value  # resolved once
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__, *_EXPORTS})
