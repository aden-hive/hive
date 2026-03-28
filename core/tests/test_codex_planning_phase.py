from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.graph.node import NodeContext, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider
from framework.llm.stream_events import FinishEvent, TextDeltaEvent
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.server.queen_orchestrator import _client_input_counts_as_planning_ask
from framework.tools.queen_lifecycle_tools import QueenPhaseState, register_queen_lifecycle_tools


class MockStreamingLLM(LLMProvider):
    """Minimal streaming LLM for planning-phase regression tests."""

    def __init__(self, scenarios: list[list[Any]] | None = None):
        self.scenarios = scenarios or []
        self._call_index = 0

    async def stream(
        self,
        messages: list[dict[str, Any]],
        system: str = "",
        tools=None,
        max_tokens: int = 4096,
    ):
        if not self.scenarios:
            return
        events = self.scenarios[self._call_index % len(self.scenarios)]
        self._call_index += 1
        for event in events:
            yield event

    def complete(self, messages, system="", **kwargs):
        raise NotImplementedError


def text_scenario(text: str) -> list[Any]:
    return [
        TextDeltaEvent(content=text, snapshot=text),
        FinishEvent(stop_reason="stop", input_tokens=10, output_tokens=5, model="mock"),
    ]


def build_ctx(spec: NodeSpec, llm: LLMProvider) -> NodeContext:
    runtime = MagicMock()
    runtime.start_run = MagicMock(return_value="session_codex_planning")
    runtime.decide = MagicMock(return_value="dec_1")
    runtime.record_outcome = MagicMock()
    runtime.end_run = MagicMock()
    runtime.report_problem = MagicMock()
    runtime.set_node = MagicMock()
    return NodeContext(
        runtime=runtime,
        node_id=spec.id,
        node_spec=spec,
        memory=SharedMemory(),
        input_data={"greeting": "Session started."},
        llm=llm,
        available_tools=[],
        stream_id="queen",
    )


@pytest.mark.asyncio
async def test_codex_style_text_only_planning_turn_counts_toward_ask_rounds() -> None:
    """Plain-text planning questions should satisfy the ask_rounds gate.

    This reproduces the Codex failure mode: the queen asks a planning question
    in plain text instead of calling ask_user(), which triggers an auto-blocked
    CLIENT_INPUT_REQUESTED event with an empty prompt.
    """
    bus = EventBus()
    phase_state = QueenPhaseState(phase="planning", event_bus=bus)
    received: list[AgentEvent] = []

    async def capture(event: AgentEvent) -> None:
        received.append(event)
        if _client_input_counts_as_planning_ask(event):
            phase_state.planning_ask_rounds += 1

    bus.subscribe([EventType.CLIENT_INPUT_REQUESTED], capture, filter_stream="queen")

    spec = NodeSpec(
        id="queen",
        name="Queen",
        description="planning orchestrator",
        node_type="event_loop",
        client_facing=True,
        output_keys=[],
        skip_judge=True,
    )
    llm = MockStreamingLLM(scenarios=[text_scenario("What kind of agent should I design for you?")])
    node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
    ctx = build_ctx(spec, llm)

    async def shutdown_after_first_block() -> None:
        await asyncio.sleep(0.05)
        node.signal_shutdown()

    task = asyncio.create_task(shutdown_after_first_block())
    result = await node.execute(ctx)
    await task

    assert result.success is True
    assert len(received) >= 1
    assert received[0].data["prompt"] == ""
    assert received[0].data["auto_blocked"] is True
    assert received[0].data["assistant_text_present"] is True
    assert received[0].data["assistant_text_requires_input"] is True
    assert phase_state.planning_ask_rounds == 1


@pytest.mark.asyncio
async def test_save_agent_draft_accepts_two_codex_style_planning_rounds() -> None:
    """Two counted auto-blocked planning turns should unlock save_agent_draft()."""
    phase_state = QueenPhaseState(phase="planning")

    codex_style_event = AgentEvent(
        type=EventType.CLIENT_INPUT_REQUESTED,
        stream_id="queen",
        data={
            "prompt": "",
            "auto_blocked": True,
            "assistant_text_present": True,
            "assistant_text_requires_input": True,
        },
    )
    for _ in range(2):
        if _client_input_counts_as_planning_ask(codex_style_event):
            phase_state.planning_ask_rounds += 1

    registry = ToolRegistry()
    session = SimpleNamespace(
        worker_runtime=None,
        event_bus=None,
        worker_path=None,
        runner=None,
    )
    register_queen_lifecycle_tools(
        registry,
        session=session,
        session_id="session_codex_planning",
        phase_state=phase_state,
    )

    save_draft = registry._tools["save_agent_draft"].executor
    result_raw = await save_draft(
        {
            "agent_name": "codex_planning_repro",
            "goal": "Reproduce the planning gate.",
            "nodes": [
                {"id": "start"},
                {"id": "discover"},
                {"id": "plan"},
                {"id": "review"},
                {"id": "finish"},
            ],
            "edges": [
                {"source": "start", "target": "discover"},
                {"source": "discover", "target": "plan"},
                {"source": "plan", "target": "review"},
                {"source": "review", "target": "finish"},
            ],
        }
    )
    result = json.loads(result_raw)

    assert phase_state.planning_ask_rounds == 2
    assert result["status"] == "draft_saved"


def test_status_only_auto_block_does_not_count_toward_planning_ask_rounds() -> None:
    """Auto-blocked acknowledgements should not satisfy the planning ask gate."""
    event = AgentEvent(
        type=EventType.CLIENT_INPUT_REQUESTED,
        stream_id="queen",
        data={
            "prompt": "",
            "auto_blocked": True,
            "assistant_text_present": True,
            "assistant_text_requires_input": False,
        },
    )

    assert _client_input_counts_as_planning_ask(event) is False
