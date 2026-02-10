"""Tests for the observability hook system.

Tests cover:
- NoOpHooks zero-overhead behavior
- CompositeHooks fan-out and error isolation
- ObservabilityConfig validation
- Event dataclass construction
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.observability.config import ObservabilityConfig
from framework.observability.hooks import (
    CompositeHooks,
    NoOpHooks,
    ObservabilityHooks,
)
from framework.observability.types import (
    DecisionEvent,
    NodeCompleteEvent,
    NodeErrorEvent,
    NodeStartEvent,
    RunCompleteEvent,
    RunStartEvent,
    ToolCallEvent,
)


# ---------------------------------------------------------------------------
# Event type tests
# ---------------------------------------------------------------------------


class TestEventTypes:
    def test_run_start_event_defaults(self):
        event = RunStartEvent(run_id="run-1", goal_id="goal-1")
        assert event.run_id == "run-1"
        assert event.goal_id == "goal-1"
        assert event.input_data == {}
        assert event.timestamp  # auto-generated

    def test_node_start_event(self):
        event = NodeStartEvent(
            run_id="run-1",
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
        )
        assert event.node_id == "node-1"
        assert event.node_name == "Search"
        assert event.node_type == "event_loop"

    def test_node_complete_event_with_metrics(self):
        event = NodeCompleteEvent(
            run_id="run-1",
            node_id="node-1",
            node_name="Search",
            node_type="event_loop",
            success=True,
            latency_ms=1500,
            tokens_used=300,
            input_tokens=200,
            output_tokens=100,
        )
        assert event.success is True
        assert event.latency_ms == 1500
        assert event.tokens_used == 300

    def test_node_error_event(self):
        event = NodeErrorEvent(
            run_id="run-1",
            node_id="node-1",
            node_name="Broken",
            node_type="function",
            error="Connection timeout",
            stacktrace="Traceback...",
        )
        assert event.error == "Connection timeout"
        assert event.stacktrace == "Traceback..."

    def test_decision_event(self):
        event = DecisionEvent(
            run_id="run-1",
            decision_id="dec-1",
            node_id="node-1",
            intent="Choose search strategy",
            chosen="web_search",
            reasoning="Most relevant",
            options_count=3,
        )
        assert event.chosen == "web_search"
        assert event.options_count == 3

    def test_tool_call_event(self):
        event = ToolCallEvent(
            run_id="run-1",
            node_id="node-1",
            tool_name="web_search",
            tool_input={"query": "test"},
            result="Found 3 results",
            is_error=False,
            latency_ms=500,
        )
        assert event.tool_name == "web_search"
        assert event.is_error is False

    def test_run_complete_event(self):
        event = RunCompleteEvent(
            run_id="run-1",
            status="success",
            duration_ms=5000,
            total_nodes_executed=3,
            total_tokens=1500,
        )
        assert event.status == "success"
        assert event.duration_ms == 5000

    def test_events_are_frozen(self):
        """Event dataclasses should be immutable."""
        event = RunStartEvent(run_id="run-1", goal_id="goal-1")
        with pytest.raises(AttributeError):
            event.run_id = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# NoOpHooks tests
# ---------------------------------------------------------------------------


class TestNoOpHooks:
    @pytest.mark.asyncio
    async def test_all_methods_are_callable(self):
        """NoOpHooks should accept all event types without error."""
        hooks = NoOpHooks()
        await hooks.on_run_start(RunStartEvent(run_id="r", goal_id="g"))
        await hooks.on_node_start(
            NodeStartEvent(run_id="r", node_id="n", node_name="N", node_type="t")
        )
        await hooks.on_node_complete(
            NodeCompleteEvent(
                run_id="r", node_id="n", node_name="N", node_type="t", success=True
            )
        )
        await hooks.on_node_error(
            NodeErrorEvent(
                run_id="r", node_id="n", node_name="N", node_type="t", error="err"
            )
        )
        await hooks.on_decision_made(
            DecisionEvent(
                run_id="r",
                decision_id="d",
                node_id="n",
                intent="i",
                chosen="c",
                reasoning="r",
            )
        )
        await hooks.on_tool_call(
            ToolCallEvent(run_id="r", node_id="n", tool_name="t")
        )
        await hooks.on_run_complete(RunCompleteEvent(run_id="r", status="success"))

    def test_satisfies_protocol(self):
        """NoOpHooks should be recognized as an ObservabilityHooks instance."""
        hooks = NoOpHooks()
        assert isinstance(hooks, ObservabilityHooks)


# ---------------------------------------------------------------------------
# CompositeHooks tests
# ---------------------------------------------------------------------------


class TestCompositeHooks:
    @pytest.mark.asyncio
    async def test_dispatches_to_all_hooks(self):
        """CompositeHooks should call every registered hook."""
        hook_a = AsyncMock(spec=NoOpHooks)
        hook_b = AsyncMock(spec=NoOpHooks)

        composite = CompositeHooks([hook_a, hook_b])

        event = RunStartEvent(run_id="run-1", goal_id="goal-1")
        await composite.on_run_start(event)

        hook_a.on_run_start.assert_awaited_once_with(event)
        hook_b.on_run_start.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_error_isolation(self):
        """One failing hook should not prevent others from receiving events."""
        hook_good = AsyncMock(spec=NoOpHooks)
        hook_bad = AsyncMock(spec=NoOpHooks)
        hook_bad.on_run_start.side_effect = RuntimeError("hook crashed")

        composite = CompositeHooks([hook_bad, hook_good])

        event = RunStartEvent(run_id="run-1", goal_id="goal-1")
        # Should not raise
        await composite.on_run_start(event)

        # The good hook should still be called
        hook_good.on_run_start.assert_awaited_once_with(event)

    @pytest.mark.asyncio
    async def test_all_event_types_dispatched(self):
        """CompositeHooks should dispatch all 7 event types."""
        hook = AsyncMock(spec=NoOpHooks)
        composite = CompositeHooks([hook])

        await composite.on_run_start(RunStartEvent(run_id="r", goal_id="g"))
        await composite.on_node_start(
            NodeStartEvent(run_id="r", node_id="n", node_name="N", node_type="t")
        )
        await composite.on_node_complete(
            NodeCompleteEvent(
                run_id="r", node_id="n", node_name="N", node_type="t", success=True
            )
        )
        await composite.on_node_error(
            NodeErrorEvent(
                run_id="r", node_id="n", node_name="N", node_type="t", error="e"
            )
        )
        await composite.on_decision_made(
            DecisionEvent(
                run_id="r",
                decision_id="d",
                node_id="n",
                intent="i",
                chosen="c",
                reasoning="r",
            )
        )
        await composite.on_tool_call(
            ToolCallEvent(run_id="r", node_id="n", tool_name="t")
        )
        await composite.on_run_complete(RunCompleteEvent(run_id="r", status="success"))

        # All 7 methods should have been called
        assert hook.on_run_start.await_count == 1
        assert hook.on_node_start.await_count == 1
        assert hook.on_node_complete.await_count == 1
        assert hook.on_node_error.await_count == 1
        assert hook.on_decision_made.await_count == 1
        assert hook.on_tool_call.await_count == 1
        assert hook.on_run_complete.await_count == 1

    @pytest.mark.asyncio
    async def test_empty_hooks_list(self):
        """CompositeHooks with no hooks should be a no-op."""
        composite = CompositeHooks([])
        # Should not raise
        await composite.on_run_start(RunStartEvent(run_id="r", goal_id="g"))


# ---------------------------------------------------------------------------
# ObservabilityConfig tests
# ---------------------------------------------------------------------------


class TestObservabilityConfig:
    def test_default_config(self):
        config = ObservabilityConfig()
        assert config.enabled is True
        assert config.hooks == []
        assert config.sample_rate == 1.0

    def test_invalid_sample_rate_raises(self):
        with pytest.raises(ValueError, match="sample_rate"):
            ObservabilityConfig(sample_rate=1.5)
        with pytest.raises(ValueError, match="sample_rate"):
            ObservabilityConfig(sample_rate=-0.1)

    def test_should_sample_disabled(self):
        config = ObservabilityConfig(enabled=False)
        assert config.should_sample() is False

    def test_should_sample_full_rate(self):
        config = ObservabilityConfig(enabled=True, sample_rate=1.0)
        # Must always be True at 100% rate
        for _ in range(100):
            assert config.should_sample() is True

    def test_should_sample_zero_rate(self):
        config = ObservabilityConfig(enabled=True, sample_rate=0.0)
        # Must always be False at 0% rate
        for _ in range(100):
            assert config.should_sample() is False

    def test_should_sample_partial_rate(self):
        """At 50% sample rate, some should be True and some False."""
        config = ObservabilityConfig(enabled=True, sample_rate=0.5)
        results = [config.should_sample() for _ in range(1000)]
        # Very unlikely all True or all False at 50%
        assert any(results)
        assert not all(results)


# ---------------------------------------------------------------------------
# Custom hook implementation test
# ---------------------------------------------------------------------------


class TestCustomHookImplementation:
    @pytest.mark.asyncio
    async def test_custom_hook_receives_events(self):
        """A user-defined hook implementation should receive all events."""

        class EventCollector:
            """Collects events for testing."""

            def __init__(self):
                self.events: list = []

            async def on_run_start(self, event: RunStartEvent) -> None:
                self.events.append(("run_start", event))

            async def on_node_start(self, event: NodeStartEvent) -> None:
                self.events.append(("node_start", event))

            async def on_node_complete(self, event: NodeCompleteEvent) -> None:
                self.events.append(("node_complete", event))

            async def on_node_error(self, event: NodeErrorEvent) -> None:
                self.events.append(("node_error", event))

            async def on_decision_made(self, event: DecisionEvent) -> None:
                self.events.append(("decision", event))

            async def on_tool_call(self, event: ToolCallEvent) -> None:
                self.events.append(("tool_call", event))

            async def on_run_complete(self, event: RunCompleteEvent) -> None:
                self.events.append(("run_complete", event))

        collector = EventCollector()

        # Simulate a run lifecycle
        await collector.on_run_start(RunStartEvent(run_id="r1", goal_id="g1"))
        await collector.on_node_start(
            NodeStartEvent(run_id="r1", node_id="n1", node_name="Search", node_type="event_loop")
        )
        await collector.on_node_complete(
            NodeCompleteEvent(
                run_id="r1",
                node_id="n1",
                node_name="Search",
                node_type="event_loop",
                success=True,
                latency_ms=1000,
            )
        )
        await collector.on_run_complete(
            RunCompleteEvent(run_id="r1", status="success", duration_ms=1000)
        )

        assert len(collector.events) == 4
        assert collector.events[0][0] == "run_start"
        assert collector.events[1][0] == "node_start"
        assert collector.events[2][0] == "node_complete"
        assert collector.events[3][0] == "run_complete"
