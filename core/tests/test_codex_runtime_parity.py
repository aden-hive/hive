from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.graph.goal import Goal
from framework.graph.node import NodeContext, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider, LLMResponse, Tool, ToolResult, ToolUse
from framework.runner.tool_registry import ToolRegistry
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runtime.core import Runtime
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.server.queen_orchestrator import _client_input_counts_as_planning_ask
from framework.tools.queen_lifecycle_tools import QueenPhaseState, register_queen_lifecycle_tools


class MockStreamingLLM(LLMProvider):
    """Mock LLM that replays deterministic stream scenarios."""

    def __init__(self, scenarios: list[list] | None = None):
        self.scenarios = scenarios or []
        self._call_index = 0

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools=None,
        max_tokens: int = 4096,
    ) -> AsyncIterator:
        if not self.scenarios:
            return
        events = self.scenarios[self._call_index % len(self.scenarios)]
        self._call_index += 1
        for event in events:
            yield event

    def complete(self, messages, system="", **kwargs) -> LLMResponse:
        return LLMResponse(content="Summary.", model="mock", stop_reason="stop")


def text_scenario(text: str, input_tokens: int = 10, output_tokens: int = 5) -> list:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(
            stop_reason="stop",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model="mock",
        ),
    ]


def tool_call_scenario(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_use_id: str = "call_1",
) -> list:
    return [
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input),
        FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"),
    ]


def multi_tool_call_scenario(*calls: tuple[str, dict[str, Any], str]) -> list:
    """Build a streamed turn with multiple tool calls before finish."""
    events = [
        ToolCallEvent(tool_use_id=tool_use_id, tool_name=tool_name, tool_input=tool_input)
        for tool_name, tool_input, tool_use_id in calls
    ]
    events.append(FinishEvent(stop_reason="tool_calls", input_tokens=10, output_tokens=5, model="mock"))
    return events


@pytest.fixture
def runtime():
    rt = MagicMock(spec=Runtime)
    rt.start_run = MagicMock(return_value="session_20250101_000000_codex01")
    rt.decide = MagicMock(return_value="dec_1")
    rt.record_outcome = MagicMock()
    rt.end_run = MagicMock()
    rt.report_problem = MagicMock()
    rt.set_node = MagicMock()
    return rt


@pytest.fixture
def memory():
    return SharedMemory()


def build_ctx(
    runtime,
    node_spec: NodeSpec,
    memory: SharedMemory,
    llm: LLMProvider,
    *,
    stream_id: str | None = None,
) -> NodeContext:
    return NodeContext(
        runtime=runtime,
        node_id=node_spec.id,
        node_spec=node_spec,
        memory=memory,
        input_data={},
        llm=llm,
        available_tools=[],
        goal_context="",
        stream_id=stream_id,
    )


def build_goal() -> Goal:
    return Goal(id="codex_goal", name="Codex parity", description="Codex parity repro")


def build_tool(name: str) -> Tool:
    return Tool(
        name=name,
        description=f"Tool {name}",
        parameters={"type": "object", "properties": {}},
    )


async def execute_registered_tool(executor, name: str, tool_input: dict[str, Any]) -> ToolResult:
    """Run a registered tool and await it when the executor is async."""
    result = executor(ToolUse(id=f"use_{name}", name=name, input=tool_input))
    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
        result = await result
    return result


@pytest.mark.asyncio
async def test_queen_auto_blocked_input_counts_as_planning_ask(runtime, memory):
    spec = NodeSpec(
        id="queen",
        name="Queen",
        description="Planning node",
        node_type="event_loop",
        output_keys=[],
        client_facing=True,
    )
    llm = MockStreamingLLM(
        scenarios=[text_scenario("I've isolated the root cause. What would you like to do next?")]
    )
    bus = EventBus()
    received = []

    async def capture(event):
        received.append(event)

    bus.subscribe([EventType.CLIENT_INPUT_REQUESTED], capture, filter_stream="queen")

    node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
    ctx = build_ctx(runtime, spec, memory, llm, stream_id="queen")

    async def shutdown():
        await asyncio.sleep(0.05)
        node.signal_shutdown()

    task = asyncio.create_task(shutdown())
    result = await node.execute(ctx)
    await task

    assert result.success is True
    assert len(received) == 1
    event = received[0]
    assert event.data["auto_blocked"] is True
    assert event.data["assistant_text_requires_input"] is True
    assert _client_input_counts_as_planning_ask(event) is True


@pytest.mark.asyncio
async def test_queen_ask_user_emits_result_text_before_question_widget(runtime, memory):
    spec = NodeSpec(
        id="queen",
        name="Queen",
        description="Planning node",
        node_type="event_loop",
        output_keys=[],
        client_facing=True,
    )
    llm = MockStreamingLLM(
        scenarios=[
            tool_call_scenario(
                "ask_user",
                {
                    "question": (
                        "Root cause: the database pool is exhausted.\n\n"
                        "What would you like to do next?"
                    ),
                    "options": ["Rerun", "Stop"],
                },
                tool_use_id="ask_1",
            )
        ]
    )
    bus = EventBus()
    output_events = []
    input_events = []

    async def capture_output(event):
        output_events.append(event)

    async def capture_input(event):
        input_events.append(event)

    bus.subscribe([EventType.CLIENT_OUTPUT_DELTA], capture_output, filter_stream="queen")
    bus.subscribe([EventType.CLIENT_INPUT_REQUESTED], capture_input, filter_stream="queen")

    node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
    ctx = build_ctx(runtime, spec, memory, llm, stream_id="queen")

    async def shutdown():
        await asyncio.sleep(0.05)
        node.signal_shutdown()

    task = asyncio.create_task(shutdown())
    result = await node.execute(ctx)
    await task

    assert result.success is True
    assert [event.data["snapshot"] for event in output_events] == [
        "Root cause: the database pool is exhausted."
    ]
    assert len(input_events) == 1
    assert input_events[0].data["prompt"] == "What would you like to do next?"
    assert input_events[0].data["options"] == ["Rerun", "Stop"]


@pytest.mark.asyncio
async def test_worker_auto_completes_after_duplicate_set_output(runtime, memory):
    spec = NodeSpec(
        id="worker",
        name="Worker",
        description="Internal worker node",
        node_type="event_loop",
        output_keys=["result"],
    )
    llm = MockStreamingLLM(
        scenarios=[
            [
                ToolCallEvent(
                    tool_use_id="set_1",
                    tool_name="set_output",
                    tool_input={"key": "result", "value": "done"},
                ),
                ToolCallEvent(
                    tool_use_id="set_2",
                    tool_name="set_output",
                    tool_input={"key": "result", "value": "done"},
                ),
                FinishEvent(
                    stop_reason="tool_calls",
                    input_tokens=10,
                    output_tokens=5,
                    model="mock",
                ),
            ]
        ]
    )

    node = EventLoopNode(config=LoopConfig(max_iterations=2, max_tool_calls_per_turn=3))
    ctx = build_ctx(runtime, spec, memory, llm, stream_id="worker")

    result = await node.execute(ctx)

    assert result.success is True
    assert result.output["result"] == "done"
    assert llm._call_index == 1


@pytest.mark.asyncio
async def test_queen_auto_blocked_planning_progresses_to_building(tmp_path, monkeypatch):
    """Codex-style text-only planning asks should still allow draft -> build progression."""
    monkeypatch.chdir(tmp_path)

    bus = EventBus()
    phase_state = QueenPhaseState(phase="planning", event_bus=bus)
    phase_events = []

    async def track_planning_asks(event: AgentEvent) -> None:
        if phase_state.phase != "planning":
            return
        if _client_input_counts_as_planning_ask(event):
            phase_state.planning_ask_rounds += 1

    async def capture_phase(event: AgentEvent) -> None:
        phase_events.append(event)

    bus.subscribe([EventType.CLIENT_INPUT_REQUESTED], track_planning_asks, filter_stream="queen")
    bus.subscribe([EventType.QUEEN_PHASE_CHANGED], capture_phase, filter_stream="queen")

    registry = ToolRegistry()
    recorded_init_inputs: dict[str, Any] = {}

    async def fake_initialize(inputs: dict[str, Any]) -> str:
        recorded_init_inputs.clear()
        recorded_init_inputs.update(inputs)
        return json.dumps({"success": True, "agent_name": inputs.get("agent_name", "")})

    registry.register(
        "initialize_and_build_agent",
        Tool(
            name="initialize_and_build_agent",
            description="Fake scaffolder for tests",
            parameters={"type": "object", "properties": {"agent_name": {"type": "string"}}},
        ),
        fake_initialize,
    )

    session = SimpleNamespace(
        id="session_codex",
        event_bus=bus,
        worker_runtime=None,
        worker_path=None,
        queen_executor=None,
        active_timer_tasks={},
        active_webhook_handlers={},
    )

    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id=session.id,
        phase_state=phase_state,
    )
    executor = registry.get_executor()

    auto_blocked = AgentEvent(
        type=EventType.CLIENT_INPUT_REQUESTED,
        stream_id="queen",
        data={"auto_blocked": True, "assistant_text_requires_input": True},
    )
    await bus.publish(auto_blocked)
    await bus.publish(auto_blocked)

    assert phase_state.planning_ask_rounds == 2

    draft_result = await execute_registered_tool(
        executor,
        "save_agent_draft",
        {
            "agent_name": "codex_runtime_agent",
            "goal": "Produce a runnable research graph",
            "nodes": [
                {"id": "intake", "name": "Intake", "description": "Clarify the user goal"},
                {
                    "id": "research",
                    "name": "Research",
                    "description": "Search for evidence and collect facts",
                },
                {
                    "id": "deep_fetch",
                    "name": "Deep Fetch",
                    "description": "Use a delegated sub-agent for deeper collection",
                    "node_type": "gcu",
                },
                {"id": "compile", "name": "Compile", "description": "Assemble the report"},
                {"id": "deliver", "name": "Deliver", "description": "Present the final answer"},
            ],
            "edges": [
                {"id": "e1", "source": "intake", "target": "research", "condition": "on_success"},
                {
                    "id": "e2",
                    "source": "research",
                    "target": "deep_fetch",
                    "condition": "on_success",
                },
                {"id": "e3", "source": "research", "target": "compile", "condition": "on_success"},
                {"id": "e4", "source": "compile", "target": "deliver", "condition": "on_success"},
            ],
        },
    )
    draft_payload = json.loads(draft_result.content)

    assert draft_payload["status"] == "draft_saved"
    assert draft_payload["node_count"] == 5
    assert phase_state.draft_graph is not None
    assert phase_state.draft_graph["entry_node"] == "intake"

    confirm_result = await execute_registered_tool(executor, "confirm_and_build", {})
    confirm_payload = json.loads(confirm_result.content)

    assert confirm_payload["status"] == "confirmed"
    assert confirm_payload["subagent_nodes_dissolved"] == 1
    assert phase_state.build_confirmed is True
    assert phase_state.draft_graph is not None
    assert all(node["id"] != "deep_fetch" for node in phase_state.draft_graph["nodes"])

    init_result = await execute_registered_tool(
        executor,
        "initialize_and_build_agent",
        {"agent_name": "codex_runtime_agent"},
    )
    init_payload = json.loads(init_result.content)

    assert init_payload["success"] is True
    assert phase_state.phase == "building"
    assert phase_state.agent_path is not None
    assert phase_state.agent_path.endswith("exports/codex_runtime_agent")
    assert recorded_init_inputs["agent_name"] == "codex_runtime_agent"
    assert "_draft" in recorded_init_inputs
    assert recorded_init_inputs["_draft"]["entry_node"] == "intake"
    assert all(node["id"] != "deep_fetch" for node in recorded_init_inputs["_draft"]["nodes"])
    assert phase_events[-1].data["phase"] == "building"


@pytest.mark.asyncio
async def test_codex_style_worker_graph_uses_tool_once_and_hands_off(runtime):
    """Repro class: real tool use + duplicate set_output should still reach the next node."""
    llm = MockStreamingLLM(
        scenarios=[
            multi_tool_call_scenario(
                ("set_output", {"key": "brief", "value": "past-week AI roundup"}, "brief_1"),
            ),
            multi_tool_call_scenario(
                ("exa_search", {"query": "AI news past week", "num_results": 3}, "search_1"),
                (
                    "set_output",
                    {"key": "articles_data", "value": json.dumps({"items": ["story-1", "story-2"]})},
                    "articles_1",
                ),
                (
                    "set_output",
                    {"key": "articles_data", "value": json.dumps({"items": ["story-1", "story-2"]})},
                    "articles_2",
                ),
            ),
            multi_tool_call_scenario(
                ("set_output", {"key": "report", "value": "final report"}, "report_1"),
            ),
        ]
    )

    graph = GraphSpec(
        id="codex_worker_graph",
        goal_id="codex_goal",
        entry_node="intake",
        nodes=[
            NodeSpec(
                id="intake",
                name="Intake",
                description="Capture the user's request",
                node_type="event_loop",
                output_keys=["brief"],
            ),
            NodeSpec(
                id="research",
                name="Research",
                description="Search and structure recent articles",
                node_type="event_loop",
                input_keys=["brief"],
                output_keys=["articles_data"],
                tools=["exa_search"],
            ),
            NodeSpec(
                id="compile",
                name="Compile",
                description="Produce the final report",
                node_type="event_loop",
                input_keys=["articles_data"],
                output_keys=["report"],
            ),
        ],
        edges=[
            EdgeSpec(id="e1", source="intake", target="research", condition=EdgeCondition.ON_SUCCESS),
            EdgeSpec(id="e2", source="research", target="compile", condition=EdgeCondition.ON_SUCCESS),
        ],
        terminal_nodes=["compile"],
        conversation_mode="continuous",
    )

    def tool_executor(tool_use: ToolUse) -> ToolResult:
        if tool_use.name == "exa_search":
            return ToolResult(
                tool_use_id=tool_use.id,
                content=json.dumps({"results": [{"title": "story-1"}, {"title": "story-2"}]}),
            )
        return ToolResult(
            tool_use_id=tool_use.id,
            content=json.dumps({"error": f"unexpected tool: {tool_use.name}"}),
            is_error=True,
        )

    executor = GraphExecutor(
        runtime=runtime,
        llm=llm,
        tools=[build_tool("exa_search")],
        tool_executor=tool_executor,
    )

    result = await executor.execute(graph=graph, goal=build_goal())

    assert result.success is True
    assert result.path == ["intake", "research", "compile"]
    assert result.output["brief"] == "past-week AI roundup"
    assert result.output["articles_data"] == {"items": ["story-1", "story-2"]}
    assert result.output["report"] == "final report"
    assert llm._call_index == 3
