"""Host layer -- how agents are triggered and hosted."""

from framework.runtime.agent_runtime import (  # noqa: F401
    AgentHost,
    AgentRuntimeConfig,
    create_agent_runtime,
)
from framework.runtime.event_bus import AgentEvent, EventBus, EventType  # noqa: F401
from framework.runtime.execution_stream import (  # noqa: F401
    EntryPointSpec,
    ExecutionManager,
)
