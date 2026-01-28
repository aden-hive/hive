"""
Event Bus - Pub/sub event system for inter-stream communication.

Allows streams to:
- Publish events about their execution
- Subscribe to events from other streams
- Coordinate based on shared state changes
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
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

    # Custom events
    CUSTOM = "custom"


@dataclass
class AgentEvent:
    """An event in the agent system."""

    type: EventType
    stream_id: str
    execution_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None  # For tracking related events

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "stream_id": self.stream_id,
            "execution_id": self.execution_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
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
    filter_execution: str | None = None  # Only receive events from this execution


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
        filter_execution: str | None = None,
    ) -> str:
        """
        Subscribe to events.

        Args:
            event_types: Types of events to receive
            handler: Async function to call when event occurs
            filter_stream: Only receive events from this stream
            filter_execution: Only receive events from this execution

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
            filter_execution=filter_execution,
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

        # Check execution filter
        if subscription.filter_execution and subscription.filter_execution != event.execution_id:
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
        execution_id: str | None = None,
        timeout: float | None = None,
    ) -> AgentEvent | None:
        """
        Wait for a specific event to occur.

        Args:
            event_type: Type of event to wait for
            stream_id: Filter by stream
            execution_id: Filter by execution
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
            filter_execution=execution_id,
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
