"""Tests for EventBus pub/sub event system.

Validates subscription management, event publishing, filtering,
concurrency handling, history operations, and convenience publishers.
"""

import asyncio
from datetime import datetime

import pytest

from framework.runtime.event_bus import (
    AgentEvent,
    EventBus,
    EventType,
)


# ---------------------------------------------------------------------------
# AgentEvent dataclass tests
# ---------------------------------------------------------------------------
class TestAgentEvent:
    """Tests for AgentEvent dataclass."""

    def test_minimal_construction(self):
        """Event can be created with just type and stream_id."""
        event = AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test_stream")
        assert event.type == EventType.EXECUTION_STARTED
        assert event.stream_id == "test_stream"
        assert event.node_id is None
        assert event.execution_id is None
        assert event.data == {}
        assert event.correlation_id is None

    def test_full_construction(self):
        """Event stores all provided fields."""
        event = AgentEvent(
            type=EventType.TOOL_CALL_COMPLETED,
            stream_id="stream_1",
            node_id="node_1",
            execution_id="exec_123",
            data={"result": "success"},
            correlation_id="corr_456",
        )
        assert event.type == EventType.TOOL_CALL_COMPLETED
        assert event.stream_id == "stream_1"
        assert event.node_id == "node_1"
        assert event.execution_id == "exec_123"
        assert event.data == {"result": "success"}
        assert event.correlation_id == "corr_456"

    def test_timestamp_auto_generated(self):
        """Timestamp is auto-generated if not provided."""
        before = datetime.now()
        event = AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test")
        after = datetime.now()
        assert before <= event.timestamp <= after

    def test_to_dict_serialization(self):
        """Event can be serialized to dictionary."""
        event = AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="stream_1",
            node_id="node_1",
            execution_id="exec_1",
            data={"output": "result"},
            correlation_id="corr_1",
            graph_id="graph_1",
        )
        d = event.to_dict()
        assert d["type"] == "execution_completed"
        assert d["stream_id"] == "stream_1"
        assert d["node_id"] == "node_1"
        assert d["execution_id"] == "exec_1"
        assert d["data"] == {"output": "result"}
        assert d["correlation_id"] == "corr_1"
        assert d["graph_id"] == "graph_1"
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# Subscription management tests
# ---------------------------------------------------------------------------
class TestSubscriptionManagement:
    """Tests for subscribe/unsubscribe operations."""

    def test_subscribe_returns_id(self):
        """subscribe() returns a subscription ID."""
        bus = EventBus()

        async def handler(event: AgentEvent) -> None:
            pass

        sub_id = bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)
        assert sub_id.startswith("sub_")

    def test_subscribe_increments_id(self):
        """Each subscription gets a unique incremented ID."""
        bus = EventBus()

        async def handler(event: AgentEvent) -> None:
            pass

        id1 = bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)
        id2 = bus.subscribe(event_types=[EventType.EXECUTION_COMPLETED], handler=handler)
        id3 = bus.subscribe(event_types=[EventType.EXECUTION_FAILED], handler=handler)

        assert id1 == "sub_1"
        assert id2 == "sub_2"
        assert id3 == "sub_3"

    def test_unsubscribe_removes_subscription(self):
        """unsubscribe() removes the subscription."""
        bus = EventBus()

        async def handler(event: AgentEvent) -> None:
            pass

        sub_id = bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)
        assert sub_id in bus._subscriptions

        result = bus.unsubscribe(sub_id)
        assert result is True
        assert sub_id not in bus._subscriptions

    def test_unsubscribe_nonexistent_returns_false(self):
        """unsubscribe() returns False for non-existent subscription."""
        bus = EventBus()
        result = bus.unsubscribe("sub_nonexistent")
        assert result is False

    def test_multiple_subscriptions_same_event_type(self):
        """Multiple handlers can subscribe to the same event type."""
        bus = EventBus()
        received = []

        async def handler1(event: AgentEvent) -> None:
            received.append("handler1")

        async def handler2(event: AgentEvent) -> None:
            received.append("handler2")

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler1)
        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler2)

        assert len(bus._subscriptions) == 2


# ---------------------------------------------------------------------------
# Event publishing tests
# ---------------------------------------------------------------------------
class TestEventPublishing:
    """Tests for publish() and event delivery."""

    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscriber(self):
        """Published events are delivered to matching subscribers."""
        bus = EventBus()
        received_events = []

        async def handler(event: AgentEvent) -> None:
            received_events.append(event)

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)

        event = AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test")
        await bus.publish(event)

        assert len(received_events) == 1
        assert received_events[0] == event

    @pytest.mark.asyncio
    async def test_publish_to_multiple_subscribers(self):
        """Event is delivered to all matching subscribers."""
        bus = EventBus()
        received = []

        async def handler1(event: AgentEvent) -> None:
            received.append("h1")

        async def handler2(event: AgentEvent) -> None:
            received.append("h2")

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler1)
        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler2)

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test"))

        assert "h1" in received
        assert "h2" in received

    @pytest.mark.asyncio
    async def test_publish_non_matching_type_not_delivered(self):
        """Events with non-matching types are not delivered."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)

        await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="test"))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_publish_adds_to_history(self):
        """Published events are added to history."""
        bus = EventBus()

        event = AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test")
        await bus.publish(event)

        history = bus.get_history()
        assert len(history) == 1
        assert history[0] == event


# ---------------------------------------------------------------------------
# Filter tests
# ---------------------------------------------------------------------------
class TestEventFiltering:
    """Tests for subscription filters."""

    @pytest.mark.asyncio
    async def test_filter_by_stream(self):
        """filter_stream only receives events from that stream."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event.stream_id)

        bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
            filter_stream="stream_a",
        )

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="stream_a"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="stream_b"))

        assert received == ["stream_a"]

    @pytest.mark.asyncio
    async def test_filter_by_node(self):
        """filter_node only receives events from that node."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event.node_id)

        bus.subscribe(
            event_types=[EventType.NODE_LOOP_STARTED],
            handler=handler,
            filter_node="node_x",
        )

        await bus.publish(
            AgentEvent(type=EventType.NODE_LOOP_STARTED, stream_id="s", node_id="node_x")
        )
        await bus.publish(
            AgentEvent(type=EventType.NODE_LOOP_STARTED, stream_id="s", node_id="node_y")
        )

        assert received == ["node_x"]

    @pytest.mark.asyncio
    async def test_filter_by_execution(self):
        """filter_execution only receives events from that execution."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event.execution_id)

        bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=handler,
            filter_execution="exec_1",
        )

        await bus.publish(
            AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s", execution_id="exec_1")
        )
        await bus.publish(
            AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s", execution_id="exec_2")
        )

        assert received == ["exec_1"]

    @pytest.mark.asyncio
    async def test_combined_filters(self):
        """Multiple filters are AND-ed together."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(True)

        bus.subscribe(
            event_types=[EventType.TOOL_CALL_COMPLETED],
            handler=handler,
            filter_stream="stream_1",
            filter_node="node_1",
        )

        # Matches both filters
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_COMPLETED,
                stream_id="stream_1",
                node_id="node_1",
            )
        )
        # Matches stream but not node
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_COMPLETED,
                stream_id="stream_1",
                node_id="node_2",
            )
        )
        # Matches node but not stream
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_COMPLETED,
                stream_id="stream_2",
                node_id="node_1",
            )
        )

        assert len(received) == 1

    @pytest.mark.asyncio
    async def test_filter_by_graph(self):
        """filter_graph only receives events from that graph."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event.graph_id)

        bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
            filter_graph="graph_a",
        )

        await bus.publish(
            AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s", graph_id="graph_a")
        )
        await bus.publish(
            AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s", graph_id="graph_b")
        )

        assert received == ["graph_a"]


# ---------------------------------------------------------------------------
# Concurrency tests
# ---------------------------------------------------------------------------
class TestConcurrency:
    """Tests for concurrent handler execution."""

    @pytest.mark.asyncio
    async def test_handler_error_doesnt_crash_others(self):
        """One handler's error doesn't prevent other handlers from running."""
        bus = EventBus()
        results = []

        async def failing_handler(event: AgentEvent) -> None:
            raise ValueError("Handler error!")

        async def working_handler(event: AgentEvent) -> None:
            results.append("success")

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=failing_handler)
        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=working_handler)

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test"))

        assert "success" in results

    @pytest.mark.asyncio
    async def test_max_concurrent_handlers_respected(self):
        """Semaphore limits concurrent handler executions."""
        bus = EventBus(max_concurrent_handlers=2)
        concurrent_count = 0
        max_concurrent = 0

        async def slow_handler(event: AgentEvent) -> None:
            nonlocal concurrent_count, max_concurrent
            concurrent_count += 1
            max_concurrent = max(max_concurrent, concurrent_count)
            await asyncio.sleep(0.1)
            concurrent_count -= 1

        # Subscribe 5 handlers
        for _ in range(5):
            bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=slow_handler)

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="test"))

        # Max concurrent should be limited to 2
        assert max_concurrent <= 2


# ---------------------------------------------------------------------------
# History and query tests
# ---------------------------------------------------------------------------
class TestHistoryAndQueries:
    """Tests for get_history() and get_stats()."""

    @pytest.mark.asyncio
    async def test_history_returns_events_most_recent_first(self):
        """get_history() returns events in reverse chronological order."""
        bus = EventBus()

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s1"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s2"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_FAILED, stream_id="s3"))

        history = bus.get_history()
        assert history[0].stream_id == "s3"  # Most recent
        assert history[1].stream_id == "s2"
        assert history[2].stream_id == "s1"  # Oldest

    @pytest.mark.asyncio
    async def test_history_filter_by_event_type(self):
        """get_history() can filter by event type."""
        bus = EventBus()

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s"))

        history = bus.get_history(event_type=EventType.EXECUTION_STARTED)
        assert len(history) == 2
        assert all(e.type == EventType.EXECUTION_STARTED for e in history)

    @pytest.mark.asyncio
    async def test_history_filter_by_stream_id(self):
        """get_history() can filter by stream_id."""
        bus = EventBus()

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="stream_a"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="stream_b"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="stream_a"))

        history = bus.get_history(stream_id="stream_a")
        assert len(history) == 2
        assert all(e.stream_id == "stream_a" for e in history)

    @pytest.mark.asyncio
    async def test_history_limit(self):
        """get_history() respects limit parameter."""
        bus = EventBus()

        for i in range(10):
            await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id=f"s{i}"))

        history = bus.get_history(limit=3)
        assert len(history) == 3

    @pytest.mark.asyncio
    async def test_max_history_enforced(self):
        """EventBus enforces max_history limit."""
        bus = EventBus(max_history=5)

        for i in range(10):
            await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id=f"s{i}"))

        assert len(bus._event_history) == 5
        # Should have the 5 most recent
        assert bus._event_history[-1].stream_id == "s9"
        assert bus._event_history[0].stream_id == "s5"

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """get_stats() returns accurate statistics."""
        bus = EventBus()

        async def handler(event: AgentEvent) -> None:
            pass

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)
        bus.subscribe(event_types=[EventType.EXECUTION_COMPLETED], handler=handler)

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s"))

        stats = bus.get_stats()
        assert stats["total_events"] == 3
        assert stats["subscriptions"] == 2
        assert stats["events_by_type"]["execution_started"] == 2
        assert stats["events_by_type"]["execution_completed"] == 1


# ---------------------------------------------------------------------------
# Wait operations tests
# ---------------------------------------------------------------------------
class TestWaitOperations:
    """Tests for wait_for() async waiting."""

    @pytest.mark.asyncio
    async def test_wait_for_receives_event(self):
        """wait_for() returns when matching event is published."""
        bus = EventBus()

        async def publish_later():
            await asyncio.sleep(0.05)
            await bus.publish(
                AgentEvent(
                    type=EventType.EXECUTION_COMPLETED,
                    stream_id="test",
                    execution_id="exec_1",
                )
            )

        asyncio.create_task(publish_later())

        event = await bus.wait_for(
            event_type=EventType.EXECUTION_COMPLETED,
            timeout=1.0,
        )

        assert event is not None
        assert event.type == EventType.EXECUTION_COMPLETED

    @pytest.mark.asyncio
    async def test_wait_for_timeout_returns_none(self):
        """wait_for() returns None on timeout."""
        bus = EventBus()

        event = await bus.wait_for(
            event_type=EventType.EXECUTION_COMPLETED,
            timeout=0.05,
        )

        assert event is None

    @pytest.mark.asyncio
    async def test_wait_for_with_filters(self):
        """wait_for() respects filters."""
        bus = EventBus()

        async def publish_events():
            await asyncio.sleep(0.02)
            # This one shouldn't match
            await bus.publish(
                AgentEvent(
                    type=EventType.EXECUTION_COMPLETED,
                    stream_id="wrong_stream",
                )
            )
            await asyncio.sleep(0.02)
            # This one should match
            await bus.publish(
                AgentEvent(
                    type=EventType.EXECUTION_COMPLETED,
                    stream_id="correct_stream",
                )
            )

        asyncio.create_task(publish_events())

        event = await bus.wait_for(
            event_type=EventType.EXECUTION_COMPLETED,
            stream_id="correct_stream",
            timeout=1.0,
        )

        assert event is not None
        assert event.stream_id == "correct_stream"

    @pytest.mark.asyncio
    async def test_wait_for_cleans_up_subscription(self):
        """wait_for() removes its subscription after completion."""
        bus = EventBus()

        initial_count = len(bus._subscriptions)

        async def publish_later():
            await asyncio.sleep(0.02)
            await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s"))

        asyncio.create_task(publish_later())

        await bus.wait_for(event_type=EventType.EXECUTION_COMPLETED, timeout=1.0)

        assert len(bus._subscriptions) == initial_count


# ---------------------------------------------------------------------------
# Convenience publisher tests
# ---------------------------------------------------------------------------
class TestConveniencePublishers:
    """Tests for emit_* convenience methods."""

    @pytest.mark.asyncio
    async def test_emit_execution_started(self):
        """emit_execution_started publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.EXECUTION_STARTED], handler=handler)

        await bus.emit_execution_started(
            stream_id="test_stream",
            execution_id="exec_1",
            input_data={"key": "value"},
            correlation_id="corr_1",
        )

        assert len(received) == 1
        assert received[0].type == EventType.EXECUTION_STARTED
        assert received[0].stream_id == "test_stream"
        assert received[0].execution_id == "exec_1"
        assert received[0].data == {"input": {"key": "value"}}
        assert received[0].correlation_id == "corr_1"

    @pytest.mark.asyncio
    async def test_emit_execution_completed(self):
        """emit_execution_completed publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.EXECUTION_COMPLETED], handler=handler)

        await bus.emit_execution_completed(
            stream_id="s",
            execution_id="e",
            output={"result": "success"},
        )

        assert len(received) == 1
        assert received[0].type == EventType.EXECUTION_COMPLETED
        assert received[0].data == {"output": {"result": "success"}}

    @pytest.mark.asyncio
    async def test_emit_execution_failed(self):
        """emit_execution_failed publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.EXECUTION_FAILED], handler=handler)

        await bus.emit_execution_failed(
            stream_id="s",
            execution_id="e",
            error="Something went wrong",
        )

        assert len(received) == 1
        assert received[0].type == EventType.EXECUTION_FAILED
        assert received[0].data == {"error": "Something went wrong"}

    @pytest.mark.asyncio
    async def test_emit_tool_call_started(self):
        """emit_tool_call_started publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.TOOL_CALL_STARTED], handler=handler)

        await bus.emit_tool_call_started(
            stream_id="s",
            node_id="n",
            tool_use_id="tool_1",
            tool_name="web_search",
            tool_input={"query": "test"},
        )

        assert len(received) == 1
        assert received[0].data["tool_name"] == "web_search"
        assert received[0].data["tool_input"] == {"query": "test"}

    @pytest.mark.asyncio
    async def test_emit_tool_call_completed(self):
        """emit_tool_call_completed publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.TOOL_CALL_COMPLETED], handler=handler)

        await bus.emit_tool_call_completed(
            stream_id="s",
            node_id="n",
            tool_use_id="tool_1",
            tool_name="web_search",
            result="search results",
            is_error=False,
        )

        assert len(received) == 1
        assert received[0].data["result"] == "search results"
        assert received[0].data["is_error"] is False

    @pytest.mark.asyncio
    async def test_emit_webhook_received(self):
        """emit_webhook_received publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.WEBHOOK_RECEIVED], handler=handler)

        await bus.emit_webhook_received(
            source_id="webhook_1",
            path="/api/webhook",
            method="POST",
            headers={"Content-Type": "application/json"},
            payload={"data": "test"},
            query_params={"token": "abc"},
        )

        assert len(received) == 1
        assert received[0].data["path"] == "/api/webhook"
        assert received[0].data["method"] == "POST"
        assert received[0].data["payload"] == {"data": "test"}

    @pytest.mark.asyncio
    async def test_emit_tool_doom_loop(self):
        """emit_tool_doom_loop publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.NODE_TOOL_DOOM_LOOP], handler=handler)

        await bus.emit_tool_doom_loop(
            stream_id="test_stream",
            node_id="node_1",
            description="Tool called same endpoint 5 times",
            execution_id="exec_1",
        )

        assert len(received) == 1
        assert received[0].type == EventType.NODE_TOOL_DOOM_LOOP
        assert received[0].stream_id == "test_stream"
        assert received[0].node_id == "node_1"
        assert received[0].data["description"] == "Tool called same endpoint 5 times"

    @pytest.mark.asyncio
    async def test_emit_escalation_requested(self):
        """emit_escalation_requested publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.ESCALATION_REQUESTED], handler=handler)

        await bus.emit_escalation_requested(
            stream_id="test_stream",
            node_id="node_1",
            reason="Need human intervention",
            context="Complex decision required",
            execution_id="exec_1",
        )

        assert len(received) == 1
        assert received[0].type == EventType.ESCALATION_REQUESTED
        assert received[0].stream_id == "test_stream"
        assert received[0].node_id == "node_1"
        assert received[0].data["reason"] == "Need human intervention"
        assert received[0].data["context"] == "Complex decision required"


# ---------------------------------------------------------------------------
# EventType enum tests
# ---------------------------------------------------------------------------
class TestEventType:
    """Tests for EventType enum."""

    def test_all_event_types_are_strings(self):
        """All EventType values are strings."""
        for event_type in EventType:
            assert isinstance(event_type.value, str)

    def test_event_types_are_unique(self):
        """All EventType values are unique."""
        values = [e.value for e in EventType]
        assert len(values) == len(set(values))

    def test_key_event_types_exist(self):
        """Key event types are defined."""
        assert EventType.EXECUTION_STARTED
        assert EventType.EXECUTION_COMPLETED
        assert EventType.EXECUTION_FAILED
        assert EventType.TOOL_CALL_STARTED
        assert EventType.TOOL_CALL_COMPLETED
        assert EventType.WEBHOOK_RECEIVED
        assert EventType.NODE_TOOL_DOOM_LOOP
        assert EventType.ESCALATION_REQUESTED
