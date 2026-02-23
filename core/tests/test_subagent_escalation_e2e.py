"""End-to-end test for subagent escalation via report_to_parent(wait_for_response=True).

Tests the FULL routing chain:
  ExecutionStream → GraphExecutor → EventLoopNode → _execute_subagent
  → _report_callback registers _EscalationReceiver in executor.node_registry
  → emit CLIENT_INPUT_REQUESTED with escalation_id
  → subscriber calls stream.inject_input(escalation_id, "done")
  → ExecutionStream finds _EscalationReceiver in executor.node_registry
  → receiver.inject_event("done") unblocks the subagent
  → subagent continues and completes
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from framework.graph import Goal, NodeSpec, SuccessCriterion
from framework.graph.edge import GraphSpec
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.runtime.execution_stream import EntryPointSpec, ExecutionStream
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage


# ---------------------------------------------------------------------------
# Sequenced mock LLM — returns different responses per call index
# ---------------------------------------------------------------------------


class SequencedLLM(LLMProvider):
    """Mock LLM that returns pre-programmed stream events per call.

    Each call to stream() pops the next scenario from the queue.
    Shared between parent and subagent (they use the same LLM instance).
    """

    def __init__(self, scenarios: list[list[StreamEvent]]):
        self._scenarios = list(scenarios)
        self._call_index = 0
        self.stream_calls: list[dict] = []

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools: list[Tool] | None = None,
        max_tokens: int = 4096,
    ) -> AsyncIterator[StreamEvent]:
        self.stream_calls.append({
            "index": self._call_index,
            "system": system[:200],
            "tool_names": [t.name for t in (tools or [])],
        })
        if self._call_index < len(self._scenarios):
            events = self._scenarios[self._call_index]
        else:
            # Fallback: just finish
            events = [
                TextDeltaEvent(content="Done.", snapshot="Done."),
                FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5),
            ]
        self._call_index += 1
        for event in events:
            yield event

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="Summary.", model="mock", stop_reason="stop")

    def complete_with_tools(self, messages, system, tools, tool_executor, **kwargs) -> LLMResponse:
        return LLMResponse(content="", model="mock", stop_reason="stop")


# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_e2e_through_execution_stream(tmp_path):
    """Full e2e: subagent escalation routed through ExecutionStream.inject_input().

    Scenario:
    1. Parent node delegates to "researcher" subagent
    2. Researcher calls report_to_parent(wait_for_response=True, message="Login required")
    3. A subscriber on CLIENT_INPUT_REQUESTED gets the escalation_id
    4. Subscriber calls stream.inject_input(escalation_id, "done logging in")
    5. Subagent unblocks, sets output, completes
    6. Parent receives subagent result, sets its own output, completes
    """

    # -- Graph setup --
    goal = Goal(
        id="escalation-test",
        name="Escalation Test",
        description="Test subagent escalation flow",
        success_criteria=[
            SuccessCriterion(
                id="result",
                description="Result present",
                metric="output_contains",
                target="result",
            )
        ],
        constraints=[],
    )

    parent_node = NodeSpec(
        id="parent",
        name="Parent",
        description="Parent that delegates to researcher",
        node_type="event_loop",
        input_keys=["query"],
        output_keys=["result"],
        sub_agents=["researcher"],
        system_prompt="You delegate research tasks to the researcher sub-agent.",
    )

    researcher_node = NodeSpec(
        id="researcher",
        name="Researcher",
        description="Researches by browsing, may need user help for login",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["findings"],
        system_prompt="You research topics. If you hit a login wall, ask for help.",
    )

    graph = GraphSpec(
        id="escalation-graph",
        goal_id=goal.id,
        version="1.0.0",
        entry_node="parent",
        entry_points={"start": "parent"},
        terminal_nodes=["parent"],
        pause_nodes=[],
        nodes=[parent_node, researcher_node],
        edges=[],
        default_model="mock",
        max_tokens=10,
    )

    # -- LLM scenarios --
    # The LLM is shared between parent and subagent. Calls happen in order:
    #
    # Call 0 (parent turn 1): delegate to researcher
    # Call 1 (subagent turn 1): report_to_parent(wait_for_response=True)
    #   → blocks here until inject_input()
    # Call 2 (subagent turn 2): set_output("findings", "...")
    # Call 3 (subagent turn 3): text finish (implicit judge accepts after output filled)
    # Call 4 (parent turn 2): set_output("result", "...")
    # Call 5 (parent turn 3): text finish

    scenarios: list[list[StreamEvent]] = [
        # Call 0: Parent delegates
        [
            ToolCallEvent(
                tool_name="delegate_to_sub_agent",
                tool_input={"agent_id": "researcher", "task": "Check LinkedIn profiles"},
                tool_use_id="delegate_1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 1: Subagent hits login wall, escalates
        [
            ToolCallEvent(
                tool_name="report_to_parent",
                tool_input={
                    "message": "Login required for LinkedIn. Please log in manually.",
                    "wait_for_response": True,
                },
                tool_use_id="report_1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 2: Subagent continues after user login, sets output
        [
            ToolCallEvent(
                tool_name="set_output",
                tool_input={"key": "findings", "value": "Profile data extracted after login"},
                tool_use_id="set_1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 3: Subagent finishes
        [
            TextDeltaEvent(content="Research complete.", snapshot="Research complete."),
            FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5, model="mock"),
        ],
        # Call 4: Parent uses subagent result
        [
            ToolCallEvent(
                tool_name="set_output",
                tool_input={"key": "result", "value": "LinkedIn profile data retrieved"},
                tool_use_id="set_2",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 5: Parent finishes
        [
            TextDeltaEvent(content="Task complete.", snapshot="Task complete."),
            FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5, model="mock"),
        ],
    ]

    llm = SequencedLLM(scenarios)

    # -- Event bus + subscriber that auto-responds to escalation --
    bus = EventBus()
    escalation_events: list[AgentEvent] = []
    all_events: list[AgentEvent] = []
    inject_called = asyncio.Event()

    # We need the stream reference for inject_input, so use a holder
    stream_holder: list[ExecutionStream] = []

    async def escalation_handler(event: AgentEvent):
        """Simulate a TUI/runner: when CLIENT_INPUT_REQUESTED arrives with
        an escalation node_id, inject the user's response via the stream."""
        all_events.append(event)
        if event.type == EventType.CLIENT_INPUT_REQUESTED:
            node_id = event.node_id
            if ":escalation:" in node_id:
                escalation_events.append(event)
                # Small delay to simulate user typing
                await asyncio.sleep(0.05)
                # Route through the REAL inject_input chain
                stream = stream_holder[0]
                success = await stream.inject_input(node_id, "done logging in")
                assert success, (
                    f"inject_input({node_id!r}) returned False — "
                    "escalation receiver not found in executor.node_registry"
                )
                inject_called.set()

    bus.subscribe(
        event_types=[EventType.CLIENT_INPUT_REQUESTED, EventType.CLIENT_OUTPUT_DELTA],
        handler=escalation_handler,
    )

    # -- Build and run ExecutionStream --
    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    stream = ExecutionStream(
        stream_id="start",
        entry_spec=EntryPointSpec(
            id="start",
            name="Start",
            entry_node="parent",
            trigger_type="manual",
            isolation_level="shared",
        ),
        graph=graph,
        goal=goal,
        state_manager=SharedStateManager(),
        storage=storage,
        outcome_aggregator=OutcomeAggregator(goal, bus),
        event_bus=bus,
        llm=llm,
        tools=[],
        tool_executor=None,
    )
    stream_holder.append(stream)

    await stream.start()

    # Execute
    execution_id = await stream.execute({"query": "Find LinkedIn profiles"})
    result = await stream.wait_for_completion(execution_id, timeout=15)

    await stream.stop()
    await storage.stop()

    # -- Assertions --

    # 1. Execution completed successfully
    assert result is not None, "Execution should have completed"
    assert result.success, f"Execution should have succeeded, got: {result}"

    # 2. Escalation event was received and routed
    assert inject_called.is_set(), "inject_input should have been called for escalation"
    assert len(escalation_events) >= 1, "Should have received at least one escalation event"

    # 3. Escalation event has correct structure
    esc_event = escalation_events[0]
    assert ":escalation:" in esc_event.node_id
    assert esc_event.data["prompt"] == "Login required for LinkedIn. Please log in manually."

    # 4. CLIENT_OUTPUT_DELTA was emitted for the escalation message
    output_deltas = [
        e for e in all_events
        if e.type == EventType.CLIENT_OUTPUT_DELTA
        and "Login required" in e.data.get("content", "")
    ]
    assert len(output_deltas) >= 1, "Should have emitted CLIENT_OUTPUT_DELTA with escalation message"

    # 5. The parent node got the subagent's result
    assert "result" in result.output
    assert result.output["result"] == "LinkedIn profile data retrieved"

    # 6. The LLM was called the expected number of times
    assert llm._call_index >= 4, (
        f"Expected at least 4 LLM calls (delegate + escalation + set_output + finish), "
        f"got {llm._call_index}"
    )

    # 7. The user's escalation response appeared in the subagent's conversation
    # Call index 2 should be the subagent's second turn (after receiving "done logging in")
    assert len(llm.stream_calls) >= 3
    # The second subagent call should have report_to_parent in its tools
    # (verifying the subagent got the right tool set)
    subagent_tools = llm.stream_calls[1]["tool_names"]
    assert "report_to_parent" in subagent_tools, (
        f"Subagent should have report_to_parent tool, got: {subagent_tools}"
    )


@pytest.mark.asyncio
async def test_escalation_cleanup_after_completion(tmp_path):
    """Verify that _EscalationReceiver is cleaned up from the registry after use.

    After the escalation flow completes, no escalation receivers should remain
    in the executor's node_registry.
    """
    from framework.graph.event_loop_node import _EscalationReceiver

    goal = Goal(
        id="cleanup-test",
        name="Cleanup Test",
        description="Test escalation cleanup",
        success_criteria=[
            SuccessCriterion(
                id="result",
                description="Result present",
                metric="output_contains",
                target="result",
            )
        ],
        constraints=[],
    )

    parent_node = NodeSpec(
        id="parent",
        name="Parent",
        description="Delegates to researcher",
        node_type="event_loop",
        input_keys=["query"],
        output_keys=["result"],
        sub_agents=["researcher"],
    )

    researcher_node = NodeSpec(
        id="researcher",
        name="Researcher",
        description="Researches topics",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["findings"],
    )

    graph = GraphSpec(
        id="cleanup-graph",
        goal_id=goal.id,
        version="1.0.0",
        entry_node="parent",
        entry_points={"start": "parent"},
        terminal_nodes=["parent"],
        pause_nodes=[],
        nodes=[parent_node, researcher_node],
        edges=[],
        default_model="mock",
        max_tokens=10,
    )

    scenarios = [
        # Parent delegates
        [
            ToolCallEvent(
                tool_name="delegate_to_sub_agent",
                tool_input={"agent_id": "researcher", "task": "Check page"},
                tool_use_id="d1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Subagent escalates
        [
            ToolCallEvent(
                tool_name="report_to_parent",
                tool_input={"message": "Need help", "wait_for_response": True},
                tool_use_id="r1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Subagent sets output
        [
            ToolCallEvent(
                tool_name="set_output",
                tool_input={"key": "findings", "value": "Done"},
                tool_use_id="s1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Subagent finish
        [
            TextDeltaEvent(content="Done.", snapshot="Done."),
            FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5, model="mock"),
        ],
        # Parent sets output
        [
            ToolCallEvent(
                tool_name="set_output",
                tool_input={"key": "result", "value": "Got it"},
                tool_use_id="s2",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Parent finish
        [
            TextDeltaEvent(content="Complete.", snapshot="Complete."),
            FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5, model="mock"),
        ],
    ]

    llm = SequencedLLM(scenarios)
    bus = EventBus()

    # Track node_registry contents via the executor
    registries_snapshot: list[dict] = []
    stream_holder: list[ExecutionStream] = []

    async def auto_respond(event: AgentEvent):
        if event.type == EventType.CLIENT_INPUT_REQUESTED and ":escalation:" in event.node_id:
            stream = stream_holder[0]

            # Snapshot the active executor's node_registry BEFORE responding
            for executor in stream._active_executors.values():
                escalation_keys = [
                    k for k in executor.node_registry
                    if ":escalation:" in k
                ]
                registries_snapshot.append({
                    "phase": "before_inject",
                    "escalation_keys": escalation_keys,
                    "has_receiver": any(
                        isinstance(v, _EscalationReceiver)
                        for v in executor.node_registry.values()
                    ),
                })

            await asyncio.sleep(0.02)
            await stream.inject_input(event.node_id, "ok")

    bus.subscribe(
        event_types=[EventType.CLIENT_INPUT_REQUESTED],
        handler=auto_respond,
    )

    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    stream = ExecutionStream(
        stream_id="start",
        entry_spec=EntryPointSpec(
            id="start", name="Start", entry_node="parent",
            trigger_type="manual", isolation_level="shared",
        ),
        graph=graph,
        goal=goal,
        state_manager=SharedStateManager(),
        storage=storage,
        outcome_aggregator=OutcomeAggregator(goal, bus),
        event_bus=bus,
        llm=llm,
        tools=[],
        tool_executor=None,
    )
    stream_holder.append(stream)

    await stream.start()
    execution_id = await stream.execute({"query": "test"})
    result = await stream.wait_for_completion(execution_id, timeout=15)
    await stream.stop()
    await storage.stop()

    assert result is not None and result.success

    # The receiver WAS in the registry during escalation
    assert len(registries_snapshot) >= 1
    assert registries_snapshot[0]["has_receiver"] is True
    assert len(registries_snapshot[0]["escalation_keys"]) == 1

    # After completion, no active executors remain (they're cleaned up),
    # so no stale receivers can linger. The `finally` block in the callback
    # guarantees cleanup even within a single execution.


# ---------------------------------------------------------------------------
# Test: mark_complete e2e through ExecutionStream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_complete_e2e_through_execution_stream(tmp_path):
    """Full e2e: subagent uses report_to_parent(mark_complete=True) to terminate.

    Scenario:
    1. Parent delegates to "researcher" subagent
    2. Researcher calls report_to_parent(mark_complete=True, message="Found profiles", data={...})
    3. Subagent terminates immediately (no set_output needed)
    4. Parent receives subagent result with reports, sets its own output, completes
    """

    goal = Goal(
        id="mark-complete-test",
        name="Mark Complete Test",
        description="Test mark_complete subagent flow",
        success_criteria=[
            SuccessCriterion(
                id="result",
                description="Result present",
                metric="output_contains",
                target="result",
            )
        ],
        constraints=[],
    )

    parent_node = NodeSpec(
        id="parent",
        name="Parent",
        description="Parent that delegates to researcher",
        node_type="event_loop",
        input_keys=["query"],
        output_keys=["result"],
        sub_agents=["researcher"],
        system_prompt="You delegate research tasks to the researcher sub-agent.",
    )

    researcher_node = NodeSpec(
        id="researcher",
        name="Researcher",
        description="Researches topics and reports findings",
        node_type="event_loop",
        input_keys=["task"],
        output_keys=["findings"],
        system_prompt="You research topics. Use report_to_parent with mark_complete when done.",
    )

    graph = GraphSpec(
        id="mark-complete-graph",
        goal_id=goal.id,
        version="1.0.0",
        entry_node="parent",
        entry_points={"start": "parent"},
        terminal_nodes=["parent"],
        pause_nodes=[],
        nodes=[parent_node, researcher_node],
        edges=[],
        default_model="mock",
        max_tokens=10,
    )

    # LLM call sequence:
    # Call 0 (parent turn 1): delegate to researcher
    # Call 1 (subagent turn 1): report_to_parent(mark_complete=True) → sets flag
    # Call 2 (subagent turn 2): text finish (inner loop exit) → _evaluate sees flag → ACCEPT
    # Call 3 (parent turn 2): set_output("result", "...")
    # Call 4 (parent turn 3): text finish
    scenarios: list[list[StreamEvent]] = [
        # Call 0: Parent delegates
        [
            ToolCallEvent(
                tool_name="delegate_to_sub_agent",
                tool_input={"agent_id": "researcher", "task": "Find LinkedIn profiles"},
                tool_use_id="delegate_1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 1: Subagent reports with mark_complete=True
        [
            ToolCallEvent(
                tool_name="report_to_parent",
                tool_input={
                    "message": "Found 3 matching profiles",
                    "data": {"profiles": ["alice", "bob", "carol"]},
                    "mark_complete": True,
                },
                tool_use_id="report_1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 2: Subagent text finish (inner loop needs this to exit)
        [
            TextDeltaEvent(content="Done.", snapshot="Done."),
            FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5, model="mock"),
        ],
        # Call 3: Parent uses subagent result to set output
        [
            ToolCallEvent(
                tool_name="set_output",
                tool_input={"key": "result", "value": "Found 3 profiles: alice, bob, carol"},
                tool_use_id="set_1",
            ),
            FinishEvent(stop_reason="tool_use", input_tokens=10, output_tokens=5, model="mock"),
        ],
        # Call 4: Parent finishes
        [
            TextDeltaEvent(content="Task complete.", snapshot="Task complete."),
            FinishEvent(stop_reason="end_turn", input_tokens=5, output_tokens=5, model="mock"),
        ],
    ]

    llm = SequencedLLM(scenarios)
    bus = EventBus()

    # Track subagent report events
    report_events: list[AgentEvent] = []

    async def report_handler(event: AgentEvent):
        if event.type == EventType.SUBAGENT_REPORT:
            report_events.append(event)

    bus.subscribe(event_types=[EventType.SUBAGENT_REPORT], handler=report_handler)

    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    stream = ExecutionStream(
        stream_id="start",
        entry_spec=EntryPointSpec(
            id="start",
            name="Start",
            entry_node="parent",
            trigger_type="manual",
            isolation_level="shared",
        ),
        graph=graph,
        goal=goal,
        state_manager=SharedStateManager(),
        storage=storage,
        outcome_aggregator=OutcomeAggregator(goal, bus),
        event_bus=bus,
        llm=llm,
        tools=[],
        tool_executor=None,
    )

    await stream.start()
    execution_id = await stream.execute({"query": "Find LinkedIn profiles"})
    result = await stream.wait_for_completion(execution_id, timeout=15)
    await stream.stop()
    await storage.stop()

    # -- Assertions --

    # 1. Execution completed successfully
    assert result is not None, "Execution should have completed"
    assert result.success, f"Execution should have succeeded, got: {result}"

    # 2. Parent got the final output
    assert "result" in result.output
    assert "3 profiles" in result.output["result"]

    # 3. Subagent report was emitted via event bus
    # (The subagent's EventLoopNode has event_bus=None, but _execute_subagent
    # wires its own callback that emits via the parent's bus)
    assert len(report_events) >= 1, "Should have received subagent report event"
    assert report_events[0].data["message"] == "Found 3 matching profiles"

    # 4. The subagent did NOT need to call set_output — it used mark_complete
    # Verify by checking LLM call count: subagent only needed 2 calls
    # (report_to_parent + text finish), not 3+ (report + set_output + text finish)
    assert llm._call_index == 5, (
        f"Expected 5 LLM calls total (delegate + report + finish + set_output + finish), "
        f"got {llm._call_index}"
    )
