"""
Event Bus - Pub/sub event system for inter-stream communication.

Allows streams to:
- Publish events about their execution
- Subscribe to events from other streams
- Coordinate based on shared state changes

Enhanced with:
- Configurable batch processing for high-throughput scenarios
- Adaptive batch sizing based on load
- Detailed metrics for monitoring
- Priority-based event delivery
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable

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


class EventPriority(int, Enum):
    """Priority levels for events."""
    CRITICAL = 0    # Processed immediately (e.g., constraint violations)
    HIGH = 1        # High priority (e.g., execution completed)
    NORMAL = 2      # Default priority
    LOW = 3         # Batch-friendly (e.g., progress updates)


# Default priority mapping for event types
DEFAULT_EVENT_PRIORITIES: dict[EventType, EventPriority] = {
    EventType.CONSTRAINT_VIOLATION: EventPriority.CRITICAL,
    EventType.EXECUTION_FAILED: EventPriority.CRITICAL,
    EventType.EXECUTION_COMPLETED: EventPriority.HIGH,
    EventType.GOAL_ACHIEVED: EventPriority.HIGH,
    EventType.EXECUTION_STARTED: EventPriority.NORMAL,
    EventType.STREAM_STARTED: EventPriority.NORMAL,
    EventType.STREAM_STOPPED: EventPriority.NORMAL,
    EventType.STATE_CHANGED: EventPriority.NORMAL,
    EventType.STATE_CONFLICT: EventPriority.HIGH,
    EventType.GOAL_PROGRESS: EventPriority.LOW,
    EventType.EXECUTION_PAUSED: EventPriority.NORMAL,
    EventType.EXECUTION_RESUMED: EventPriority.NORMAL,
    EventType.CUSTOM: EventPriority.NORMAL,
}


@dataclass
class AgentEvent:
    """An event in the agent system."""
    type: EventType
    stream_id: str
    execution_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None  # For tracking related events
    priority: EventPriority | None = None  # Optional explicit priority

    def __post_init__(self):
        """Set default priority based on event type if not specified."""
        if self.priority is None:
            self.priority = DEFAULT_EVENT_PRIORITIES.get(
                self.type, EventPriority.NORMAL
            )

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type.value,
            "stream_id": self.stream_id,
            "execution_id": self.execution_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "priority": self.priority.value if self.priority else None,
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


@dataclass
class EventBusConfig:
    """Configuration for EventBus behavior.
    
    Attributes:
        max_history: Maximum events to keep in history
        max_concurrent_handlers: Maximum concurrent handler executions
        enable_batching: Enable batch processing for high-throughput
        batch_interval_ms: Interval between batch flushes (milliseconds)
        max_batch_size: Maximum events per batch
        adaptive_batching: Automatically adjust batch size based on load
        min_batch_size: Minimum batch size when adaptive batching is enabled
        adaptive_threshold_events_per_sec: Events/sec threshold to enable batching
    """
    max_history: int = 1000
    max_concurrent_handlers: int = 10
    enable_batching: bool = False
    batch_interval_ms: int = 50
    max_batch_size: int = 100
    adaptive_batching: bool = False
    min_batch_size: int = 10
    adaptive_threshold_events_per_sec: float = 100.0


@dataclass
class EventBusMetrics:
    """Metrics for EventBus performance monitoring."""
    total_events_published: int = 0
    total_events_delivered: int = 0
    total_handler_errors: int = 0
    total_batches_processed: int = 0
    events_per_batch_avg: float = 0.0
    handler_latency_avg_ms: float = 0.0
    current_queue_size: int = 0
    events_per_second: float = 0.0
    _event_timestamps: list[float] = field(default_factory=list)
    _handler_latencies: list[float] = field(default_factory=list)
    _max_latency_samples: int = 1000
    _events_window_seconds: float = 60.0

    def record_event_published(self) -> None:
        """Record that an event was published."""
        self.total_events_published += 1
        now = time.time()
        self._event_timestamps.append(now)
        # Cleanup old timestamps
        cutoff = now - self._events_window_seconds
        self._event_timestamps = [t for t in self._event_timestamps if t > cutoff]
        # Update events per second
        if self._event_timestamps:
            time_span = max(now - self._event_timestamps[0], 1.0)
            self.events_per_second = len(self._event_timestamps) / time_span

    def record_event_delivered(self) -> None:
        """Record that an event was delivered to a handler."""
        self.total_events_delivered += 1

    def record_handler_error(self) -> None:
        """Record a handler error."""
        self.total_handler_errors += 1

    def record_handler_latency(self, latency_ms: float) -> None:
        """Record handler execution latency."""
        self._handler_latencies.append(latency_ms)
        if len(self._handler_latencies) > self._max_latency_samples:
            self._handler_latencies = self._handler_latencies[-self._max_latency_samples:]
        if self._handler_latencies:
            self.handler_latency_avg_ms = sum(self._handler_latencies) / len(self._handler_latencies)

    def record_batch_processed(self, batch_size: int) -> None:
        """Record that a batch was processed."""
        self.total_batches_processed += 1
        if self.total_batches_processed == 1:
            self.events_per_batch_avg = float(batch_size)
        else:
            # Exponential moving average
            alpha = 0.1
            self.events_per_batch_avg = alpha * batch_size + (1 - alpha) * self.events_per_batch_avg

    def to_dict(self) -> dict:
        """Convert metrics to dictionary."""
        return {
            "total_events_published": self.total_events_published,
            "total_events_delivered": self.total_events_delivered,
            "total_handler_errors": self.total_handler_errors,
            "total_batches_processed": self.total_batches_processed,
            "events_per_batch_avg": round(self.events_per_batch_avg, 2),
            "handler_latency_avg_ms": round(self.handler_latency_avg_ms, 2),
            "current_queue_size": self.current_queue_size,
            "events_per_second": round(self.events_per_second, 2),
        }


class EventBus:
    """
    Pub/sub event bus for inter-stream communication.

    Features:
    - Async event handling
    - Type-based subscriptions
    - Stream/execution filtering
    - Event history for debugging
    - Optional batch processing for high-throughput scenarios
    - Priority-based event delivery
    - Detailed metrics for monitoring

    Example:
        # Standard usage
        bus = EventBus()

        # High-throughput configuration
        config = EventBusConfig(
            enable_batching=True,
            batch_interval_ms=50,
            max_batch_size=100,
            adaptive_batching=True,
        )
        bus = EventBus(config=config)
        await bus.start()  # Start batch processor

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

        await bus.stop()  # Stop batch processor
    """

    def __init__(
        self,
        config: EventBusConfig | None = None,
        # Legacy parameters for backward compatibility
        max_history: int | None = None,
        max_concurrent_handlers: int | None = None,
    ):
        """
        Initialize event bus.

        Args:
            config: EventBus configuration (recommended)
            max_history: [DEPRECATED] Use config.max_history instead
            max_concurrent_handlers: [DEPRECATED] Use config.max_concurrent_handlers instead
        """
        # Handle legacy parameters
        if config is None:
            config = EventBusConfig()
        if max_history is not None:
            config.max_history = max_history
        if max_concurrent_handlers is not None:
            config.max_concurrent_handlers = max_concurrent_handlers

        self._config = config
        self._subscriptions: dict[str, Subscription] = {}
        self._event_history: list[AgentEvent] = []
        self._semaphore = asyncio.Semaphore(config.max_concurrent_handlers)
        self._subscription_counter = 0
        self._lock = asyncio.Lock()

        # Batching infrastructure
        self._event_queue: asyncio.PriorityQueue | None = None
        self._batch_task: asyncio.Task | None = None
        self._running = False

        # Metrics
        self._metrics = EventBusMetrics()

    @property
    def config(self) -> EventBusConfig:
        """Get the current configuration."""
        return self._config

    @property
    def metrics(self) -> EventBusMetrics:
        """Get current metrics."""
        if self._event_queue:
            self._metrics.current_queue_size = self._event_queue.qsize()
        return self._metrics

    async def start(self) -> None:
        """Start the event bus (required for batching mode)."""
        if self._running:
            return

        self._running = True

        if self._config.enable_batching or self._config.adaptive_batching:
            self._event_queue = asyncio.PriorityQueue()
            self._batch_task = asyncio.create_task(self._batch_processor())
            logger.info(
                f"EventBus started with batching (interval={self._config.batch_interval_ms}ms, "
                f"max_batch={self._config.max_batch_size})"
            )
        else:
            logger.info("EventBus started (immediate delivery mode)")

    async def stop(self) -> None:
        """Stop the event bus and flush pending events."""
        if not self._running:
            return

        self._running = False

        if self._batch_task:
            # Process remaining events
            if self._event_queue:
                await self._flush_queue()

            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
            self._batch_task = None

        logger.info("EventBus stopped")

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
        self._metrics.record_event_published()

        # Add to history
        async with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._config.max_history:
                self._event_history = self._event_history[-self._config.max_history:]

        # Determine delivery mode
        should_batch = self._should_batch(event)

        if should_batch and self._event_queue is not None:
            # Queue for batch processing
            # Priority queue item: (priority, timestamp, event)
            # Lower priority value = higher priority
            priority_val = event.priority.value if event.priority else EventPriority.NORMAL.value
            await self._event_queue.put((priority_val, time.time(), event))
        else:
            # Immediate delivery (critical events or non-batching mode)
            await self._deliver_event(event)

    def _should_batch(self, event: AgentEvent) -> bool:
        """Determine if an event should be batched."""
        if not self._running:
            return False

        # Critical events are never batched
        if event.priority == EventPriority.CRITICAL:
            return False

        # Check if batching is enabled
        if self._config.enable_batching:
            return True

        # Adaptive batching: enable if throughput exceeds threshold
        if self._config.adaptive_batching:
            return self._metrics.events_per_second > self._config.adaptive_threshold_events_per_sec

        return False

    async def _deliver_event(self, event: AgentEvent) -> None:
        """Deliver an event to all matching subscribers."""
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
                start_time = time.time()
                try:
                    await handler(event)
                    self._metrics.record_event_delivered()
                except Exception as e:
                    logger.error(f"Handler error for {event.type}: {e}")
                    self._metrics.record_handler_error()
                finally:
                    latency_ms = (time.time() - start_time) * 1000
                    self._metrics.record_handler_latency(latency_ms)

        # Run all handlers concurrently
        await asyncio.gather(*[run_handler(h) for h in handlers], return_exceptions=True)

    async def _batch_processor(self) -> None:
        """Background task that processes batched events."""
        while self._running:
            try:
                batch: list[AgentEvent] = []
                batch_start = time.time()

                # Determine effective batch size (adaptive)
                if self._config.adaptive_batching:
                    # Scale batch size based on throughput
                    throughput_ratio = self._metrics.events_per_second / max(
                        self._config.adaptive_threshold_events_per_sec, 1.0
                    )
                    effective_batch_size = min(
                        int(self._config.min_batch_size + 
                            (self._config.max_batch_size - self._config.min_batch_size) * 
                            min(throughput_ratio, 1.0)),
                        self._config.max_batch_size
                    )
                else:
                    effective_batch_size = self._config.max_batch_size

                # Collect events for the batch
                interval_sec = self._config.batch_interval_ms / 1000.0

                while len(batch) < effective_batch_size:
                    remaining_time = interval_sec - (time.time() - batch_start)
                    if remaining_time <= 0:
                        break

                    try:
                        _, _, event = await asyncio.wait_for(
                            self._event_queue.get(),
                            timeout=remaining_time
                        )
                        batch.append(event)
                    except asyncio.TimeoutError:
                        break

                # Process the batch
                if batch:
                    self._metrics.record_batch_processed(len(batch))
                    # Deliver all events in the batch
                    await asyncio.gather(
                        *[self._deliver_event(event) for event in batch],
                        return_exceptions=True
                    )

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Batch processor error: {e}")

    async def _flush_queue(self) -> None:
        """Flush all remaining events in the queue."""
        if not self._event_queue:
            return

        events = []
        while not self._event_queue.empty():
            try:
                _, _, event = self._event_queue.get_nowait()
                events.append(event)
            except asyncio.QueueEmpty:
                break

        if events:
            await asyncio.gather(
                *[self._deliver_event(event) for event in events],
                return_exceptions=True
            )

    # === CONVENIENCE PUBLISHERS ===

    async def emit_execution_started(
        self,
        stream_id: str,
        execution_id: str,
        input_data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit execution started event."""
        await self.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id=stream_id,
            execution_id=execution_id,
            data={"input": input_data or {}},
            correlation_id=correlation_id,
        ))

    async def emit_execution_completed(
        self,
        stream_id: str,
        execution_id: str,
        output: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> None:
        """Emit execution completed event."""
        await self.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id=stream_id,
            execution_id=execution_id,
            data={"output": output or {}},
            correlation_id=correlation_id,
        ))

    async def emit_execution_failed(
        self,
        stream_id: str,
        execution_id: str,
        error: str,
        correlation_id: str | None = None,
    ) -> None:
        """Emit execution failed event."""
        await self.publish(AgentEvent(
            type=EventType.EXECUTION_FAILED,
            stream_id=stream_id,
            execution_id=execution_id,
            data={"error": error},
            correlation_id=correlation_id,
        ))

    async def emit_goal_progress(
        self,
        stream_id: str,
        progress: float,
        criteria_status: dict[str, Any],
    ) -> None:
        """Emit goal progress event."""
        await self.publish(AgentEvent(
            type=EventType.GOAL_PROGRESS,
            stream_id=stream_id,
            data={
                "progress": progress,
                "criteria_status": criteria_status,
            },
        ))

    async def emit_constraint_violation(
        self,
        stream_id: str,
        execution_id: str,
        constraint_id: str,
        description: str,
    ) -> None:
        """Emit constraint violation event."""
        await self.publish(AgentEvent(
            type=EventType.CONSTRAINT_VIOLATION,
            stream_id=stream_id,
            execution_id=execution_id,
            data={
                "constraint_id": constraint_id,
                "description": description,
            },
        ))

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
        await self.publish(AgentEvent(
            type=EventType.STATE_CHANGED,
            stream_id=stream_id,
            execution_id=execution_id,
            data={
                "key": key,
                "old_value": old_value,
                "new_value": new_value,
                "scope": scope,
            },
        ))

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
            "metrics": self._metrics.to_dict(),
            "config": {
                "batching_enabled": self._config.enable_batching,
                "adaptive_batching": self._config.adaptive_batching,
                "batch_interval_ms": self._config.batch_interval_ms,
                "max_batch_size": self._config.max_batch_size,
                "max_concurrent_handlers": self._config.max_concurrent_handlers,
            },
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
                except asyncio.TimeoutError:
                    return None
            else:
                await event_received.wait()

            return result
        finally:
            self.unsubscribe(sub_id)
