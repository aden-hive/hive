"""Integration tests for Execution Intelligence runtime wiring."""

import asyncio
import json
from datetime import datetime

import pytest

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import NodeSpec
from framework.llm.mock import MockLLMProvider
from framework.runtime.agent_runtime import AgentRuntime, AgentRuntimeConfig
from framework.runtime.execution_stream import EntryPointSpec


def _run(coro):
    return asyncio.run(coro)


def _build_minimal_graph() -> GraphSpec:
    node = NodeSpec(
        id="single",
        name="Single Node",
        description="Single-node deterministic test graph",
        node_type="event_loop",
        input_keys=["prompt"],
        output_keys=[],
        system_prompt="Reply briefly.",
        max_retries=0,
    )

    return GraphSpec(
        id="trace-int-graph",
        goal_id="trace-int-goal",
        version="1.0.0",
        entry_node="single",
        entry_points={"start": "single"},
        terminal_nodes=["single"],
        pause_nodes=[],
        nodes=[node],
        edges=[],
        max_steps=5,
        max_tokens=128,
    )


def _build_goal() -> Goal:
    return Goal(
        id="trace-int-goal",
        name="Trace Integration Goal",
        description="Validate execution trace integration end-to-end",
    )


async def _run_runtime_once(tmp_path, monkeypatch=None, force_node_exception: bool = False):
    graph = _build_minimal_graph()
    goal = _build_goal()

    if force_node_exception:
        from framework.graph.event_loop_node import EventLoopNode

        async def _failing_execute(self, ctx):
            raise RuntimeError("forced-node-error")

        monkeypatch.setattr(EventLoopNode, "execute", _failing_execute)

    runtime = AgentRuntime(
        graph=graph,
        goal=goal,
        storage_path=tmp_path,
        llm=MockLLMProvider(),
        config=AgentRuntimeConfig(enable_execution_trace=True),
    )

    runtime.register_entry_point(
        EntryPointSpec(
            id="manual",
            name="Manual",
            entry_node="single",
            trigger_type="manual",
        )
    )

    await runtime.start()
    try:
        execution_id = await runtime.trigger("manual", {"prompt": "hello"})
        stream = runtime.get_stream("manual")
        assert stream is not None
        result = await stream.wait_for_completion(execution_id, timeout=5)
        assert result is not None
        return execution_id, result.success
    finally:
        await runtime.stop()


def _load_trace_payload(tmp_path, execution_id: str) -> dict:
    trace_path = tmp_path / "sessions" / execution_id / "execution_trace.json"
    assert trace_path.exists(), f"Trace file missing: {trace_path}"
    return json.loads(trace_path.read_text(encoding="utf-8"))


def _parse_iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts)


def test_execution_trace_integration_success(tmp_path):
    execution_id, was_success = _run(_run_runtime_once(tmp_path))
    assert was_success is True

    payload = _load_trace_payload(tmp_path, execution_id)

    assert isinstance(payload.get("execution_id"), str)
    assert payload["execution_id"] == execution_id
    assert isinstance(payload.get("spans"), list)

    spans = payload["spans"]
    assert spans, "Expected at least one span"

    root_spans = [s for s in spans if s["parent_id"] is None]
    assert len(root_spans) == 1
    graph_span = root_spans[0]
    assert graph_span["name"] == "graph_execution"

    node_spans = [s for s in spans if s["name"] == "node_execution"]
    assert len(node_spans) == 1
    node_span = node_spans[0]
    assert node_span["parent_id"] == graph_span["id"]

    llm_spans = [s for s in spans if s["name"] == "llm_call"]
    assert len(llm_spans) >= 1
    assert any(s["parent_id"] == node_span["id"] for s in llm_spans)

    for span in spans:
        assert span["status"] == "success"
        assert _parse_iso(span["start_time"]) < _parse_iso(span["end_time"])


def test_execution_trace_integration_failure_sets_error_status(tmp_path, monkeypatch):
    execution_id, was_success = _run(
        _run_runtime_once(tmp_path, monkeypatch=monkeypatch, force_node_exception=True)
    )
    assert was_success is False

    payload = _load_trace_payload(tmp_path, execution_id)
    spans = payload["spans"]

    node_spans = [s for s in spans if s["name"] == "node_execution"]
    assert len(node_spans) == 1
    assert node_spans[0]["status"] == "error"

    assert any(s["status"] == "error" for s in spans)
