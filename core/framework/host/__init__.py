"""Host layer -- how agents are triggered and hosted."""

from framework.host.agent_host import (  # noqa: F401
    AgentHost,
    AgentRuntimeConfig,
    create_agent_runtime,
)
from framework.host.event_bus import AgentEvent, EventBus, EventType  # noqa: F401
from framework.host.execution_manager import (  # noqa: F401
    EntryPointSpec,
    ExecutionManager,
)
