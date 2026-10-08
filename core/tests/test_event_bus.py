"""Tests for EventBus pub/sub event system.

Validates subscription management, event publishing, filtering,
concurrency handling, history operations, and convenience publishers.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from framework.host.event_bus import (
    AgentEvent,
    EventBus,
    EventType,
    _event_to_disk_dict,
    collect_resolved_request_seqs,
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
            colony_id="colony_1",
        )
        d = event.to_dict()
        assert d["type"] == "execution_completed"
        assert d["stream_id"] == "stream_1"
        assert d["colony_id"] == "colony_1"

    def test_to_dict_includes_run_id(self):
        """run_id is included in to_dict() when set."""
        event = AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="s1",
            run_id="run-abc",
        )
        d = event.to_dict()
        assert d["run_id"] == "run-abc"

    def test_to_dict_omits_run_id_when_none(self):
        """run_id is omitted from to_dict() when None."""
        event = AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="s1",
        )
        d = event.to_dict()
        assert "run_id" not in d


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

        await bus.publish(AgentEvent(type=EventType.NODE_LOOP_STARTED, stream_id="s", node_id="node_x"))
        await bus.publish(AgentEvent(type=EventType.NODE_LOOP_STARTED, stream_id="s", node_id="node_y"))

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

        await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s", execution_id="exec_1"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_COMPLETED, stream_id="s", execution_id="exec_2"))

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
    async def test_filter_by_colony(self):
        """filter_colony only receives events from that colony."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event.colony_id)

        bus.subscribe(
            event_types=[EventType.EXECUTION_STARTED],
            handler=handler,
            filter_colony="colony_a",
        )

        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s", colony_id="colony_a"))
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="s", colony_id="colony_b"))

        assert received == ["colony_a"]


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

    @pytest.mark.asyncio
    async def test_emit_llm_turn_complete(self):
        """emit_llm_turn_complete publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.LLM_TURN_COMPLETE], handler=handler)

        await bus.emit_llm_turn_complete(
            stream_id="test_stream",
            node_id="node_1",
            stop_reason="end_turn",
            model="claude-sonnet-4-20250514",
            input_tokens=100,
            output_tokens=50,
            cached_tokens=30,
            cache_creation_tokens=10,
            cost_usd=0.0042,
            execution_id="exec_1",
            iteration=3,
        )

        assert len(received) == 1
        assert received[0].type == EventType.LLM_TURN_COMPLETE
        assert received[0].data["stop_reason"] == "end_turn"
        assert received[0].data["model"] == "claude-sonnet-4-20250514"
        assert received[0].data["input_tokens"] == 100
        assert received[0].data["output_tokens"] == 50
        # cached / cache_creation are subsets of input — propagated for
        # display, NOT additive to input_tokens.
        assert received[0].data["cached_tokens"] == 30
        assert received[0].data["cache_creation_tokens"] == 10
        assert received[0].data["cost_usd"] == 0.0042
        assert received[0].data["iteration"] == 3

    @pytest.mark.asyncio
    async def test_emit_subagent_report(self):
        """emit_subagent_report publishes correct event."""
        bus = EventBus()
        received = []

        async def handler(event: AgentEvent) -> None:
            received.append(event)

        bus.subscribe(event_types=[EventType.SUBAGENT_REPORT], handler=handler)

        await bus.emit_subagent_report(
            stream_id="test_stream",
            node_id="queen",
            subagent_id="worker-1",
            message="Task 50% complete",
            data={"progress": 0.5},
        )

        assert len(received) == 1
        assert received[0].type == EventType.SUBAGENT_REPORT
        assert received[0].data["subagent_id"] == "worker-1"
        assert received[0].data["message"] == "Task 50% complete"
        assert received[0].data["data"]["progress"] == 0.5


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
        assert EventType.EXECUTION_PAUSED
        assert EventType.EXECUTION_RESUMED
        assert EventType.TOOL_CALL_STARTED
        assert EventType.TOOL_CALL_COMPLETED
        assert EventType.WEBHOOK_RECEIVED
        assert EventType.NODE_TOOL_DOOM_LOOP
        assert EventType.ESCALATION_REQUESTED
        assert EventType.LLM_TURN_COMPLETE
        assert EventType.WORKER_COLONY_LOADED
        assert EventType.CREDENTIALS_REQUIRED
        assert EventType.EXECUTION_RESURRECTED
        assert EventType.QUEEN_PHASE_CHANGED
        assert EventType.SUBAGENT_REPORT
        assert EventType.TRIGGER_AVAILABLE
        assert EventType.TRIGGER_FIRED


class TestEventToDiskDict:
    """`_event_to_disk_dict` — what actually gets persisted to events.jsonl."""

    def test_strips_full_request_from_persisted_event(self) -> None:
        """`full_request` is the entire LLM prompt re-serialised on every
        context tick — it must never reach events.jsonl."""
        event = AgentEvent(
            type=EventType.CONTEXT_USAGE_UPDATED,
            stream_id="queen",
            node_id="queen",
            data={
                "usage_pct": 73,
                "estimated_tokens": 1234,
                "full_request": {"messages": ["the", "whole", "context"]},
            },
        )
        disk = _event_to_disk_dict(event)
        assert "full_request" not in disk["data"]
        # The real metrics survive.
        assert disk["data"]["usage_pct"] == 73
        assert disk["data"]["estimated_tokens"] == 1234

    def test_does_not_mutate_the_live_event(self) -> None:
        """The live SSE broadcast still carries the full event — only the
        on-disk copy is trimmed."""
        event = AgentEvent(
            type=EventType.CONTEXT_USAGE_UPDATED,
            stream_id="queen",
            node_id="queen",
            data={"usage_pct": 10, "full_request": {"big": "payload"}},
        )
        _event_to_disk_dict(event)
        assert event.data["full_request"] == {"big": "payload"}

    def test_ordinary_event_passes_through_unchanged(self) -> None:
        event = AgentEvent(
            type=EventType.CLIENT_INPUT_RECEIVED,
            stream_id="queen",
            node_id="queen",
            data={"content": "hello"},
        )
        disk = _event_to_disk_dict(event)
        assert disk["data"] == {"content": "hello"}


# ---------------------------------------------------------------------------
# collect_resolved_request_seqs
# ---------------------------------------------------------------------------
class TestCollectResolvedRequestSeqs:
    """`collect_resolved_request_seqs` — which CLIENT_INPUT_REQUESTED events
    the SSE replay must suppress because they've already been answered.

    Getting this wrong has a concrete user-visible cost: an un-suppressed
    request is replayed on reconnect and re-pops a question modal the user
    already dismissed. So these tests pin *resolution*, not mechanics.
    """

    async def _publish(self, bus: EventBus, event_type: EventType) -> None:
        await bus.publish(AgentEvent(type=event_type, stream_id="queen", node_id="queen"))

    @pytest.mark.asyncio
    async def test_answered_request_is_resolved(self) -> None:
        """A request followed by an answer is suppressed from replay."""
        bus = EventBus()
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)
        await self._publish(bus, EventType.CLIENT_INPUT_RECEIVED)
        assert collect_resolved_request_seqs(bus) == {1}

    @pytest.mark.asyncio
    async def test_unanswered_request_is_not_resolved(self) -> None:
        """A still-open question must keep replaying so the user can answer."""
        bus = EventBus()
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)
        assert collect_resolved_request_seqs(bus) == set()

    @pytest.mark.asyncio
    async def test_one_answer_resolves_every_duplicate_request(self) -> None:
        """The regression guard: re-emits of the SAME question (one per
        resume, one per spurious re-wait) all land before a single answer.
        Resolving only the latest would orphan the earlier duplicates, and
        the SSE replay would re-pop the question the user already answered.
        """
        bus = EventBus()
        # The same question, re-emitted three times before any answer.
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)  # seq 1
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)  # seq 2
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)  # seq 3
        await self._publish(bus, EventType.CLIENT_INPUT_RECEIVED)  # seq 4
        # Every duplicate is resolved — none survives to be replayed.
        assert collect_resolved_request_seqs(bus) == {1, 2, 3}

    @pytest.mark.asyncio
    async def test_a_later_unanswered_question_stays_open(self) -> None:
        """An answer resolves only the questions that preceded it — a fresh
        question asked afterwards is still pending."""
        bus = EventBus()
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)  # seq 1
        await self._publish(bus, EventType.CLIENT_INPUT_RECEIVED)  # seq 2
        await self._publish(bus, EventType.CLIENT_INPUT_REQUESTED)  # seq 3 — new
        assert collect_resolved_request_seqs(bus) == {1}


# compute_session_snapshot — park_reason (read from the loop-state cell)
# ---------------------------------------------------------------------------
class TestSessionSnapshotParkReason:
    """``park_reason`` comes from the loop's LOOP_STATE_CHANGED
    announcement (cached in ``_latest_loop_state``), NOT from
    CLIENT_INPUT_REQUESTED. The debug panel can tell a healthy park from
    a broken one because the loop labels it at the source."""

    @pytest.mark.asyncio
    async def test_park_reason_captured_from_loop_state(self) -> None:
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "interrupted", "park_reason": "llm_error"},
            )
        )
        snap = compute_session_snapshot(bus)
        assert snap["interrupted"] is True
        assert snap["park_reason"] == "llm_error"

    @pytest.mark.asyncio
    async def test_park_reason_cleared_when_loop_resumes(self) -> None:
        """A new LOOP_STATE_CHANGED to EXECUTING overwrites the cell —
        park_reason from the previous parked announcement is gone."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "awaiting_user", "park_reason": "ask_user"},
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "executing"},
            )
        )
        snap = compute_session_snapshot(bus)
        assert snap["is_executing"] is True
        assert snap["awaiting_input"] is False
        assert snap["park_reason"] is None

    @pytest.mark.asyncio
    async def test_client_input_requested_does_not_set_park_reason(self) -> None:
        """Discipline check: CLIENT_INPUT_REQUESTED carries park_reason on
        the wire for the renderer's question modal, but the snapshot is
        the loop's verdict only. Without a LOOP_STATE_CHANGED, the
        snapshot reports no activity and no park_reason — even when a
        CLIENT_INPUT_REQUESTED has a park_reason field."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(
            AgentEvent(
                type=EventType.CLIENT_INPUT_REQUESTED,
                stream_id="queen",
                data={"park_reason": "llm_error"},
            )
        )
        snap = compute_session_snapshot(bus)
        assert snap["activity"] is None
        assert snap["awaiting_input"] is False
        assert snap["interrupted"] is False
        assert snap["park_reason"] is None

    @pytest.mark.asyncio
    async def test_park_reason_absent_when_no_state_announced(self) -> None:
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="queen"))
        snap = compute_session_snapshot(bus)
        assert snap["activity"] is None
        assert snap["awaiting_input"] is False
        assert snap["park_reason"] is None


# ---------------------------------------------------------------------------
# compute_session_snapshot — authoritative 3-state activity model
# ---------------------------------------------------------------------------
class TestSessionSnapshotActivity:
    """The snapshot derives is_executing / awaiting_input / interrupted from
    the latest LOOP_STATE_CHANGED event. The three are structurally mutually
    exclusive — exactly one is ever true."""

    @staticmethod
    def _state_event(
        activity: str,
        *,
        stream_id: str = "queen",
        park_reason: str | None = None,
        interrupt_cause: str | None = None,
    ) -> AgentEvent:
        return AgentEvent(
            type=EventType.LOOP_STATE_CHANGED,
            stream_id=stream_id,
            data={
                "activity": activity,
                "park_reason": park_reason,
                "interrupt_cause": interrupt_cause,
            },
        )

    @staticmethod
    def _assert_exactly_one(snap: dict) -> None:
        flags = [snap["is_executing"], snap["awaiting_input"], snap["interrupted"]]
        assert sum(1 for f in flags if f) == 1, flags

    @pytest.mark.asyncio
    async def test_executing(self) -> None:
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("executing"))
        snap = compute_session_snapshot(bus)
        assert snap["activity"] == "executing"
        assert snap["is_executing"] is True
        self._assert_exactly_one(snap)

    @pytest.mark.asyncio
    async def test_awaiting_user(self) -> None:
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("awaiting_user", park_reason="turn_done"))
        snap = compute_session_snapshot(bus)
        assert snap["awaiting_input"] is True
        assert snap["park_reason"] == "turn_done"
        self._assert_exactly_one(snap)

    @pytest.mark.asyncio
    async def test_interrupted(self) -> None:
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("interrupted", interrupt_cause="stream_stall"))
        snap = compute_session_snapshot(bus)
        assert snap["interrupted"] is True
        assert snap["interrupt_cause"] == "stream_stall"
        assert snap["queen_busy_reason"] == "interrupted"
        self._assert_exactly_one(snap)

    @pytest.mark.asyncio
    async def test_llm_error_park_is_not_awaiting_input(self) -> None:
        """Regression for the named bug: a broken (LLM error) park reports
        interrupted, NOT awaiting_input."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("interrupted", park_reason="llm_error"))
        snap = compute_session_snapshot(bus)
        assert snap["awaiting_input"] is False
        assert snap["interrupted"] is True
        assert snap["park_reason"] == "llm_error"

    @pytest.mark.asyncio
    async def test_latest_state_event_wins(self) -> None:
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("interrupted", interrupt_cause="llm_error"))
        await bus.publish(self._state_event("executing"))
        snap = compute_session_snapshot(bus)
        assert snap["activity"] == "executing"
        assert snap["interrupted"] is False

    @pytest.mark.asyncio
    async def test_worker_state_event_ignored(self) -> None:
        """A worker-stream LOOP_STATE_CHANGED never moves the queen snapshot."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("executing"))
        await bus.publish(self._state_event("interrupted", stream_id="worker-1", interrupt_cause="crashed"))
        snap = compute_session_snapshot(bus)
        assert snap["activity"] == "executing"
        assert snap["interrupted"] is False

    @pytest.mark.asyncio
    async def test_stale_executing_becomes_interrupted(self) -> None:
        """A loop that announced EXECUTING but emitted nothing for the
        staleness window is reclassified INTERRUPTED/stale — a hard crash
        cannot self-announce."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("executing"))
        bus._event_history[-1].timestamp = datetime.now() - timedelta(seconds=400)
        snap = compute_session_snapshot(bus)
        assert snap["interrupted"] is True
        assert snap["interrupt_cause"] == "stale"
        assert snap["is_executing"] is False

    @pytest.mark.asyncio
    async def test_stale_awaiting_user_left_alone(self) -> None:
        """A stale AWAITING_USER is NOT reclassified — the user simply
        hasn't replied yet."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(self._state_event("awaiting_user", park_reason="turn_done"))
        bus._event_history[-1].timestamp = datetime.now() - timedelta(seconds=400)
        snap = compute_session_snapshot(bus)
        assert snap["awaiting_input"] is True
        assert snap["interrupted"] is False

    @pytest.mark.asyncio
    async def test_no_state_announced_reports_no_activity(self) -> None:
        """Discipline: if the loop has never emitted LOOP_STATE_CHANGED,
        the snapshot reports ``activity=None`` and all flags False — it
        does NOT guess from EXECUTION_STARTED or other side-effect
        events. Re-derivation was the previous bug; the cell is now the
        single source of truth."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="queen"))
        await bus.publish(AgentEvent(type=EventType.TOOL_CALL_STARTED, stream_id="queen", data={"tool_use_id": "t1", "tool_name": "ls"}))
        snap = compute_session_snapshot(bus)
        assert snap["activity"] is None
        assert snap["is_executing"] is False
        assert snap["awaiting_input"] is False
        assert snap["interrupted"] is False
        # Side-effect data is still walked, so the tool is visible.
        assert snap["current_tool_calls"] == []  # cleared because not is_executing


# ---------------------------------------------------------------------------
# EventBus._latest_loop_state — the sticky LoopActivity cell
# ---------------------------------------------------------------------------
class TestLatestLoopStateCell:
    """The cell is the single bridge between the loop's announcement and
    the snapshot. Its job: survive ring-buffer eviction, ignore worker
    streams, mirror exactly what was published."""

    @pytest.mark.asyncio
    async def test_cell_starts_none(self) -> None:
        bus = EventBus()
        assert bus._latest_loop_state is None

    @pytest.mark.asyncio
    async def test_cell_written_on_loop_state_changed(self) -> None:
        bus = EventBus()
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                node_id="queen",
                data={
                    "activity": "interrupted",
                    "park_reason": "user_stopped",
                    "interrupt_cause": None,
                },
            )
        )
        cell = bus._latest_loop_state
        assert cell is not None
        assert cell["activity"] == "interrupted"
        assert cell["park_reason"] == "user_stopped"
        assert cell["interrupt_cause"] is None
        assert cell["stream_id"] == "queen"

    @pytest.mark.asyncio
    async def test_cell_overwritten_by_later_announcement(self) -> None:
        """Each LOOP_STATE_CHANGED replaces the cell wholesale — partial
        merges would let stale park_reason / interrupt_cause leak past a
        transition."""
        bus = EventBus()
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "interrupted", "park_reason": "user_stopped"},
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "executing"},
            )
        )
        cell = bus._latest_loop_state
        assert cell["activity"] == "executing"
        assert cell["park_reason"] is None
        assert cell["interrupt_cause"] is None

    @pytest.mark.asyncio
    async def test_cell_ignores_worker_stream(self) -> None:
        """Workers run their own LoopActivity but it must not overwrite
        the queen's state in the snapshot's authoritative cell."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "executing"},
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="worker-1",
                data={"activity": "interrupted", "interrupt_cause": "crashed"},
            )
        )
        cell = bus._latest_loop_state
        assert cell["activity"] == "executing"  # worker did NOT overwrite
        snap = compute_session_snapshot(bus)
        assert snap["activity"] == "executing"
        assert snap["interrupted"] is False

    @pytest.mark.asyncio
    async def test_cell_survives_ring_buffer_eviction(self) -> None:
        """The whole reason the cell exists: when the LOOP_STATE_CHANGED
        event ages out of the bounded event history, the snapshot still
        reflects the loop's last announcement. Without the cell, an
        aged-out announcement would force the snapshot into a "no
        activity" verdict and the renderer's debug panel would go dark
        mid-session."""
        from framework.host.event_bus import compute_session_snapshot

        # Small buffer so we can blow past it cheaply.
        bus = EventBus(max_history=4)
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "awaiting_user", "park_reason": "turn_done"},
            )
        )
        # Now flood the buffer past max_history.
        for i in range(10):
            await bus.publish(
                AgentEvent(
                    type=EventType.TOOL_CALL_STARTED,
                    stream_id="queen",
                    data={"tool_use_id": f"t{i}", "tool_name": "noop"},
                )
            )

        # The LOOP_STATE_CHANGED event is no longer in history…
        types_in_history = [e.type for e in bus._event_history]
        assert EventType.LOOP_STATE_CHANGED not in types_in_history

        # …but the cell preserves the loop's verdict.
        snap = compute_session_snapshot(bus)
        assert snap["activity"] == "awaiting_user"
        assert snap["awaiting_input"] is True
        assert snap["park_reason"] == "turn_done"

    @pytest.mark.asyncio
    async def test_snapshot_does_not_re_derive_from_events(self) -> None:
        """Discipline regression: even with a parade of EXECUTION_STARTED
        / TOOL_CALL_STARTED events, the snapshot reports whatever the
        cell says — including ``interrupted=True`` while side-effect
        events suggest activity. The cell wins; the events do not."""
        from framework.host.event_bus import compute_session_snapshot

        bus = EventBus()
        await bus.publish(AgentEvent(type=EventType.EXECUTION_STARTED, stream_id="queen"))
        await bus.publish(AgentEvent(type=EventType.TOOL_CALL_STARTED, stream_id="queen", data={"tool_use_id": "t1", "tool_name": "ls"}))
        await bus.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id="queen",
                data={"activity": "interrupted", "park_reason": "user_stopped"},
            )
        )
        # More events that USED TO flip is_executing in the legacy walk.
        await bus.publish(AgentEvent(type=EventType.TOOL_CALL_COMPLETED, stream_id="queen", data={"tool_use_id": "t1"}))
        await bus.publish(AgentEvent(type=EventType.NODE_LOOP_ITERATION, stream_id="queen"))

        snap = compute_session_snapshot(bus)
        # The cell still says interrupted; the trailing side-effect events
        # do NOT re-derive is_executing.
        assert snap["activity"] == "interrupted"
        assert snap["is_executing"] is False
        assert snap["interrupted"] is True
        assert snap["park_reason"] == "user_stopped"
