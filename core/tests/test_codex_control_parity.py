from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock

import pytest

from framework.graph.event_loop_node import EventLoopNode, LoopConfig
from framework.graph.node import NodeContext, NodeSpec, SharedMemory
from framework.llm.provider import LLMProvider
from framework.llm.stream_events import FinishEvent, TextDeltaEvent, ToolCallEvent
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.server.queen_orchestrator import _client_input_counts_as_planning_ask
from framework.tools.queen_lifecycle_tools import QueenPhaseState


class MockStreamingLLM(LLMProvider):
    """Minimal streaming LLM for Codex-vs-control parity checks."""

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


def tool_call_scenario(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    tool_use_id: str = "call_1",
    preamble_text: str = "",
) -> list[Any]:
    events: list[Any] = []
    if preamble_text:
        events.append(TextDeltaEvent(content=preamble_text, snapshot=preamble_text))
    events.append(
        ToolCallEvent(
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_input=tool_input,
        )
    )
    events.append(
        FinishEvent(
            stop_reason="tool_calls",
            input_tokens=10,
            output_tokens=5,
            model="mock",
        )
    )
    return events


def build_ctx(spec: NodeSpec, llm: LLMProvider, *, stream_id: str) -> NodeContext:
    runtime = MagicMock()
    runtime.start_run = MagicMock(return_value=f"session_{stream_id}")
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
        input_data={},
        llm=llm,
        available_tools=[],
        stream_id=stream_id,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("style", "first_turn"),
    [
        (
            "control",
            tool_call_scenario(
                "ask_user",
                {
                    "question": "What kind of agent should I design for you?",
                    "options": ["Summarizer"],
                },
                tool_use_id="ask_1",
            ),
        ),
        (
            "codex",
            text_scenario("What kind of agent should I design for you?"),
        ),
    ],
)
async def test_codex_and_control_styles_both_count_toward_planning_gate(
    style: str,
    first_turn: list[Any],
) -> None:
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
    llm = MockStreamingLLM(scenarios=[first_turn])
    node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
    ctx = build_ctx(spec, llm, stream_id="queen")

    async def shutdown_after_first_block() -> None:
        await asyncio.sleep(0.05)
        node.signal_shutdown()

    task = asyncio.create_task(shutdown_after_first_block())
    result = await node.execute(ctx)
    await task

    assert result.success is True
    assert phase_state.planning_ask_rounds == 1
    assert received
    if style == "control":
        assert received[0].data["prompt"] == "What kind of agent should I design for you?"
        assert received[0].data.get("auto_blocked") is not True
    else:
        assert received[0].data["prompt"] == ""
        assert received[0].data["auto_blocked"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("style", "scenarios"),
    [
        (
            "control",
            [
                tool_call_scenario(
                    "ask_user",
                    {
                        "question": "Paste old and new policy text.",
                        "options": ["I'll paste both now"],
                    },
                    tool_use_id="ask_1",
                ),
                tool_call_scenario(
                    "set_output",
                    {
                        "key": "important_changes",
                        "value": "- Remote days increased from 2 to 4",
                    },
                    tool_use_id="set_1",
                ),
            ],
        ),
        (
            "codex",
            [
                text_scenario("Paste old and new policy text."),
                tool_call_scenario(
                    "set_output",
                    {
                        "key": "important_changes",
                        "value": "- Remote days increased from 2 to 4",
                    },
                    tool_use_id="set_1",
                ),
            ],
        ),
    ],
)
async def test_codex_and_control_styles_complete_same_human_in_loop_run(
    style: str,
    scenarios: list[list[Any]],
) -> None:
    spec = NodeSpec(
        id=f"policy_diff_{style}",
        name="Policy Diff Worker",
        description="Compare two policy versions",
        node_type="event_loop",
        output_keys=["important_changes"],
        client_facing=True,
    )
    llm = MockStreamingLLM(scenarios=scenarios)
    node = EventLoopNode(config=LoopConfig(max_iterations=6))
    ctx = build_ctx(spec, llm, stream_id=f"worker_{style}")

    async def user_responds() -> None:
        await asyncio.sleep(0.05)
        await node.inject_event("Old policy ... New policy ...")

    task = asyncio.create_task(user_responds())
    result = await node.execute(ctx)
    await task

    assert result.success is True
    assert result.output["important_changes"] == "- Remote days increased from 2 to 4"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("style", "scenario"),
    [
        (
            "control",
            tool_call_scenario(
                "ask_user",
                {"question": "What would you like to do next?", "options": ["Rerun", "Stop"]},
                tool_use_id="ask_1",
                preamble_text="Root cause: checkout is failing because the DB pool is exhausted.",
            ),
        ),
        (
            "codex",
            tool_call_scenario(
                "ask_user",
                {
                    "question": (
                        "Root cause: checkout is failing because the DB pool is exhausted.\n\n"
                        "What would you like to do next?"
                    ),
                    "options": ["Rerun", "Stop"],
                },
                tool_use_id="ask_1",
            ),
        ),
    ],
)
async def test_codex_and_control_styles_surface_result_before_followup_widget(
    style: str,
    scenario: list[Any],
) -> None:
    spec = NodeSpec(
        id=f"queen_{style}",
        name="Queen",
        description="orchestrator",
        node_type="event_loop",
        client_facing=True,
        output_keys=[],
        skip_judge=True,
    )
    llm = MockStreamingLLM(scenarios=[scenario])
    bus = EventBus()
    received: list[AgentEvent] = []

    async def capture(event: AgentEvent) -> None:
        received.append(event)

    bus.subscribe(
        event_types=[EventType.CLIENT_OUTPUT_DELTA, EventType.CLIENT_INPUT_REQUESTED],
        handler=capture,
    )

    node = EventLoopNode(event_bus=bus, config=LoopConfig(max_iterations=5))
    ctx = build_ctx(spec, llm, stream_id="queen")

    async def shutdown() -> None:
        await asyncio.sleep(0.05)
        node.signal_shutdown()

    task = asyncio.create_task(shutdown())
    await node.execute(ctx)
    await task

    output_events = [e for e in received if e.type == EventType.CLIENT_OUTPUT_DELTA]
    input_events = [e for e in received if e.type == EventType.CLIENT_INPUT_REQUESTED]

    assert output_events
    assert input_events
    assert "DB pool is exhausted" in output_events[0].data["snapshot"]
    assert input_events[0].data["prompt"] == "What would you like to do next?"
