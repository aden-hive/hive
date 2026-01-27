"""Runtime core for agent execution."""

from framework.runtime.core import Runtime
from framework.runtime.event_bus import EventBus, EventType, AgentEvent
from framework.runtime.event_types import (
    NodeStartedEvent,
    NodeCompletedEvent,
    NodeFailedEvent,
    DecisionMadeEvent,
    DecisionOutcomeEvent,
    ToolCalledEvent,
    ToolResultEvent,
    ExecutionStartedEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionPausedEvent,
    ExecutionResumedEvent,
    GoalProgressEvent,
    ConstraintViolationEvent,
    GuardrailCheckEvent,
)

# WebSocket server (optional - requires websockets package)
try:
    from framework.runtime.websocket_server import (
        WebSocketEventServer,
        create_websocket_server,
    )
    WEBSOCKET_AVAILABLE = True
except ImportError:
    WEBSOCKET_AVAILABLE = False
    WebSocketEventServer = None
    create_websocket_server = None

__all__ = [
    "Runtime",
    # Events
    "EventBus",
    "EventType",
    "AgentEvent",
    # Event Types
    "NodeStartedEvent",
    "NodeCompletedEvent",
    "NodeFailedEvent",
    "DecisionMadeEvent",
    "DecisionOutcomeEvent",
    "ToolCalledEvent",
    "ToolResultEvent",
    "ExecutionStartedEvent",
    "ExecutionCompletedEvent",
    "ExecutionFailedEvent",
    "ExecutionPausedEvent",
    "ExecutionResumedEvent",
    "GoalProgressEvent",
    "ConstraintViolationEvent",
    "GuardrailCheckEvent",
    # WebSocket (optional)
    "WebSocketEventServer",
    "create_websocket_server",
    "WEBSOCKET_AVAILABLE",
]
