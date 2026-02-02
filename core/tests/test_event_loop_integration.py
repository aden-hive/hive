"""
Integration tests for EventLoopNode lifecycle

Default: real LLM (cerebras/zai-glm-4.7).
Set HIVE_TEST_LLM_MODE=mock for fast, deterministic, no-API tests.
Set HIVE_TEST_LLM_MODEL=<model> to override the real model.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.event_loop_node import (
    EventLoopNode,
    JudgeVerdict,
    LoopConfig,
)
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import (
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    SharedMemory,
)
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.runtime.core import Runtime
from framework.runtime.event_bus import AgentEvent, EventBus, EventType

# ---------------------------------------------------------------------------
# Config: mock / real toggle
# ---------------------------------------------------------------------------

USE_MOCK_LLM = os.environ.get("HIVE_TEST_LLM_MODE", "mock").lower() == "mock"
LLM_MODEL = os.environ.get("HIVE_TEST_LLM_MODEL", "cerebras/zai-glm-4.7")


# ---------------------------------------------------------------------------
# ScriptableMockLLMProvider
# ---------------------------------------------------------------------------


@dataclass
class StreamScript:
    """One scripted stream() invocation.

    - text only  -> yields TextDeltaEvent + FinishEvent (turn ends)
    - tool_calls -> yields ToolCallEvent(s) + FinishEvent (node executes tools, calls stream again)
    """

    text: str = ""
    tool_calls: list[dict] | None = None  # [{name, id, input}, ...]


class ScriptableMockLLMProvider(LLMProvider):
    """Mock LLM that plays back a flat list of StreamScript entries.

    Each call to stream() pops the next entry and yields the corresponding events.
    complete() returns a fixed summary (used by _generate_compaction_summary).
    """

    def __init__(self, scripts: list[StreamScript] | None = None):
        self._scripts: list[StreamScript] = list(scripts or [])
        self._call_index = 0
        self.model = "mock-scriptable"

    def complete(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 1024,
        response_format: dict[str, Any] | None = None,
        json_mode: bool = False,
    ) -> LLMResponse:
        return LLMResponse(
            content="Conversation summary for compaction.",
            model=self.model,
            input_tokens=10,
            output_tokens=10,
        )

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        tool_executor: Callable[[ToolUse], ToolResult] | None = None,
        max_iterations: int = 10,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        return self.complete(messages, system, tools, max_tokens)

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        if self._call_index >= len(self._scripts):
            # Fallback: yield empty text finish so node can terminate
            yield TextDeltaEvent(content="(no more scripts)", snapshot="(no more scripts)")
            yield FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5)
            return

        script = self._scripts[self._call_index]
        self._call_index += 1

        if script.tool_calls:
            # Yield tool call events
            for tc in script.tool_calls:
                yield ToolCallEvent(
                    tool_use_id=tc.get("id", f"tc_{self._call_index}"),
                    tool_name=tc["name"],
                    tool_input=tc.get("input", {}),
                )
            if script.text:
                yield TextDeltaEvent(content=script.text, snapshot=script.text)
            yield FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=10)
        else:
            # Text-only response
            if script.text:
                yield TextDeltaEvent(content=script.text, snapshot=script.text)
            yield FinishEvent(stop_reason="end_turn", input_tokens=10, output_tokens=10)


# ---------------------------------------------------------------------------
# MockConversationStore
# ---------------------------------------------------------------------------


class MockConversationStore:
    """In-memory ConversationStore for testing persistence and restore."""

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, Any]] = {}
        self._meta: dict[str, Any] | None = None
        self._cursor: dict[str, Any] | None = None

    async def write_part(self, seq: int, data: dict[str, Any]) -> None:
        self._parts[seq] = data

    async def read_parts(self) -> list[dict[str, Any]]:
        return [self._parts[k] for k in sorted(self._parts)]

    async def write_meta(self, data: dict[str, Any]) -> None:
        self._meta = data

    async def read_meta(self) -> dict[str, Any] | None:
        return self._meta

    async def write_cursor(self, data: dict[str, Any]) -> None:
        self._cursor = data

    async def read_cursor(self) -> dict[str, Any] | None:
        return self._cursor

    async def delete_parts_before(self, seq: int) -> None:
        keys_to_delete = [k for k in self._parts if k < seq]
        for k in keys_to_delete:
            del self._parts[k]

    async def close(self) -> None:
        pass

    async def destroy(self) -> None:
        self._parts.clear()
        self._meta = None
        self._cursor = None


# ---------------------------------------------------------------------------
# Judge helpers
# ---------------------------------------------------------------------------


class AlwaysAcceptJudge:
    """Judge that always accepts."""

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict:
        return JudgeVerdict(action="ACCEPT")


class AlwaysRetryJudge:
    """Judge that always retries with feedback."""

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict:
        return JudgeVerdict(action="RETRY", feedback="Try harder.")


class CountingJudge:
    """Judge that retries N times then accepts."""

    def __init__(self, retry_count: int = 1):
        self._retry_count = retry_count
        self._calls = 0

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict:
        self._calls += 1
        if self._calls <= self._retry_count:
            return JudgeVerdict(action="RETRY", feedback=f"Retry {self._calls}")
        return JudgeVerdict(action="ACCEPT")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_llm(scripts: list[StreamScript] | None = None) -> LLMProvider:
    """Create an LLM provider based on the test mode."""
    if USE_MOCK_LLM:
        return ScriptableMockLLMProvider(scripts)
    # Real mode: use LiteLLM
    from framework.llm.litellm import LiteLLMProvider

    return LiteLLMProvider(model=LLM_MODEL)


def make_tool_executor(results_map: dict[str, str]) -> Callable:
    """Create a tool executor that returns predetermined results."""

    def executor(tool_use: ToolUse) -> ToolResult:
        content = results_map.get(tool_use.name, f"Unknown tool: {tool_use.name}")
        return ToolResult(
            tool_use_id=tool_use.id,
            content=content,
            is_error=tool_use.name not in results_map,
        )

    return executor


def make_ctx(
    node_id: str = "test_node",
    llm: LLMProvider | None = None,
    output_keys: list[str] | None = None,
    input_keys: list[str] | None = None,
    input_data: dict[str, Any] | None = None,
    system_prompt: str = "You are a test assistant.",
    client_facing: bool = False,
    available_tools: list[Tool] | None = None,
) -> NodeContext:
    """Build a NodeContext for direct EventLoopNode testing."""
    runtime = MagicMock(spec=Runtime)
    runtime.start_run = MagicMock(return_value="run_id")
    runtime.decide = MagicMock(return_value="dec_id")
    runtime.record_outcome = MagicMock()
    runtime.end_run = MagicMock()
    runtime.report_problem = MagicMock()
    runtime.set_node = MagicMock()

    spec = NodeSpec(
        id=node_id,
        name=f"Test {node_id}",
        description="test node",
        node_type="event_loop",
        output_keys=output_keys or [],
        input_keys=input_keys or [],
        system_prompt=system_prompt,
        client_facing=client_facing,
    )

    memory = SharedMemory()

    return NodeContext(
        runtime=runtime,
        node_id=node_id,
        node_spec=spec,
        memory=memory,
        input_data=input_data or {},
        llm=llm,
        available_tools=available_tools or [],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runtime():
    """Create a mock Runtime."""
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="test_run_id")
    rt.decide = MagicMock(return_value="test_decision_id")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.set_node = MagicMock()
    return rt


@pytest.fixture
def event_bus():
    """Create a real EventBus."""
    return EventBus()


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    """Mock asyncio.sleep to avoid real delays from exponential backoff."""
    monkeypatch.setattr("asyncio.sleep", AsyncMock())


# ===========================================================================
# Group 1: Core Lifecycle
# ===========================================================================


@pytest.mark.asyncio
async def test_event_loop_node_in_graph(runtime):
    """EventLoopNode runs inside GraphExecutor, produces output."""
    scripts = [
        # stream 1: call set_output("result", "ok")
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_1", "input": {"key": "result", "value": "ok"}}
            ],
        ),
        # stream 2: text finish (turn ends, implicit judge accepts because all keys present)
        StreamScript(text="Done."),
    ]
    llm = make_llm(scripts)

    node_spec = NodeSpec(
        id="el_node",
        name="Event Loop Node",
        description="test event loop",
        node_type="event_loop",
        output_keys=["result"],
    )
    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="el_node",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["el_node"],
    )
    goal = Goal(id="test_goal", name="Test Goal", description="test")

    executor = GraphExecutor(runtime=runtime, llm=llm)
    el_node = EventLoopNode(config=LoopConfig(max_iterations=5))
    executor.register_node("el_node", el_node)

    result = await executor.execute(graph, goal, {})

    assert result.success
    if USE_MOCK_LLM:
        assert result.output.get("result") == "ok"
    else:
        assert "result" in result.output


@pytest.mark.asyncio
async def test_event_loop_with_event_bus():
    """Lifecycle events are published correctly to EventBus."""
    recorded: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        recorded.append(event)

    bus = EventBus()
    bus.subscribe(
        event_types=[
            EventType.NODE_LOOP_STARTED,
            EventType.NODE_LOOP_ITERATION,
            EventType.NODE_LOOP_COMPLETED,
        ],
        handler=handler,
    )

    scripts = [StreamScript(text="All done.")]
    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=[])

    node = EventLoopNode(
        event_bus=bus,
        config=LoopConfig(max_iterations=5),
    )
    result = await node.execute(ctx)

    assert result.success

    event_types = [e.type for e in recorded]
    assert EventType.NODE_LOOP_STARTED in event_types
    assert EventType.NODE_LOOP_ITERATION in event_types
    assert EventType.NODE_LOOP_COMPLETED in event_types

    # Verify ordering: STARTED before ITERATION before COMPLETED
    started_idx = event_types.index(EventType.NODE_LOOP_STARTED)
    iteration_idx = event_types.index(EventType.NODE_LOOP_ITERATION)
    completed_idx = event_types.index(EventType.NODE_LOOP_COMPLETED)
    assert started_idx < iteration_idx < completed_idx


@pytest.mark.asyncio
async def test_event_loop_tool_execution():
    """Custom tools execute, results feed back to LLM."""
    recorded_events: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        recorded_events.append(event)

    bus = EventBus()
    bus.subscribe(
        event_types=[EventType.TOOL_CALL_STARTED, EventType.TOOL_CALL_COMPLETED],
        handler=handler,
    )

    scripts = [
        # stream 1: call search_crm tool
        StreamScript(
            tool_calls=[{"name": "search_crm", "id": "tc_crm", "input": {"query": "TechCorp"}}],
        ),
        # stream 2: call set_output with result
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_so",
                    "input": {"key": "result", "value": "Found: TechCorp"},
                }
            ],
        ),
        # stream 3: text finish
        StreamScript(text="Search complete."),
    ]
    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=["result"])

    search_tool = Tool(
        name="search_crm",
        description="Search CRM",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
    )
    ctx.available_tools = [search_tool]

    tool_executor = make_tool_executor({"search_crm": "Found: TechCorp"})

    node = EventLoopNode(
        event_bus=bus,
        tool_executor=tool_executor,
        config=LoopConfig(max_iterations=5),
    )
    result = await node.execute(ctx)

    assert result.success

    # Check tool events were published
    tool_event_types = [e.type for e in recorded_events]
    assert EventType.TOOL_CALL_STARTED in tool_event_types
    assert EventType.TOOL_CALL_COMPLETED in tool_event_types


# ===========================================================================
# Group 2: Output Collection
# ===========================================================================


@pytest.mark.asyncio
async def test_event_loop_set_output():
    """set_output tool sets values in NodeResult.output."""
    scripts = [
        # stream 1: set lead_score
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_1", "input": {"key": "lead_score", "value": "87"}}
            ],
        ),
        # stream 2: set company
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_2",
                    "input": {"key": "company", "value": "TechCorp"},
                }
            ],
        ),
        # stream 3: text finish
        StreamScript(text="Outputs set."),
    ]
    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=["lead_score", "company"])

    node = EventLoopNode(config=LoopConfig(max_iterations=5))
    result = await node.execute(ctx)

    assert result.success
    if USE_MOCK_LLM:
        assert result.output == {"lead_score": "87", "company": "TechCorp"}
    else:
        assert "lead_score" in result.output
        assert "company" in result.output
        assert len(result.output["lead_score"]) > 0
        assert len(result.output["company"]) > 0


@pytest.mark.asyncio
async def test_event_loop_missing_output_keys_retried():
    """Missing output keys trigger implicit judge retry."""
    scripts = [
        # Iteration 1: only set "score" (missing "reason")
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_1", "input": {"key": "score", "value": "87"}}
            ],
        ),
        StreamScript(text="Scored the lead."),
        # Iteration 2 (after implicit retry feedback): set "reason"
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_2",
                    "input": {"key": "reason", "value": "good fit"},
                }
            ],
        ),
        StreamScript(text="Complete."),
    ]
    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=["score", "reason"])

    node = EventLoopNode(config=LoopConfig(max_iterations=10))
    result = await node.execute(ctx)

    assert result.success
    assert "score" in result.output
    assert "reason" in result.output
    if USE_MOCK_LLM:
        assert result.output["score"] == "87"
        assert result.output["reason"] == "good fit"


# ===========================================================================
# Group 3: Compaction
# ===========================================================================


@pytest.mark.asyncio
async def test_event_loop_conversation_compaction():
    """Long conversations compact, output keys survive."""
    # Build enough scripts for 4 iterations (CountingJudge retries 3 times then accepts)
    scripts = []
    for i in range(4):
        scripts.append(
            StreamScript(
                tool_calls=[
                    {
                        "name": "set_output",
                        "id": f"tc_{i}",
                        "input": {"key": "result", "value": f"val_{i}"},
                    }
                ],
            )
        )
        scripts.append(StreamScript(text=f"Iteration {i} done. " + "x" * 200))

    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=["result"])

    judge = CountingJudge(retry_count=3)
    node = EventLoopNode(
        judge=judge,
        config=LoopConfig(max_iterations=10, max_history_tokens=200),
    )
    result = await node.execute(ctx)

    assert result.success
    assert "result" in result.output


# ===========================================================================
# Group 4: Crash Recovery
# ===========================================================================


@pytest.mark.asyncio
async def test_event_loop_checkpoint_and_restore():
    """Crash mid-loop, resume from checkpoint via ConversationStore."""
    store = MockConversationStore()

    # Phase 1: Run with max_iterations=2, judge always retries -> fails at max
    scripts_phase1 = [
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_p1", "input": {"key": "score", "value": "50"}}
            ],
        ),
        StreamScript(text="Phase 1 iter 0."),
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_p1b", "input": {"key": "score", "value": "60"}}
            ],
        ),
        StreamScript(text="Phase 1 iter 1."),
    ]
    llm1 = ScriptableMockLLMProvider(scripts_phase1)
    ctx1 = make_ctx(node_id="el_restore", llm=llm1, output_keys=["score", "reason"])

    node1 = EventLoopNode(
        judge=AlwaysRetryJudge(),
        config=LoopConfig(max_iterations=2),
        conversation_store=store,
    )
    result1 = await node1.execute(ctx1)

    # Phase 1 should fail (max iterations)
    assert not result1.success
    assert "max iterations" in result1.error.lower()

    # Store should have persisted data (meta + parts from conversation write-through)
    meta = await store.read_meta()
    assert meta is not None  # Conversation was persisted
    parts = await store.read_parts()
    assert len(parts) > 0  # Messages were written

    # The cursor may be overwritten by conversation's _persist (which writes {next_seq})
    # after _write_cursor (which writes {iteration, ...}). This is expected behavior:
    # the last write wins. What matters for restore is that meta and parts exist.

    # Phase 2: Resume with higher limit, implicit judge (accepts when all keys present).
    # The cursor's "outputs" may have been overwritten by conversation _persist,
    # so the accumulator may not have "score". Re-set both keys to be safe.
    scripts_phase2 = [
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_p2a", "input": {"key": "score", "value": "75"}}
            ],
        ),
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_p2b",
                    "input": {"key": "reason", "value": "recovered"},
                }
            ],
        ),
        StreamScript(text="Phase 2 done."),
    ]
    llm2 = ScriptableMockLLMProvider(scripts_phase2)
    ctx2 = make_ctx(node_id="el_restore", llm=llm2, output_keys=["score", "reason"])

    node2 = EventLoopNode(
        config=LoopConfig(max_iterations=10),
        conversation_store=store,
    )
    result2 = await node2.execute(ctx2)

    assert result2.success
    assert "score" in result2.output
    assert "reason" in result2.output


# ===========================================================================
# Group 5: External Injection
# ===========================================================================


@pytest.mark.asyncio
async def test_event_loop_external_injection():
    """inject_event() appears as user message in conversation."""
    store = MockConversationStore()

    scripts = [
        StreamScript(text="First response."),
        StreamScript(text="Second response after injection."),
    ]
    llm = ScriptableMockLLMProvider(scripts)
    ctx = make_ctx(llm=llm, output_keys=[])

    judge = CountingJudge(retry_count=1)  # RETRY once then ACCEPT
    node = EventLoopNode(
        judge=judge,
        config=LoopConfig(max_iterations=5),
        conversation_store=store,
    )

    # Run in a task so we can inject mid-execution
    async def run_with_injection():
        # Inject before running - will be drained at iteration start
        await node.inject_event("Priority: CEO email")
        return await node.execute(ctx)

    result = await run_with_injection()
    assert result.success

    # Check that the injection appeared in the stored messages
    parts = await store.read_parts()
    all_content = " ".join(p.get("content", "") for p in parts)
    assert "[External event]: Priority: CEO email" in all_content


# ===========================================================================
# Group 6: Pause/Resume
# ===========================================================================


@pytest.mark.asyncio
async def test_event_loop_pause_and_resume():
    """Pause triggers early return, resume continues."""
    store = MockConversationStore()

    # Phase 1: pause_requested=True -> immediate return
    scripts_phase1 = [
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_p",
                    "input": {"key": "partial", "value": "started"},
                }
            ],
        ),
        StreamScript(text="Should not reach here in phase 1."),
    ]
    llm1 = ScriptableMockLLMProvider(scripts_phase1)
    ctx1 = make_ctx(
        llm=llm1, output_keys=["partial", "final"], input_data={"pause_requested": True}
    )

    node1 = EventLoopNode(
        config=LoopConfig(max_iterations=5),
        conversation_store=store,
    )
    result1 = await node1.execute(ctx1)

    # Pause returns success immediately (before any LLM call)
    assert result1.success

    # Phase 2: Resume without pause
    scripts_phase2 = [
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_r1",
                    "input": {"key": "partial", "value": "resumed"},
                }
            ],
        ),
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_r2", "input": {"key": "final", "value": "done"}}
            ],
        ),
        StreamScript(text="Resume complete."),
    ]
    llm2 = ScriptableMockLLMProvider(scripts_phase2)
    ctx2 = make_ctx(llm=llm2, output_keys=["partial", "final"], input_data={})

    node2 = EventLoopNode(
        config=LoopConfig(max_iterations=10),
        conversation_store=store,
    )
    result2 = await node2.execute(ctx2)

    assert result2.success
    assert "final" in result2.output


# ===========================================================================
# Group 7: Executor Retry Enforcement
# ===========================================================================


class AlwaysFailsNode(NodeProtocol):
    """A test node that always fails (for retry enforcement testing)."""

    def __init__(self):
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(success=False, error=f"Permanent error (attempt {self.attempt_count})")


@pytest.mark.asyncio
async def test_event_loop_no_executor_retry(runtime):
    """Executor runs event_loop exactly once (no retry)."""
    node_spec = NodeSpec(
        id="el_fail",
        name="Failing Event Loop",
        description="event loop that fails",
        node_type="event_loop",
        max_retries=3,
        output_keys=["result"],
    )
    graph = GraphSpec(
        id="test_graph",
        goal_id="test_goal",
        name="Test Graph",
        entry_node="el_fail",
        nodes=[node_spec],
        edges=[],
        terminal_nodes=["el_fail"],
    )
    goal = Goal(id="test_goal", name="Test", description="test")

    executor = GraphExecutor(runtime=runtime)
    failing_node = AlwaysFailsNode()
    executor.register_node("el_fail", failing_node)

    result = await executor.execute(graph, goal, {})

    assert not result.success
    assert failing_node.attempt_count == 1  # Executor forced max_retries to 0


# ===========================================================================
# Group 8: Context Handoff
# ===========================================================================


@pytest.mark.asyncio
async def test_context_handoff_between_nodes(runtime):
    """Output from one event_loop feeds into next via shared memory."""
    # Enrichment node scripts: set lead_score
    enrichment_scripts = [
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_e", "input": {"key": "lead_score", "value": "92"}}
            ],
        ),
        StreamScript(text="Enrichment complete."),
    ]
    enrichment_llm = ScriptableMockLLMProvider(enrichment_scripts)

    # Strategy node scripts: set strategy
    strategy_scripts = [
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_s",
                    "input": {"key": "strategy", "value": "premium"},
                }
            ],
        ),
        StreamScript(text="Strategy determined."),
    ]
    enrichment_spec = NodeSpec(
        id="enrichment",
        name="Enrichment",
        description="Enrich lead data",
        node_type="event_loop",
        output_keys=["lead_score"],
    )
    strategy_spec = NodeSpec(
        id="strategy",
        name="Strategy",
        description="Determine strategy",
        node_type="event_loop",
        # Note: input_keys left empty so scoped memory allows reading all keys.
        # EventLoopNode._check_pause() reads "pause_requested" from memory,
        # and a restrictive scope would block it. The node still receives
        # lead_score via input_data mapping from the edge.
        output_keys=["strategy"],
    )

    graph = GraphSpec(
        id="handoff_graph",
        goal_id="test_goal",
        name="Handoff Graph",
        entry_node="enrichment",
        nodes=[enrichment_spec, strategy_spec],
        edges=[
            EdgeSpec(
                id="e_to_s",
                source="enrichment",
                target="strategy",
                condition=EdgeCondition.ON_SUCCESS,
            ),
        ],
        terminal_nodes=["strategy"],
    )
    goal = Goal(id="test_goal", name="Handoff Test", description="test context handoff")

    executor = GraphExecutor(runtime=runtime, llm=enrichment_llm)

    el_enrichment = EventLoopNode(config=LoopConfig(max_iterations=5))
    el_strategy = EventLoopNode(config=LoopConfig(max_iterations=5))

    executor.register_node("enrichment", el_enrichment)
    executor.register_node("strategy", el_strategy)

    # Override: the executor uses self.llm for all nodes, but EventLoopNode uses ctx.llm.
    # For this test, we need different LLMs per node. Since the executor passes self.llm
    # via context, and EventLoopNode uses ctx.llm, we need a workaround.
    # The simplest approach: use one LLM that serves both scripts sequentially.
    combined_scripts = enrichment_scripts + strategy_scripts
    combined_llm = ScriptableMockLLMProvider(combined_scripts)
    executor.llm = combined_llm

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert "lead_score" in result.output
    assert "strategy" in result.output
    if USE_MOCK_LLM:
        assert result.output["lead_score"] == "92"
        assert result.output["strategy"] == "premium"


# ===========================================================================
# Group 9: Client I/O
# ===========================================================================


@pytest.mark.asyncio
async def test_client_facing_node_streams_output():
    """Client-facing node emits CLIENT_OUTPUT_DELTA events."""
    recorded: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        recorded.append(event)

    bus = EventBus()
    bus.subscribe(
        event_types=[EventType.CLIENT_OUTPUT_DELTA, EventType.LLM_TEXT_DELTA],
        handler=handler,
    )

    scripts = [StreamScript(text="Hello, user!")]
    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=[], client_facing=True)

    node = EventLoopNode(
        event_bus=bus,
        config=LoopConfig(max_iterations=5),
    )
    result = await node.execute(ctx)

    assert result.success

    event_types = [e.type for e in recorded]
    assert EventType.CLIENT_OUTPUT_DELTA in event_types
    # Should NOT have LLM_TEXT_DELTA (that's for internal nodes)
    assert EventType.LLM_TEXT_DELTA not in event_types

    # Verify node_id is correct
    client_events = [e for e in recorded if e.type == EventType.CLIENT_OUTPUT_DELTA]
    assert all(e.node_id == "test_node" for e in client_events)


@pytest.mark.asyncio
async def test_internal_node_no_client_output():
    """Internal node emits LLM_TEXT_DELTA, not CLIENT_OUTPUT_DELTA."""
    recorded: list[AgentEvent] = []

    async def handler(event: AgentEvent) -> None:
        recorded.append(event)

    bus = EventBus()
    bus.subscribe(
        event_types=[EventType.CLIENT_OUTPUT_DELTA, EventType.LLM_TEXT_DELTA],
        handler=handler,
    )

    scripts = [StreamScript(text="Internal processing.")]
    llm = make_llm(scripts)
    ctx = make_ctx(llm=llm, output_keys=[], client_facing=False)

    node = EventLoopNode(
        event_bus=bus,
        config=LoopConfig(max_iterations=5),
    )
    result = await node.execute(ctx)

    assert result.success

    event_types = [e.type for e in recorded]
    assert EventType.LLM_TEXT_DELTA in event_types
    assert EventType.CLIENT_OUTPUT_DELTA not in event_types


# ===========================================================================
# Group 10: Full Pipeline
# ===========================================================================


@pytest.mark.asyncio
async def test_mixed_node_graph(runtime):
    """function -> event_loop -> function end-to-end."""

    # Function 1: write leads to memory
    def load_leads(**kwargs):
        return ["lead_A", "lead_B", "lead_C"]

    # Event loop: process leads, produce summary
    el_scripts = [
        StreamScript(
            tool_calls=[
                {
                    "name": "set_output",
                    "id": "tc_sum",
                    "input": {"key": "summary", "value": "3 leads processed"},
                }
            ],
        ),
        StreamScript(text="Processing complete."),
    ]
    el_llm = ScriptableMockLLMProvider(el_scripts)

    # Function 2: format final output
    def format_output(**kwargs):
        summary = kwargs.get("summary", "no summary")
        return f"Report: {summary}"

    # Node specs
    load_spec = NodeSpec(
        id="load",
        name="Load Leads",
        description="Load lead data",
        node_type="function",
        function="load_leads",
        output_keys=["leads"],
    )
    process_spec = NodeSpec(
        id="process",
        name="Process Leads",
        description="Process leads with LLM",
        node_type="event_loop",
        # input_keys left empty: EventLoopNode._check_pause() reads "pause_requested"
        # from memory, and a restrictive scope would block it. Data flows via input_data.
        output_keys=["summary"],
    )
    format_spec = NodeSpec(
        id="format",
        name="Format Output",
        description="Format final report",
        node_type="function",
        function="format_output",
        # input_keys left empty for same scoping reason with FunctionNode
        output_keys=["report"],
    )

    graph = GraphSpec(
        id="pipeline_graph",
        goal_id="test_goal",
        name="Pipeline Graph",
        entry_node="load",
        nodes=[load_spec, process_spec, format_spec],
        edges=[
            EdgeSpec(id="e1", source="load", target="process", condition=EdgeCondition.ON_SUCCESS),
            EdgeSpec(
                id="e2", source="process", target="format", condition=EdgeCondition.ON_SUCCESS
            ),
        ],
        terminal_nodes=["format"],
    )
    goal = Goal(id="test_goal", name="Pipeline Test", description="test full pipeline")

    executor = GraphExecutor(runtime=runtime, llm=el_llm)
    executor.register_function("load", load_leads)
    executor.register_node("process", EventLoopNode(config=LoopConfig(max_iterations=5)))
    executor.register_function("format", format_output)

    result = await executor.execute(graph, goal, {})

    assert result.success
    assert "summary" in result.output
    assert "report" in result.output
    if USE_MOCK_LLM:
        assert "3 leads processed" in result.output["summary"]


# ===========================================================================
# Group 11: Validation
# ===========================================================================


@pytest.mark.asyncio
async def test_fan_out_rejects_overlapping_output_keys(runtime):
    """Parallel event_loop nodes with same output_keys fail at execution.

    The GraphExecutor's parallel execution with overlapping keys uses
    last-wins memory strategy, which can cause data corruption.
    We verify the behavior is at least deterministic (both branches execute).
    """
    scripts_a = [
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_a", "input": {"key": "result", "value": "from_A"}}
            ],
        ),
        StreamScript(text="A done."),
    ]
    scripts_b = [
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_b", "input": {"key": "result", "value": "from_B"}}
            ],
        ),
        StreamScript(text="B done."),
    ]
    # Combined scripts: A's scripts then B's scripts
    combined = scripts_a + scripts_b

    source_spec = NodeSpec(
        id="source",
        name="Source",
        description="Source node",
        node_type="event_loop",
        output_keys=["trigger"],
    )
    branch_a_spec = NodeSpec(
        id="branch_a",
        name="Branch A",
        description="Parallel branch A",
        node_type="event_loop",
        output_keys=["result"],
    )
    branch_b_spec = NodeSpec(
        id="branch_b",
        name="Branch B",
        description="Parallel branch B",
        node_type="event_loop",
        output_keys=["result"],  # Same key as branch A
    )

    graph = GraphSpec(
        id="fanout_graph",
        goal_id="test_goal",
        name="Fan Out Graph",
        entry_node="source",
        nodes=[source_spec, branch_a_spec, branch_b_spec],
        edges=[
            EdgeSpec(
                id="e_a", source="source", target="branch_a", condition=EdgeCondition.ON_SUCCESS
            ),
            EdgeSpec(
                id="e_b", source="source", target="branch_b", condition=EdgeCondition.ON_SUCCESS
            ),
        ],
        terminal_nodes=["branch_a", "branch_b"],
    )
    goal = Goal(id="test_goal", name="Fanout Test", description="test fanout")

    # Source node: simple success
    source_scripts = [
        StreamScript(
            tool_calls=[
                {"name": "set_output", "id": "tc_src", "input": {"key": "trigger", "value": "go"}}
            ],
        ),
        StreamScript(text="Source done."),
    ]
    all_scripts = source_scripts + combined
    all_llm = ScriptableMockLLMProvider(all_scripts)

    executor = GraphExecutor(runtime=runtime, llm=all_llm)
    executor.register_node("source", EventLoopNode(config=LoopConfig(max_iterations=5)))
    executor.register_node("branch_a", EventLoopNode(config=LoopConfig(max_iterations=5)))
    executor.register_node("branch_b", EventLoopNode(config=LoopConfig(max_iterations=5)))

    result = await executor.execute(graph, goal, {})

    # GraphSpec.validate() catches overlapping output_keys on parallel
    # event_loop branches and rejects the graph before execution starts.
    assert not result.success
    assert "Invalid graph" in result.error


# ===========================================================================
# Group 12: Edge Cases
# ===========================================================================


@pytest.mark.asyncio
async def test_max_iterations_exceeded():
    """Loop hits max_iterations, returns failure."""
    scripts = [
        StreamScript(text="Response 1."),
        StreamScript(text="Response 2."),
        StreamScript(text="Response 3."),  # Extra safety
    ]
    llm = ScriptableMockLLMProvider(scripts)
    ctx = make_ctx(llm=llm, output_keys=[])

    node = EventLoopNode(
        judge=AlwaysRetryJudge(),
        config=LoopConfig(max_iterations=2),
    )
    result = await node.execute(ctx)

    assert not result.success
    assert "max iterations" in result.error.lower()


@pytest.mark.asyncio
async def test_stall_detection():
    """N identical responses trigger stall failure."""
    # 3 identical text responses will trigger stall (threshold=3)
    scripts = [
        StreamScript(text="I am stuck"),
        StreamScript(text="I am stuck"),
        StreamScript(text="I am stuck"),
        StreamScript(text="I am stuck"),  # Extra safety
    ]
    llm = ScriptableMockLLMProvider(scripts)
    ctx = make_ctx(llm=llm, output_keys=[])

    node = EventLoopNode(
        judge=AlwaysRetryJudge(),
        config=LoopConfig(stall_detection_threshold=3, max_iterations=10),
    )
    result = await node.execute(ctx)

    assert not result.success
    assert "stall" in result.error.lower()
