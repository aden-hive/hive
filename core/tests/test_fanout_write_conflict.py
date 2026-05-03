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
    return GraphSpec(
        id="test-graph",
        goal_id="test-goal",
        entry_node=entry_node,
        nodes=[NodeSpec(id=entry_node, name="test", description="test")],
        edges=[],
        max_tokens=4096,
    )


def _make_goal() -> Goal:
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
        value_template: str = "from-{}",
    ) -> list[str]:
        """Fire ``_write_outputs`` on N workers concurrently and return
        the final value of ``gc._fanout_written_keys[key]`` and the
        buffer value."""

        workers = [_make_worker(wid, gc, via_branch=wid) for wid in worker_ids]

        async def fire(w: NodeWorker) -> None:
            await w._write_outputs(_result({key: value_template.format(w.node_spec.id)}))

        await asyncio.gather(*[fire(w) for w in workers])

        # Who does the conflict tracker think won?
        winner = gc._fanout_written_keys.get(key, "<never-set>")
        return winner

    # -- first_wins -------------------------------------------------------

    async def test_first_wins_only_one_write(self):
        """first_wins: only the first concurrent write wins."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")
        winner = await self._race_workers(gc, ["w1", "w2", "w3"])

        # Exactly one worker's ID should be recorded
        assert winner in {"w1", "w2", "w3"}, f"Unexpected winner: {winner}"
        # Only one entry in written_keys
        assert len(gc._fanout_written_keys) == 1

    async def test_first_wins_buffer_value_from_winner(self):
        """first_wins: buffer holds the winner's value."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")

        workers = [
            _make_worker("w1", gc, via_branch="w1"),
            _make_worker("w2", gc, via_branch="w2"),
        ]

        async def fire(w: NodeWorker, val: str) -> None:
            await w._write_outputs(_result({"result": val}))

        await asyncio.gather(fire(workers[0], "aaa"), fire(workers[1], "bbb"))

        # Buffer value should be from whichever worker won
        assert gc.buffer.read("result") in {"aaa", "bbb"}
        assert len(gc._fanout_written_keys) == 1

    async def test_first_wins_ten_workers(self):
        """first_wins: with 10 concurrent workers, exactly 1 wins."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")
        winner = await self._race_workers(
            gc, [f"w{i}" for i in range(10)],
        )
        assert winner.startswith("w")
        assert len(gc._fanout_written_keys) == 1

    # -- last_wins --------------------------------------------------------

    async def test_last_wins_overwrites(self):
        """last_wins: the last concurrent write wins (key tracking works)."""
        gc = _make_graph_context(buffer_conflict_strategy="last_wins")
        await self._race_workers(gc, ["w1", "w2", "w3"])

        # Under last_wins, all workers set _fanout_written_keys (last one wins)
        # But because of the lock, only one value will be in _fanout_written_keys
        # Actually, with last_wins, each worker overwrites, so the last one to
        # acquire the lock sets the value. We can't predict which, but we can
        # verify the buffer write happened.
        written_keys_count = len(gc._fanout_written_keys)
        assert written_keys_count == 1, (
            f"Expected 1 key in written_keys, got {written_keys_count}"
        )

    async def test_last_wins_buffer_has_some_value(self):
        """last_wins: buffer ends up with a value from one of the workers."""
        gc = _make_graph_context(buffer_conflict_strategy="last_wins")

        workers = [
            _make_worker("w1", gc, via_branch="w1"),
            _make_worker("w2", gc, via_branch="w2"),
        ]

        async def fire(w: NodeWorker, val: str) -> None:
            await w._write_outputs(_result({"result": val}))

        await asyncio.gather(fire(workers[0], "from-w1"), fire(workers[1], "from-w2"))

        # Buffer has some value
        val = gc.buffer.read("result")
        assert val is not None
        # And it's from one of the workers
        assert val in {"from-w1", "from-w2"}

    # -- error ------------------------------------------------------------

    async def test_error_raises_on_conflict(self):
        """error strategy: raises RuntimeError when two workers conflict."""
        gc = _make_graph_context(buffer_conflict_strategy="error")

        workers = [
            _make_worker("w1", gc, via_branch="w1"),
            _make_worker("w2", gc, via_branch="w2"),
        ]

        async def fire(w: NodeWorker) -> None:
            await w._write_outputs(_result({"result": w.node_spec.id}))

        with pytest.raises(RuntimeError, match="conflict"):
            await asyncio.gather(*[fire(w) for w in workers])

    # -- non-fan-out ------------------------------------------------------

    async def test_non_fanout_no_contention(self):
        """Non-fan-out workers bypass conflict tracking entirely."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")

        # No via_branch → not a fan-out worker
        w1 = _make_worker("w1", gc, via_branch=None)
        w2 = _make_worker("w2", gc, via_branch=None)

        await asyncio.gather(
            w1._write_outputs(_result({"result": "a"})),
            w2._write_outputs(_result({"result": "b"})),
        )

        # Non-fan-out: no _fanout_written_keys set, buffer has last write
        assert len(gc._fanout_written_keys) == 0
        # Buffer was written by both (last_wins by default for non-fan-out)
        assert gc.buffer.read("result") == "b"

    # -- different keys ---------------------------------------------------

    async def test_different_keys_no_conflict(self):
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

    # -- same worker, same key (no self-conflict) -------------------------

    async def test_same_worker_no_self_conflict(self):
        """A worker writing its own key does not conflict with itself."""
        gc = _make_graph_context(buffer_conflict_strategy="first_wins")
        w1 = _make_worker("w1", gc, via_branch="w1")

        await w1._write_outputs(_result({"result": "first"}))
        await w1._write_outputs(_result({"result": "second"}))

        # Same worker ID → prior_worker check passes (prior_worker == node_spec.id)
        assert gc._fanout_written_keys.get("result") == "w1"
        assert gc.buffer.read("result") == "second"

    # -- lock isolation ---------------------------------------------------

    async def test_lock_is_independent_from_buffer_lock(self):
        """_fanout_lock does not interfere with buffer writes."""
        gc = _make_graph_context(buffer_conflict_strategy="last_wins")
        w = _make_worker("w1", gc, via_branch="w1")

        # Write a key outside the fan-out path
        gc.buffer.write("other", 42, validate=False)

        # Fan-out write to a different key
        await w._write_outputs(_result({"result": "ok"}))

        assert gc.buffer.read("other") == 42
        assert gc.buffer.read("result") == "ok"

    # -- parallel_config None ---------------------------------------------

    async def test_no_parallel_config_defaults_to_last_wins(self):
        """When parallel_config is None, fall back to last_wins."""
        gc = _make_graph_context(buffer_conflict_strategy="last_wins")
        gc.parallel_config = None

        w1 = _make_worker("w1", gc, via_branch="w1")
        w2 = _make_worker("w2", gc, via_branch="w2")

        # Should not raise despite conflict (last_wins is default)
        await asyncio.gather(
            w1._write_outputs(_result({"result": "a"})),
            w2._write_outputs(_result({"result": "b"})),
        )

        # Buffer has some value
        assert gc.buffer.read("result") is not None
