"""Tests for TOCTOU race condition fix in fan-out write conflict check.

Covers #7125: two concurrent fan-out workers can both pass the
``_fanout_written_keys`` conflict check before either records its write,
silently defeating all three conflict strategies.

The fix adds ``_fanout_lock`` to ``GraphContext`` and wraps the
check-and-write block in ``_write_outputs`` with ``async with``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from framework.orchestrator.context import GraphContext
from framework.orchestrator.edge import GraphSpec
from framework.orchestrator.goal import Goal, SuccessCriterion
from framework.orchestrator.node import DataBuffer, NodeResult, NodeSpec
from framework.orchestrator.node_worker import FanOutTag, NodeWorker
from framework.orchestrator.orchestrator import ParallelExecutionConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_graph_spec(entry_node: str = "n1") -> GraphSpec:
    """Minimal GraphSpec for test GraphContext construction."""
    return GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        entry_node=entry_node,
        nodes=[NodeSpec(id=entry_node, name="test", description="test")],
        edges=[],
        max_tokens=4096,
    )


def _make_goal() -> Goal:
    """Minimal Goal for test GraphContext construction."""
    return Goal(
        id="test-goal",
        name="test-goal",
        title="test",
        description="test",
        success_criteria=[
            SuccessCriterion(
                id="sc-1",
                description="done",
                metric="llm_judge",
                target="done",
            ),
        ],
    )


def _make_graph_context(
    buffer_conflict_strategy: str = "last_wins",
) -> GraphContext:
    """Construct a GraphContext with a given buffer conflict strategy."""
    return GraphContext(
        graph=_make_graph_spec(),
        goal=_make_goal(),
        buffer=DataBuffer(),
        runtime=MagicMock(),
        llm=None,
        tools=[],
        tool_executor=MagicMock(),
        event_bus=MagicMock(),
        execution_id="test-exec",
        stream_id="test-stream",
        run_id="test-run",
        storage_path=None,
        parallel_config=ParallelExecutionConfig(
            buffer_conflict_strategy=buffer_conflict_strategy,
        ),
    )


def _make_worker(
    node_id: str,
    gc: GraphContext,
    via_branch: str | None = None,
) -> NodeWorker:
    """Create a NodeWorker, optionally with fan-out tags."""
    node_spec = NodeSpec(
        id=node_id,
        name=node_id,
        description=node_id,
        output_keys=["result"],
    )
    worker = NodeWorker(node_spec=node_spec, graph_context=gc)

    if via_branch is not None:
        tag = FanOutTag(
            fan_out_id="fo-1",
            fan_out_source="source",
            branches=frozenset({via_branch}),
            via_branch=via_branch,
        )
        worker._inherited_fan_out_tags = [tag]

    return worker


def _result(output: dict) -> NodeResult:
    """Shorthand for a successful NodeResult with the given output."""
    return NodeResult(success=True, output=output)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.asyncio


class TestFanOutWriteConflict:
    """Concurrent fan-out workers writing the same buffer key."""

    @staticmethod
    async def _race_workers(
        gc: GraphContext,
        worker_ids: list[str],
        key: str = "result",
    ) -> str:
        """Fire ``_write_outputs`` on N workers concurrently, return winner id."""
        workers = [_make_worker(wid, gc, via_branch=wid) for wid in worker_ids]

        async def fire(w: NodeWorker) -> None:
            await w._write_outputs(_result({key: w.node_spec.id}))

        await asyncio.gather(*[fire(w) for w in workers])

        return gc._fanout_written_keys.get(key, "<never-set>")

    async def test_first_wins_three_workers(self):
        """first_wins: 3 concurrent workers, only 1 wins."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")
        winner = await self._race_workers(gc, ["w1", "w2", "w3"])

        assert winner in {"w1", "w2", "w3"}
        assert len(gc._fanout_written_keys) == 1

    async def test_first_wins_ten_workers(self):
        """first_wins: 10 concurrent workers, only 1 wins."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")
        winner = await self._race_workers(gc, [f"w{i}" for i in range(10)])

        assert winner.startswith("w")
        assert len(gc._fanout_written_keys) == 1

    async def test_last_wins_writes_buffer(self):
        """last_wins: all workers write, buffer ends up with a value."""
        gc = _make_graph_context(buffer_conflict_strategy="last_wins")

        w1 = _make_worker("w1", gc, via_branch="w1")
        w2 = _make_worker("w2", gc, via_branch="w2")

        async def fire(w: NodeWorker, val: str) -> None:
            await w._write_outputs(_result({"result": val}))

        await asyncio.gather(fire(w1, "from-w1"), fire(w2, "from-w2"))

        assert gc.buffer.read("result") in {"from-w1", "from-w2"}
        assert len(gc._fanout_written_keys) == 1

    async def test_error_raises_on_conflict(self):
        """error: RuntimeError when two workers conflict on the same key."""
        gc = _make_graph_context(buffer_conflict_strategy="error")

        w1 = _make_worker("w1", gc, via_branch="w1")
        w2 = _make_worker("w2", gc, via_branch="w2")

        async def fire(w: NodeWorker) -> None:
            await w._write_outputs(_result({"result": w.node_spec.id}))

        with pytest.raises(RuntimeError, match="conflict"):
            await asyncio.gather(fire(w1), fire(w2))

    async def test_non_fanout_bypasses_lock(self):
        """Non-fan-out workers skip conflict tracking entirely."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")

        w1 = _make_worker("w1", gc)
        w2 = _make_worker("w2", gc)

        await asyncio.gather(
            w1._write_outputs(_result({"result": "a"})),
            w2._write_outputs(_result({"result": "b"})),
        )

        assert len(gc._fanout_written_keys) == 0

    async def test_different_keys_no_contention(self):
        """Fan-out workers writing different keys never contend."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")

        w1 = _make_worker("w1", gc, via_branch="w1")
        w2 = _make_worker("w2", gc, via_branch="w2")

        w1.node_spec.output_keys = ["key_a"]
        w2.node_spec.output_keys = ["key_b"]

        await asyncio.gather(
            w1._write_outputs(_result({"key_a": 1})),
            w2._write_outputs(_result({"key_b": 2})),
        )

        assert gc.buffer.read("key_a") == 1
        assert gc.buffer.read("key_b") == 2
        assert len(gc._fanout_written_keys) == 2

    async def test_same_worker_no_self_conflict(self):
        """Same worker writing its own key multiple times is not a conflict."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")
        w = _make_worker("w1", gc, via_branch="w1")

        await w._write_outputs(_result({"result": "first"}))
        await w._write_outputs(_result({"result": "second"}))

        assert gc._fanout_written_keys.get("result") == "w1"
        assert gc.buffer.read("result") == "second"

    async def test_no_parallel_config_defaults_to_last_wins(self):
        """Fall back to last_wins when parallel_config is None."""
        gc = _make_graph_context(buffer_conflict_strategy="last_wins")
        gc.parallel_config = None

        w1 = _make_worker("w1", gc, via_branch="w1")
        w2 = _make_worker("w2", gc, via_branch="w2")

        await asyncio.gather(
            w1._write_outputs(_result({"result": "a"})),
            w2._write_outputs(_result({"result": "b"})),
        )

        assert gc.buffer.read("result") is not None
