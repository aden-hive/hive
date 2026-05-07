"""Regression test for fan-out TOCTOU race when multiple branches write same key.

This test ensures the new AsyncLockRegistry and guarded writes prevent two
concurrent fan-out branches from violating the configured conflict strategy
(``first_wins``). The test simulates two workers completing at the same time
and verifies only one writer wins the key claim.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest

from framework.orchestrator.node import NodeSpec, DataBuffer, NodeResult, NodeProtocol
from framework.orchestrator.edge import EdgeSpec, EdgeCondition, GraphSpec
from framework.orchestrator.context import GraphContext
from framework.tracker.decision_tracker import DecisionTracker
from framework.schemas.goal import Goal


class _MockNode(NodeProtocol):
    def __init__(self, out: dict[str, str], ready: asyncio.Event):
        self._out = out
        self._ready = ready

    async def execute(self, ctx):
        # Wait until both workers are ready to finish simultaneously
        await self._ready.wait()
        return NodeResult(success=True, output=self._out)


def test_fanout_writers_respect_first_wins(tmp_path: Path) -> None:
    async def _inner():
        # Build minimal graph with two target nodes that will both write 'conflict'
        a = NodeSpec(id="A", name="A", description="A", node_type="custom", output_keys=["conflict"]) 
        b = NodeSpec(id="B", name="B", description="B", node_type="custom", output_keys=["conflict"]) 
        g = GraphSpec(id="g", goal_id="g1", entry_node="A", nodes=[a, b], edges=[])

        # Build GraphContext
        buffer = DataBuffer()
        runtime = DecisionTracker(tmp_path / "dt")
        gc = GraphContext(
            graph=g,
            goal=Goal(id="g", name="g", description="g"),
            buffer=buffer,
            runtime=runtime,
            llm=None,
            tools=[],
            tool_executor=None,
            event_bus=None,
            execution_id="exec",
            stream_id="s",
            run_id="r",
            storage_path=tmp_path,
        )

        # Set parallel config to first_wins so second writer must not overwrite
        gc.parallel_config = SimpleNamespace(buffer_conflict_strategy="first_wins")

        # Prepare ready barrier so both nodes return at the same time
        ready = asyncio.Event()

        # Register simple node implementations
        gc.node_registry["A"] = _MockNode({"conflict": "from-A"}, ready)
        gc.node_registry["B"] = _MockNode({"conflict": "from-B"}, ready)

        # Create workers
        from framework.orchestrator.node_worker import NodeWorker, FanOutTag

        wa = NodeWorker(a, gc)
        wb = NodeWorker(b, gc)

        # Mark both as fan-out branches for the same fan_out_id
        tag_a = FanOutTag(fan_out_id="f1", fan_out_source="src", branches=frozenset({"A", "B"}), via_branch="A")
        tag_b = FanOutTag(fan_out_id="f1", fan_out_source="src", branches=frozenset({"A", "B"}), via_branch="B")

        wa.activate(inherited_tags=[tag_a])
        wb.activate(inherited_tags=[tag_b])

        # Let both workers proceed to finish at the same time
        await asyncio.sleep(0.05)
        ready.set()

        # Wait for both to complete
        await asyncio.wait_for(wa._task, timeout=5.0)
        await asyncio.wait_for(wb._task, timeout=5.0)

        # Validate that only one writer won the claim
        assert "conflict" in gc._fanout_written_keys
        writer = gc._fanout_written_keys["conflict"]
        assert writer in ("A", "B")
        val = gc.buffer.read("conflict")
        assert val in ("from-A", "from-B")

        # Ensure buffer value aligns with recorded writer
        if writer == "A":
            assert val == "from-A"
        else:
            assert val == "from-B"

    asyncio.run(_inner())
