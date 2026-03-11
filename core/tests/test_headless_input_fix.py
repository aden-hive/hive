"""Tests for the headless (non-TTY) input deadlock fix.

Bug: runner.py gated stdin handler registration behind sys.stdin.isatty().
In non-TTY environments (CI, piped stdin, WSL2), the handler was never
registered, so CLIENT_INPUT_REQUESTED had no responder and _await_user_input()
blocked on an asyncio.Event that was never set — deadlock.

Fix: remove the isatty() guard so the handler is always registered for
client_facing agents, and pass is_client_input=True so injected stdin input
is treated as a real user message rather than an external event.

These tests operate at the EventLoopNode + EventBus level (no AgentRuntime
needed) to deterministically verify the blocking/unblocking behaviour.
"""

from __future__ import annotations

import asyncio
import io
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.graph.node import NodeContext, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider, LLMResponse, Tool
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runner.runner import AgentRunner, ExecutionResult
from framework.runtime.core import Runtime
from framework.runtime.event_bus import EventBus, EventType


# ---------------------------------------------------------------------------
# Minimal mock LLM (same pattern as test_event_loop_node.py)
# ---------------------------------------------------------------------------


class MockStreamingLLM(LLMProvider):
    def __init__(self, scenarios: list[list] | None = None):
        self.scenarios = scenarios or []
        self._call_index = 0
        self.stream_calls: list[dict] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator:
        self.stream_calls.append({"messages": messages, "system": system, "tools": tools})
        if not self.scenarios:
            return
        events = self.scenarios[self._call_index % len(self.scenarios)]
        self._call_index += 1
        for event in events:
            yield event

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="summary", model="mock", stop_reason="stop")


def text_scenario(text: str) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def tool_call_scenario(tool_name: str, tool_input: dict, tool_use_id: str = "tc_1") -> list:
    return [
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime():
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="session_headless_test")
    rt.decide = MagicMock(return_value="dec_1")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.set_node = MagicMock()
    return rt


@pytest.fixture
def memory():
    return SharedMemory()


@pytest.fixture
def client_spec():
    return NodeSpec(
        id="intake",
        name="Intake",
        description="client-facing intake node",
        node_type="event_loop",
        output_keys=[],
        client_facing=True,
    )


def build_ctx(runtime, node_spec, memory, llm):
    return NodeContext(
        runtime=runtime,
        node_id=node_spec.id,
        node_spec=node_spec,
        memory=memory,
        input_data={},
        llm=llm,
        available_tools=[],
        stream_id="queen",  # ask_user requires stream_id="queen" for free-text input
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHeadlessInputFix:
    @pytest.mark.asyncio
    async def test_deadlock_without_handler(self, runtime, memory, client_spec):
        """Regression: without a CLIENT_INPUT_REQUESTED handler the node blocks forever.

        This reproduces the pre-fix behaviour. asyncio.wait_for() with a short
        timeout stands in for the real-world symptom of an infinite hang.
        """
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("ask_user", {"question": "What file should I analyse?"}),
            ]
        )
        bus = EventBus()
        # No handler subscribed — nothing will ever call inject_event()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=3))
        ctx = build_ctx(runtime, client_spec, memory, llm)

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(node.execute(ctx), timeout=0.5)

    @pytest.mark.asyncio
    async def test_node_unblocks_when_handler_injects(self, runtime, memory, client_spec):
        """Fix: with the runner's CLIENT_INPUT_REQUESTED handler registered, the
        node receives stdin input and completes normally.
        """
        client_spec.output_keys = ["answer"]
        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: node asks the user for input
                tool_call_scenario(
                    "ask_user",
                    {"question": "What file should I analyse?"},
                    tool_use_id="ask_1",
                ),
                # Turn 2: after input received, set the output
                tool_call_scenario(
                    "set_output",
                    {"key": "answer", "value": "analysis complete"},
                    tool_use_id="set_1",
                ),
                # Turn 3: finish
                text_scenario("Done."),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))

        # Simulate what runner._handle_input_requested does after the fix:
        # subscribe unconditionally (no isatty() guard) and inject with is_client_input=True
        async def handler(event):
            await node.inject_event("/tmp/test_data.csv", is_client_input=True)

        bus.subscribe(event_types=[EventType.CLIENT_INPUT_REQUESTED], handler=handler)

        ctx = build_ctx(runtime, client_spec, memory, llm)
        result = await asyncio.wait_for(node.execute(ctx), timeout=5.0)

        assert result.success is True
        assert result.output.get("answer") == "analysis complete"

    @pytest.mark.asyncio
    async def test_injected_input_is_client_input_not_external_event(
        self, runtime, memory, client_spec
    ):
        """Fix: is_client_input=True means the LLM sees the raw user message,
        not one prefixed with '[External event]:'.

        Before the fix, inject_input() defaulted to is_client_input=False which
        caused _drain_injection_queue to prepend '[External event]: ' — confusing
        the LLM into treating the user's stdin response as a system notification.
        """
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("ask_user", {"question": "Say hi"}, tool_use_id="ask_1"),
                text_scenario("Hi back!"),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))

        async def handler(event):
            await node.inject_event("hello from user", is_client_input=True)

        bus.subscribe(event_types=[EventType.CLIENT_INPUT_REQUESTED], handler=handler)

        ctx = build_ctx(runtime, client_spec, memory, llm)
        await asyncio.wait_for(node.execute(ctx), timeout=5.0)

        # Inspect the messages the LLM received on the turn after the user responded.
        # The user's message should be plain text, not wrapped with [External event]: prefix.
        all_user_contents = [
            str(m["content"])
            for call in llm.stream_calls
            for m in call["messages"]
            if m.get("role") == "user"
        ]
        assert any("hello from user" in c for c in all_user_contents), (
            "User's stdin input was never delivered to the LLM"
        )
        assert not any("[External event]" in c for c in all_user_contents), (
            "User's stdin input was incorrectly prefixed with '[External event]:' "
            "(is_client_input was False)"
        )

    @pytest.mark.asyncio
    async def test_eof_stdin_signals_clean_shutdown(self, runtime, memory, client_spec):
        """Fix: when stdin hits EOF in non-TTY mode, the node should exit cleanly
        (success=False) rather than looping on empty strings up to max_iterations.

        Simulates what runner._handle_input_requested does on EOFError:
        calls node.signal_shutdown() instead of injecting "".
        """
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("ask_user", {"question": "What file?"}),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=50))

        async def eof_handler(event):
            # Simulates runtime.signal_node_shutdown(node_id) on EOFError
            node.signal_shutdown()
            await asyncio.sleep(0)  # yield to event loop; required by EventHandler protocol

        bus.subscribe(event_types=[EventType.CLIENT_INPUT_REQUESTED], handler=eof_handler)

        ctx = build_ctx(runtime, client_spec, memory, llm)
        result = await asyncio.wait_for(node.execute(ctx), timeout=2.0)

        # Clean shutdown returns success=True (no error), but with empty output
        # because no set_output() was ever called before EOF.
        assert result.error is None
        assert result.output == {}
        # LLM called only once — no degraded loop of empty-string injections
        assert len(llm.stream_calls) == 1, (
            f"Expected 1 LLM call (clean exit), got {len(llm.stream_calls)} "
            "(EOF triggered a degraded loop)"
        )


class TestRunnerHandlerRegistration:
    """Runner-level tests: verify _run_with_agent_runtime registers the
    CLIENT_INPUT_REQUESTED handler regardless of sys.stdin.isatty().

    These tests prove the isatty() guard removal in runner.py:1584 actually
    wires up the handler — closing the gap the EventLoopNode-level tests leave.
    """

    def _make_runner(self, client_facing: bool) -> AgentRunner:
        """Build a minimal AgentRunner without triggering __init__."""
        node = NodeSpec(
            id="intake",
            name="Intake",
            description="intake node",
            node_type="event_loop",
            output_keys=[],
            client_facing=client_facing,
        )
        graph = GraphSpec(
            id="test-graph",
            goal_id="test-goal",
            name="Test Graph",
            entry_node="intake",
            nodes=[node],
            edges=[],
            terminal_nodes=["intake"],
        )
        runner = AgentRunner.__new__(AgentRunner)
        runner.graph = graph
        # __new__ skips __init__; stub out attributes touched by __del__ / cleanup
        runner._tool_registry = MagicMock()
        runner._temp_dir = None
        return runner

    def _make_mock_runtime(self) -> MagicMock:
        """Build a mock AgentRuntime that satisfies _run_with_agent_runtime."""
        runtime = MagicMock()
        runtime.is_running = True
        runtime.subscribe_to_events = MagicMock(side_effect=["sub-output", "sub-input"])
        runtime.get_entry_points = MagicMock(return_value=[])
        runtime.trigger_and_wait = AsyncMock(
            return_value=ExecutionResult(success=True, output={})
        )
        runtime.unsubscribe_from_events = MagicMock()
        return runtime

    @pytest.mark.asyncio
    async def test_handler_registered_in_non_tty(self):
        """With isatty()=False (CI/pipe/WSL2), CLIENT_INPUT_REQUESTED handler
        must still be registered — this is the core of the bug fix."""
        runner = self._make_runner(client_facing=True)
        mock_runtime = self._make_mock_runtime()
        runner._agent_runtime = mock_runtime

        fake_stdin = io.StringIO("some piped input\n")
        with patch("sys.stdin", fake_stdin):
            await runner._run_with_agent_runtime({})

        subscribed_event_types = [
            c.kwargs.get("event_types") or c.args[0]
            for c in mock_runtime.subscribe_to_events.call_args_list
        ]
        assert any(
            EventType.CLIENT_INPUT_REQUESTED in et for et in subscribed_event_types
        ), "CLIENT_INPUT_REQUESTED handler was not registered in non-TTY mode"

    @pytest.mark.asyncio
    async def test_handler_registered_in_tty(self):
        """With isatty()=True (normal terminal), handler is also registered —
        the fix must not break the interactive (TTY) path."""
        runner = self._make_runner(client_facing=True)
        mock_runtime = self._make_mock_runtime()
        runner._agent_runtime = mock_runtime

        fake_tty = MagicMock()
        fake_tty.isatty = MagicMock(return_value=True)
        with patch("sys.stdin", fake_tty):
            await runner._run_with_agent_runtime({})

        subscribed_event_types = [
            c.kwargs.get("event_types") or c.args[0]
            for c in mock_runtime.subscribe_to_events.call_args_list
        ]
        assert any(
            EventType.CLIENT_INPUT_REQUESTED in et for et in subscribed_event_types
        ), "CLIENT_INPUT_REQUESTED handler was not registered in TTY mode"

    @pytest.mark.asyncio
    async def test_handler_not_registered_when_no_client_facing_nodes(self):
        """When no nodes are client_facing, no I/O handlers should be registered —
        the has_client_facing guard must remain intact."""
        runner = self._make_runner(client_facing=False)
        mock_runtime = self._make_mock_runtime()
        runner._agent_runtime = mock_runtime

        fake_stdin = io.StringIO("")
        with patch("sys.stdin", fake_stdin):
            await runner._run_with_agent_runtime({})

        assert mock_runtime.subscribe_to_events.call_count == 0, (
            "subscribe_to_events should not be called when no client-facing nodes exist"
        )


class TestInjectionPathRouting:
    """Prove that ExecutionStream.inject_input correctly routes to node.inject_event.

    This closes the gap between the runner-level tests (which only verify that
    subscribe_to_events is called) and the node-level tests (which call
    node.inject_event directly).  Here we test the actual routing code in
    execution_stream.py:421-425.
    """

    @pytest.mark.asyncio
    async def test_execution_stream_inject_routes_to_node(self):
        """ExecutionStream.inject_input finds the node in _active_executors and
        calls inject_event, setting _input_ready so _await_user_input unblocks."""
        from framework.runtime.execution_stream import ExecutionStream

        node = EventLoopNode(config=LoopConfig(max_iterations=3))

        # Build a minimal executor stub — only node_registry is needed
        mock_executor = MagicMock()
        mock_executor.node_registry = {"intake": node}

        # Instantiate ExecutionStream without __init__ (heavy dependencies)
        # and wire only what inject_input touches
        stream = ExecutionStream.__new__(ExecutionStream)
        stream._active_executors = {"exec_1": mock_executor}

        result = await stream.inject_input("intake", "hello from stdin", is_client_input=True)

        assert result is True, "inject_input should return True when node is found"
        assert not node._injection_queue.empty(), "content should be in node's injection queue"
        content, is_client = node._injection_queue.get_nowait()
        assert content == "hello from stdin"
        assert is_client is True, "is_client_input flag must be preserved through the routing chain"

    @pytest.mark.asyncio
    async def test_execution_stream_inject_returns_false_for_unknown_node(self):
        """inject_input returns False (not silently deadlocking) when the node_id
        is not found — e.g. if the executor hasn't registered the node yet."""
        from framework.runtime.execution_stream import ExecutionStream

        stream = ExecutionStream.__new__(ExecutionStream)
        stream._active_executors = {}  # no executors registered

        result = await stream.inject_input("unknown_node", "hello")

        assert result is False


class TestRateLimitRetryCap:
    """Prove that the streaming retry loop stops after RATE_LIMIT_MAX_RETRY_WALL_TIME.

    Before the fix: 10 retries × up to 120 s each = ~20 min per LLM call.
    After the fix: total retry time is capped at RATE_LIMIT_MAX_RETRY_WALL_TIME.
    """

    @pytest.mark.asyncio
    async def test_retry_budget_stops_retries_after_wall_time_exceeded(self):
        """With a tiny wall-time budget, the loop stops after the first retry
        even though RATE_LIMIT_MAX_RETRIES has not been exhausted."""
        from litellm.exceptions import RateLimitError
        import framework.llm.litellm as litellm_module
        from framework.llm.litellm import LiteLLMProvider

        provider = LiteLLMProvider(model="mock-model")

        call_count = 0

        async def fake_acompletion(**_kwargs):
            nonlocal call_count
            call_count += 1
            raise RateLimitError("rate limited", llm_provider="mock", model="mock-model")

        # Patch: tiny budget + zero backoff so the second attempt immediately
        # exceeds the wall-time budget without sleeping 2 s in the test.
        with (
            patch.object(litellm_module, "RATE_LIMIT_MAX_RETRY_WALL_TIME", 0.01),
            patch.object(litellm_module, "RATE_LIMIT_BACKOFF_BASE", 0),
            patch("litellm.acompletion", fake_acompletion),
        ):
            events = []
            async for event in provider.stream(messages=[{"role": "user", "content": "hi"}]):
                events.append(event)

        from framework.llm.stream_events import StreamErrorEvent

        # Budget check fires after the sleep on attempt 0, so attempt 1 is the
        # one that sees elapsed > budget and stops — 2 total LLM calls.
        assert call_count == 2, (
            f"Expected 2 LLM calls (initial + 1 retry before budget cut-off), got {call_count}"
        )
        assert len(events) == 1 and isinstance(events[0], StreamErrorEvent), (
            "Should yield a StreamErrorEvent when budget is exhausted"
        )

    @pytest.mark.asyncio
    async def test_retry_proceeds_within_budget(self):
        """Within the budget, retries still happen normally."""
        from litellm.exceptions import RateLimitError
        import framework.llm.litellm as litellm_module
        from framework.llm.litellm import LiteLLMProvider
        from framework.llm.stream_events import StreamErrorEvent

        provider = LiteLLMProvider(model="mock-model")

        call_count = 0

        async def fake_acompletion(**_kwargs):
            nonlocal call_count
            call_count += 1
            raise RateLimitError("rate limited", llm_provider="mock", model="mock-model")

        # Large budget (1000 s) but only 2 max retries → stops after 3 calls
        with (
            patch.object(litellm_module, "RATE_LIMIT_MAX_RETRIES", 2),
            patch.object(litellm_module, "RATE_LIMIT_MAX_RETRY_WALL_TIME", 1000),
            patch.object(litellm_module, "RATE_LIMIT_BACKOFF_BASE", 0),  # no sleep
            patch("litellm.acompletion", fake_acompletion),
        ):
            events = []
            async for event in provider.stream(messages=[{"role": "user", "content": "hi"}]):
                events.append(event)

        assert call_count == 3, (
            f"Expected 3 calls (initial + 2 retries), got {call_count}"
        )
        assert isinstance(events[0], StreamErrorEvent)
