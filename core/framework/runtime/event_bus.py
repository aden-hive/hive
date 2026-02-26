"""
Event Bus - Pub/sub event system for inter-stream communication.

Allows streams to:
- Publish events about their execution
- Subscribe to events from other streams
- Coordinate based on shared state changes
"""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import IO, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HIVE_DEBUG_EVENTS — write every published event to a JSONL file.
#
# Set the env var to any truthy value to enable:
#   HIVE_DEBUG_EVENTS=1          → writes to ~/.hive/event_logs/<ts>.jsonl
#   HIVE_DEBUG_EVENTS=/tmp/ev    → writes to that exact directory
#
# Each line is a full JSON serialisation of the AgentEvent.
# The file is opened lazily on first publish and flushed after every write.
# ---------------------------------------------------------------------------
_DEBUG_EVENTS_RAW = os.environ.get("HIVE_DEBUG_EVENTS", "").strip()
_DEBUG_EVENTS_ENABLED = _DEBUG_EVENTS_RAW.lower() in ("1", "true", "full") or (
    bool(_DEBUG_EVENTS_RAW) and _DEBUG_EVENTS_RAW.lower() not in ("0", "false", "")
)


def _open_event_log() -> IO[str] | None:
    """Open a JSONL event log file.  Returns None if disabled."""
    if not _DEBUG_EVENTS_ENABLED:
        return None
    raw = _DEBUG_EVENTS_RAW
    if raw.lower() in ("1", "true", "full"):
        log_dir = Path.home() / ".hive" / "event_logs"
    else:
        log_dir = Path(raw)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"{ts}.jsonl"
    logger.info("Event debug log → %s", path)
    return open(path, "a", encoding="utf-8")  # noqa: SIM115


_event_log_file: IO[str] | None = None
_event_log_ready = False  # lazy init guard


class EventType(StrEnum):
    """Types of events that can be published."""

    # Execution lifecycle
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_PAUSED = "execution_paused"
    EXECUTION_RESUMED = "execution_resumed"

    # State changes
    STATE_CHANGED = "state_changed"
    STATE_CONFLICT = "state_conflict"

    # Goal tracking
    GOAL_PROGRESS = "goal_progress"
    GOAL_ACHIEVED = "goal_achieved"
    CONSTRAINT_VIOLATION = "constraint_violation"

    # Stream lifecycle
    STREAM_STARTED = "stream_started"
    STREAM_STOPPED = "stream_stopped"

    # Node event-loop lifecycle
    NODE_LOOP_STARTED = "node_loop_started"
    NODE_LOOP_ITERATION = "node_loop_iteration"
    NODE_LOOP_COMPLETED = "node_loop_completed"
    NODE_ACTION_PLAN = "node_action_plan"

    # LLM streaming observability
    LLM_TEXT_DELTA = "llm_text_delta"
    LLM_REASONING_DELTA = "llm_reasoning_delta"

    # Tool lifecycle
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"

    # Client I/O (client_facing=True nodes only)
    CLIENT_OUTPUT_DELTA = "client_output_delta"
    CLIENT_INPUT_REQUESTED = "client_input_requested"

    # Internal node observability (client_facing=False nodes)
    NODE_INTERNAL_OUTPUT = "node_internal_output"
    NODE_INPUT_BLOCKED = "node_input_blocked"
    NODE_STALLED = "node_stalled"
    NODE_TOOL_DOOM_LOOP = "node_tool_doom_loop"

    # Judge decisions
    JUDGE_VERDICT = "judge_verdict"

    # Output tracking
    OUTPUT_KEY_SET = "output_key_set"

    # Retry / edge tracking
    NODE_RETRY = "node_retry"
    EDGE_TRAVERSED = "edge_traversed"

    # Context management
    CONTEXT_COMPACTED = "context_compacted"

    # External triggers
    WEBHOOK_RECEIVED = "webhook_received"

    # Custom events
    CUSTOM = "custom"

    # Escalation (agent requests handoff to hive_coder)
    ESCALATION_REQUESTED = "escalation_requested"

    # Worker health monitoring (judge → queen → operator)
    WORKER_ESCALATION_TICKET = "worker_escalation_ticket"
    QUEEN_INTERVENTION_REQUESTED = "queen_intervention_requested"

    # Worker lifecycle (session manager → frontend)
    WORKER_LOADED = "worker_loaded"


@dataclass
class AgentEvent:
    """An event in the agent system."""

    type: EventType
    stream_id: str
    node_id: str | None = None  # Which node emitted this event
    execution_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None  # For tracking related events
    graph_id: str | None = None  # Which graph emitted this event (multi-graph sessions)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "stream_id": self.stream_id,
            "node_id": self.node_id,
            "execution_id": self.execution_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "graph_id": self.graph_id,
        }


# Type for event handlers
EventHandler = Callable[[AgentEvent], Awaitable[None]]


@dataclass
class Subscription:
    """A subscription to events."""

    id: str
    event_types: set[EventType]
    handler: EventHandler
    filter_stream: str | None = None  # Only receive events from this stream
    filter_node: str | None = None  # Only receive events from this node
    filter_execution: str | None = None  # Only receive events from this execution
    filter_graph: str | None = None  # Only receive events from this graph


class EventBus:
    """
    Pub/sub event bus for inter-stream communication.

    Features:
    - Async event handling
    - Type-based subscriptions
    - Stream/execution filtering
    - Event history for debugging

    Example:
        bus = EventBus()

        # Subscribe to execution events
        async def on_execution_complete(event: AgentEvent):
            print(f"Execution {event.execution_id} completed")

        bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=on_execution_complete,
        )

        # Publish an event
        await bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="webhook",
            execution_id="exec_123",
            data={"result": "success"},
        ))
    """

    def __init__(
        self,
        max_history: int = 1000,
        max_concurrent_handlers: int = 10,
    ):
        """
        Initialize event bus.

        Args:
            max_history: Maximum events to keep in history
            max_concurrent_handlers: Maximum concurrent handler executions
        """
        self._subscriptions: dict[str, Subscription] = {}
        self._event_history: list[AgentEvent] = []
        self._max_history = max_history
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)
        self._subscription_counter = 0
        self._lock = asyncio.Lock()

    def subscribe(
        self,
        event_types: list[EventType],
        handler: EventHandler,
        filter_stream: str | None = None,
        filter_node: str | None = None,
        filter_execution: str | None = None,
        filter_graph: str | None = None,
    ) -> str:
        """
        Subscribe to events.

        Args:
            event_types: Types of events to receive
            handler: Async function to call when event occurs
            filter_stream: Only receive events from this stream
            filter_node: Only receive events from this node
            filter_execution: Only receive events from this execution
            filter_graph: Only receive events from this graph

        Returns:
            Subscription ID (use to unsubscribe)
        """
        self._subscription_counter += 1
        sub_id = f"sub_{self._subscription_counter}"

        subscription = Subscription(
            id=sub_id,
            event_types=set(event_types),
            handler=handler,
            filter_stream=filter_stream,
            filter_node=filter_node,
            filter_execution=filter_execution,
            filter_graph=filter_graph,
        )

        self._subscriptions[sub_id] = subscription
        logger.debug(f"Subscription {sub_id} registered for {event_types}")

        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from events.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if subscription was found and removed
        """
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            logger.debug(f"Subscription {subscription_id} removed")
            return True
        return False

    async def publish(self, event: AgentEvent) -> None:
        """
        Publish an event to all matching subscribers.

        Args:
            event: Event to publish
        """
        # Add to history
        async with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history :]

        # Write event to JSONL file (gated by HIVE_DEBUG_EVENTS env var)
        if _DEBUG_EVENTS_ENABLED:
            global _event_log_file, _event_log_ready  # noqa: PLW0603
            if not _event_log_ready:
                _event_log_file = _open_event_log()
                _event_log_ready = True
            if _event_log_file is not None:
                try:
                    line = json.dumps(event.to_dict(), default=str)
                    _event_log_file.write(line + "\n")
                    _event_log_file.flush()
                except Exception:
                    pass  # never break event delivery

        # Find matching subscriptions
        matching_handlers: list[EventHandler] = []

        for subscription in self._subscriptions.values():
            if self._matches(subscription, event):
                matching_handlers.append(subscription.handler)

        # Execute handlers concurrently
        if matching_handlers:
            await self._execute_handlers(event, matching_handlers)

    def _matches(self, subscription: Subscription, event: AgentEvent) -> bool:
        """Check if a subscription matches an event."""
        # Check event type
        if event.type not in subscription.event_types:
            return False

        # Check stream filter
        if subscription.filter_stream and subscription.filter_stream != event.stream_id:
            return False

        # Check node filter
        if subscription.filter_node and subscription.filter_node != event.node_id:
            return False

        # Check execution filter
        if subscription.filter_execution and subscription.filter_execution != event.execution_id:
            return False

        # Check graph filter
        if subscription.filter_graph and subscription.filter_graph != event.graph_id:
            return False

        return True

    async def _execute_handlers(
        self,
        event: AgentEvent,
        handlers: list[EventHandler],
    ) -> None:
        """Execute handlers concurrently with rate limiting."""

        async def run_handler(handler: EventHandler) -> None:
            async with self._semaphore:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Handler error for {event.type}: {e}")

        # Run all handlers concurrently
        await asyncio.gather(*[run_handler(h) for h in handlers], return_exceptions=True)

    # === CONVENIENCE PUBLISHERS ===

    async def emit_execution_started(
        self,
        stream_id: str,
        execution_id: str,
        input_data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit execution started event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={"input": input_data or {}},
                correlation_id=correlation_id,
            )
        )

    async def emit_execution_completed(
        self,
        stream_id: str,
        execution_id: str,
        output: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit execution completed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_COMPLETED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={"output": output or {}},
                correlation_id=correlation_id,
            )
        )

    async def emit_execution_failed(
        self,
        stream_id: str,
        execution_id: str,
        error: str,
        correlation_id: str | None = None,
    ) -> None:
        """Emit execution failed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_FAILED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={"error": error},
                correlation_id=correlation_id,
            )
        )

    async def emit_goal_progress(
        self,
        stream_id: str,
        progress: float,
        criteria_status: dict[str, Any],
    ) -> None:
        """Emit goal progress event."""
        await self.publish(
            AgentEvent(
                type=EventType.GOAL_PROGRESS,
                stream_id=stream_id,
                data={
                    "progress": progress,
                    "criteria_status": criteria_status,
                },
            )
        )

    async def emit_constraint_violation(
        self,
        stream_id: str,
        execution_id: str,
        constraint_id: str,
        description: str,
    ) -> None:
        """Emit constraint violation event."""
        await self.publish(
            AgentEvent(
                type=EventType.CONSTRAINT_VIOLATION,
                stream_id=stream_id,
                execution_id=execution_id,
                data={
                    "constraint_id": constraint_id,
                    "description": description,
                },
            )
        )

    async def emit_state_changed(
        self,
        stream_id: str,
        execution_id: str,
        key: str,
        old_value: Any,
        new_value: Any,
        scope: str,
    ) -> None:
        """Emit state changed event."""
        await self.publish(
            AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={
                    "key": key,
                    "old_value": old_value,
                    "new_value": new_value,
                    "scope": scope,
                },
            )
        )

    # === NODE EVENT-LOOP PUBLISHERS ===

    async def emit_node_loop_started(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        """Emit node loop started event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_LOOP_STARTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"max_iterations": max_iterations},
            )
        )

    async def emit_node_loop_iteration(
        self,
        stream_id: str,
        node_id: str,
        iteration: int,
        execution_id: str | None = None,
    ) -> None:
        """Emit node loop iteration event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_LOOP_ITERATION,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"iteration": iteration},
            )
        )

    async def emit_node_loop_completed(
        self,
        stream_id: str,
        node_id: str,
        iterations: int,
        execution_id: str | None = None,
    ) -> None:
        """Emit node loop completed event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_LOOP_COMPLETED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"iterations": iterations},
            )
        )

    async def emit_node_action_plan(
        self,
        stream_id: str,
        node_id: str,
        plan: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit node action plan event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_ACTION_PLAN,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"plan": plan},
            )
        )

    # === LLM STREAMING PUBLISHERS ===

    async def emit_llm_text_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit LLM text delta event."""
        await self.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"content": content, "snapshot": snapshot},
            )
        )

    async def emit_llm_reasoning_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit LLM reasoning delta event."""
        await self.publish(
            AgentEvent(
                type=EventType.LLM_REASONING_DELTA,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"content": content},
            )
        )

    # === TOOL LIFECYCLE PUBLISHERS ===

    async def emit_tool_call_started(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Emit tool call started event."""
        await self.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_STARTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input or {},
                },
            )
        )

    async def emit_tool_call_completed(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        result: str = "",
        is_error: bool = False,
        execution_id: str | None = None,
    ) -> None:
        """Emit tool call completed event."""
        await self.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_COMPLETED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "result": result,
                    "is_error": is_error,
                },
            )
        )

    # === CLIENT I/O PUBLISHERS ===

    async def emit_client_output_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        execution_id: str | None = None,
        iteration: int | None = None,
    ) -> None:
        """Emit client output delta event (client_facing=True nodes)."""
        data: dict = {"content": content, "snapshot": snapshot}
        if iteration is not None:
            data["iteration"] = iteration
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_OUTPUT_DELTA,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_client_input_requested(
        self,
        stream_id: str,
        node_id: str,
        prompt: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit client input requested event (client_facing=True nodes)."""
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_INPUT_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"prompt": prompt},
            )
        )

    # === INTERNAL NODE PUBLISHERS ===

    async def emit_node_internal_output(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit node internal output event (client_facing=False nodes)."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_INTERNAL_OUTPUT,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"content": content},
            )
        )

    async def emit_node_stalled(
        self,
        stream_id: str,
        node_id: str,
        reason: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit node stalled event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_STALLED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"reason": reason},
            )
        )

    async def emit_tool_doom_loop(
        self,
        stream_id: str,
        node_id: str,
        description: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit tool doom loop detection event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_TOOL_DOOM_LOOP,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"description": description},
            )
        )

    async def emit_node_input_blocked(
        self,
        stream_id: str,
        node_id: str,
        prompt: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit node input blocked event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_INPUT_BLOCKED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"prompt": prompt},
            )
        )

    # === JUDGE / OUTPUT / RETRY / EDGE PUBLISHERS ===

    async def emit_judge_verdict(
        self,
        stream_id: str,
        node_id: str,
        action: str,
        feedback: str = "",
        judge_type: str = "implicit",
        iteration: int = 0,
        execution_id: str | None = None,
    ) -> None:
        """Emit judge verdict event."""
        await self.publish(
            AgentEvent(
                type=EventType.JUDGE_VERDICT,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "action": action,
                    "feedback": feedback,
                    "judge_type": judge_type,
                    "iteration": iteration,
                },
            )
        )

    async def emit_output_key_set(
        self,
        stream_id: str,
        node_id: str,
        key: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit output key set event."""
        await self.publish(
            AgentEvent(
                type=EventType.OUTPUT_KEY_SET,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"key": key},
            )
        )

    async def emit_node_retry(
        self,
        stream_id: str,
        node_id: str,
        retry_count: int,
        max_retries: int,
        error: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit node retry event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_RETRY,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "error": error,
                },
            )
        )

    async def emit_edge_traversed(
        self,
        stream_id: str,
        source_node: str,
        target_node: str,
        edge_condition: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit edge traversed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EDGE_TRAVERSED,
                stream_id=stream_id,
                node_id=source_node,
                execution_id=execution_id,
                data={
                    "source_node": source_node,
                    "target_node": target_node,
                    "edge_condition": edge_condition,
                },
            )
        )

    async def emit_execution_paused(
        self,
        stream_id: str,
        node_id: str,
        reason: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit execution paused event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_PAUSED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"reason": reason},
            )
        )

    async def emit_execution_resumed(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit execution resumed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_RESUMED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={},
            )
        )

    async def emit_webhook_received(
        self,
        source_id: str,
        path: str,
        method: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        query_params: dict[str, str] | None = None,
    ) -> None:
        """Emit webhook received event."""
        await self.publish(
            AgentEvent(
                type=EventType.WEBHOOK_RECEIVED,
                stream_id=source_id,
                data={
                    "path": path,
                    "method": method,
                    "headers": headers,
                    "payload": payload,
                    "query_params": query_params or {},
                },
            )
        )

    async def emit_escalation_requested(
        self,
        stream_id: str,
        node_id: str,
        reason: str = "",
        context: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit escalation requested event (agent wants hive_coder)."""
        await self.publish(
            AgentEvent(
                type=EventType.ESCALATION_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"reason": reason, "context": context},
            )
        )

    async def emit_worker_escalation_ticket(
        self,
        stream_id: str,
        node_id: str,
        ticket: dict,
        execution_id: str | None = None,
    ) -> None:
        """Emitted by health judge when worker shows a degradation pattern."""
        await self.publish(
            AgentEvent(
                type=EventType.WORKER_ESCALATION_TICKET,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"ticket": ticket},
            )
        )

    async def emit_queen_intervention_requested(
        self,
        stream_id: str,
        node_id: str,
        ticket_id: str,
        analysis: str,
        severity: str,
        queen_graph_id: str,
        queen_stream_id: str,
        execution_id: str | None = None,
    ) -> None:
        """Emitted by queen when she decides the operator should be involved."""
        await self.publish(
            AgentEvent(
                type=EventType.QUEEN_INTERVENTION_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "ticket_id": ticket_id,
                    "analysis": analysis,
                    "severity": severity,
                    "queen_graph_id": queen_graph_id,
                    "queen_stream_id": queen_stream_id,
                },
            )
        )

    # === QUERY OPERATIONS ===

    def get_history(
        self,
        event_type: EventType | None = None,
        stream_id: str | None = None,
        execution_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentEvent]:
        """
        Get event history with optional filtering.

        Args:
            event_type: Filter by event type
            stream_id: Filter by stream
            execution_id: Filter by execution
            limit: Maximum events to return

        Returns:
            List of matching events (most recent first)
        """
        events = self._event_history[::-1]  # Reverse for most recent first

        # Apply filters
        if event_type:
            events = [e for e in events if e.type == event_type]
        if stream_id:
            events = [e for e in events if e.stream_id == stream_id]
        if execution_id:
            events = [e for e in events if e.execution_id == execution_id]

        return events[:limit]

    def get_stats(self) -> dict:
        """Get event bus statistics."""
        type_counts = {}
        for event in self._event_history:
            type_counts[event.type.value] = type_counts.get(event.type.value, 0) + 1

        return {
            "total_events": len(self._event_history),
            "subscriptions": len(self._subscriptions),
            "events_by_type": type_counts,
        }

    # === WAITING OPERATIONS ===

    async def wait_for(
        self,
        event_type: EventType,
        stream_id: str | None = None,
        node_id: str | None = None,
        execution_id: str | None = None,
        graph_id: str | None = None,
        timeout: float | None = None,
    ) -> AgentEvent | None:
        """
        Wait for a specific event to occur.

        Args:
            event_type: Type of event to wait for
            stream_id: Filter by stream
            node_id: Filter by node
            execution_id: Filter by execution
            graph_id: Filter by graph
            timeout: Maximum time to wait (seconds)

        Returns:
            The event if received, None if timeout
        """
        result: AgentEvent | None = None
        event_received = asyncio.Event()

        async def handler(event: AgentEvent) -> None:
            nonlocal result
            result = event
            event_received.set()

        # Subscribe
        sub_id = self.subscribe(
            event_types=[event_type],
            handler=handler,
            filter_stream=stream_id,
            filter_node=node_id,
            filter_execution=execution_id,
            filter_graph=graph_id,
        )

        try:
            # Wait with timeout
            if timeout:
                try:
                    await asyncio.wait_for(event_received.wait(), timeout=timeout)
                except TimeoutError:
                    return None
            else:
                await event_received.wait()

            return result
        finally:
            self.unsubscribe(sub_id)
