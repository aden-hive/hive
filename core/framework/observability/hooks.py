"""Observability hooks for agent lifecycle monitoring.

ObservabilityHooks defines the contract for observing agent execution.
Implementations receive events at key lifecycle points without modifying
the core execution path.

Built-in implementations:
- NoOpHooks: Zero-overhead default (all methods are no-ops)
- CompositeHooks: Fans out to multiple hook implementations

Usage::

    # Custom monitoring
    class MyHooks(ObservabilityHooks):
        async def on_node_start(self, event: NodeStartEvent) -> None:
            print(f"Node {event.node_id} starting")

    runtime = Runtime(
        storage_path="./logs",
        observability_hooks=MyHooks(),
    )
"""

from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from framework.observability.types import (
    DecisionEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    NodeStartEvent,
    RunCompleteEvent,
    RunStartEvent,
    ToolCallEvent,
)

logger = logging.getLogger(__name__)


@runtime_checkable
class ObservabilityHooks(Protocol):
    """Protocol for lifecycle event observers.

    All methods are async to support non-blocking I/O (e.g., sending
    metrics to a remote backend). Implementations MUST NOT raise —
    hook failures should be logged and swallowed to avoid disrupting
    agent execution.
    """

    async def on_run_start(self, event: RunStartEvent) -> None:
        """Called when a graph run begins."""
        ...

    async def on_node_start(self, event: NodeStartEvent) -> None:
        """Called when a node begins execution."""
        ...

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        """Called when a node finishes (success or failure)."""
        ...

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        """Called when a node raises an exception."""
        ...

    async def on_decision_made(self, event: DecisionEvent) -> None:
        """Called when the agent records a decision via Runtime.decide()."""
        ...

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        """Called when a tool is invoked during node execution."""
        ...

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        """Called when a graph run finishes."""
        ...


class NoOpHooks:
    """Zero-overhead default implementation.

    All methods are synchronous no-ops. Because the protocol methods
    are async, calling code uses ``await``, but Python's ``await`` on
    a regular method that returns ``None`` is essentially free.
    """

    async def on_run_start(self, event: RunStartEvent) -> None:
        pass

    async def on_node_start(self, event: NodeStartEvent) -> None:
        pass

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        pass

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        pass

    async def on_decision_made(self, event: DecisionEvent) -> None:
        pass

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        pass

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        pass


class CompositeHooks:
    """Fans out events to multiple hook implementations.

    Useful for running multiple exporters simultaneously, e.g.
    console + Prometheus + OTLP.

    Exceptions in individual hooks are caught and logged — one failing
    hook does not prevent others from receiving the event.

    Usage::

        hooks = CompositeHooks([
            ConsoleExporter(),
            PrometheusExporter(port=9090),
        ])
    """

    def __init__(self, hooks: list[ObservabilityHooks]) -> None:
        self._hooks = hooks

    async def _dispatch(self, method_name: str, event: object) -> None:
        """Dispatch an event to all registered hooks."""
        for hook in self._hooks:
            try:
                method = getattr(hook, method_name)
                await method(event)
            except Exception:
                logger.exception(
                    "Observability hook %s.%s failed (non-fatal)",
                    type(hook).__name__,
                    method_name,
                )

    async def on_run_start(self, event: RunStartEvent) -> None:
        await self._dispatch("on_run_start", event)

    async def on_node_start(self, event: NodeStartEvent) -> None:
        await self._dispatch("on_node_start", event)

    async def on_node_complete(self, event: NodeCompleteEvent) -> None:
        await self._dispatch("on_node_complete", event)

    async def on_node_error(self, event: NodeErrorEvent) -> None:
        await self._dispatch("on_node_error", event)

    async def on_decision_made(self, event: DecisionEvent) -> None:
        await self._dispatch("on_decision_made", event)

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        await self._dispatch("on_tool_call", event)

    async def on_run_complete(self, event: RunCompleteEvent) -> None:
        await self._dispatch("on_run_complete", event)
