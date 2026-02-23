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
        assert result.output["result"] == 42

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
    @pytest.mark.skip(reason="Hangs in non-interactive shells (client-facing blocks on stdin)")
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

        # Text-only on client_facing no longer blocks (no ask_user), so
        # the node completes without needing shutdown.
        await node.execute(ctx)

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
    @pytest.mark.skip(reason="Hangs in non-interactive shells (client-facing blocks on stdin)")
    async def test_text_only_no_blocking(self, runtime, memory, client_spec):
        """client_facing + text-only (no ask_user) should NOT block."""
        llm = MockStreamingLLM(
            scenarios=[
                text_scenario("Hello! Here is your status update."),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, client_spec, memory, llm)

        # Should complete without blocking — no ask_user called, no output_keys required
        result = await node.execute(ctx)

        assert result.success is True
        assert llm._call_index >= 1

    @pytest.mark.asyncio
    async def test_ask_user_triggers_blocking(self, runtime, memory, client_spec):
        """client_facing + ask_user() blocks until inject_event."""
        # Give the node an output key so the judge doesn't auto-accept
        # after the user responds — it needs set_output first.
        client_spec.output_keys = ["answer"]
        llm = MockStreamingLLM(
            scenarios=[
                # Turn 1: LLM greets user and calls ask_user
                tool_call_scenario(
                    "ask_user", {"question": "What do you need?"}, tool_use_id="ask_1"
                ),
                # Turn 2: after user responds, LLM processes and sets output
                tool_call_scenario("set_output", {"key": "answer", "value": "help provided"}),
                # Turn 3: text finish (implicit judge accepts — output key set)
                text_scenario("Got your message."),
            ]
        )
        bus = EventBus()
        node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, client_spec, memory, llm)

        async def user_responds():
            await asyncio.sleep(0.05)
            await node.inject_event("I need help")

        user_task = asyncio.create_task(user_responds())
        result = await node.execute(ctx)
        await user_task

        assert result.success is True
        # LLM called at least twice: once for ask_user turn, once after user responded
        assert llm._call_index >= 2
        assert result.output["answer"] == "help provided"

    @pytest.mark.asyncio
    async def test_client_facing_does_not_block_on_tools(self, runtime, memory):
        """client_facing + tool calls (no ask_user) should NOT block."""
        spec = NodeSpec(
            id="chat",
            name="Chat",
            description="chat node",
            node_type="event_loop",
            output_keys=["result"],
            client_facing=True,
        )
        # Scenario 1: LLM calls set_output
        # Scenario 2: LLM produces text — implicit judge ACCEPTs (output key set)
        # No ask_user called, so no blocking occurs.
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("set_output", {"key": "result", "value": "done"}),
                text_scenario("All set!"),
            ]
        )
        node = EventLoopNode(config=LoopConfig(max_iterations=5))
        ctx = build_ctx(runtime, spec, memory, llm)

        # Should complete without blocking — no ask_user called
        result = await node.execute(ctx)

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
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("ask_user", {"question": "Waiting..."}, tool_use_id="ask_1"),
            ]
        )
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
        """CLIENT_INPUT_REQUESTED should be published when ask_user blocks."""
        llm = MockStreamingLLM(
            scenarios=[
                tool_call_scenario("ask_user", {"question": "Hello!"}, tool_use_id="ask_1"),
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
        ctx = build_ctx(runtime, client_spec, memory, llm)

        async def shutdown():
            await asyncio.sleep(0.05)
            node.signal_shutdown()

        task = asyncio.create_task(shutdown())
        await node.execute(ctx)
        await task

        assert len(received) >= 1
        assert received[0].type == EventType.CLIENT_INPUT_REQUESTED

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Hangs in non-interactive shells (client-facing blocks on stdin)")
    async def test_ask_user_with_real_tools(self, runtime, memory):
        """ask_user alongside real tool calls still triggers blocking."""
        spec = NodeSpec(
            id="chat",
            name="Chat",
            description="chat node",
            node_type="event_loop",
            output_keys=[],
            client_facing=True,
        )
        # LLM calls a real tool AND ask_user in the same turn
        llm = MockStreamingLLM(
            scenarios=[
                [
                    ToolCallEvent(
                        tool_use_id="tool_1", tool_name="search", tool_input={"q": "test"}
                    ),
                    ToolCallEvent(tool_use_id="ask_1", tool_name="ask_user", tool_input={}),
                    FinishEvent(
                        stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"
                    ),
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
            runtime, spec, memory, llm, tools=[Tool(name="search", description="", parameters={})]
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
    async def test_ask_user_not_available_non_client_facing(self, runtime, memory):
        """ask_user tool should NOT be injected for non-client-facing nodes."""
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

        await node.execute(ctx)

        # Verify ask_user was NOT in the tools passed to the LLM
        assert llm._call_index >= 1
        for call in llm.stream_calls:
            tool_names = [t.name for t in (call["tools"] or [])]
            assert "ask_user" not in tool_names


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

    def complete_with_tools(self, messages, system, tools, tool_executor, **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


class TestTransientErrorRetry:
    """Test retry-with-backoff for transient LLM errors in EventLoopNode."""

    @pytest.mark.asyncio
    async def test_transient_error_retries_then_succeeds(self, runtime, node_spec, memory):
        """A transient error on the first try should retry and succeed."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=ConnectionError("connection reset"),
            fail_count=1,
            success_scenario=text_scenario("success"),
        )
        ctx = build_ctx(runtime, node_spec, memory, llm)
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
    async def test_permanent_error_no_retry(self, runtime, node_spec, memory):
        """A permanent error (ValueError) should NOT be retried."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=ValueError("bad request: invalid model"),
            fail_count=1,
            success_scenario=text_scenario("success"),
        )
        ctx = build_ctx(runtime, node_spec, memory, llm)
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
    async def test_transient_error_exhausts_retries(self, runtime, node_spec, memory):
        """Transient errors that exhaust retries should raise."""
        node_spec.output_keys = []
        llm = ErrorThenSuccessLLM(
            error=TimeoutError("request timed out"),
            fail_count=100,  # always fails
            success_scenario=text_scenario("unreachable"),
        )
        ctx = build_ctx(runtime, node_spec, memory, llm)
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
    async def test_stream_error_event_retried_as_runtime_error(self, runtime, node_spec, memory):
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

            def complete_with_tools(
                self,
                messages,
                system,
                tools,
                tool_executor,
                **kwargs,
            ):
                return LLMResponse(
                    content="",
                    model="mock",
                    stop_reason="stop",
                )

        llm = StreamErrorThenSuccessLLM()
        ctx = build_ctx(runtime, node_spec, memory, llm)
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
    async def test_retry_emits_event_bus_event(self, runtime, node_spec, memory):
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

        ctx = build_ctx(runtime, node_spec, memory, llm)
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

    @pytest.mark.asyncio
    async def test_recoverable_stream_error_retried_not_silent(self, runtime, node_spec, memory):
        """Recoverable StreamErrorEvent with empty response should raise ConnectionError.

        Previously, recoverable stream errors were silently swallowed,
        producing empty responses that the judge retried — creating an
        infinite loop of 50+ empty-response iterations.  Now they raise
        ConnectionError so the outer transient-error retry handles them
        with proper backoff.
        """
        node_spec.output_keys = ["result"]

        call_index = 0

        class RecoverableErrorThenSuccessLLM(LLMProvider):
            async def stream(self, messages, system="", tools=None, max_tokens=4096):
                nonlocal call_index
                idx = call_index
                call_index += 1
                if idx == 0:
                    # Recoverable error with no content
                    yield StreamErrorEvent(
                        error="503 service unavailable",
                        recoverable=True,
                    )
                elif idx == 1:
                    # Success: set output
                    for event in tool_call_scenario(
                        "set_output", {"key": "result", "value": "done"}
                    ):
                        yield event
                else:
                    # Subsequent calls: text-only (no more tool calls)
                    for event in text_scenario("done"):
                        yield event

            def complete(self, messages, system="", **kwargs):
                return LLMResponse(content="ok", model="mock", stop_reason="stop")

            def complete_with_tools(self, messages, system, tools, tool_executor, **kwargs):
                return LLMResponse(content="", model="mock", stop_reason="stop")

        llm = RecoverableErrorThenSuccessLLM()
        ctx = build_ctx(runtime, node_spec, memory, llm)
        node = EventLoopNode(
            config=LoopConfig(
                max_iterations=5,
                max_stream_retries=3,
                stream_retry_backoff_base=0.01,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        assert result.output.get("result") == "done"
        # call 0: recoverable error → ConnectionError raised → outer retry
        # call 1: set_output tool call succeeds
        # call 2: inner tool loop re-invokes LLM after tool result → text "done"
        assert call_index == 3


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
        assert EventLoopNode._fingerprint_tool_calls(r1) != (
            EventLoopNode._fingerprint_tool_calls(r2)
        )

    def test_sort_keys_deterministic(self):
        r1 = [{"tool_name": "t", "tool_input": {"b": 2, "a": 1}}]
        r2 = [{"tool_name": "t", "tool_input": {"a": 1, "b": 2}}]
        assert EventLoopNode._fingerprint_tool_calls(r1) == EventLoopNode._fingerprint_tool_calls(
            r2
        )


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
        fp1 = [("search", '{"q": "a"}')]
        fp2 = [("search", '{"q": "b"}')]
        fp3 = [("search", '{"q": "c"}')]
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

    def complete_with_tools(
        self,
        messages,
        system,
        tools,
        tool_executor,
        **kwargs,
    ) -> LLMResponse:
        return LLMResponse(
            content="",
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
        memory,
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
            memory,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_doom_loop_emits_event(
        self,
        runtime,
        node_spec,
        memory,
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

        ctx = build_ctx(
            runtime,
            node_spec,
            memory,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            event_bus=bus,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
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
        memory,
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
            memory,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_enabled=False,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_different_args_no_doom_loop(
        self,
        runtime,
        node_spec,
        memory,
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

            def complete_with_tools(
                self,
                messages,
                system,
                tools,
                tool_executor,
                **kw,
            ):
                return LLMResponse(
                    content="",
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
            memory,
            llm,
            tools=[Tool(name="search", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_doom_loop_detects_repeated_failing_tool(
        self,
        runtime,
        node_spec,
        memory,
    ):
        """A tool that keeps failing with is_error=True should trigger doom loop.

        Regression test: previously, errored tool calls were excluded from
        doom loop fingerprinting (``not tc.get("is_error")``), so a tool like
        browser_snapshot failing with the same accessibility error every turn
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
        llm = ToolRepeatLLM("browser_snapshot", {}, tool_turns=4)
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

        ctx = build_ctx(
            runtime,
            node_spec,
            memory,
            llm,
            tools=[Tool(name="browser_snapshot", description="s", parameters={})],
        )
        node = EventLoopNode(
            judge=judge,
            tool_executor=tool_exec,
            event_bus=bus,
            config=LoopConfig(
                max_iterations=10,
                tool_doom_loop_threshold=3,
            ),
        )
        result = await node.execute(ctx)
        assert result.success is True
        # Doom loop MUST fire for repeatedly-failing tool calls
        assert len(doom_events) >= 1
        assert "browser_snapshot" in doom_events[0].data["description"]


# ===========================================================================
# execution_id plumbing
# ===========================================================================


class TestExecutionId:
    """Tests for execution_id on NodeContext and its wiring through the framework."""

    def test_node_context_accepts_execution_id(self, runtime, node_spec, memory):
        """NodeContext stores execution_id when constructed with one."""
        ctx = NodeContext(
            runtime=runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            memory=memory,
            execution_id="exec_abc",
        )
        assert ctx.execution_id == "exec_abc"

    def test_node_context_execution_id_defaults_to_empty(self, runtime, node_spec, memory):
        """build_ctx without execution_id gives ctx.execution_id == ''."""
        llm = MockStreamingLLM()
        ctx = build_ctx(runtime, node_spec, memory, llm)
        assert ctx.execution_id == ""

    def test_stream_runtime_adapter_exposes_execution_id(self):
        """StreamRuntimeAdapter.execution_id returns the value passed at construction."""
        from framework.runtime.stream_runtime import StreamRuntimeAdapter

        mock_stream_runtime = MagicMock()
        adapter = StreamRuntimeAdapter(stream_runtime=mock_stream_runtime, execution_id="exec_456")
        assert adapter.execution_id == "exec_456"

    def test_build_context_passes_execution_id_from_adapter(self):
        """_build_context picks up execution_id from a StreamRuntimeAdapter runtime."""
        from framework.graph.executor import GraphExecutor
        from framework.graph.goal import Goal

        runtime = MagicMock()
        runtime.execution_id = "exec_123"
        executor = GraphExecutor(runtime=runtime)

        goal = Goal(id="g1", name="test", description="test", success_criteria=[])
        node_spec = NodeSpec(
            id="n1", name="n1", description="test", node_type="event_loop", output_keys=["r"]
        )
        ctx = executor._build_context(
            node_spec=node_spec, memory=SharedMemory(), goal=goal, input_data={}
        )
        assert ctx.execution_id == "exec_123"

    def test_build_context_defaults_execution_id_for_plain_runtime(self):
        """Plain Runtime.execution_id returns '' by default."""
        from framework.graph.executor import GraphExecutor
        from framework.graph.goal import Goal

        runtime = MagicMock(spec=Runtime)
        runtime.execution_id = ""
        executor = GraphExecutor(runtime=runtime)

        goal = Goal(id="g1", name="test", description="test", success_criteria=[])
        node_spec = NodeSpec(
            id="n1", name="n1", description="test", node_type="event_loop", output_keys=["r"]
        )
        ctx = executor._build_context(
            node_spec=node_spec, memory=SharedMemory(), goal=goal, input_data={}
        )
        assert ctx.execution_id == ""
