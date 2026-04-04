"""Component tests: Escalation — worker escalate tool and event publishing.

Exercises the escalate synthetic tool to verify workers can signal
blockers that bubble up through the event bus.
"""

from __future__ import annotations

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.node import NodeSpec
from framework.runtime.event_bus import EventBus, EventType

from .conftest import make_executor


@pytest.mark.asyncio
async def test_escalation_worker_calls_escalate(runtime, goal, llm_provider, tmp_path, artifact):
    """Worker LLM should call the escalate tool when instructed.

    After calling escalate, the worker blocks waiting for queen input.
    Since there's no queen, we timeout and verify the event was emitted.
    """
    import asyncio as _asyncio

    from framework.graph.executor import GraphExecutor

    graph = GraphSpec(
        id="escalate-test",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Worker that must escalate",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "You MUST immediately call the escalate tool "
                    "with reason='need human approval for "
                    "deployment'. "
                    "Do not call set_output. Do not write text."
                ),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )

    event_bus = EventBus()
    escalations = []

    async def _capture_escalation(event):
        escalations.append(event)

    event_bus.subscribe(
        event_types=[EventType.ESCALATION_REQUESTED],
        handler=_capture_escalation,
    )

    executor = GraphExecutor(
        runtime=runtime,
        llm=llm_provider,
        loop_config={"max_iterations": 3},
        storage_path=tmp_path / "session",
        event_bus=event_bus,
        stream_id="worker",
    )

    # Worker will block after escalate. Short timeout is fine.
    try:
        await _asyncio.wait_for(
            executor.execute(
                graph,
                goal,
                {},
                validate_graph=False,
            ),
            timeout=30,
        )
    except TimeoutError:
        pass  # Expected: worker hangs waiting for queen

    artifact.record_value(
        "escalation_count",
        len(escalations),
        expected=">=1 ESCALATION_REQUESTED event emitted",
    )

    artifact.check(
        "escalation event emitted",
        len(escalations) >= 1,
        actual=str(len(escalations)),
        expected_val=">=1",
    )
    assert len(escalations) >= 1, "No ESCALATION_REQUESTED event emitted"


@pytest.mark.asyncio
async def test_escalation_node_terminates(runtime, goal, llm_provider, tmp_path, artifact):
    """Worker that escalates should still terminate (not hang forever)."""
    graph = GraphSpec(
        id="escalate-terminate",
        goal_id="dummy",
        entry_node="worker",
        entry_points={"start": "worker"},
        terminal_nodes=["worker"],
        nodes=[
            NodeSpec(
                id="worker",
                name="Worker",
                description="Escalate then finish",
                node_type="event_loop",
                output_keys=["result"],
                system_prompt=(
                    "Call the escalate tool with "
                    "reason='blocked on credentials'. "
                    "Then call set_output with key='result' "
                    "and value='escalated'."
                ),
            ),
        ],
        edges=[],
        memory_keys=["result"],
        conversation_mode="continuous",
    )
    executor = make_executor(
        runtime,
        llm_provider,
        loop_config={"max_iterations": 5},
        storage_path=tmp_path / "session",
    )
    result = await executor.execute(
        graph,
        goal,
        {},
        validate_graph=False,
    )
    artifact.record(
        result,
        expected="steps_executed=1 (terminates, does not hang)",
    )

    artifact.check(
        "steps_executed is 1",
        result.steps_executed == 1,
        actual=str(result.steps_executed),
        expected_val="1",
    )
    assert result.steps_executed == 1
