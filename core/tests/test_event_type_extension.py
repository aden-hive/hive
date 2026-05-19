"""Tests for extending the stream event type system.

Validates that the StreamEvent discriminated union pattern supports:
- Type-based dispatch (matching on event.type)
- Pattern matching / isinstance branching
- Custom event subclasses following the same frozen-dataclass convention
- Serialization of mixed event sequences

WP-2 tests validate EventType enum extension and node-level event routing:
- All 12 new EventType enum members with correct string values
- node_id routing on AgentEvent
- filter_node on Subscription
- Backward compatibility with existing enum members
"""

import asyncio
from dataclasses import FrozenInstanceError, asdict, dataclass, field
from typing import Any, Literal

import pytest

from framework.llm.stream_events import (
    FinishEvent,
    ReasoningDeltaEvent,
    ReasoningStartEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from framework.runtime.event_bus import AgentEvent, EventBus, EventType, Subscription


# ---------------------------------------------------------------------------
# Helpers: type-based dispatch
# ---------------------------------------------------------------------------
def dispatch_event(event) -> str:
    """Dispatch an event by its type field, returning a label."""
    handlers = {
        "text_delta": lambda e: f"text:{e.content}",
        "text_end": lambda e: f"end:{len(e.full_text)}chars",
        "tool_call": lambda e: f"call:{e.tool_name}",
        "tool_result": lambda e: f"result:{e.tool_use_id}",
        "reasoning_start": lambda _: "reasoning:start",
        "reasoning_delta": lambda e: f"reasoning:{e.content[:20]}",
        "finish": lambda e: f"finish:{e.stop_reason}",
        "error": lambda e: f"error:{e.error}",
    }
    handler = handlers.get(event.type)
    if handler is None:
        return f"unknown:{event.type}"
    return handler(event)


def collect_text(events: list) -> str:
    """Accumulate full text from a stream of events."""
    for event in reversed(events):
        if isinstance(event, TextEndEvent):
            return event.full_text
        if isinstance(event, TextDeltaEvent):
            return event.snapshot
    return ""


def extract_tool_calls(events: list) -> list[dict[str, Any]]:
    """Extract tool call info from a stream of events."""
    return [
        {"id": e.tool_use_id, "name": e.tool_name, "input": e.tool_input}
        for e in events
        if isinstance(e, ToolCallEvent)
    ]


# ---------------------------------------------------------------------------
# Type-based dispatch tests
# ---------------------------------------------------------------------------
class TestTypeDispatch:
    """Dispatch on event.type string for handler routing."""

    def test_dispatch_text_delta(self):
        e = TextDeltaEvent(content="hello")
        assert dispatch_event(e) == "text:hello"

    def test_dispatch_text_end(self):
        e = TextEndEvent(full_text="hello world")
        assert dispatch_event(e) == "end:11chars"

    def test_dispatch_tool_call(self):
        e = ToolCallEvent(tool_name="web_search")
        assert dispatch_event(e) == "call:web_search"

    def test_dispatch_tool_result(self):
        e = ToolResultEvent(tool_use_id="abc")
        assert dispatch_event(e) == "result:abc"

    def test_dispatch_reasoning_start(self):
        e = ReasoningStartEvent()
        assert dispatch_event(e) == "reasoning:start"

    def test_dispatch_reasoning_delta(self):
        e = ReasoningDeltaEvent(content="Let me think step by step")
        assert dispatch_event(e) == "reasoning:Let me think step by"

    def test_dispatch_finish(self):
        e = FinishEvent(stop_reason="end_turn")
        assert dispatch_event(e) == "finish:end_turn"

    def test_dispatch_error(self):
        e = StreamErrorEvent(error="timeout")
        assert dispatch_event(e) == "error:timeout"


# ---------------------------------------------------------------------------
# isinstance-based filtering
# ---------------------------------------------------------------------------
class TestInstanceFiltering:
    """Filter event streams using isinstance for each event type."""

    @pytest.fixture
    def text_stream(self) -> list:
        """Simulate a text-only stream."""
        return [
            TextDeltaEvent(content="Hello", snapshot="Hello"),
            TextDeltaEvent(content=" world", snapshot="Hello world"),
            TextDeltaEvent(content="!", snapshot="Hello world!"),
            TextEndEvent(full_text="Hello world!"),
            FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=3, model="test"),
        ]

    @pytest.fixture
    def tool_stream(self) -> list:
        """Simulate a tool call stream."""
        return [
            ToolCallEvent(
                tool_use_id="call_1",
                tool_name="get_weather",
                tool_input={"city": "London"},
            ),
            ToolCallEvent(
                tool_use_id="call_2",
                tool_name="calculator",
                tool_input={"expression": "2+2"},
            ),
            FinishEvent(stop_reason="tool_calls"),
        ]

    @pytest.fixture
    def reasoning_stream(self) -> list:
        """Simulate a stream with reasoning blocks."""
        return [
            ReasoningStartEvent(),
            ReasoningDeltaEvent(content="Let me analyze this..."),
            ReasoningDeltaEvent(content="The answer is 42."),
            TextDeltaEvent(content="The answer is 42.", snapshot="The answer is 42."),
            TextEndEvent(full_text="The answer is 42."),
            FinishEvent(stop_reason="end_turn"),
        ]

    def test_collect_text(self, text_stream):
        assert collect_text(text_stream) == "Hello world!"

    def test_collect_text_from_tool_stream(self, tool_stream):
        assert collect_text(tool_stream) == ""

    def test_extract_tool_calls(self, tool_stream):
        calls = extract_tool_calls(tool_stream)
        assert len(calls) == 2
        assert calls[0]["name"] == "get_weather"
        assert calls[1]["name"] == "calculator"

    def test_extract_tool_calls_from_text_stream(self, text_stream):
        assert extract_tool_calls(text_stream) == []

    def test_filter_text_deltas(self, text_stream):
        deltas = [e for e in text_stream if isinstance(e, TextDeltaEvent)]
        assert len(deltas) == 3

    def test_filter_finish(self, text_stream):
        finishes = [e for e in text_stream if isinstance(e, FinishEvent)]
        assert len(finishes) == 1
        assert finishes[0].stop_reason == "stop"

    def test_reasoning_then_text(self, reasoning_stream):
        reasoning = [e for e in reasoning_stream if isinstance(e, ReasoningDeltaEvent)]
        text = collect_text(reasoning_stream)
        assert len(reasoning) == 2
        assert text == "The answer is 42."

    def test_mixed_stream_type_counts(self, reasoning_stream):
        type_counts = {}
        for e in reasoning_stream:
            type_counts[e.type] = type_counts.get(e.type, 0) + 1
        assert type_counts == {
            "reasoning_start": 1,
            "reasoning_delta": 2,
            "text_delta": 1,
            "text_end": 1,
            "finish": 1,
        }


# ---------------------------------------------------------------------------
# Custom event extension pattern
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CustomMetricsEvent:
    """Example custom event following the same pattern."""

    type: Literal["custom_metrics"] = "custom_metrics"
    latency_ms: float = 0.0
    tokens_per_second: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomCitationEvent:
    """Example citation event extending the pattern."""

    type: Literal["citation"] = "citation"
    source_url: str = ""
    quote: str = ""
    confidence: float = 0.0


class TestCustomEventExtension:
    """Custom events should follow the same frozen-dataclass convention."""

    def test_custom_event_construction(self):
        e = CustomMetricsEvent(latency_ms=150.5, tokens_per_second=42.3)
        assert e.type == "custom_metrics"
        assert e.latency_ms == 150.5

    def test_custom_event_frozen(self):
        e = CustomMetricsEvent()
        with pytest.raises(FrozenInstanceError):
            e.type = "modified"

    def test_custom_event_serialization(self):
        e = CustomMetricsEvent(
            latency_ms=100.0,
            tokens_per_second=50.0,
            metadata={"provider": "anthropic"},
        )
        d = asdict(e)
        assert d["type"] == "custom_metrics"
        assert d["metadata"] == {"provider": "anthropic"}

    def test_custom_event_dispatch(self):
        """Custom events can extend the dispatch map."""
        e = CustomMetricsEvent(latency_ms=200.0)
        # Falls through to "unknown" in our dispatch_event
        assert dispatch_event(e) == "unknown:custom_metrics"

    def test_custom_event_in_mixed_stream(self):
        """Custom events can coexist with standard events in a list."""
        stream = [
            TextDeltaEvent(content="hi", snapshot="hi"),
            CustomMetricsEvent(latency_ms=50.0),
            TextEndEvent(full_text="hi"),
            CustomCitationEvent(source_url="https://example.com", quote="hi"),
            FinishEvent(stop_reason="stop"),
        ]
        standard = [
            e
            for e in stream
            if hasattr(e, "type")
            and e.type
            in {
                "text_delta",
                "text_end",
                "tool_call",
                "tool_result",
                "reasoning_start",
                "reasoning_delta",
                "finish",
                "error",
            }
        ]
        custom = [
            e
            for e in stream
            if e.type
            not in {
                "text_delta",
                "text_end",
                "tool_call",
                "tool_result",
                "reasoning_start",
                "reasoning_delta",
                "finish",
                "error",
            }
        ]
        assert len(standard) == 3
        assert len(custom) == 2


# ---------------------------------------------------------------------------
# Serialization of full event sequences
# ---------------------------------------------------------------------------
class TestSequenceSerialization:
    """Serialize entire event sequences, as done by the dump tests."""

    def test_serialize_text_sequence(self):
        events = [
            TextDeltaEvent(content="Hello", snapshot="Hello"),
            TextDeltaEvent(content=" world", snapshot="Hello world"),
            TextEndEvent(full_text="Hello world"),
            FinishEvent(stop_reason="stop", model="test-model"),
        ]
        serialized = [{"index": i, **asdict(e)} for i, e in enumerate(events)]
        assert len(serialized) == 4
        assert serialized[0]["index"] == 0
        assert serialized[0]["type"] == "text_delta"
        assert serialized[-1]["type"] == "finish"
        assert serialized[-1]["model"] == "test-model"

    def test_serialize_tool_sequence(self):
        events = [
            ToolCallEvent(
                tool_use_id="call_1",
                tool_name="search",
                tool_input={"query": "test"},
            ),
            FinishEvent(stop_reason="tool_calls"),
        ]
        serialized = [{"index": i, **asdict(e)} for i, e in enumerate(events)]
        assert serialized[0]["tool_input"] == {"query": "test"}
        assert serialized[1]["stop_reason"] == "tool_calls"

    def test_serialize_error_sequence(self):
        events = [
            TextDeltaEvent(content="partial"),
            StreamErrorEvent(error="connection reset", recoverable=True),
            FinishEvent(stop_reason="error"),
        ]
        serialized = [{"index": i, **asdict(e)} for i, e in enumerate(events)]
        assert serialized[1]["type"] == "error"
        assert serialized[1]["recoverable"] is True

    def test_roundtrip_snapshot_accumulation(self):
        """Verify snapshot grows monotonically through serialization."""
        chunks = ["Hello", " beautiful", " world", "!"]
        events = []
        snapshot = ""
        for chunk in chunks:
            snapshot += chunk
            events.append(TextDeltaEvent(content=chunk, snapshot=snapshot))

        serialized = [asdict(e) for e in events]
        for i in range(1, len(serialized)):
            assert len(serialized[i]["snapshot"]) > len(serialized[i - 1]["snapshot"])
        assert serialized[-1]["snapshot"] == "Hello beautiful world!"


# ===========================================================================
# WP-2: EventType Enum Extension + Node-Level Event Routing
# ===========================================================================

# The 12 new EventType members added by WP-2
WP2_EVENT_TYPES = {
    # Node event-loop lifecycle
    EventType.NODE_LOOP_STARTED: "node_loop_started",
    EventType.NODE_LOOP_ITERATION: "node_loop_iteration",
    EventType.NODE_LOOP_COMPLETED: "node_loop_completed",
    # LLM streaming observability
    EventType.LLM_TEXT_DELTA: "llm_text_delta",
    EventType.LLM_REASONING_DELTA: "llm_reasoning_delta",
    # Tool lifecycle
    EventType.TOOL_CALL_STARTED: "tool_call_started",
    EventType.TOOL_CALL_COMPLETED: "tool_call_completed",
    # Client I/O
    EventType.CLIENT_OUTPUT_DELTA: "client_output_delta",
    EventType.CLIENT_INPUT_REQUESTED: "client_input_requested",
    # Internal node observability
    EventType.NODE_INTERNAL_OUTPUT: "node_internal_output",
    EventType.NODE_INPUT_BLOCKED: "node_input_blocked",
    EventType.NODE_STALLED: "node_stalled",
}

# Pre-existing enum members that must remain unchanged
ORIGINAL_EVENT_TYPES = {
    EventType.EXECUTION_STARTED: "execution_started",
    EventType.EXECUTION_COMPLETED: "execution_completed",
    EventType.EXECUTION_FAILED: "execution_failed",
    EventType.EXECUTION_PAUSED: "execution_paused",
    EventType.EXECUTION_RESUMED: "execution_resumed",
    EventType.STATE_CHANGED: "state_changed",
    EventType.STATE_CONFLICT: "state_conflict",
    EventType.GOAL_PROGRESS: "goal_progress",
    EventType.GOAL_ACHIEVED: "goal_achieved",
    EventType.CONSTRAINT_VIOLATION: "constraint_violation",
    EventType.STREAM_STARTED: "stream_started",
    EventType.STREAM_STOPPED: "stream_stopped",
    EventType.CUSTOM: "custom",
}


# ---------------------------------------------------------------------------
# WP-2 Part A: EventType enum members
# ---------------------------------------------------------------------------
class TestWP2EventTypeEnumMembers:
    """All 12 new EventType members exist with correct string values."""

    @pytest.mark.parametrize(
        "member,expected_value",
        WP2_EVENT_TYPES.items(),
        ids=lambda x: x.name if isinstance(x, EventType) else x,
    )
    def test_new_member_value(self, member, expected_value):
        assert member.value == expected_value

    def test_all_12_new_members_exist(self):
        assert len(WP2_EVENT_TYPES) == 12

    def test_new_member_string_values_are_unique(self):
        values = list(WP2_EVENT_TYPES.values())
        assert len(values) == len(set(values))

    def test_no_collision_with_original_members(self):
        new_values = set(WP2_EVENT_TYPES.values())
        old_values = set(ORIGINAL_EVENT_TYPES.values())
        overlap = new_values & old_values
        assert overlap == set(), f"Colliding values: {overlap}"

    @pytest.mark.parametrize(
        "member,expected_value",
        ORIGINAL_EVENT_TYPES.items(),
        ids=lambda x: x.name if isinstance(x, EventType) else x,
    )
    def test_original_members_unchanged(self, member, expected_value):
        assert member.value == expected_value

    def test_event_type_is_str_enum(self):
        """EventType members compare equal to their string values."""
        assert EventType.NODE_LOOP_STARTED == "node_loop_started"
        assert EventType.LLM_TEXT_DELTA == "llm_text_delta"
        assert EventType.LLM_TEXT_DELTA.value == "llm_text_delta"

    def test_event_type_accessible_by_name(self):
        assert EventType["NODE_LOOP_STARTED"] is EventType.NODE_LOOP_STARTED
        assert EventType["TOOL_CALL_COMPLETED"] is EventType.TOOL_CALL_COMPLETED

    def test_event_type_accessible_by_value(self):
        assert EventType("node_loop_started") is EventType.NODE_LOOP_STARTED
        assert EventType("tool_call_completed") is EventType.TOOL_CALL_COMPLETED


# ---------------------------------------------------------------------------
# WP-2 Part B: AgentEvent.node_id and Subscription.filter_node
# ---------------------------------------------------------------------------
class TestWP2AgentEventNodeId:
    """AgentEvent supports node_id as a first-class field."""

    def test_node_id_defaults_to_none(self):
        event = AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="stream-1",
        )
        assert event.node_id is None

    def test_node_id_can_be_set(self):
        event = AgentEvent(
            type=EventType.LLM_TEXT_DELTA,
            stream_id="stream-1",
            node_id="email_composer",
        )
        assert event.node_id == "email_composer"

    def test_node_id_in_to_dict(self):
        event = AgentEvent(
            type=EventType.TOOL_CALL_STARTED,
            stream_id="stream-1",
            node_id="search_node",
        )
        d = event.to_dict()
        assert d["node_id"] == "search_node"

    def test_node_id_none_in_to_dict(self):
        event = AgentEvent(
            type=EventType.EXECUTION_STARTED,
            stream_id="stream-1",
        )
        d = event.to_dict()
        assert "node_id" in d
        assert d["node_id"] is None


class TestWP2SubscriptionFilterNode:
    """Subscription supports filter_node for node-level routing."""

    @staticmethod
    async def _noop_handler(event: AgentEvent) -> None:
        pass

    def test_filter_node_defaults_to_none(self):
        sub = Subscription(
            id="sub_1",
            event_types={EventType.LLM_TEXT_DELTA},
            handler=self._noop_handler,
        )
        assert sub.filter_node is None

    def test_filter_node_can_be_set(self):
        sub = Subscription(
            id="sub_1",
            event_types={EventType.LLM_TEXT_DELTA},
            handler=self._noop_handler,
            filter_node="email_composer",
        )
        assert sub.filter_node == "email_composer"


# ---------------------------------------------------------------------------
# WP-2 Part B: Node-level event routing integration tests
# ---------------------------------------------------------------------------
class TestWP2NodeLevelRouting:
    """EventBus routes events by node_id using filter_node."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_filter_node_receives_matching_events(self, bus):
        """Subscriber with filter_node='node-A' receives events from node-A."""
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(
            event_types=[EventType.LLM_TEXT_DELTA],
            handler=handler,
            filter_node="node-A",
        )

        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="stream-1",
                node_id="node-A",
                data={"content": "hello"},
            )
        )

        assert len(received) == 1
        assert received[0].node_id == "node-A"
        assert received[0].data["content"] == "hello"

    @pytest.mark.asyncio
    async def test_filter_node_rejects_non_matching_events(self, bus):
        """Subscriber with filter_node='node-B' does NOT receive node-A events."""
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(
            event_types=[EventType.LLM_TEXT_DELTA],
            handler=handler,
            filter_node="node-B",
        )

        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="stream-1",
                node_id="node-A",
                data={"content": "hello"},
            )
        )

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_no_filter_node_receives_all_events(self, bus):
        """Subscriber with no filter_node receives events from all nodes."""
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(
            event_types=[EventType.LLM_TEXT_DELTA],
            handler=handler,
        )

        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="stream-1",
                node_id="node-A",
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="stream-1",
                node_id="node-B",
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="stream-1",
                node_id=None,
            )
        )

        assert len(received) == 3

    @pytest.mark.asyncio
    async def test_interleaved_nodes_separated_by_filter(self, bus):
        """Two subscribers on different nodes get only their node's events."""
        node_a_events = []
        node_b_events = []

        async def handler_a(event):
            node_a_events.append(event)

        async def handler_b(event):
            node_b_events.append(event)

        bus.subscribe(
            event_types=[EventType.LLM_TEXT_DELTA],
            handler=handler_a,
            filter_node="email_sender",
        )
        bus.subscribe(
            event_types=[EventType.LLM_TEXT_DELTA],
            handler=handler_b,
            filter_node="inbox_scanner",
        )

        # Interleaved events from both nodes
        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="webhook",
                node_id="email_sender",
                data={"content": "Dear Jo"},
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="webhook",
                node_id="inbox_scanner",
                data={"content": "RE: Meeting conf"},
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="webhook",
                node_id="email_sender",
                data={"content": "hn, Thank you for"},
            )
        )
        await bus.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id="webhook",
                node_id="inbox_scanner",
                data={"content": "irmed for Thursday"},
            )
        )

        assert len(node_a_events) == 2
        assert len(node_b_events) == 2
        assert node_a_events[0].data["content"] == "Dear Jo"
        assert node_a_events[1].data["content"] == "hn, Thank you for"
        assert node_b_events[0].data["content"] == "RE: Meeting conf"
        assert node_b_events[1].data["content"] == "irmed for Thursday"

    @pytest.mark.asyncio
    async def test_filter_node_combined_with_filter_stream(self, bus):
        """filter_node and filter_stream work together."""
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(
            event_types=[EventType.TOOL_CALL_STARTED],
            handler=handler,
            filter_stream="webhook",
            filter_node="search_node",
        )

        # Matching both filters
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_STARTED,
                stream_id="webhook",
                node_id="search_node",
            )
        )
        # Wrong stream
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_STARTED,
                stream_id="api",
                node_id="search_node",
            )
        )
        # Wrong node
        await bus.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_STARTED,
                stream_id="webhook",
                node_id="other_node",
            )
        )

        assert len(received) == 1
        assert received[0].stream_id == "webhook"
        assert received[0].node_id == "search_node"

    @pytest.mark.asyncio
    async def test_wait_for_with_node_id(self, bus):
        """wait_for() accepts node_id parameter for filtering."""

        async def publish_later():
            await asyncio.sleep(0.01)
            await bus.publish(
                AgentEvent(
                    type=EventType.NODE_LOOP_COMPLETED,
                    stream_id="stream-1",
                    node_id="target_node",
                    data={"iterations": 3},
                )
            )

        task = asyncio.create_task(publish_later())
        event = await bus.wait_for(
            event_type=EventType.NODE_LOOP_COMPLETED,
            node_id="target_node",
            timeout=2.0,
        )
        await task

        assert event is not None
        assert event.node_id == "target_node"
        assert event.data["iterations"] == 3

    @pytest.mark.asyncio
    async def test_wait_for_ignores_wrong_node(self, bus):
        """wait_for() with node_id ignores events from other nodes."""

        async def publish_wrong_then_right():
            await asyncio.sleep(0.01)
            # Wrong node — should be ignored
            await bus.publish(
                AgentEvent(
                    type=EventType.NODE_LOOP_COMPLETED,
                    stream_id="stream-1",
                    node_id="wrong_node",
                )
            )
            await asyncio.sleep(0.01)
            # Right node
            await bus.publish(
                AgentEvent(
                    type=EventType.NODE_LOOP_COMPLETED,
                    stream_id="stream-1",
                    node_id="target_node",
                    data={"iterations": 5},
                )
            )

        task = asyncio.create_task(publish_wrong_then_right())
        event = await bus.wait_for(
            event_type=EventType.NODE_LOOP_COMPLETED,
            node_id="target_node",
            timeout=2.0,
        )
        await task

        assert event is not None
        assert event.node_id == "target_node"
        assert event.data["iterations"] == 5


# ---------------------------------------------------------------------------
# WP-2: Convenience publisher methods
# ---------------------------------------------------------------------------
class TestWP2ConveniencePublishers:
    """EventBus convenience methods for new WP-2 event types."""

    @pytest.fixture
    def bus(self):
        return EventBus()

    @pytest.mark.asyncio
    async def test_emit_node_loop_started(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.NODE_LOOP_STARTED], handler=handler)
        await bus.emit_node_loop_started(
            stream_id="s1",
            node_id="n1",
            max_iterations=10,
        )

        assert len(received) == 1
        assert received[0].node_id == "n1"
        assert received[0].data["max_iterations"] == 10

    @pytest.mark.asyncio
    async def test_emit_node_loop_iteration(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.NODE_LOOP_ITERATION], handler=handler)
        await bus.emit_node_loop_iteration(
            stream_id="s1",
            node_id="n1",
            iteration=3,
        )

        assert len(received) == 1
        assert received[0].data["iteration"] == 3

    @pytest.mark.asyncio
    async def test_emit_node_loop_completed(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.NODE_LOOP_COMPLETED], handler=handler)
        await bus.emit_node_loop_completed(
            stream_id="s1",
            node_id="n1",
            iterations=5,
        )

        assert len(received) == 1
        assert received[0].data["iterations"] == 5

    @pytest.mark.asyncio
    async def test_emit_llm_text_delta(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.LLM_TEXT_DELTA], handler=handler)
        await bus.emit_llm_text_delta(
            stream_id="s1",
            node_id="n1",
            content="hello",
            snapshot="hello world",
        )

        assert len(received) == 1
        assert received[0].data["content"] == "hello"
        assert received[0].data["snapshot"] == "hello world"

    @pytest.mark.asyncio
    async def test_emit_tool_call_started(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.TOOL_CALL_STARTED], handler=handler)
        await bus.emit_tool_call_started(
            stream_id="s1",
            node_id="n1",
            tool_use_id="call_1",
            tool_name="web_search",
            tool_input={"query": "test"},
        )

        assert len(received) == 1
        assert received[0].data["tool_name"] == "web_search"
        assert received[0].data["tool_input"] == {"query": "test"}

    @pytest.mark.asyncio
    async def test_emit_tool_call_completed(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.TOOL_CALL_COMPLETED], handler=handler)
        await bus.emit_tool_call_completed(
            stream_id="s1",
            node_id="n1",
            tool_use_id="call_1",
            tool_name="web_search",
            result="3 results found",
        )

        assert len(received) == 1
        assert received[0].data["result"] == "3 results found"
        assert received[0].data["is_error"] is False

    @pytest.mark.asyncio
    async def test_emit_client_output_delta(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.CLIENT_OUTPUT_DELTA], handler=handler)
        await bus.emit_client_output_delta(
            stream_id="s1",
            node_id="n1",
            content="chunk",
            snapshot="full chunk",
        )

        assert len(received) == 1
        assert received[0].data["content"] == "chunk"

    @pytest.mark.asyncio
    async def test_emit_node_stalled(self, bus):
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(event_types=[EventType.NODE_STALLED], handler=handler)
        await bus.emit_node_stalled(
            stream_id="s1",
            node_id="n1",
            reason="no progress after 10 iterations",
        )

        assert len(received) == 1
        assert received[0].data["reason"] == "no progress after 10 iterations"

    @pytest.mark.asyncio
    async def test_convenience_publishers_set_node_id(self, bus):
        """All WP-2 convenience publishers set node_id on the emitted event."""
        received = []

        async def handler(event):
            received.append(event)

        bus.subscribe(
            event_types=[EventType.LLM_TEXT_DELTA, EventType.TOOL_CALL_STARTED],
            handler=handler,
            filter_node="my_node",
        )

        await bus.emit_llm_text_delta(
            stream_id="s1",
            node_id="my_node",
            content="hi",
            snapshot="hi",
        )
        await bus.emit_tool_call_started(
            stream_id="s1",
            node_id="my_node",
            tool_use_id="c1",
            tool_name="calc",
        )
        # Wrong node — should not be received
        await bus.emit_llm_text_delta(
            stream_id="s1",
            node_id="other_node",
            content="bye",
            snapshot="bye",
        )

        assert len(received) == 2
        assert all(e.node_id == "my_node" for e in received)
