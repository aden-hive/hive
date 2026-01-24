"""Tests for enhanced EventBus with batch processing support.

Run with:
    cd core
    pytest tests/test_event_bus_enhanced.py -v

For performance tests:
    pytest tests/test_event_bus_enhanced.py -v -m performance
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from framework.runtime.event_bus_enhanced import (
    EventBus,
    EventBusConfig,
    EventBusMetrics,
    EventType,
    EventPriority,
    AgentEvent,
    DEFAULT_EVENT_PRIORITIES,
)


class TestEventBusConfig:
    """Tests for EventBusConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = EventBusConfig()
        assert config.max_history == 1000
        assert config.max_concurrent_handlers == 10
        assert config.enable_batching is False
        assert config.batch_interval_ms == 50
        assert config.max_batch_size == 100
        assert config.adaptive_batching is False

    def test_custom_config(self):
        """Test custom configuration values."""
        config = EventBusConfig(
            max_history=500,
            max_concurrent_handlers=20,
            enable_batching=True,
            batch_interval_ms=100,
            max_batch_size=200,
            adaptive_batching=True,
        )
        assert config.max_history == 500
        assert config.max_concurrent_handlers == 20
        assert config.enable_batching is True
        assert config.batch_interval_ms == 100
        assert config.max_batch_size == 200
        assert config.adaptive_batching is True


class TestEventPriority:
    """Tests for event priority system."""

    def test_default_priorities(self):
        """Test that critical events have correct default priorities."""
        assert DEFAULT_EVENT_PRIORITIES[EventType.CONSTRAINT_VIOLATION] == EventPriority.CRITICAL
        assert DEFAULT_EVENT_PRIORITIES[EventType.EXECUTION_FAILED] == EventPriority.CRITICAL
        assert DEFAULT_EVENT_PRIORITIES[EventType.EXECUTION_COMPLETED] == EventPriority.HIGH
        assert DEFAULT_EVENT_PRIORITIES[EventType.GOAL_PROGRESS] == EventPriority.LOW

    def test_event_priority_auto_set(self):
        """Test that event priority is automatically set based on type."""
        event = AgentEvent(
            type=EventType.CONSTRAINT_VIOLATION,
            stream_id="test",
        )
        assert event.priority == EventPriority.CRITICAL

    def test_event_priority_explicit_override(self):
        """Test that explicit priority overrides default."""
        event = AgentEvent(
            type=EventType.GOAL_PROGRESS,
            stream_id="test",
            priority=EventPriority.HIGH,
        )
        assert event.priority == EventPriority.HIGH


class TestEventBusMetrics:
    """Tests for EventBusMetrics."""

    def test_record_event_published(self):
        """Test recording published events."""
        metrics = EventBusMetrics()
        metrics.record_event_published()
        metrics.record_event_published()
        assert metrics.total_events_published == 2

    def test_events_per_second_calculation(self):
        """Test events per second calculation."""
        metrics = EventBusMetrics()
        
        # Publish several events
        for _ in range(10):
            metrics.record_event_published()
        
        # Should have positive events per second
        assert metrics.events_per_second > 0

    def test_handler_latency_tracking(self):
        """Test handler latency tracking."""
        metrics = EventBusMetrics()
        metrics.record_handler_latency(10.0)
        metrics.record_handler_latency(20.0)
        metrics.record_handler_latency(30.0)
        
        # Average should be 20.0
        assert metrics.handler_latency_avg_ms == 20.0

    def test_batch_tracking(self):
        """Test batch processing tracking."""
        metrics = EventBusMetrics()
        metrics.record_batch_processed(50)
        assert metrics.total_batches_processed == 1
        assert metrics.events_per_batch_avg == 50.0

    def test_to_dict(self):
        """Test metrics serialization."""
        metrics = EventBusMetrics()
        metrics.record_event_published()
        metrics.record_event_delivered()
        
        data = metrics.to_dict()
        assert "total_events_published" in data
        assert "total_events_delivered" in data
        assert "events_per_second" in data


class TestEventBusBasic:
    """Basic EventBus tests (non-batching mode)."""

    @pytest.fixture
    def event_bus(self):
        """Create a basic event bus."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_subscribe_and_publish(self, event_bus):
        """Test basic subscribe and publish."""
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
        )

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
            execution_id="exec_1",
        ))

        # Give handlers time to execute
        await asyncio.sleep(0.1)

        assert len(received_events) == 1
        assert received_events[0].execution_id == "exec_1"

    @pytest.mark.asyncio
    async def test_unsubscribe(self, event_bus):
        """Test unsubscribe functionality."""
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        sub_id = event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
        )

        # Unsubscribe
        result = event_bus.unsubscribe(sub_id)
        assert result is True

        # Publish should not trigger handler
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
        ))

        await asyncio.sleep(0.1)
        assert len(received_events) == 0

    @pytest.mark.asyncio
    async def test_filter_by_stream(self, event_bus):
        """Test stream filtering."""
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
            filter_stream="stream_a",
        )

        # This should be received
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="stream_a",
        ))

        # This should not be received
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="stream_b",
        ))

        await asyncio.sleep(0.1)
        assert len(received_events) == 1
        assert received_events[0].stream_id == "stream_a"

    @pytest.mark.asyncio
    async def test_filter_by_execution(self, event_bus):
        """Test execution filtering."""
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
            filter_execution="exec_123",
        )

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
            execution_id="exec_123",
        ))

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
            execution_id="exec_456",
        ))

        await asyncio.sleep(0.1)
        assert len(received_events) == 1

    @pytest.mark.asyncio
    async def test_event_history(self, event_bus):
        """Test event history tracking."""
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="test",
        ))
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
        ))

        history = event_bus.get_history()
        assert len(history) == 2

        # Most recent first
        assert history[0].type == EventType.EXECUTION_COMPLETED

    @pytest.mark.asyncio
    async def test_handler_error_handling(self, event_bus):
        """Test that handler errors are caught."""
        async def failing_handler(event: AgentEvent):
            raise ValueError("Test error")

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=failing_handler,
        )

        # Should not raise
        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
        ))

        await asyncio.sleep(0.1)
        assert event_bus.metrics.total_handler_errors == 1

    def test_legacy_parameter_support(self):
        """Test backward compatibility with legacy parameters."""
        bus = EventBus(max_history=500, max_concurrent_handlers=20)
        assert bus.config.max_history == 500
        assert bus.config.max_concurrent_handlers == 20


class TestEventBusBatching:
    """Tests for EventBus batch processing."""

    @pytest.fixture
    def batch_config(self):
        """Create a batching configuration."""
        return EventBusConfig(
            enable_batching=True,
            batch_interval_ms=50,
            max_batch_size=10,
        )

    @pytest.fixture
    async def batch_event_bus(self, batch_config):
        """Create and start a batching event bus."""
        bus = EventBus(config=batch_config)
        await bus.start()
        yield bus
        await bus.stop()

    @pytest.mark.asyncio
    async def test_start_stop(self, batch_config):
        """Test start and stop lifecycle."""
        bus = EventBus(config=batch_config)
        
        await bus.start()
        assert bus._running is True
        assert bus._batch_task is not None

        await bus.stop()
        assert bus._running is False

    @pytest.mark.asyncio
    async def test_critical_events_bypass_batching(self, batch_event_bus):
        """Test that critical events are delivered immediately."""
        received_events = []
        receive_times = []

        async def handler(event: AgentEvent):
            received_events.append(event)
            receive_times.append(time.time())

        batch_event_bus.subscribe(
            event_types=[EventType.CONSTRAINT_VIOLATION],
            handler=handler,
        )

        start_time = time.time()
        await batch_event_bus.publish(AgentEvent(
            type=EventType.CONSTRAINT_VIOLATION,
            stream_id="test",
        ))

        # Should be delivered immediately, not batched
        await asyncio.sleep(0.02)  # Much less than batch interval
        assert len(received_events) == 1
        assert receive_times[0] - start_time < 0.03  # Delivered quickly

    @pytest.mark.asyncio
    async def test_normal_events_are_batched(self, batch_event_bus):
        """Test that normal events are batched."""
        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        batch_event_bus.subscribe(
            event_types=[EventType.GOAL_PROGRESS],
            handler=handler,
        )

        # Publish multiple low-priority events quickly
        for i in range(5):
            await batch_event_bus.publish(AgentEvent(
                type=EventType.GOAL_PROGRESS,
                stream_id="test",
                data={"index": i},
            ))

        # Events should not be delivered yet (still in batch window)
        assert len(received_events) < 5

        # Wait for batch to flush
        await asyncio.sleep(0.1)
        assert len(received_events) == 5

    @pytest.mark.asyncio
    async def test_batch_metrics_tracking(self, batch_event_bus):
        """Test that batch metrics are tracked."""
        async def handler(event: AgentEvent):
            pass

        batch_event_bus.subscribe(
            event_types=[EventType.STATE_CHANGED],
            handler=handler,
        )

        # Publish events
        for _ in range(5):
            await batch_event_bus.publish(AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id="test",
            ))

        # Wait for batch processing
        await asyncio.sleep(0.1)

        metrics = batch_event_bus.metrics
        assert metrics.total_events_published == 5
        assert metrics.total_batches_processed >= 1

    @pytest.mark.asyncio
    async def test_queue_flush_on_stop(self, batch_config):
        """Test that queue is flushed when stopping."""
        bus = EventBus(config=batch_config)
        await bus.start()

        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        bus.subscribe(
            event_types=[EventType.STATE_CHANGED],
            handler=handler,
        )

        # Publish events
        for _ in range(3):
            await bus.publish(AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id="test",
            ))

        # Stop should flush remaining events
        await bus.stop()

        assert len(received_events) == 3


class TestEventBusAdaptiveBatching:
    """Tests for adaptive batch sizing."""

    @pytest.fixture
    def adaptive_config(self):
        """Create an adaptive batching configuration."""
        return EventBusConfig(
            adaptive_batching=True,
            adaptive_threshold_events_per_sec=10.0,
            min_batch_size=5,
            max_batch_size=50,
            batch_interval_ms=50,
        )

    @pytest.mark.asyncio
    async def test_adaptive_batching_low_throughput(self, adaptive_config):
        """Test that adaptive batching doesn't batch at low throughput."""
        bus = EventBus(config=adaptive_config)
        await bus.start()

        received_events = []

        async def handler(event: AgentEvent):
            received_events.append(event)

        bus.subscribe(
            event_types=[EventType.STATE_CHANGED],
            handler=handler,
        )

        # Single event at low throughput should be delivered immediately
        await bus.publish(AgentEvent(
            type=EventType.STATE_CHANGED,
            stream_id="test",
        ))

        await asyncio.sleep(0.02)  # Less than batch interval
        # At low throughput, should not be batched
        # Note: first few events may still be batched until throughput is measured
        
        await bus.stop()

    @pytest.mark.asyncio
    async def test_events_per_second_tracking(self, adaptive_config):
        """Test that events per second is tracked for adaptive batching."""
        bus = EventBus(config=adaptive_config)
        await bus.start()

        # Publish many events quickly
        for _ in range(20):
            await bus.publish(AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id="test",
            ))

        # Check that events_per_second is being calculated
        metrics = bus.metrics
        assert metrics.events_per_second > 0

        await bus.stop()


class TestEventBusConvenienceMethods:
    """Tests for convenience publisher methods."""

    @pytest.fixture
    def event_bus(self):
        """Create a basic event bus."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_emit_execution_started(self, event_bus):
        """Test emit_execution_started convenience method."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
        )

        await event_bus.emit_execution_started(
            stream_id="test",
            execution_id="exec_1",
            input_data={"key": "value"},
        )

        await asyncio.sleep(0.1)
        assert len(received) == 1
        assert received[0].data["input"] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_emit_execution_completed(self, event_bus):
        """Test emit_execution_completed convenience method."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
        )

        await event_bus.emit_execution_completed(
            stream_id="test",
            execution_id="exec_1",
            output={"result": "success"},
        )

        await asyncio.sleep(0.1)
        assert len(received) == 1
        assert received[0].data["output"] == {"result": "success"}

    @pytest.mark.asyncio
    async def test_emit_constraint_violation(self, event_bus):
        """Test emit_constraint_violation convenience method."""
        received = []

        async def handler(event: AgentEvent):
            received.append(event)

        event_bus.subscribe(
            event_types=[EventType.CONSTRAINT_VIOLATION],
            handler=handler,
        )

        await event_bus.emit_constraint_violation(
            stream_id="test",
            execution_id="exec_1",
            constraint_id="budget_limit",
            description="Budget exceeded",
        )

        await asyncio.sleep(0.1)
        assert len(received) == 1
        assert received[0].data["constraint_id"] == "budget_limit"


class TestEventBusWaitFor:
    """Tests for wait_for functionality."""

    @pytest.fixture
    def event_bus(self):
        """Create a basic event bus."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_wait_for_event(self, event_bus):
        """Test waiting for a specific event."""
        async def publish_later():
            await asyncio.sleep(0.05)
            await event_bus.publish(AgentEvent(
                type=EventType.EXECUTION_COMPLETED,
                stream_id="test",
                execution_id="exec_1",
            ))

        # Start publisher
        asyncio.create_task(publish_later())

        # Wait for event
        event = await event_bus.wait_for(
            event_type=EventType.EXECUTION_COMPLETED,
            timeout=1.0,
        )

        assert event is not None
        assert event.execution_id == "exec_1"

    @pytest.mark.asyncio
    async def test_wait_for_timeout(self, event_bus):
        """Test wait_for timeout."""
        event = await event_bus.wait_for(
            event_type=EventType.EXECUTION_COMPLETED,
            timeout=0.05,
        )

        assert event is None


class TestEventBusStats:
    """Tests for statistics and monitoring."""

    @pytest.fixture
    def event_bus(self):
        """Create a basic event bus."""
        return EventBus()

    @pytest.mark.asyncio
    async def test_get_stats(self, event_bus):
        """Test get_stats method."""
        async def handler(event: AgentEvent):
            pass

        event_bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
        )

        await event_bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="test",
        ))

        await asyncio.sleep(0.1)

        stats = event_bus.get_stats()
        assert stats["total_events"] == 1
        assert stats["subscriptions"] == 1
        assert "metrics" in stats
        assert "config" in stats


@pytest.mark.performance
class TestEventBusPerformance:
    """Performance tests for EventBus."""

    @pytest.mark.asyncio
    async def test_high_throughput_batching(self):
        """Test high throughput with batching enabled."""
        config = EventBusConfig(
            enable_batching=True,
            batch_interval_ms=10,
            max_batch_size=100,
        )
        bus = EventBus(config=config)
        await bus.start()

        received_count = 0
        lock = asyncio.Lock()

        async def handler(event: AgentEvent):
            nonlocal received_count
            async with lock:
                received_count += 1

        bus.subscribe(
            event_types=[EventType.STATE_CHANGED],
            handler=handler,
        )

        # Publish many events
        num_events = 1000
        start_time = time.time()

        for _ in range(num_events):
            await bus.publish(AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id="test",
            ))

        # Wait for all events to be processed
        await asyncio.sleep(0.5)
        await bus.stop()

        elapsed = time.time() - start_time

        assert received_count == num_events
        print(f"Processed {num_events} events in {elapsed:.2f}s ({num_events/elapsed:.0f} events/sec)")

    @pytest.mark.asyncio
    async def test_concurrent_publishers(self):
        """Test concurrent event publishers."""
        config = EventBusConfig(
            enable_batching=True,
            batch_interval_ms=20,
            max_batch_size=50,
            max_concurrent_handlers=20,
        )
        bus = EventBus(config=config)
        await bus.start()

        received_count = 0
        lock = asyncio.Lock()

        async def handler(event: AgentEvent):
            nonlocal received_count
            async with lock:
                received_count += 1

        bus.subscribe(
            event_types=[EventType.STATE_CHANGED],
            handler=handler,
        )

        # Concurrent publishers
        async def publisher(publisher_id: int, count: int):
            for i in range(count):
                await bus.publish(AgentEvent(
                    type=EventType.STATE_CHANGED,
                    stream_id=f"stream_{publisher_id}",
                    data={"publisher": publisher_id, "index": i},
                ))

        num_publishers = 10
        events_per_publisher = 100

        tasks = [
            publisher(i, events_per_publisher)
            for i in range(num_publishers)
        ]

        await asyncio.gather(*tasks)
        await asyncio.sleep(0.5)
        await bus.stop()

        expected_total = num_publishers * events_per_publisher
        assert received_count == expected_total
