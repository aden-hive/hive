"""Agent loop -- the core agent execution primitive."""

from framework.agent_loop.conversation import (  # noqa: F401
    ConversationStore,
    Message,
    NodeConversation,
)

# Lazy import to avoid circular dependency with graph/event_loop/
# (graph/event_loop/* imports framework.graph.conversation which is a shim
# pointing here, which would trigger agent_loop.py loading, which imports
# graph/event_loop/* again)


def __getattr__(name: str):
    if name in ("AgentLoop", "JudgeProtocol", "JudgeVerdict", "LoopConfig", "OutputAccumulator"):
        from framework.agent_loop.agent_loop import (
            AgentLoop,
            JudgeProtocol,
            JudgeVerdict,
            LoopConfig,
            OutputAccumulator,
        )
        _exports = {
            "AgentLoop": AgentLoop,
            "JudgeProtocol": JudgeProtocol,
            "JudgeVerdict": JudgeVerdict,
            "LoopConfig": LoopConfig,
            "OutputAccumulator": OutputAccumulator,
        }
        return _exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
