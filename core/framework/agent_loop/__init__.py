"""Agent loop -- the core agent execution primitive."""

from framework.agent_loop.conversation import (  # noqa: F401
    ConversationStore,
    Message,
    NodeConversation,
)
from framework.agent_loop.types import (  # noqa: F401
    AgentContext,
    AgentProtocol,
    AgentResult,
    AgentSpec,
)


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
