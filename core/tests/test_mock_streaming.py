"""Tests for MockLLMProvider streaming scenarios and helper functions.

Proves that the enhanced MockLLMProvider can deterministically simulate
text-only, tool-call, error, and multi-turn streaming sequences for CI
without any real API calls.
"""

from __future__ import annotations

import pytest

from framework.llm.mock import (
    MockLLMProvider,
    error_scenario,
    text_scenario,
    tool_call_scenario,
)
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    TextEndEvent,
    ToolCallEvent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect(provider, **kwargs):
    """Collect all events from a single stream() call."""
    events = []
    async for event in provider.stream(messages=[{"role": "user", "content": "hi"}], **kwargs):
        events.append(event)
    return events


# ===========================================================================
# Default (no scenarios) — backward compatibility
# ===========================================================================


class TestDefaultNoScenarios:
    @pytest.mark.asyncio
    async def test_default_no_scenarios(self):
        """No scenarios = word-split TextDeltaEvents + TextEndEvent + FinishEvent."""
        provider = MockLLMProvider()
        events = await _collect(provider)

        text_deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        text_ends = [e for e in events if isinstance(e, TextEndEvent)]
        finishes = [e for e in events if isinstance(e, FinishEvent)]

        assert len(text_deltas) >= 1
        assert len(text_ends) == 1
        assert len(finishes) == 1
        assert finishes[0].stop_reason == "mock_complete"

        # Snapshot of last delta should match full_text of TextEndEvent
        assert text_deltas[-1].snapshot == text_ends[0].full_text

    @pytest.mark.asyncio
    async def test_event_type_sequence(self):
        """Events follow TextDeltaEvent*, TextEndEvent, FinishEvent pattern."""
        provider = MockLLMProvider(model="mock-test")
        events = await _collect(provider)

        # All events before the last two must be TextDeltaEvent
        for e in events[:-2]:
            assert isinstance(e, TextDeltaEvent)
        assert isinstance(events[-2], TextEndEvent)
        assert isinstance(events[-1], FinishEvent)

    @pytest.mark.asyncio
    async def test_snapshot_monotonic_growth(self):
        """Each TextDeltaEvent.snapshot is a prefix of the next."""
        provider = MockLLMProvider(model="mock-test")
        events = await _collect(provider)

        deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        for i in range(1, len(deltas)):
            assert deltas[i].snapshot.startswith(deltas[i - 1].snapshot)

    @pytest.mark.asyncio
    async def test_full_text_matches_chunks(self):
        """TextEndEvent.full_text == concatenation of all chunk contents."""
        provider = MockLLMProvider(model="mock-test")
        events = await _collect(provider)

        deltas = [e for e in events if isinstance(e, TextDeltaEvent)]
        concatenated = "".join(e.content for e in deltas)
        end_event = next(e for e in events if isinstance(e, TextEndEvent))
        assert end_event.full_text == concatenated


# ===========================================================================
# text_scenario
# ===========================================================================


class TestTextScenario:
    @pytest.mark.asyncio
    async def test_text_scenario(self):
        """text_scenario yields TextDeltaEvent then FinishEvent(stop_reason='stop')."""
        provider = MockLLMProvider(scenarios=[text_scenario("Hello world")])
        events = await _collect(provider)

        assert len(events) == 2
        assert isinstance(events[0], TextDeltaEvent)
        assert events[0].content == "Hello world"
        assert events[0].snapshot == "Hello world"
        assert isinstance(events[1], FinishEvent)
        assert events[1].stop_reason == "stop"

    @pytest.mark.asyncio
    async def test_text_scenario_custom_tokens(self):
        """text_scenario respects custom input/output token counts."""
        provider = MockLLMProvider(
            scenarios=[text_scenario("ok", input_tokens=100, output_tokens=50)]
        )
        events = await _collect(provider)

        finish = events[-1]
        assert finish.input_tokens == 100
        assert finish.output_tokens == 50


# ===========================================================================
# tool_call_scenario
# ===========================================================================


class TestToolCallScenario:
    @pytest.mark.asyncio
    async def test_tool_call_scenario(self):
        """tool_call_scenario yields ToolCallEvent + FinishEvent(stop_reason='tool_calls')."""
        provider = MockLLMProvider(scenarios=[tool_call_scenario("search", {"query": "test"})])
        events = await _collect(provider)

        assert len(events) == 2
        assert isinstance(events[0], ToolCallEvent)
        assert events[0].tool_name == "search"
        assert events[0].tool_input == {"query": "test"}
        assert events[0].tool_use_id == "call_1"
        assert isinstance(events[1], FinishEvent)
        assert events[1].stop_reason == "tool_calls"

    @pytest.mark.asyncio
    async def test_tool_call_with_text(self):
        """tool_call_scenario with text= yields TextDeltaEvent before ToolCallEvent."""
        provider = MockLLMProvider(
            scenarios=[tool_call_scenario("run", {"cmd": "ls"}, text="Let me check")]
        )
        events = await _collect(provider)

        assert len(events) == 3
        assert isinstance(events[0], TextDeltaEvent)
        assert events[0].content == "Let me check"
        assert isinstance(events[1], ToolCallEvent)
        assert isinstance(events[2], FinishEvent)

    @pytest.mark.asyncio
    async def test_tool_call_custom_id(self):
        """tool_call_scenario respects custom tool_use_id."""
        provider = MockLLMProvider(
            scenarios=[tool_call_scenario("search", {}, tool_use_id="custom_123")]
        )
        events = await _collect(provider)

        tool_event = events[0]
        assert tool_event.tool_use_id == "custom_123"


# ===========================================================================
# error_scenario
# ===========================================================================


class TestErrorScenario:
    @pytest.mark.asyncio
    async def test_error_scenario(self):
        """error_scenario yields StreamErrorEvent with correct fields."""
        provider = MockLLMProvider(scenarios=[error_scenario()])
        events = await _collect(provider)

        assert len(events) == 1
        assert isinstance(events[0], StreamErrorEvent)
        assert events[0].error == "Connection lost"
        assert events[0].recoverable is False

    @pytest.mark.asyncio
    async def test_error_scenario_custom(self):
        """error_scenario respects custom error and recoverable."""
        provider = MockLLMProvider(scenarios=[error_scenario(error="Rate limit", recoverable=True)])
        events = await _collect(provider)

        assert events[0].error == "Rate limit"
        assert events[0].recoverable is True


# ===========================================================================
# Multi-turn cycling
# ===========================================================================


class TestMultiTurnCycling:
    @pytest.mark.asyncio
    async def test_multi_turn_cycling(self):
        """Two scenarios, two stream() calls — first yields scenario 1, second scenario 2."""
        provider = MockLLMProvider(
            scenarios=[
                text_scenario("first"),
                text_scenario("second"),
            ]
        )

        events1 = await _collect(provider)
        events2 = await _collect(provider)

        assert events1[0].content == "first"
        assert events2[0].content == "second"

    @pytest.mark.asyncio
    async def test_scenario_wraps_around(self):
        """One scenario, three stream() calls — all yield the same events."""
        provider = MockLLMProvider(scenarios=[text_scenario("only")])

        events1 = await _collect(provider)
        events2 = await _collect(provider)
        events3 = await _collect(provider)

        assert events1[0].content == "only"
        assert events2[0].content == "only"
        assert events3[0].content == "only"
        assert provider._call_index == 3


# ===========================================================================
# Call recording
# ===========================================================================


class TestCallRecording:
    @pytest.mark.asyncio
    async def test_call_recording(self):
        """stream_calls captures messages, system, tools from each call."""
        provider = MockLLMProvider(scenarios=[text_scenario("ok")])

        tools = [{"name": "search"}]
        await _collect(provider, system="Be helpful", tools=tools)

        assert len(provider.stream_calls) == 1
        call = provider.stream_calls[0]
        # _collect passes messages=[{"role": "user", "content": "hi"}]
        assert call["messages"] == [{"role": "user", "content": "hi"}]
        assert call["system"] == "Be helpful"
        assert call["tools"] == tools

    @pytest.mark.asyncio
    async def test_call_recording_default_fallback(self):
        """stream_calls works in default (no scenario) mode too."""
        provider = MockLLMProvider()
        await _collect(provider)

        assert len(provider.stream_calls) == 1
        assert provider.stream_calls[0]["system"] == ""
        assert provider.stream_calls[0]["tools"] is None


# ===========================================================================
# Model preservation
# ===========================================================================


class TestModelPreserved:
    @pytest.mark.asyncio
    async def test_model_preserved(self):
        """MockLLMProvider(model='gpt-test') default stream uses that model in FinishEvent."""
        provider = MockLLMProvider(model="gpt-test")
        events = await _collect(provider)

        finish = [e for e in events if isinstance(e, FinishEvent)][0]
        assert finish.model == "gpt-test"


# ===========================================================================
# No-arg construction (SpyLLMProvider compat)
# ===========================================================================


class TestNoArgConstruction:
    @pytest.mark.asyncio
    async def test_no_arg_construction(self):
        """MockLLMProvider() works with no arguments (SpyLLMProvider compat)."""
        provider = MockLLMProvider()
        assert provider.model == "mock-model"
        assert provider.scenarios == []
        assert provider._call_index == 0
        assert provider.stream_calls == []

        # Should still stream without error
        events = await _collect(provider)
        assert len(events) >= 2  # at least one TextDelta + FinishEvent
