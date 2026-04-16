"""WP-8: Tests for EventLoopNode, OutputAccumulator, LoopConfig, JudgeProtocol.

Uses real FileConversationStore (no mocks for storage) and a MockStreamingLLM
that yields pre-programmed StreamEvents to control the loop deterministically.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.agent_loop.agent_loop import AgentLoop as EventLoopNode, OutputAccumulator
from framework.agent_loop.conversation import NodeConversation
from framework.agent_loop.internals.types import JudgeProtocol, JudgeVerdict, LoopConfig
from framework.host.event_bus import EventBus, EventType
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.orchestrator.node import DataBuffer, NodeContext, NodeSpec
from framework.storage.conversation_store import FileConversationStore
from framework.tracker.decision_tracker import DecisionTracker as Runtime

# ---------------------------------------------------------------------------
# Mock LLM that yields pre-programmed stream events
# ---------------------------------------------------------------------------


class MockStreamingLLM(LLMProvider):
    """Mock LLM that yields pre-programmed StreamEvent sequences.

    Each call to stream() consumes the next scenario from the list.
    Cycles back to the beginning if more calls are made than scenarios.
    """

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
        return LLMResponse(content="Summary of conversation.", model="mock", stop_reason="stop")


# ---------------------------------------------------------------------------
# Helper: build a simple text-only scenario
# ---------------------------------------------------------------------------


def text_scenario(text: str, input_tokens: int = 10, output_tokens: int = 5) -> list:
    """Build a stream scenario that produces text and finishes."""
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=input_tokens, output_tokens=output_tokens, model="mock"),
    ]


def tool_call_scenario(
    tool_name: str,
    tool_input: dict,
    tool_use_id: str = "call_1",
    text: str = "",
) -> list:
    """Build a stream scenario that produces a tool call."""
    events = []
    if text:
        events.append(TextDeltaEvent(content=text, snapshot=text))
    events.append(ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input))
    events.append(FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"))
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime():
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="session_20250101_000000_eventlp01")
    rt.decide = MagicMock(return_value="dec_1")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.set_node = MagicMock()
    return rt


@pytest.fixture
def node_spec():
    return NodeSpec(
        id="test_loop",
        name="Test Loop",
        description="A test event loop node",
        node_type="event_loop",
        output_keys=["result"],
        system_prompt="You are a test assistant.",
    )


@pytest.fixture
def buffer():
    return DataBuffer()


def build_ctx(
    runtime,
    node_spec,
    buffer,
    llm,
    tools=None,
    input_data=None,
    goal_context="",
    stream_id=None,
    is_subagent_mode=False,
):
    """Build a NodeContext for testing.

    When AgentLoop is constructed with event_bus, a non-queen/non-judge node
    is treated as a worker and auto-escalates to queen on text-only turns.
    Standalone tests with event_bus but no queen pass ``is_subagent_mode=True``
    to opt out -- this is mapped to ``stream_id="judge"`` which the AgentLoop
    treats as escalation-exempt.
    """
    if is_subagent_mode:
        # The new opt-out mechanism: stream_id="judge" bypasses worker
        # auto-escalation. The legacy ``is_subagent_mode`` field is gone.
        stream_id = "judge"
    return NodeContext(
        runtime=runtime,
        node_id=node_spec.id,
        node_spec=node_spec,
        buffer=buffer,
        input_data=input_data or {},
        llm=llm,
        available_tools=tools or [],
        goal_context=goal_context,
        stream_id=stream_id or "",
    )


# ===========================================================================
# AgentLoop public surface
# ===========================================================================
# AgentLoop is no longer a NodeProtocol subclass -- it is a standalone
# event loop. Tests just verify the public API surface still exists.


class TestAgentLoopSurface:
    def test_has_execute_method(self):
        node = EventLoopNode()
        assert hasattr(node, "execute")
        assert asyncio.iscoroutinefunction(node.execute)

    def test_has_validate_input(self):
        node = EventLoopNode()
        assert hasattr(node, "validate_input")


# ===========================================================================
# Basic loop execution
# ===========================================================================


class TestBasicLoop:
    @pytest.mark.asyncio
    async def test_basic_text_only_implicit_accept(self, runtime, node_spec, buffer):
        """No tools, no judge. LLM produces text, implicit accept on stop."""
        # Override to no output_keys so implicit judge accepts immediately
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Hello world")])
        ctx = build_ctx(runtime, node_spec, buffer, llm)

        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert result.tokens_used > 0

    @pytest.mark.asyncio
    async def test_no_llm_returns_failure(self, runtime, node_spec, buffer):
        """ctx.llm=None should return failure immediately."""
        ctx = build_ctx(runtime, node_spec, buffer, llm=None)

        node = EventLoopNode()
        result = await node.execute(ctx)

        assert result.success is False
        assert "LLM" in result.error

    @pytest.mark.asyncio
    async def test_max_iterations_failure(self, runtime, node_spec, buffer):
        """When max_iterations is reached without acceptance, should fail."""
        # LLM always produces text but never calls set_output, so implicit
        # judge retries asking for missing keys
        llm = MockStreamingLLM(scenarios=[text_scenario("thinking...")])
        ctx = build_ctx(runtime, node_spec, buffer, llm)

        node = EventLoopNode(config=LoopConfig(max_iterations=2))
        result = await node.execute(ctx)

        assert result.success is False
        assert "Max iterations" in result.error


# ===========================================================================
# Judge integration
# ===========================================================================


class TestJudgeIntegration:
    @pytest.mark.asyncio
    async def test_judge_accept(self, runtime, node_spec, buffer):
        """Mock judge ACCEPT -> success."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Done!")])

        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(return_value=JudgeVerdict(action="ACCEPT"))

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        judge.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_judge_escalate(self, runtime, node_spec, buffer):
        """Mock judge ESCALATE -> failure."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Attempt")])

        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(return_value=JudgeVerdict(action="ESCALATE", feedback="Tone violation"))

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is False
        assert "escalated" in result.error.lower()
        assert "Tone violation" in result.error

    @pytest.mark.asyncio
    async def test_judge_retry_then_accept(self, runtime, node_spec, buffer):
        """RETRY twice, then ACCEPT. Should run 3 iterations."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(
            scenarios=[
                text_scenario("attempt 1"),
                text_scenario("attempt 2"),
                text_scenario("attempt 3"),
            ]
        )

        call_count = 0

        async def evaluate_fn(context):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return JudgeVerdict(action="RETRY", feedback="Try harder")
            return JudgeVerdict(action="ACCEPT")

        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(side_effect=evaluate_fn)

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=10))
        result = await node.execute(ctx)

        assert result.success is True
        assert call_count == 3


# ===========================================================================
# set_output tool
# ===========================================================================


class TestStallDetection:
    @pytest.mark.asyncio
    async def test_stall_detection(self, runtime, node_spec, buffer):
        """3 identical responses should trigger stall detection."""
        node_spec.output_keys = []  # so implicit judge would accept
        # But we need the judge to RETRY so we actually get 3 identical responses
        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(return_value=JudgeVerdict(action="RETRY"))

        llm = MockStreamingLLM(scenarios=[text_scenario("same answer")])

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            judge=judge,
            config=LoopConfig(max_iterations=10, stall_detection_threshold=3),
        )
        result = await node.execute(ctx)

        assert result.success is False
        assert "stalled" in result.error.lower()


# ===========================================================================
# EventBus lifecycle events
# ===========================================================================


class TestEventBusLifecycle:
    @pytest.mark.asyncio
    async def test_lifecycle_events_published(self, runtime, node_spec, buffer):
        """NODE_LOOP_STARTED, NODE_LOOP_ITERATION, NODE_LOOP_COMPLETED should be published."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("ok")])
        bus = EventBus()

        received_events = []
        bus.subscribe(
            event_types=[
                EventType.NODE_LOOP_STARTED,
                EventType.NODE_LOOP_ITERATION,
                EventType.NODE_LOOP_COMPLETED,
            ],
            handler=lambda e: received_events.append(e.type),
        )

        # Subagent mode opts out of worker auto-escalation (no queen in tests).
        ctx = build_ctx(runtime, node_spec, buffer, llm, is_subagent_mode=True)
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert EventType.NODE_LOOP_STARTED in received_events
        assert EventType.NODE_LOOP_ITERATION in received_events
        assert EventType.NODE_LOOP_COMPLETED in received_events

    @pytest.mark.skip(reason="Hangs in non-interactive shells (client-facing blocks on stdin)")
    async def test_queen_stream_uses_client_output_delta(self, runtime, buffer):
        """Queen streams should emit CLIENT_OUTPUT_DELTA instead of LLM_TEXT_DELTA."""
        spec = NodeSpec(
            id="ui_node",
            name="UI Node",
            description="Streams to user",
            node_type="event_loop",
            output_keys=[],
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("visible to user")])
        bus = EventBus()

        received_types = []
        bus.subscribe(
            event_types=[EventType.CLIENT_OUTPUT_DELTA, EventType.LLM_TEXT_DELTA],
            handler=lambda e: received_types.append(e.type),
        )

        ctx = build_ctx(runtime, spec, buffer, llm, stream_id="queen")
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))

        # Text-only on client_facing no longer blocks (no ask_user), so
        # the node completes without needing shutdown.
        await node.execute(ctx)

        assert EventType.CLIENT_OUTPUT_DELTA in received_types
        assert EventType.LLM_TEXT_DELTA not in received_types


# ===========================================================================
# Client-facing blocking
# ===========================================================================


class TestQueenInteractionBlocking:
    """Tests for queen-native input blocking in EventLoopNode."""

    @pytest.fixture
    def client_spec(self):
        return NodeSpec(
            id="chat",
            name="Chat",
            description="chat node",
            node_type="event_loop",
            output_keys=[],
        )

    @pytest.mark.skip(reason="Hangs in non-interactive shells (client-facing blocks on stdin)")
    async def test_text_only_no_blocking(self, runtime, buffer, client_spec):
        """client_facing + text-only (no ask_user) should NOT block."""
        llm = MockStreamingLLM(
            scenarios=[
                text_scenario("Hello! Here is your status update."),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, client_spec, buffer, llm, stream_id="queen")

        # Should complete without blocking — no ask_user called, no output_keys required
        result = await node.execute(ctx)

        assert result.success is True
        assert llm._call_index >= 1

    @pytest.mark.asyncio
    async def test_non_client_facing_unchanged(self, runtime, buffer):
        """client_facing=False should not block — existing behavior."""
        spec = NodeSpec(
            id="internal",
            name="Internal",
            description="internal node",
            node_type="event_loop",
            output_keys=[],
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("thinking...")])
        node = EventLoopNode(config=LoopConfig(max_iterations=2))
        ctx = build_ctx(runtime, spec, buffer, llm)

        # Should complete without blocking (implicit judge ACCEPTs on no tools + no keys)
        result = await node.execute(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_signal_shutdown_unblocks(self, runtime, buffer, client_spec):
        """signal_shutdown should unblock a waiting client_facing node."""
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario(
                    "ask_user",
                    {"question": "Waiting...", "options": ["Continue", "Stop"]},
                    tool_use_id="ask_1",
                ),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=10))
        ctx = build_ctx(runtime, client_spec, buffer, llm, stream_id="queen")

        async def shutdown_after_delay():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown_after_delay())
        result = await node.execute(ctx)
        await task

        assert result.success is True

    @pytest.mark.asyncio
    async def test_client_input_requested_event_published(self, runtime, buffer, client_spec):
        """CLIENT_INPUT_REQUESTED should be published when ask_user blocks."""
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario(
                    "ask_user",
                    {"question": "Hello!", "options": ["Yes", "No"]},
                    tool_use_id="ask_1",
                ),
            ]
        )
        bus = EventBus()
        received = []

        async def capture(e):
            received.append(e)

        bus.subscribe(
            event_types=[EventType.CLIENT_INPUT_REQUESTED],
            handler=capture,
        )

        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, client_spec, buffer, llm, stream_id="queen")

        async def shutdown():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown())
        await node.execute(ctx)
        await task

        assert len(received) >= 1
        assert received[0].type == EventType.CLIENT_INPUT_REQUESTED

    @pytest.mark.skip(reason="Hangs in non-interactive shells (client-facing blocks on stdin)")
    async def test_queen_ask_user_with_real_tools(self, runtime, buffer):
        """ask_user alongside real tool calls still triggers blocking."""
        spec = NodeSpec(
            id="chat",
            name="Chat",
            description="chat node",
            node_type="event_loop",
            output_keys=[],
        )
        # LLM calls a real tool AND ask_user in the same turn
        llm = MockStreamingLLM(
            scenarios=[
                [
                    ToolCallEvent(tool_use_id="tool_1", tool_name="search", tool_input={"q": "test"}),
                    ToolCallEvent(tool_use_id="ask_1", tool_name="ask_user", tool_input={}),
                    FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
                ],
                text_scenario("Done"),
            ]
        )

        def my_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(tool_use_id=tool_use.id, content="result", is_error=False)

        node = EventLoopNode(
            tool_executor=my_executor,
            config=LoopConfig(max_iterations=5),
        )
        ctx = build_ctx(
            runtime,
            spec,
            buffer,
            llm,
            tools=[Tool(name="search", description="", parameters={})],
            stream_id="queen",
        )

        async def unblock():
            await asyncio.sleep(0.05)
            await node.inject_event("user input")

        task = asyncio.create_task(unblock())
        result = await node.execute(ctx)
        await task

        assert result.success is True
        assert llm._call_index >= 2

    @pytest.mark.asyncio
    async def test_ask_user_not_available_for_workers_even_with_legacy_client_facing(self, runtime, buffer):
        """Workers should not receive ask_user even if legacy client_facing=True is set."""
        spec = NodeSpec(
            id="internal",
            name="Internal",
            description="internal node",
            node_type="event_loop",
            output_keys=[],
            client_facing=True,
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("thinking...")])
        node = EventLoopNode(config=LoopConfig(max_iterations=2))
        ctx = build_ctx(runtime, spec, buffer, llm, stream_id="worker")

        await node.execute(ctx)

        # Verify ask_user was NOT in the tools passed to the LLM
        assert llm._call_index >= 1
        for call in llm.stream_calls:
            tool_names = [t.name for t in (call["tools"] or [])]
            assert "ask_user" not in tool_names
            assert "ask_user_multiple" not in tool_names
            assert "escalate" in tool_names

    @pytest.mark.asyncio
    async def test_escalate_available_for_worker_stream(self, runtime, buffer):
        """Workers should receive escalate synthetic tool."""
        spec = NodeSpec(
            id="internal",
            name="Internal",
            description="internal node",
            node_type="event_loop",
            output_keys=[],
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("thinking...")])
        node = EventLoopNode(config=LoopConfig(max_iterations=2))
        ctx = build_ctx(runtime, spec, buffer, llm, stream_id="worker")

        await node.execute(ctx)

        assert llm._call_index >= 1
        tool_names = [t.name for t in (llm.stream_calls[0]["tools"] or [])]
        assert "escalate" in tool_names

    @pytest.mark.asyncio
    async def test_escalate_not_available_for_queen_stream(self, runtime, buffer):
        """Queen stream should not receive escalate tool."""
        spec = NodeSpec(
            id="queen",
            name="Queen",
            description="queen node",
            node_type="event_loop",
            output_keys=[],
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("monitoring...")])
        node = EventLoopNode(config=LoopConfig(max_iterations=2))
        ctx = build_ctx(runtime, spec, buffer, llm, stream_id="queen")

        async def shutdown_after_turn():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown_after_turn())
        await node.execute(ctx)
        await task

        assert llm._call_index >= 1
        tool_names = [t.name for t in (llm.stream_calls[0]["tools"] or [])]
        assert "escalate" not in tool_names


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_tool_execution_feedback(self, runtime, node_spec, buffer):
        """Tool call -> result fed back to conversation via stream loop."""
        node_spec.output_keys = []

        def my_tool_executor(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content=f"Result for {tool_use.name}",
                is_error=False,
            )

        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: call a tool
                tool_call_scenario("search", {"query": "test"}, tool_use_id="call_search"),
                # Turn 2: text response after seeing tool result
                text_scenario("Found the answer"),
            ]
        )

        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=[Tool(name="search", description="Search", parameters={})],
        )
        node = EventLoopNode(
            tool_executor=my_tool_executor,
            config=LoopConfig(max_iterations=5),
        )
        result = await node.execute(ctx)

        assert result.success is True
        # stream() should have been called twice (tool call turn + final text turn)
        assert llm._call_index >= 2


# ===========================================================================
# Write-through persistence with real FileConversationStore
# ===========================================================================


class TestWriteThroughPersistence:
    @pytest.mark.asyncio
    async def test_messages_written_to_store(self, tmp_path, runtime, node_spec, buffer):
        """Messages should be persisted immediately via write-through."""
        store = FileConversationStore(tmp_path / "conv")
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Hello")])

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            conversation_store=store,
            config=LoopConfig(max_iterations=5),
        )
        result = await node.execute(ctx)

        assert result.success is True

        # Verify parts were written to disk
        parts = await store.read_parts()
        assert len(parts) >= 2  # at least initial user msg + assistant msg


class TestCrashRecovery:
    @pytest.mark.asyncio
    async def test_restore_from_checkpoint(self, tmp_path, runtime, node_spec, buffer):
        """Populate a store with state, then verify EventLoopNode restores from it."""
        store = FileConversationStore(tmp_path / "conv")

        # Simulate a previous run that wrote conversation + cursor
        conv = NodeConversation(
            system_prompt="You are a test assistant.",
            output_keys=["result"],
            store=store,
        )
        # Tag messages with phase_id matching the node so restore() finds them.
        # Restore filters parts by phase_id=ctx.node_id in non-continuous mode.
        conv.set_current_phase(node_spec.id)
        await conv.add_user_message("Initial input")
        await conv.add_assistant_message("Working on it...")

        # Write cursor with iteration and outputs
        await store.write_cursor(
            {
                "iteration": 1,
                "next_seq": conv.next_seq,
                "outputs": {"result": "partial_value"},
            }
        )

        # Now create a new EventLoopNode and execute -- it should restore
        node_spec.output_keys = []  # no required keys so implicit accept works
        llm = MockStreamingLLM(scenarios=[text_scenario("Continuing...")])

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            conversation_store=store,
            config=LoopConfig(max_iterations=5),
        )
        result = await node.execute(ctx)

        assert result.success is True
        # Should have the restored output
        assert result.output.get("result") == "partial_value"

    @pytest.mark.asyncio
    async def test_restore_reblocks_pending_user_input_instead_of_continuing(self, tmp_path, runtime, buffer):
        """A restored queen wait should re-emit the question, not self-continue."""
        store = FileConversationStore(tmp_path / "conv")
        conv = NodeConversation(
            system_prompt="You are a test assistant.",
            output_keys=[],
            store=store,
        )
        conv.set_current_phase("queen")
        await conv.add_user_message("Session started.")
        await conv.add_assistant_message(
            "",
            tool_calls=[
                {
                    "id": "ask_1",
                    "type": "function",
                    "function": {
                        "name": "ask_user",
                        "arguments": '{"question":"What city?","options":["Seattle","Chicago"]}',
                    },
                }
            ],
        )
        await conv.add_tool_result("ask_1", "Waiting for user input...")
        await conv.add_assistant_message("What city should I target?")
        await store.write_cursor(
            {
                "iteration": 4,
                "next_seq": conv.next_seq,
                "pending_input": {
                    "prompt": "What city?",
                    "options": ["Seattle", "Chicago"],
                    "questions": None,
                    "emit_client_request": True,
                },
            }
        )

        spec = NodeSpec(
            id="queen",
            name="Queen",
            description="interactive queen",
            node_type="event_loop",
            output_keys=[],
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("This should not run.")])
        bus = EventBus()
        input_events = []

        async def capture(event):
            input_events.append(event)

        bus.subscribe(event_types=[EventType.CLIENT_INPUT_REQUESTED], handler=capture)

        node = EventLoopNode(
            event_bus=bus,
            conversation_store=store,
            config=LoopConfig(max_iterations=10),
        )
        ctx = build_ctx(runtime, spec, buffer, llm, stream_id="queen")

        async def shutdown_after_prompt():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown_after_prompt())
        result = await node.execute(ctx)
        await task

        assert result.success is True
        assert llm._call_index == 0
        assert len(input_events) == 1
        assert input_events[0].data["prompt"] == "What city?"

    @pytest.mark.asyncio
    @pytest.mark.skip(
        reason=(
            "Restore path for legacy unphased stores is not writing "
            "messages into the LLM call — separate pre-existing bug. "
            "The queen's forever-alive semantics (skip_judge=True) are "
            "tested via test_session_manager_worker_handoff and the "
            "live manual flow. Unskip once the legacy restore is fixed."
        )
    )
    async def test_restore_legacy_unphased_assistant_message_preserves_store(self, tmp_path, runtime, buffer):
        """Legacy queen stores without phase_id should resume instead of being cleared.

        The queen node uses skip_judge=True (forever-alive conversational
        semantics), so a text-only turn auto-blocks on user input. We
        pre-signal shutdown right after the LLM call so the loop exits
        cleanly while still verifying the restore path injected the
        stored messages into the conversation.
        """
        store = FileConversationStore(tmp_path / "conv")
        await store.write_meta(
            {
                "system_prompt": "You are a test assistant.",
                "max_context_tokens": 32000,
                "compaction_threshold": 0.8,
                "output_keys": [],
            }
        )
        await store.write_part(
            0,
            {
                "seq": 0,
                "role": "assistant",
                "content": "[Error: previous turn failed.]",
            },
        )
        await store.write_cursor({"iteration": 0, "next_seq": 1})

        spec = NodeSpec(
            id="queen",
            name="Queen",
            description="interactive queen",
            node_type="event_loop",
            output_keys=[],
            skip_judge=True,
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("Recovered after restore.")])
        node = EventLoopNode(
            conversation_store=store,
            config=LoopConfig(max_iterations=5),
        )
        ctx = build_ctx(runtime, spec, buffer, llm, stream_id="queen")

        # Pre-signal shutdown once the LLM call has landed so the
        # auto-block wait returns False and the loop exits cleanly
        # with success=True instead of hanging on _input_ready.
        import asyncio as _aio

        async def _shutdown_after_first_turn():
            for _ in range(50):
                await _aio.sleep(0.01)
                if llm.stream_calls:
                    break
            node.signal_shutdown()

        _sd_task = _aio.create_task(_shutdown_after_first_turn())
        try:
            result = await node.execute(ctx)
        finally:
            if not _sd_task.done():
                _sd_task.cancel()

        assert result.success is True
        assert len(llm.stream_calls) == 1
        assert [m["role"] for m in llm.stream_calls[0]["messages"]] == ["assistant", "user"]
        assert llm.stream_calls[0]["messages"][0]["content"] == "[Error: previous turn failed.]"
        assert llm.stream_calls[0]["messages"][1]["content"] == ("[Continue working on your current task.]")

        restored = await NodeConversation.restore(store, phase_id="queen")
        assert restored is not None
        assert [m.role for m in restored.messages] == ["assistant", "user", "assistant"]
        assert restored.messages[0].content == "[Error: previous turn failed.]"
        assert restored.messages[1].content == "[Continue working on your current task.]"
        assert restored.messages[2].content == "Recovered after restore."


# ===========================================================================
# External event injection
# ===========================================================================


class TestEventInjection:
    @pytest.mark.asyncio
    async def test_inject_event(self, runtime, node_spec, buffer):
        """inject_event() content should appear as user message in next iteration."""
        node_spec.output_keys = []

        judge_calls = []

        async def evaluate_fn(context):
            judge_calls.append(context)
            if len(judge_calls) >= 2:
                return JudgeVerdict(action="ACCEPT")
            return JudgeVerdict(action="RETRY")

        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(side_effect=evaluate_fn)

        llm = MockStreamingLLM(
            scenarios=[
                text_scenario("iteration 1"),
                text_scenario("iteration 2"),
            ]
        )

        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            judge=judge,
            config=LoopConfig(max_iterations=5),
        )

        # Pre-inject an event before execute runs
        await node.inject_event("Priority: CEO wants meeting rescheduled")

        result = await node.execute(ctx)
        assert result.success is True

        # Verify the injected content made it into the LLM messages
        all_messages = []
        for call in llm.stream_calls:
            all_messages.extend(call["messages"])
        injected_found = any("[External event]" in str(m.get("content", "")) for m in all_messages)
        assert injected_found


# ===========================================================================
# Pause/resume
# ===========================================================================


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_returns_early(self, runtime, node_spec, buffer):
        """pause_requested in input_data should trigger early return."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("should not run")])

        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            input_data={"pause_requested": True},
        )
        node = EventLoopNode(config=LoopConfig(max_iterations=10))
        result = await node.execute(ctx)

        # Should return success (paused, not failed)
        assert result.success is True
        # LLM should not have been called (paused before first turn)
        assert llm._call_index == 0


# ===========================================================================
# Stream errors
# ===========================================================================


class TestOutputAccumulator:
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        acc = OutputAccumulator()
        await acc.set("key1", "value1")
        assert acc.get("key1") == "value1"
        assert acc.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_to_dict(self):
        acc = OutputAccumulator()
        await acc.set("a", 1)
        await acc.set("b", 2)
        assert acc.to_dict() == {"a": 1, "b": 2}

    @pytest.mark.asyncio
    async def test_has_all_keys(self):
        acc = OutputAccumulator()
        assert acc.has_all_keys([]) is True
        assert acc.has_all_keys(["x"]) is False
        await acc.set("x", "val")
        assert acc.has_all_keys(["x"]) is True

    @pytest.mark.asyncio
    async def test_write_through_to_real_store(self, tmp_path):
        """OutputAccumulator should write through to FileConversationStore cursor."""
        store = FileConversationStore(tmp_path / "acc_test")
        acc = OutputAccumulator(store=store)

        await acc.set("result", "hello")

        cursor = await store.read_cursor()
        assert cursor["outputs"]["result"] == "hello"

    @pytest.mark.asyncio
    async def test_restore_from_real_store(self, tmp_path):
        """OutputAccumulator.restore() should rebuild from FileConversationStore."""
        store = FileConversationStore(tmp_path / "acc_restore")
        await store.write_cursor({"outputs": {"key1": "val1", "key2": "val2"}})

        acc = await OutputAccumulator.restore(store)
        assert acc.get("key1") == "val1"
        assert acc.get("key2") == "val2"
        assert acc.has_all_keys(["key1", "key2"]) is True

    @pytest.mark.asyncio
    async def test_flat_cursor_state(self, tmp_path):
        store = FileConversationStore(tmp_path / "acc_runs")
        acc_a = OutputAccumulator(store=store, run_id="run-a")
        acc_b = OutputAccumulator(store=store, run_id="run-b")

        await acc_a.set("result", "alpha")
        await acc_b.set("result", "beta")

        restored = await OutputAccumulator.restore(store)

        # Flat cursor: last write wins regardless of run_id
        assert restored.get("result") == "beta"


# ===========================================================================
# Transient error retry (ITEM 2)
# ===========================================================================


class ErrorThenSuccessLLM(LLMProvider):
    """LLM that raises on the first N calls, then succeeds.

    Used to test the retry-with-backoff wrapper around _run_single_turn().
    """

    def __init__(self, error: Exception, fail_count: int, success_scenario: list):
        self.error = error
        self.fail_count = fail_count
        self.success_scenario = success_scenario
        self._call_index = 0

    async def stream(self, messages, system="", tools=None, max_tokens=4096):
        call_num = self._call_index
        self._call_index += 1
        if call_num < self.fail_count:
            raise self.error
        for event in self.success_scenario:
            yield event

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="ok", model="mock", stop_reason="stop")


class TestTransientErrorRetry:
    """Test retry-with-backoff for transient LLM errors in EventLoopNode."""

    @pytest.mark.asyncio
    async def test_transient_error_retries_then_succeeds(self, runtime, node_spec, buffer):
        """A transient error on the first try should retry and succeed."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=ConnectionError("connection reset"),
            fail_count=1,
            success_scenario=text_scenario("success"),
        )
        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            config=LoopConfig(
                max_iterations=5,
                max_stream_retries=3,
                stream_retry_backoff_base=0.01,  # fast for tests
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        assert llm._call_index == 2  # 1 failure + 1 success

    @pytest.mark.asyncio
    async def test_permanent_error_no_retry(self, runtime, node_spec, buffer):
        """A permanent error (ValueError) should NOT be retried."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=ValueError("bad request: invalid model"),
            fail_count=1,
            success_scenario=text_scenario("success"),
        )
        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            config=LoopConfig(
                max_iterations=5,
                max_stream_retries=3,
                stream_retry_backoff_base=0.01,
            ),
        )
        with pytest.raises(ValueError, match="bad request"):
            await node.execute(ctx)
        assert llm._call_index == 1  # only tried once

    @pytest.mark.asyncio
    async def test_queen_non_transient_error_does_not_crash(self, runtime, node_spec, buffer):
        """Queen non-transient errors should wait for input, not crash on token vars."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=ValueError("bad request: blocked by policy"),
            fail_count=100,  # always fails
            success_scenario=text_scenario("unreachable"),
        )
        ctx = build_ctx(runtime, node_spec, buffer, llm, stream_id="queen")
        node = EventLoopNode(
            config=LoopConfig(
                max_iterations=1,
                max_stream_retries=0,
                stream_retry_backoff_base=0.01,
            ),
        )
        node._await_user_input = AsyncMock(return_value=None)

        result = await node.execute(ctx)

        assert result.success is False
        assert "Max iterations" in (result.error or "")
        node._await_user_input.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_transient_error_exhausts_retries(self, runtime, node_spec, buffer):
        """Transient errors that exhaust retries should raise."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=TimeoutError("request timed out"),
            fail_count=100,  # always fails
            success_scenario=text_scenario("unreachable"),
        )
        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            config=LoopConfig(
                max_iterations=5,
                max_stream_retries=2,
                stream_retry_backoff_base=0.01,
            ),
        )
        with pytest.raises(TimeoutError, match="request timed out"):
            await node.execute(ctx)
        assert llm._call_index == 3  # 1 initial + 2 retries

    @pytest.mark.asyncio
    async def test_stream_error_event_retried_as_runtime_error(self, runtime, node_spec, buffer):
        """StreamErrorEvent(recoverable=False) raises RuntimeError caught by retry."""
        node_spec.output_keys = []

        # Scenario: non-recoverable StreamErrorEvent with transient keywords
        error_scenario = [
            StreamErrorEvent(
                error="Stream error: 503 service unavailable",
                recoverable=False,
            )
        ]
        success_scenario = text_scenario("recovered")

        call_index = 0

        class StreamErrorThenSuccessLLM(LLMProvider):
            async def stream(self, messages, system="", tools=None, max_tokens=4096):
                nonlocal call_index
                idx = call_index
                call_index += 1
                if idx == 0:
                    for event in error_scenario:
                        yield event
                else:
                    for event in success_scenario:
                        yield event

            def complete(self, messages, system="", **kwargs):
                return LLMResponse(
                    content="ok",
                    model="mock",
                    stop_reason="stop",
                )

        llm = StreamErrorThenSuccessLLM()
        ctx = build_ctx(runtime, node_spec, buffer, llm)
        node = EventLoopNode(
            config=LoopConfig(
                max_iterations=5,
                max_stream_retries=3,
                stream_retry_backoff_base=0.01,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        assert call_index == 2

    @pytest.mark.asyncio
    async def test_retry_emits_event_bus_event(self, runtime, node_spec, buffer):
        """Retry should emit NODE_RETRY event on the event bus."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=ConnectionError("network down"),
            fail_count=1,
            success_scenario=text_scenario("ok"),
        )
        bus = EventBus()
        retry_events = []
        bus.subscribe(
            event_types=[EventType.NODE_RETRY],
            handler=lambda e: retry_events.append(e),
        )

        # is_subagent_mode=True opts out of worker auto-escalation.
        ctx = build_ctx(runtime, node_spec, buffer, llm, is_subagent_mode=True)
        node = EventLoopNode(
            event_bus=bus,
            config=LoopConfig(
                max_iterations=5,
                max_stream_retries=3,
                stream_retry_backoff_base=0.01,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        assert len(retry_events) == 1
        assert retry_events[0].data["retry_count"] == 1


class TestIsTransientError:
    """Unit tests for _is_transient_error() classification."""

    def test_timeout_error(self):
        assert EventLoopNode._is_transient_error(TimeoutError("timed out")) is True

    def test_connection_error(self):
        assert EventLoopNode._is_transient_error(ConnectionError("reset")) is True

    def test_os_error(self):
        assert EventLoopNode._is_transient_error(OSError("network unreachable")) is True

    def test_value_error_not_transient(self):
        assert EventLoopNode._is_transient_error(ValueError("bad input")) is False

    def test_type_error_not_transient(self):
        assert EventLoopNode._is_transient_error(TypeError("wrong type")) is False

    def test_runtime_error_with_transient_keywords(self):
        check = EventLoopNode._is_transient_error
        assert check(RuntimeError("Stream error: 429 rate limit")) is True
        assert check(RuntimeError("Stream error: 503")) is True
        assert check(RuntimeError("Stream error: connection reset")) is True
        assert check(RuntimeError("Stream error: timeout exceeded")) is True

    def test_runtime_error_without_transient_keywords(self):
        assert EventLoopNode._is_transient_error(RuntimeError("authentication failed")) is False
        assert EventLoopNode._is_transient_error(RuntimeError("invalid JSON in response")) is False


# ===========================================================================
# Tool doom loop detection (ITEM 1)
# ===========================================================================


class TestFingerprintToolCalls:
    """Unit tests for _fingerprint_tool_calls()."""

    def test_basic_fingerprint(self):
        results = [
            {"tool_name": "search", "tool_input": {"q": "hello"}},
        ]
        fps = EventLoopNode._fingerprint_tool_calls(results)
        assert len(fps) == 1
        assert fps[0][0] == "search"
        # Args should be JSON with sort_keys
        assert fps[0][1] == '{"q": "hello"}'

    def test_order_sensitive(self):
        r1 = [
            {"tool_name": "search", "tool_input": {"q": "a"}},
            {"tool_name": "fetch", "tool_input": {"url": "b"}},
        ]
        r2 = [
            {"tool_name": "fetch", "tool_input": {"url": "b"}},
            {"tool_name": "search", "tool_input": {"q": "a"}},
        ]
        assert EventLoopNode._fingerprint_tool_calls(r1) != (EventLoopNode._fingerprint_tool_calls(r2))

    def test_sort_keys_deterministic(self):
        r1 = [{"tool_name": "t", "tool_input": {"b": 2, "a": 1}}]
        r2 = [{"tool_name": "t", "tool_input": {"a": 1, "b": 2}}]
        assert EventLoopNode._fingerprint_tool_calls(r1) == EventLoopNode._fingerprint_tool_calls(r2)


class TestIsToolDoomLoop:
    """Unit tests for _is_tool_doom_loop()."""

    def test_below_threshold(self):
        node = EventLoopNode(config=LoopConfig(tool_doom_loop_threshold=3))
        fp = [("search", '{"q": "hello"}')]
        is_doom, _ = node._is_tool_doom_loop([fp, fp])
        assert is_doom is False

    def test_at_threshold_identical(self):
        node = EventLoopNode(config=LoopConfig(tool_doom_loop_threshold=3))
        fp = [("search", '{"q": "hello"}')]
        is_doom, desc = node._is_tool_doom_loop([fp, fp, fp])
        assert is_doom is True
        assert "search" in desc

    def test_different_args_no_doom(self):
        node = EventLoopNode(config=LoopConfig(tool_doom_loop_threshold=3))
        fp1 = [("search", '{"q": "deploy kubernetes cluster to production"}')]
        fp2 = [("read_file", '{"path": "/etc/nginx/nginx.conf"}')]
        fp3 = [("execute", '{"command": "SELECT * FROM users WHERE active=true"}')]
        is_doom, _ = node._is_tool_doom_loop([fp1, fp2, fp3])
        assert is_doom is False

    def test_disabled_via_config(self):
        node = EventLoopNode(
            config=LoopConfig(tool_doom_loop_enabled=False),
        )
        fp = [("search", '{"q": "hello"}')]
        is_doom, _ = node._is_tool_doom_loop([fp, fp, fp])
        assert is_doom is False

    def test_empty_fingerprints_no_doom(self):
        node = EventLoopNode(config=LoopConfig(tool_doom_loop_threshold=3))
        is_doom, _ = node._is_tool_doom_loop([[], [], []])
        assert is_doom is False


class ToolRepeatLLM(LLMProvider):
    """LLM that produces identical tool calls across outer iterations.

    Alternates: even calls → tool call, odd calls → text (exits inner loop).
    This ensures each outer iteration = 2 LLM calls with 1 tool executed.
    After tool_turns outer iterations, always returns text.
    """

    def __init__(
        self,
        tool_name: str,
        tool_input: dict,
        tool_turns: int,
        final_text: str = "done",
    ):
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.tool_turns = tool_turns
        self.final_text = final_text
        self._call_index = 0

    async def stream(self, messages, system="", tools=None, max_tokens=4096):
        idx = self._call_index
        self._call_index += 1
        # Which outer iteration we're in (2 calls per iteration)
        outer_iter = idx // 2
        is_tool_call = (idx % 2 == 0) and outer_iter < self.tool_turns
        if is_tool_call:
            yield ToolCallEvent(
                tool_use_id=f"call_{outer_iter}",
                tool_name=self.tool_name,
                tool_input=self.tool_input,
            )
            yield FinishEvent(
                stop_reason="tool_calls",
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )
        else:
            # Unique text per call to avoid stall detection
            text = f"{self.final_text} (call {idx})"
            yield TextDeltaEvent(content=text, snapshot=text)
            yield FinishEvent(
                stop_reason="stop",
                input_tokens=10,
                output_tokens=5,
                model="mock",
            )

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(
            content="ok",
            model="mock",
            stop_reason="stop",
        )


class TestToolDoomLoopIntegration:
    """Integration tests for doom loop detection in execute().

    Uses ToolRepeatLLM: returns tool calls for first N calls, then text.
    Each outer iteration = 2 LLM calls (tool call + text exit for inner loop).
    logged_tool_calls accumulates across inner iterations.
    """

    @pytest.mark.asyncio
    async def test_doom_loop_injects_warning(
        self,
        runtime,
        node_spec,
        buffer,
    ):
        """3 identical tool call turns should inject a warning."""
        node_spec.output_keys = []
        judge = AsyncMock(spec=JudgeProtocol)
        eval_count = 0

        async def judge_eval(*args, **kwargs):
            nonlocal eval_count
            eval_count += 1
            if eval_count >= 4:
                return JudgeVerdict(action="ACCEPT")
            return JudgeVerdict(action="RETRY")

        judge.evaluate = judge_eval

        # 3 tool calls (6 LLM calls: tool+text each), then 1 text
        llm = ToolRepeatLLM("search", {"q": "hello"}, tool_turns=3)

        def tool_exec(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="result",
                is_error=False,
            )

        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
                stall_similarity_threshold=1.0,  # disable fuzzy stall detection
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_doom_loop_emits_event(
        self,
        runtime,
        node_spec,
        buffer,
    ):
        """Doom loop should emit NODE_TOOL_DOOM_LOOP event."""
        node_spec.output_keys = []
        judge = AsyncMock(spec=JudgeProtocol)
        eval_count = 0

        async def judge_eval(*args, **kwargs):
            nonlocal eval_count
            eval_count += 1
            if eval_count >= 4:
                return JudgeVerdict(action="ACCEPT")
            return JudgeVerdict(action="RETRY")

        judge.evaluate = judge_eval

        llm = ToolRepeatLLM("search", {"q": "hello"}, tool_turns=3)
        bus = EventBus()
        doom_events: list = []
        bus.subscribe(
            event_types=[EventType.NODE_TOOL_DOOM_LOOP],
            handler=lambda e: doom_events.append(e),
        )

        def tool_exec(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="result",
                is_error=False,
            )

        # is_subagent_mode=True opts out of worker auto-escalation.
        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
            is_subagent_mode=True,
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            event_bus=bus,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
                stall_similarity_threshold=1.0,  # disable fuzzy stall detection
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        assert len(doom_events) == 1
        assert "search" in doom_events[0].data["description"]

    @pytest.mark.asyncio
    async def test_doom_loop_disabled(
        self,
        runtime,
        node_spec,
        buffer,
    ):
        """Disabled doom loop should not trigger with identical calls."""
        node_spec.output_keys = []
        judge = AsyncMock(spec=JudgeProtocol)
        eval_count = 0

        async def judge_eval(*args, **kwargs):
            nonlocal eval_count
            eval_count += 1
            if eval_count >= 4:
                return JudgeVerdict(action="ACCEPT")
            return JudgeVerdict(action="RETRY")

        judge.evaluate = judge_eval

        llm = ToolRepeatLLM("search", {"q": "hello"}, tool_turns=4)

        def tool_exec(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="result",
                is_error=False,
            )

        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_enabled=False,
                stall_similarity_threshold=1.0,  # disable fuzzy stall detection
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_different_args_no_doom_loop(
        self,
        runtime,
        node_spec,
        buffer,
    ):
        """Different tool args each turn should NOT trigger doom loop."""
        node_spec.output_keys = []
        judge = AsyncMock(spec=JudgeProtocol)
        eval_count = 0

        async def judge_eval(*args, **kwargs):
            nonlocal eval_count
            eval_count += 1
            if eval_count >= 4:
                return JudgeVerdict(action="ACCEPT")
            return JudgeVerdict(action="RETRY")

        judge.evaluate = judge_eval

        # LLM that returns different args each call
        call_idx = 0

        class DiffArgsLLM(LLMProvider):
            async def stream(self, messages, **kwargs):
                nonlocal call_idx
                idx = call_idx
                call_idx += 1
                if idx < 3:
                    yield ToolCallEvent(
                        tool_use_id=f"c{idx}",
                        tool_name="search",
                        tool_input={"q": f"query_{idx}"},
                    )
                    yield FinishEvent(
                        stop_reason="tool_calls",
                        input_tokens=10,
                        output_tokens=5,
                        model="mock",
                    )
                else:
                    text = f"done (call {idx})"
                    yield TextDeltaEvent(
                        content=text,
                        snapshot=text,
                    )
                    yield FinishEvent(
                        stop_reason="stop",
                        input_tokens=10,
                        output_tokens=5,
                        model="mock",
                    )

            def complete(self, messages, **kwargs):
                return LLMResponse(
                    content="ok",
                    model="mock",
                    stop_reason="stop",
                )

        llm = DiffArgsLLM()

        def tool_exec(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="result",
                is_error=False,
            )

        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
                stall_similarity_threshold=1.0,  # disable fuzzy stall detection
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_doom_loop_detects_repeated_failing_tool(
        self,
        runtime,
        node_spec,
        buffer,
    ):
        """A tool that keeps failing with is_error=True should trigger doom loop.

        Regression test: previously, errored tool calls were excluded from
        doom loop fingerprinting (``not tc.get("is_error")``), so a tool like
        a tool failing with the same error every turn
        would never be detected.
        """
        node_spec.output_keys = []
        judge = AsyncMock(spec=JudgeProtocol)
        eval_count = 0

        async def judge_eval(*args, **kwargs):
            nonlocal eval_count
            eval_count += 1
            if eval_count >= 5:
                return JudgeVerdict(action="ACCEPT")
            return JudgeVerdict(action="RETRY")

        judge.evaluate = judge_eval

        # 4 turns of the same failing tool call, then text
        llm = ToolRepeatLLM("failing_tool", {}, tool_turns=4)
        bus = EventBus()
        doom_events: list = []
        bus.subscribe(
            event_types=[EventType.NODE_TOOL_DOOM_LOOP],
            handler=lambda e: doom_events.append(e),
        )

        def tool_exec(tool_use: ToolUse) -> ToolResult:
            return ToolResult(
                tool_use_id=tool_use.id,
                content="Error: accessibility tree unavailable",
                is_error=True,
            )

        # is_subagent_mode=True opts out of worker auto-escalation.
        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=[Tool(name="failing_tool", description="s", parameters={})],
            is_subagent_mode=True,
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            event_bus=bus,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
                stall_similarity_threshold=1.0,  # disable fuzzy stall detection
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        # Doom loop MUST fire for repeatedly-failing tool calls
        assert len(doom_events) >= 1
        assert "failing_tool" in doom_events[0].data["description"]


# ===========================================================================
# execution_id plumbing
# ===========================================================================


class TestExecutionId:
    """Tests for execution_id on NodeContext and its wiring through the framework."""

    def test_node_context_accepts_execution_id(self, runtime, node_spec, buffer):
        """NodeContext stores execution_id when constructed with one."""
        ctx = NodeContext(
            runtime=runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            buffer=buffer,
            execution_id="exec_abc",
        )
        assert ctx.execution_id == "exec_abc"

    def test_node_context_execution_id_defaults_to_empty(self, runtime, node_spec, buffer):
        """build_ctx without execution_id gives ctx.execution_id == ''."""
        llm = MockStreamingLLM()
        ctx = build_ctx(runtime, node_spec, buffer, llm)
        assert ctx.execution_id == ""

    def test_stream_runtime_adapter_exposes_execution_id(self):
        """StreamRuntimeAdapter.execution_id returns the value passed at construction."""
        from framework.host.stream_runtime import StreamRuntimeAdapter

        mock_stream_runtime = MagicMock()
        adapter = StreamRuntimeAdapter(stream_runtime=mock_stream_runtime, execution_id="exec_456")
        assert adapter.execution_id == "exec_456"


# ---------------------------------------------------------------------------
# Subagent data buffer snapshot includes accumulator outputs
# ---------------------------------------------------------------------------


class TestSubagentAccumulatorMemory:
    """Verify that subagent data buffer construction merges accumulator outputs
    and includes the subagent's input_keys in read permissions."""

    def test_accumulator_values_merged_into_parent_data(self):
        """Keys from OutputAccumulator should appear in subagent data buffer."""
        # Simulate what _execute_subagent does internally:
        # parent shared data buffer has user_request but NOT tweet_content
        parent_buffer = DataBuffer()
        parent_buffer.write("user_request", "post a joke")
        parent_data = parent_buffer.read_all()  # {"user_request": "post a joke"}

        # Accumulator has tweet_content (set via set_output before delegation)
        acc = OutputAccumulator(values={"tweet_content": "Hello world!"})

        # Merge accumulator outputs (the fix)
        for key, value in acc.to_dict().items():
            if key not in parent_data:
                parent_data[key] = value

        # Build subagent data buffer
        subagent_buffer = DataBuffer()
        for key, value in parent_data.items():
            subagent_buffer.write(key, value, validate=False)

        subagent_input_keys = ["tweet_content"]
        read_keys = set(parent_data.keys()) | set(subagent_input_keys)
        scoped = subagent_buffer.with_permissions(read_keys=list(read_keys), write_keys=[])

        # This would have raised PermissionError before the fix
        assert scoped.read("tweet_content") == "Hello world!"
        assert scoped.read("user_request") == "post a joke"

    def test_input_keys_allowed_even_if_not_in_data(self):
        """Subagent input_keys should be in read permissions even if the
        key doesn't exist in data buffer (returns None instead of PermissionError)."""
        parent_buffer = DataBuffer()
        parent_buffer.write("user_request", "hi")
        parent_data = parent_buffer.read_all()

        subagent_buffer = DataBuffer()
        for key, value in parent_data.items():
            subagent_buffer.write(key, value, validate=False)

        # input_keys includes "tweet_content" which isn't in parent_data
        read_keys = set(parent_data.keys()) | {"tweet_content"}
        scoped = subagent_buffer.with_permissions(read_keys=list(read_keys), write_keys=[])

        # Should return None (not raise PermissionError)
        assert scoped.read("tweet_content") is None
        assert scoped.read("user_request") == "hi"


# ---------------------------------------------------------------------------
# Tool concurrency partitioning (Gap 5)
# ---------------------------------------------------------------------------


def _multi_tool_scenario(*calls: tuple[str, dict, str]) -> list:
    """Build a stream scenario that emits multiple tool calls in one turn.

    Each ``calls`` entry is ``(tool_name, tool_input, tool_use_id)``.
    """
    events: list = []
    for name, inp, uid in calls:
        events.append(ToolCallEvent(tool_use_id=uid, tool_name=name, tool_input=inp))
    events.append(FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"))
    return events


class TestToolConcurrencyPartition:
    """Gap 5: safe tools run in parallel, unsafe tools serialize after them."""

    @pytest.mark.asyncio
    async def test_safe_tools_overlap_unsafe_tools_do_not(self, runtime, node_spec, buffer):
        """A turn with (safe, safe, unsafe) schedules safes in parallel and
        runs unsafe strictly after both safes have started."""
        scenario = _multi_tool_scenario(
            ("read_file", {"path": "/a"}, "call_1"),
            ("read_file", {"path": "/b"}, "call_2"),
            ("execute_command", {"command": "echo hi"}, "call_3"),
        )
        # Second turn emits plain text so the loop terminates.
        llm = MockStreamingLLM(scenarios=[scenario, text_scenario("done")])
        node_spec.output_keys = []

        start_events: list[tuple[str, float]] = []
        end_events: list[tuple[str, float]] = []

        async def tool_exec(tool_use: ToolUse) -> ToolResult:
            start_events.append((tool_use.id, asyncio.get_event_loop().time()))
            # The two safes sleep long enough that a serial scheduler
            # would show them end-before-start, but a parallel scheduler
            # overlaps them. execute_command also sleeps so we can prove
            # it started AFTER both safes started.
            await asyncio.sleep(0.05)
            end_events.append((tool_use.id, asyncio.get_event_loop().time()))
            return ToolResult(tool_use_id=tool_use.id, content="ok", is_error=False)

        tools = [
            Tool(
                name="read_file",
                description="",
                parameters={},
                concurrency_safe=True,
            ),
            Tool(
                name="execute_command",
                description="",
                parameters={},
                concurrency_safe=False,
            ),
        ]

        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=tools,
            is_subagent_mode=True,
        )
        node = EventLoopNode(
            tool_executor=tool_exec,
            config=LoopConfig(max_iterations=3),
        )
        await node.execute(ctx)

        # Build lookup dicts for readability.
        starts = dict(start_events)
        ends = dict(end_events)

        # Both safe reads must start (approximately) together and before
        # either has finished - proving they ran concurrently.
        assert starts["call_1"] < ends["call_2"]
        assert starts["call_2"] < ends["call_1"]

        # The unsafe tool must start strictly AFTER both safes have ended -
        # proving it was serialized after the parallel batch.
        assert starts["call_3"] >= ends["call_1"]
        assert starts["call_3"] >= ends["call_2"]

    @pytest.mark.asyncio
    async def test_serial_exception_cascades_cancel_siblings(self, runtime, node_spec, buffer):
        """When an unsafe tool raises, the remaining unsafe siblings are
        cancelled with a clear error rather than silently executed."""
        scenario = _multi_tool_scenario(
            ("execute_command", {"command": "boom"}, "call_1"),
            ("execute_command", {"command": "echo survivor"}, "call_2"),
        )
        llm = MockStreamingLLM(scenarios=[scenario, text_scenario("done")])
        node_spec.output_keys = []

        executed: list[str] = []

        async def tool_exec(tool_use: ToolUse) -> ToolResult:
            executed.append(tool_use.id)
            if tool_use.id == "call_1":
                raise RuntimeError("first tool exploded")
            return ToolResult(tool_use_id=tool_use.id, content="ok", is_error=False)

        tools = [
            Tool(
                name="execute_command",
                description="",
                parameters={},
                concurrency_safe=False,
            ),
        ]
        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=tools,
            is_subagent_mode=True,
        )
        node = EventLoopNode(
            tool_executor=tool_exec,
            config=LoopConfig(max_iterations=3),
        )
        await node.execute(ctx)

        # First tool ran (and raised); second tool must NOT have run.
        assert executed == ["call_1"]

    @pytest.mark.asyncio
    async def test_safe_tool_starts_before_finish_event(self, runtime, node_spec, buffer):
        """Gap 1: a concurrency-safe tool must start executing while the
        stream is still in flight, not after the final FinishEvent.

        Builds a custom LLM that sleeps between the ToolCallEvent and
        the FinishEvent. A well-behaved harness starts the tool as soon
        as the ToolCallEvent arrives, so by the time FinishEvent lands
        the tool has already been running for ~sleep_seconds.
        """
        from framework.llm.stream_events import FinishEvent, ToolCallEvent

        delay = 0.25

        class SlowStreamLLM(LLMProvider):
            def __init__(self):
                self._calls = 0

            async def stream(self, messages, system="", tools=None, max_tokens=4096):
                self._calls += 1
                if self._calls == 1:
                    # Emit the tool call, stall, then finish.
                    yield ToolCallEvent(
                        tool_use_id="call_1",
                        tool_name="read_file",
                        tool_input={"path": "/a"},
                    )
                    await asyncio.sleep(delay)
                    yield FinishEvent(
                        stop_reason="tool_calls",
                        input_tokens=10,
                        output_tokens=5,
                        model="mock",
                    )
                else:
                    # Turn 2 needs to match text_scenario shape so the
                    # outer loop terminates cleanly (needs a text delta
                    # before the finish event; empty turns are treated
                    # as worker silence and fall into the escalation
                    # grace window).
                    yield TextDeltaEvent(content="done", snapshot="done")
                    yield FinishEvent(
                        stop_reason="stop",
                        input_tokens=1,
                        output_tokens=1,
                        model="mock",
                    )

            def complete(self, messages, system="", **kwargs) -> LLMResponse:
                return LLMResponse(content="", model="mock", stop_reason="stop")

        tool_started_at: list[float] = []
        tool_finished_at: list[float] = []

        async def tool_exec(tool_use: ToolUse) -> ToolResult:
            tool_started_at.append(asyncio.get_event_loop().time())
            # Short simulated work so the tool finishes before the stream
            # does; this proves the tool was running concurrently with
            # the sleep inside the LLM stream.
            await asyncio.sleep(0.05)
            tool_finished_at.append(asyncio.get_event_loop().time())
            return ToolResult(tool_use_id=tool_use.id, content="ok", is_error=False)

        tools = [
            Tool(
                name="read_file",
                description="",
                parameters={},
                concurrency_safe=True,
            ),
        ]
        node_spec.output_keys = []
        llm = SlowStreamLLM()
        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=tools,
            is_subagent_mode=True,
        )
        node = EventLoopNode(
            tool_executor=tool_exec,
            config=LoopConfig(max_iterations=3),
        )
        turn_started = asyncio.get_event_loop().time()
        await node.execute(ctx)
        turn_ended = asyncio.get_event_loop().time()

        assert tool_started_at, "tool never ran"
        # The tool must have STARTED within the LLM's sleep window -
        # i.e. before turn_started + delay, not after. A post-stream
        # dispatcher would start the tool at turn_started + delay or
        # later.
        assert tool_started_at[0] < turn_started + delay, (
            f"tool started at +{tool_started_at[0] - turn_started:.3f}s, "
            f"but the stream sleep was {delay}s - the harness is still "
            f"waiting for FinishEvent before dispatching."
        )
        # Sanity: the whole turn took at least the sleep window (the
        # stream had to drain before dispatch).
        assert turn_ended - turn_started >= delay

    @pytest.mark.asyncio
    async def test_soft_error_does_not_cascade(self, runtime, node_spec, buffer):
        """A ToolResult with is_error=True (e.g. 'file not found') is a
        normal return and must NOT cancel subsequent serial siblings - the
        model needs to see all tool errors to decide what to do next."""
        scenario = _multi_tool_scenario(
            ("execute_command", {"command": "false"}, "call_1"),
            ("execute_command", {"command": "echo two"}, "call_2"),
        )
        llm = MockStreamingLLM(scenarios=[scenario, text_scenario("done")])
        node_spec.output_keys = []

        executed: list[str] = []

        async def tool_exec(tool_use: ToolUse) -> ToolResult:
            executed.append(tool_use.id)
            return ToolResult(
                tool_use_id=tool_use.id,
                content="soft error" if tool_use.id == "call_1" else "ok",
                is_error=(tool_use.id == "call_1"),
            )

        tools = [
            Tool(
                name="execute_command",
                description="",
                parameters={},
                concurrency_safe=False,
            ),
        ]
        ctx = build_ctx(
            runtime,
            node_spec,
            buffer,
            llm,
            tools=tools,
            is_subagent_mode=True,
        )
        node = EventLoopNode(
            tool_executor=tool_exec,
            config=LoopConfig(max_iterations=3),
        )
        await node.execute(ctx)

        # Both tools must have run: soft errors don't cascade.
        assert executed == ["call_1", "call_2"]
