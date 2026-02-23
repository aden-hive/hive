"""Tests for stream event dataclasses.

Validates construction, defaults, immutability, serialization, and the
StreamEvent discriminated union type.
"""

from dataclasses import FrozenInstanceError, asdict, fields

import pytest

from framework.llm.stream_events import (
    FinishEvent,
    ReasoningDeltaEvent,
    ReasoningStartEvent,
    StreamErrorEvent,
    StreamEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
    ToolResultEvent,
)

# All concrete event classes in the union
ALL_EVENT_CLASSES = [
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ReasoningStartEvent,
    ReasoningDeltaEvent,
    FinishEvent,
    StreamErrorEvent,
]


# ---------------------------------------------------------------------------
# Construction & defaults
# ---------------------------------------------------------------------------
class TestEventDefaults:
    """Each event class should be constructible with zero arguments."""

    @pytest.mark.parametrize("cls", ALL_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_default_construction(self, cls):
        event = cls()
        assert event.type != ""

    def test_text_delta_defaults(self):
        e = TextDeltaEvent()
        assert e.type == "text_delta"
        assert e.content == ""
        assert e.snapshot == ""

    def test_text_end_defaults(self):
        e = TextEndEvent()
        assert e.type == "text_end"
        assert e.full_text == ""

    def test_tool_call_defaults(self):
        e = ToolCallEvent()
        assert e.type == "tool_call"
        assert e.tool_use_id == ""
        assert e.tool_name == ""
        assert e.tool_input == {}

    def test_tool_result_defaults(self):
        e = ToolResultEvent()
        assert e.type == "tool_result"
        assert e.tool_use_id == ""
        assert e.content == ""
        assert e.is_error is False

    def test_reasoning_start_defaults(self):
        e = ReasoningStartEvent()
        assert e.type == "reasoning_start"

    def test_reasoning_delta_defaults(self):
        e = ReasoningDeltaEvent()
        assert e.type == "reasoning_delta"
        assert e.content == ""

    def test_finish_defaults(self):
        e = FinishEvent()
        assert e.type == "finish"
        assert e.stop_reason == ""
        assert e.input_tokens == 0
        assert e.output_tokens == 0
        assert e.model == ""

    def test_stream_error_defaults(self):
        e = StreamErrorEvent()
        assert e.type == "error"
        assert e.error == ""
        assert e.recoverable is False


# ---------------------------------------------------------------------------
# Construction with values
# ---------------------------------------------------------------------------
class TestEventConstruction:
    """Events should store provided field values correctly."""

    def test_text_delta_with_values(self):
        e = TextDeltaEvent(content="hello", snapshot="hello world")
        assert e.content == "hello"
        assert e.snapshot == "hello world"

    def test_text_end_with_values(self):
        e = TextEndEvent(full_text="the complete response")
        assert e.full_text == "the complete response"

    def test_tool_call_with_values(self):
        e = ToolCallEvent(
            tool_use_id="call_abc123",
            tool_name="web_search",
            tool_input={"query": "python", "num_results": 5},
        )
        assert e.tool_use_id == "call_abc123"
        assert e.tool_name == "web_search"
        assert e.tool_input == {"query": "python", "num_results": 5}

    def test_tool_result_with_values(self):
        e = ToolResultEvent(
            tool_use_id="call_abc123",
            content="search results here",
            is_error=False,
        )
        assert e.tool_use_id == "call_abc123"
        assert e.content == "search results here"
        assert e.is_error is False

    def test_tool_result_error(self):
        e = ToolResultEvent(
            tool_use_id="call_fail",
            content="timeout",
            is_error=True,
        )
        assert e.is_error is True

    def test_reasoning_delta_with_content(self):
        e = ReasoningDeltaEvent(content="Let me think about this...")
        assert e.content == "Let me think about this..."

    def test_finish_with_values(self):
        e = FinishEvent(
            stop_reason="end_turn",
            input_tokens=150,
            output_tokens=300,
            model="claude-haiku-4-5",
        )
        assert e.stop_reason == "end_turn"
        assert e.input_tokens == 150
        assert e.output_tokens == 300
        assert e.model == "claude-haiku-4-5"

    def test_stream_error_with_values(self):
        e = StreamErrorEvent(error="rate limit exceeded", recoverable=True)
        assert e.error == "rate limit exceeded"
        assert e.recoverable is True


# ---------------------------------------------------------------------------
# Frozen immutability
# ---------------------------------------------------------------------------
class TestEventImmutability:
    """All events are frozen dataclasses — fields cannot be reassigned."""

    @pytest.mark.parametrize("cls", ALL_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_frozen(self, cls):
        event = cls()
        with pytest.raises(FrozenInstanceError):
            event.type = "modified"

    def test_text_delta_frozen_content(self):
        e = TextDeltaEvent(content="hello")
        with pytest.raises(FrozenInstanceError):
            e.content = "modified"

    def test_tool_call_frozen_input(self):
        e = ToolCallEvent(tool_input={"key": "value"})
        with pytest.raises(FrozenInstanceError):
            e.tool_input = {}


# ---------------------------------------------------------------------------
# Type literal values
# ---------------------------------------------------------------------------
class TestTypeLiterals:
    """Each event's `type` field should match its Literal annotation."""

    EXPECTED_TYPES = {
        TextDeltaEvent: "text_delta",
        TextEndEvent: "text_end",
        ToolCallEvent: "tool_call",
        ToolResultEvent: "tool_result",
        ReasoningStartEvent: "reasoning_start",
        ReasoningDeltaEvent: "reasoning_delta",
        FinishEvent: "finish",
        StreamErrorEvent: "error",
    }

    @pytest.mark.parametrize(
        "cls,expected_type",
        EXPECTED_TYPES.items(),
        ids=lambda x: x.__name__ if isinstance(x, type) else x,
    )
    def test_type_value(self, cls, expected_type):
        assert cls().type == expected_type

    def test_all_types_unique(self):
        types = [cls().type for cls in ALL_EVENT_CLASSES]
        assert len(types) == len(set(types)), f"Duplicate type values: {types}"


# ---------------------------------------------------------------------------
# Serialization via dataclasses.asdict
# ---------------------------------------------------------------------------
class TestEventSerialization:
    """Events should round-trip through asdict for JSON serialization."""

    def test_text_delta_asdict(self):
        e = TextDeltaEvent(content="chunk", snapshot="full chunk")
        d = asdict(e)
        assert d == {"type": "text_delta", "content": "chunk", "snapshot": "full chunk"}

    def test_tool_call_asdict(self):
        e = ToolCallEvent(
            tool_use_id="id_1",
            tool_name="calc",
            tool_input={"expression": "2+2"},
        )
        d = asdict(e)
        assert d["tool_name"] == "calc"
        assert d["tool_input"] == {"expression": "2+2"}

    def test_finish_asdict(self):
        e = FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=20, model="gpt-4")
        d = asdict(e)
        assert d == {
            "type": "finish",
            "stop_reason": "stop",
            "input_tokens": 10,
            "output_tokens": 20,
            "model": "gpt-4",
        }

    @pytest.mark.parametrize("cls", ALL_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_asdict_contains_type(self, cls):
        d = asdict(cls())
        assert "type" in d

    @pytest.mark.parametrize("cls", ALL_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_asdict_keys_match_fields(self, cls):
        event = cls()
        d = asdict(event)
        field_names = {f.name for f in fields(cls)}
        assert set(d.keys()) == field_names


# ---------------------------------------------------------------------------
# StreamEvent union type
# ---------------------------------------------------------------------------
class TestStreamEventUnion:
    """The StreamEvent union should include all event classes."""

    def test_union_contains_all_classes(self):
        # StreamEvent is a UnionType (PEP 604 syntax: X | Y | Z)
        union_args = StreamEvent.__args__  # type: ignore[attr-defined]
        for cls in ALL_EVENT_CLASSES:
            assert cls in union_args, f"{cls.__name__} not in StreamEvent union"

    def test_union_has_exactly_expected_members(self):
        union_args = set(StreamEvent.__args__)  # type: ignore[attr-defined]
        expected = set(ALL_EVENT_CLASSES)
        assert union_args == expected

    @pytest.mark.parametrize("cls", ALL_EVENT_CLASSES, ids=lambda c: c.__name__)
    def test_isinstance_check(self, cls):
        """Each event instance should be an instance of its class (basic sanity)."""
        event = cls()
        assert isinstance(event, cls)


# ---------------------------------------------------------------------------
# Equality & hashing (frozen dataclasses support both)
# ---------------------------------------------------------------------------
class TestEventEquality:
    """Frozen dataclasses support equality and hashing."""

    def test_equal_events(self):
        a = TextDeltaEvent(content="hi", snapshot="hi")
        b = TextDeltaEvent(content="hi", snapshot="hi")
        assert a == b

    def test_unequal_events(self):
        a = TextDeltaEvent(content="hi")
        b = TextDeltaEvent(content="bye")
        assert a != b

    def test_different_types_not_equal(self):
        a = TextDeltaEvent(content="hi")
        b = ReasoningDeltaEvent(content="hi")
        assert a != b

    def test_hashable(self):
        e = FinishEvent(stop_reason="stop", model="gpt-4")
        s = {e}  # should be hashable since frozen
        assert e in s

    def test_equal_events_same_hash(self):
        a = FinishEvent(stop_reason="stop", model="gpt-4")
        b = FinishEvent(stop_reason="stop", model="gpt-4")
        assert hash(a) == hash(b)

    def test_events_with_dict_not_hashable(self):
        """Events containing dict fields (e.g. tool_input) are not hashable."""
        e = ToolCallEvent(tool_use_id="x", tool_name="y", tool_input={"key": "val"})
        with pytest.raises(TypeError, match="unhashable type"):
            hash(e)
