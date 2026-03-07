"""Tests for SharedStateManager.write_batch() atomicity fix.

Covers Issue #5946: write_batch() executes sequential writes — not atomic
under SYNCHRONIZED isolation. The fix acquires all per-key locks before
writing so concurrent readers never see a partial batch.
"""

from __future__ import annotations

import asyncio

import pytest

from framework.runtime.shared_state import (
    IsolationLevel,
    SharedStateManager,
    StateScope,
)


@pytest.fixture
def manager():
    return SharedStateManager()


class TestWriteBatchAtomicity:
    """Verify write_batch holds all locks during SYNCHRONIZED writes."""

    @pytest.mark.asyncio
    async def test_batch_write_synchronized_all_or_nothing(self, manager):
        """Under SYNCHRONIZED + STREAM scope, a concurrent reader sees either
        all keys from the batch or none."""
        exec_id = "exec_1"
        stream_id = "stream_1"

        # Seed initial state so we can detect partial writes
        await manager.write(
            "a", "old_a", exec_id, stream_id,
            IsolationLevel.SYNCHRONIZED, StateScope.STREAM,
        )
        await manager.write(
            "b", "old_b", exec_id, stream_id,
            IsolationLevel.SYNCHRONIZED, StateScope.STREAM,
        )

        snapshots: list[dict] = []
        stop = asyncio.Event()

        async def reader():
            """Continuously read both keys and record snapshots."""
            while not stop.is_set():
                a = await manager.read("a", exec_id, stream_id, IsolationLevel.SYNCHRONIZED)
                b = await manager.read("b", exec_id, stream_id, IsolationLevel.SYNCHRONIZED)
                snapshots.append({"a": a, "b": b})
                await asyncio.sleep(0)  # yield

        reader_task = asyncio.create_task(reader())
        # Yield so the reader collects at least one snapshot
        await asyncio.sleep(0)

        # Perform a batch write
        await manager.write_batch(
            {"a": "new_a", "b": "new_b"},
            exec_id, stream_id,
            IsolationLevel.SYNCHRONIZED,
            StateScope.STREAM,
        )

        # Let reader collect a few more snapshots after the write
        await asyncio.sleep(0.01)
        stop.set()
        await reader_task

        # Ensure the reader actually ran (guards against vacuous pass)
        assert snapshots, "Reader collected no snapshots — test is inconclusive"

        # Every snapshot should be consistent: either both old or both new
        for snap in snapshots:
            assert (
                (snap["a"] == "old_a" and snap["b"] == "old_b")
                or (snap["a"] == "new_a" and snap["b"] == "new_b")
            ), f"Partial batch visible: {snap}"

    @pytest.mark.asyncio
    async def test_batch_write_isolated_still_works(self, manager):
        """ISOLATED write_batch should still write all keys (no locks needed)."""
        exec_id = "exec_2"
        stream_id = "stream_2"

        await manager.write_batch(
            {"x": 1, "y": 2, "z": 3},
            exec_id, stream_id,
            IsolationLevel.ISOLATED,
            StateScope.EXECUTION,
        )

        assert await manager.read("x", exec_id, stream_id, IsolationLevel.ISOLATED) == 1
        assert await manager.read("y", exec_id, stream_id, IsolationLevel.ISOLATED) == 2
        assert await manager.read("z", exec_id, stream_id, IsolationLevel.ISOLATED) == 3

    @pytest.mark.asyncio
    async def test_batch_write_records_changes(self, manager):
        """write_batch should record a StateChange for every key."""
        exec_id = "exec_3"
        stream_id = "stream_3"

        initial_changes = len(manager._change_history)

        await manager.write_batch(
            {"k1": "v1", "k2": "v2"},
            exec_id, stream_id,
            IsolationLevel.SYNCHRONIZED,
            StateScope.STREAM,
        )

        new_changes = manager._change_history[initial_changes:]
        changed_keys = {c.key for c in new_changes}
        assert "k1" in changed_keys
        assert "k2" in changed_keys

    @pytest.mark.asyncio
    async def test_batch_write_no_deadlock_on_sorted_keys(self, manager):
        """Two concurrent batch writes with overlapping keys must not deadlock.
        Lock acquisition in sorted key order prevents this."""
        exec_id = "exec_4"
        stream_id = "stream_4"

        async def writer_a():
            await manager.write_batch(
                {"alpha": 1, "beta": 2},
                exec_id, stream_id,
                IsolationLevel.SYNCHRONIZED,
                StateScope.STREAM,
            )

        async def writer_b():
            await manager.write_batch(
                {"beta": 20, "alpha": 10},
                exec_id, stream_id,
                IsolationLevel.SYNCHRONIZED,
                StateScope.STREAM,
            )

        # Should complete without deadlock within 2 seconds
        await asyncio.wait_for(
            asyncio.gather(writer_a(), writer_b()),
            timeout=2.0,
        )

        # Both completed — values should be from whichever ran last
        a = await manager.read("alpha", exec_id, stream_id, IsolationLevel.SYNCHRONIZED)
        b = await manager.read("beta", exec_id, stream_id, IsolationLevel.SYNCHRONIZED)
        assert a in (1, 10)
        assert b in (2, 20)
