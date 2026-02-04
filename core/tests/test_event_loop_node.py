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

from framework.graph.conversation import NodeConversation
from framework.graph.event_loop_node import (
    EventLoopNode,
    JudgeProtocol,
    JudgeVerdict,
    LoopConfig,
    OutputAccumulator,
)
from framework.graph.node import NodeContext, NodeProtocol, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.runtime.core import Runtime
from framework.runtime.event_bus import EventBus, EventType
from framework.storage.conversation_store import FileConversationStore

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

    def complete_with_tools(self, messages, system, tools, tool_executor, **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


# ---------------------------------------------------------------------------
# Helper: build a simple text-only scenario
# ---------------------------------------------------------------------------


def text_scenario(text: str, input_tokens: int = 10, output_tokens: int = 5) -> list:
    """Build a stream scenario that produces text and finishes."""
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(
            stop_reason="stop", input_tokens=input_tokens, output_tokens=output_tokens, model="mock"
        ),
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
    events.append(
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input)
    )
    events.append(
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock")
    )
    return events


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime():
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="run_1")
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
def memory():
    return SharedMemory()


def build_ctx(runtime, node_spec, memory, llm, tools=None, input_data=None, goal_context=""):
    """Build a NodeContext for testing."""
    return NodeContext(
        runtime=runtime,
        node_id=node_spec.id,
        node_spec=node_spec,
        memory=memory,
        input_data=input_data or {},
        llm=llm,
        available_tools=tools or [],
        goal_context=goal_context,
    )


# ===========================================================================
# NodeProtocol conformance
# ===========================================================================


class TestNodeProtocolConformance:
    def test_subclasses_node_protocol(self):
        """EventLoopNode must be a subclass of NodeProtocol."""
        assert issubclass(EventLoopNode, NodeProtocol)

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
    async def test_basic_text_only_implicit_accept(self, runtime, node_spec, memory):
        """No tools, no judge. LLM produces text, implicit accept on stop."""
        # Override to no output_keys so implicit judge accepts immediately
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Hello world")])
        ctx = build_ctx(runtime, node_spec, memory, llm)

        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert result.tokens_used > 0

    @pytest.mark.asyncio
    async def test_no_llm_returns_failure(self, runtime, node_spec, memory):
        """ctx.llm=None should return failure immediately."""
        ctx = build_ctx(runtime, node_spec, memory, llm=None)

        node = EventLoopNode()
        result = await node.execute(ctx)

        assert result.success is False
        assert "LLM" in result.error

    @pytest.mark.asyncio
    async def test_max_iterations_failure(self, runtime, node_spec, memory):
        """When max_iterations is reached without acceptance, should fail."""
        # LLM always produces text but never calls set_output, so implicit
        # judge retries asking for missing keys
        llm = MockStreamingLLM(scenarios=[text_scenario("thinking...")])
        ctx = build_ctx(runtime, node_spec, memory, llm)

        node = EventLoopNode(config=LoopConfig(max_iterations=2))
        result = await node.execute(ctx)

        assert result.success is False
        assert "Max iterations" in result.error


# ===========================================================================
# Judge integration
# ===========================================================================


class TestJudgeIntegration:
    @pytest.mark.asyncio
    async def test_judge_accept(self, runtime, node_spec, memory):
        """Mock judge ACCEPT -> success."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Done!")])

        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(return_value=JudgeVerdict(action="ACCEPT"))

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        judge.evaluate.assert_called_once()

    @pytest.mark.asyncio
    async def test_judge_escalate(self, runtime, node_spec, memory):
        """Mock judge ESCALATE -> failure."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Attempt")])

        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(
            return_value=JudgeVerdict(action="ESCALATE", feedback="Tone violation")
        )

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is False
        assert "escalated" in result.error.lower()
        assert "Tone violation" in result.error

    @pytest.mark.asyncio
    async def test_judge_retry_then_accept(self, runtime, node_spec, memory):
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

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=10))
        result = await node.execute(ctx)

        assert result.success is True
        assert call_count == 3


# ===========================================================================
# set_output tool
# ===========================================================================


class TestSetOutput:
    @pytest.mark.asyncio
    async def test_set_output_accumulates(self, runtime, node_spec, memory):
        """LLM calls set_output -> values appear in NodeResult.output."""
        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: call set_output
                tool_call_scenario("set_output", {"key": "result", "value": "42"}),
                # Turn 2: text response (triggers implicit judge)
                text_scenario("Done, result is 42"),
            ]
        )

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert result.output["result"] == "42"

    @pytest.mark.asyncio
    async def test_set_output_rejects_invalid_key(self, runtime, node_spec, memory):
        """set_output with key not in output_keys -> is_error=True."""
        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: call set_output with bad key
                tool_call_scenario("set_output", {"key": "bad_key", "value": "x"}),
                # Turn 2: call set_output with good key
                tool_call_scenario("set_output", {"key": "result", "value": "ok"}),
                # Turn 3: text done
                text_scenario("Done"),
            ]
        )

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert result.output["result"] == "ok"
        assert "bad_key" not in result.output

    @pytest.mark.asyncio
    async def test_missing_keys_triggers_retry(self, runtime, node_spec, memory):
        """Judge accepts but output keys are missing -> retry with hint."""
        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(return_value=JudgeVerdict(action="ACCEPT"))

        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: text without set_output -> judge accepts but keys missing -> retry
                text_scenario("I'll get to it"),
                # Turn 2: set_output
                tool_call_scenario("set_output", {"key": "result", "value": "done"}),
                # Turn 3: text -> judge accepts, keys present -> success
                text_scenario("All done"),
            ]
        )

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(judge=judge, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert result.output["result"] == "done"


# ===========================================================================
# Stall detection
# ===========================================================================


class TestStallDetection:
    @pytest.mark.asyncio
    async def test_stall_detection(self, runtime, node_spec, memory):
        """3 identical responses should trigger stall detection."""
        node_spec.output_keys = []  # so implicit judge would accept
        # But we need the judge to RETRY so we actually get 3 identical responses
        judge = AsyncMock(spec=JudgeProtocol)
        judge.evaluate = AsyncMock(return_value=JudgeVerdict(action="RETRY"))

        llm = MockStreamingLLM(scenarios=[text_scenario("same answer")])

        ctx = build_ctx(runtime, node_spec, memory, llm)
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
    async def test_lifecycle_events_published(self, runtime, node_spec, memory):
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

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        result = await node.execute(ctx)

        assert result.success is True
        assert EventType.NODE_LOOP_STARTED in received_events
        assert EventType.NODE_LOOP_ITERATION in received_events
        assert EventType.NODE_LOOP_COMPLETED in received_events

    @pytest.mark.asyncio
    async def test_client_facing_uses_client_output_delta(self, runtime, memory):
        """client_facing=True should emit CLIENT_OUTPUT_DELTA instead of LLM_TEXT_DELTA."""
        spec = NodeSpec(
            id="ui_node",
            name="UI Node",
            description="Streams to user",
            node_type="event_loop",
            output_keys=[],
            client_facing=True,
        )
        llm = MockStreamingLLM(scenarios=[text_scenario("visible to user")])
        bus = EventBus()

        received_types = []
        bus.subscribe(
            event_types=[EventType.CLIENT_OUTPUT_DELTA, EventType.LLM_TEXT_DELTA],
            handler=lambda e: received_types.append(e.type),
        )

        ctx = build_ctx(runtime, spec, memory, llm)
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))

        # client_facing + text-only blocks for user input; use shutdown to unblock
        async def auto_shutdown():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(auto_shutdown())
        await node.execute(ctx)
        await task

        assert EventType.CLIENT_OUTPUT_DELTA in received_types
        assert EventType.LLM_TEXT_DELTA not in received_types


# ===========================================================================
# Client-facing blocking
# ===========================================================================


class TestClientFacingBlocking:
    """Tests for native client_facing input blocking in EventLoopNode."""

    @pytest.fixture
    def client_spec(self):
        return NodeSpec(
            id="chat",
            name="Chat",
            description="chat node",
            node_type="event_loop",
            output_keys=[],
            client_facing=True,
        )

    @pytest.mark.asyncio
    async def test_client_facing_blocks_on_text(self, runtime, memory, client_spec):
        """client_facing + text-only response blocks until inject_event."""
        llm = MockStreamingLLM(
            scenarios=[
                text_scenario("Hello!"),
                text_scenario("Got your message."),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, client_spec, memory, llm)

        async def user_responds():
            await asyncio.sleep(0.05)
            await node.inject_event("I need help")
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        user_task = asyncio.create_task(user_responds())
        result = await node.execute(ctx)
        await user_task

        assert result.success is True
        # LLM should have been called at least twice (first response + after inject)
        assert llm._call_index >= 2

    @pytest.mark.asyncio
    async def test_client_facing_does_not_block_on_tools(self, runtime, memory):
        """client_facing + tool calls should NOT block — judge evaluates normally."""
        spec = NodeSpec(
            id="chat",
            name="Chat",
            description="chat node",
            node_type="event_loop",
            output_keys=["result"],
            client_facing=True,
        )
        # Scenario 1: LLM calls set_output (tool call present → no blocking, judge RETRYs)
        # Scenario 2: LLM produces text (implicit judge sees output key set → ACCEPT)
        # But scenario 2 is text-only on client_facing → would block.
        # So we need shutdown to handle that case.
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("set_output", {"key": "result", "value": "done"}),
                text_scenario("All set!"),
            ]
        )
        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, spec, memory, llm)

        # After set_output, implicit judge RETRYs (tool calls present).
        # Next turn: text-only on client_facing → blocks.
        # But implicit judge should ACCEPT first (output key is set, no tools).
        # Actually, client_facing check happens BEFORE judge, so it blocks.
        # Use shutdown as safety net.
        async def auto_shutdown():
            await asyncio.sleep(0.1)
            node.signal_shutdown()

        task = asyncio.create_task(auto_shutdown())
        result = await node.execute(ctx)
        await task

        assert result.success is True
        assert result.output["result"] == "done"

    @pytest.mark.asyncio
    async def test_non_client_facing_unchanged(self, runtime, memory):
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
        ctx = build_ctx(runtime, spec, memory, llm)

        # Should complete without blocking (implicit judge ACCEPTs on no tools + no keys)
        result = await node.execute(ctx)
        assert result is not None

    @pytest.mark.asyncio
    async def test_signal_shutdown_unblocks(self, runtime, memory, client_spec):
        """signal_shutdown should unblock a waiting client_facing node."""
        llm = MockStreamingLLM(scenarios=[text_scenario("Waiting...")])
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=10))
        ctx = build_ctx(runtime, client_spec, memory, llm)

        async def shutdown_after_delay():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown_after_delay())
        result = await node.execute(ctx)
        await task

        assert result.success is True

    @pytest.mark.asyncio
    async def test_client_input_requested_event_published(self, runtime, memory, client_spec):
        """CLIENT_INPUT_REQUESTED should be published when blocking."""
        llm = MockStreamingLLM(scenarios=[text_scenario("Hello!")])
        bus = EventBus()
        received = []

        async def capture(e):
            received.append(e)

        bus.subscribe(
            event_types=[EventType.CLIENT_INPUT_REQUESTED],
            handler=capture,
        )

        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, client_spec, memory, llm)

        async def shutdown():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown())
        await node.execute(ctx)
        await task

        assert len(received) >= 1
        assert received[0].type == EventType.CLIENT_INPUT_REQUESTED


# ===========================================================================
# Tool execution
# ===========================================================================


class TestToolExecution:
    @pytest.mark.asyncio
    async def test_tool_execution_feedback(self, runtime, node_spec, memory):
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
            memory,
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
    async def test_messages_written_to_store(self, tmp_path, runtime, node_spec, memory):
        """Messages should be persisted immediately via write-through."""
        store = FileConversationStore(tmp_path / "conv")
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("Hello")])

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(
            conversation_store=store,
            config=LoopConfig(max_iterations=5),
        )
        result = await node.execute(ctx)

        assert result.success is True

        # Verify parts were written to disk
        parts = await store.read_parts()
        assert len(parts) >= 2  # at least initial user msg + assistant msg

    @pytest.mark.asyncio
    async def test_output_accumulator_write_through(self, tmp_path, runtime, node_spec, memory):
        """set_output values should be persisted in cursor immediately."""
        store = FileConversationStore(tmp_path / "conv")
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("set_output", {"key": "result", "value": "persisted_value"}),
                text_scenario("Done"),
            ]
        )

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(
            conversation_store=store,
            config=LoopConfig(max_iterations=5),
        )
        result = await node.execute(ctx)

        assert result.success is True
        assert result.output["result"] == "persisted_value"

        # Verify output was written to cursor on disk
        cursor = await store.read_cursor()
        assert cursor is not None
        assert cursor["outputs"]["result"] == "persisted_value"


# ===========================================================================
# Crash recovery (restore from real FileConversationStore)
# ===========================================================================


class TestCrashRecovery:
    @pytest.mark.asyncio
    async def test_restore_from_checkpoint(self, tmp_path, runtime, node_spec, memory):
        """Populate a store with state, then verify EventLoopNode restores from it."""
        store = FileConversationStore(tmp_path / "conv")

        # Simulate a previous run that wrote conversation + cursor
        conv = NodeConversation(
            system_prompt="You are a test assistant.",
            output_keys=["result"],
            store=store,
        )
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

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(
            conversation_store=store,
            config=LoopConfig(max_iterations=5),
        )
        result = await node.execute(ctx)

        assert result.success is True
        # Should have the restored output
        assert result.output.get("result") == "partial_value"


# ===========================================================================
# External event injection
# ===========================================================================


class TestEventInjection:
    @pytest.mark.asyncio
    async def test_inject_event(self, runtime, node_spec, memory):
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

        ctx = build_ctx(runtime, node_spec, memory, llm)
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
    async def test_pause_returns_early(self, runtime, node_spec, memory):
        """pause_requested in input_data should trigger early return."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(scenarios=[text_scenario("should not run")])

        ctx = build_ctx(
            runtime,
            node_spec,
            memory,
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


class TestStreamErrors:
    @pytest.mark.asyncio
    async def test_non_recoverable_stream_error_raises(self, runtime, node_spec, memory):
        """Non-recoverable StreamErrorEvent should raise RuntimeError."""
        node_spec.output_keys = []
        llm = MockStreamingLLM(
            scenarios=[
                [StreamErrorEvent(error="Connection lost", recoverable=False)],
            ]
        )

        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(config=LoopConfig(max_iterations=5))

        with pytest.raises(RuntimeError, match="Stream error"):
            await node.execute(ctx)


# ===========================================================================
# OutputAccumulator unit tests
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
