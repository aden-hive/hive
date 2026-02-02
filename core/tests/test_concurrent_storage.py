"""Tests for ConcurrentStorage race condition and cache invalidation fixes."""

import asyncio
from pathlib import Path

import pytest

from framework.schemas.run import Run, RunMetrics, RunStatus
from framework.storage.concurrent import ConcurrentStorage


def create_test_run(
    run_id: str, goal_id: str = "test-goal", status: RunStatus = RunStatus.RUNNING
) -> Run:
    """Create a minimal test Run object."""
    return Run(
        id=run_id,
        goal_id=goal_id,
        status=status,
        narrative="Test run",
        metrics=RunMetrics(
            nodes_executed=[],
        ),
        decisions=[],
        problems=[],
    )


@pytest.mark.asyncio
async def test_cache_invalidation_on_save(tmp_path: Path):
    """Test that summary cache is invalidated when a run is saved.

    This tests the fix for the cache invalidation bug where load_summary()
    would return stale data after a run was updated.
    """
    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    try:
        run_id = "test-run-1"

        # Create and save initial run
        run = create_test_run(run_id, status=RunStatus.RUNNING)
        await storage.save_run(run, immediate=True)

        # Load summary to populate the cache
        summary = await storage.load_summary(run_id)
        assert summary is not None
        assert summary.status == RunStatus.RUNNING

        # Update run with new status
        run.status = RunStatus.COMPLETED
        await storage.save_run(run, immediate=True)

        # Load summary again - should get fresh data, not cached stale data
        summary = await storage.load_summary(run_id)
        assert summary is not None
        assert summary.status == RunStatus.COMPLETED, (
            "Summary cache should be invalidated on save - got stale data"
        )
    finally:
        await storage.stop()


@pytest.mark.asyncio
async def test_batched_write_cache_consistency(tmp_path: Path):
    """Test that cache is only updated after successful batched write.

    This tests the fix for the race condition where cache was updated
    before the batched write completed.
    """
    storage = ConcurrentStorage(tmp_path, batch_interval=0.05)
    await storage.start()

    try:
        run_id = "test-run-2"

        # Save via batching (immediate=False)
        run = create_test_run(run_id, status=RunStatus.RUNNING)
        await storage.save_run(run, immediate=False)

        # Before batch flush, cache should NOT contain the run
        # (This is the fix - previously cache was updated immediately)
        cache_key = f"run:{run_id}"
        assert cache_key not in storage._cache, (
            "Cache should not be updated before batch is flushed"
        )

        # Wait for batch to flush
        await asyncio.sleep(0.1)

        # After batch flush, cache should contain the run
        assert cache_key in storage._cache, "Cache should be updated after batch flush"

        # Verify data on disk matches cache
        loaded_run = await storage.load_run(run_id, use_cache=False)
        assert loaded_run is not None
        assert loaded_run.id == run_id
        assert loaded_run.status == RunStatus.RUNNING
    finally:
        await storage.stop()


@pytest.mark.asyncio
async def test_immediate_write_updates_cache(tmp_path: Path):
    """Test that immediate writes still update cache correctly."""
    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    try:
        run_id = "test-run-3"

        # Save with immediate=True
        run = create_test_run(run_id, status=RunStatus.COMPLETED)
        await storage.save_run(run, immediate=True)

        # Cache should be updated immediately for immediate writes
        cache_key = f"run:{run_id}"
        assert cache_key in storage._cache, "Cache should be updated after immediate write"

        # Verify cached value is correct
        cached_run = storage._cache[cache_key].value
        assert cached_run.id == run_id
        assert cached_run.status == RunStatus.COMPLETED
    finally:
        await storage.stop()


@pytest.mark.asyncio
async def test_summary_cache_invalidated_on_multiple_saves(tmp_path: Path):
    """Test that summary cache is invalidated on each save, not just the first."""
    storage = ConcurrentStorage(tmp_path)
    await storage.start()

    try:
        run_id = "test-run-4"

        # First save
        run = create_test_run(run_id, status=RunStatus.RUNNING)
        await storage.save_run(run, immediate=True)

        # Load summary to cache it
        summary1 = await storage.load_summary(run_id)
        assert summary1.status == RunStatus.RUNNING

        # Second save with new status
        run.status = RunStatus.RUNNING
        await storage.save_run(run, immediate=True)

        # Load summary - should be fresh
        summary2 = await storage.load_summary(run_id)
        assert summary2.status == RunStatus.RUNNING

        # Third save with final status
        run.status = RunStatus.COMPLETED
        await storage.save_run(run, immediate=True)

        # Load summary - should be fresh again
        summary3 = await storage.load_summary(run_id)
        assert summary3.status == RunStatus.COMPLETED
    finally:
        await storage.stop()
