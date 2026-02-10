"""
Observability module for automatic trace correlation, structured logging,
and lifecycle hooks.

This module provides zero-friction observability:
- Automatic trace context propagation via ContextVar
- Structured JSON logging for production
- Human-readable logging for development
- Lifecycle hooks for monitoring and telemetry
- No manual ID passing required
"""

from framework.observability.config import ObservabilityConfig
from framework.observability.hooks import (
    CompositeHooks,
    NoOpHooks,
    ObservabilityHooks,
)
from framework.observability.logging import (
    clear_trace_context,
    configure_logging,
    get_trace_context,
    set_trace_context,
)
from framework.observability.types import (
    DecisionEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    NodeStartEvent,
    RunCompleteEvent,
    RunStartEvent,
    ToolCallEvent,
)

__all__ = [
    # Logging
    "configure_logging",
    "get_trace_context",
    "set_trace_context",
    "clear_trace_context",
    # Hooks
    "ObservabilityHooks",
    "NoOpHooks",
    "CompositeHooks",
    "ObservabilityConfig",
    # Event types
    "RunStartEvent",
    "NodeStartEvent",
    "NodeCompleteEvent",
    "NodeErrorEvent",
    "DecisionEvent",
    "ToolCallEvent",
    "RunCompleteEvent",
]
