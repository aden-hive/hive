"""Tests for the storage module - ConcurrentStorage backend.

DEPRECATED: FileStorage has been removed.
New sessions use unified storage at sessions/{session_id}/state.json.
These tests are kept for backward compatibility verification of ConcurrentStorage only.
"""

import time
from pathlib import Path

import pytest

from framework.schemas.run import Run, RunMetrics, RunStatus
from framework.storage.concurrent import CacheEntry, ConcurrentStorage

# === HELPER FUNCTIONS ===


def create_test_run(
    run_id: str = "test_run_1",
    goal_id: str = "test_goal",
    status: RunStatus = RunStatus.COMPLETED,
    nodes_executed: list[str] | None = None,
) -> Run:
    """Create a test Run object with minimal required fields."""
    metrics = RunMetrics(
        total_decisions=1,
        successful_decisions=1,
        failed_decisions=0,
        nodes_executed=nodes_executed or ["node_1"],
    )
    return Run(
        id=run_id,
        goal_id=goal_id,
        status=status,
        metrics=metrics,
        narrative="Test run completed.",
    )


# === CACHE ENTRY TESTS ===


class TestCacheEntry:
    """Test CacheEntry dataclass."""

    def test_is_expired_false_when_fresh(self):
        """Cache entry should not be expired when fresh."""
        entry = CacheEntry(value="test", timestamp=time.time())
        assert entry.is_expired(ttl=60.0) is False

    def test_is_expired_true_when_old(self):
        """Cache entry should be expired when older than TTL."""
        old_timestamp = time.time() - 120  # 2 minutes ago
        entry = CacheEntry(value="test", timestamp=old_timestamp)
        assert entry.is_expired(ttl=60.0) is True


# === CONCURRENTSTORAGE TESTS ===


class TestConcurrentStorageBasics:
    """Test basic ConcurrentStorage operations."""

    def test_init(self, tmp_path: Path):
        """Test ConcurrentStorage initialization."""
        storage = ConcurrentStorage(tmp_path)

        assert storage.base_path == tmp_path
        assert storage._running is False

    @pytest.mark.asyncio
    async def test_start_and_stop(self, tmp_path: Path):
        """Test starting and stopping the storage."""
        storage = ConcurrentStorage(tmp_path)

        await storage.start()
        assert storage._running is True
        assert storage._batch_task is not None

        await storage.stop()
        assert storage._running is False

    @pytest.mark.asyncio
    async def test_double_start_is_idempotent(self, tmp_path: Path):
        """Starting twice should be safe."""
        storage = ConcurrentStorage(tmp_path)

        await storage.start()
        await storage.start()  # Should not raise
        assert storage._running is True

        await storage.stop()

    @pytest.mark.asyncio
    async def test_double_stop_is_idempotent(self, tmp_path: Path):
        """Stopping twice should be safe."""
        storage = ConcurrentStorage(tmp_path)

        await storage.start()
        await storage.stop()
        await storage.stop()  # Should not raise
        assert storage._running is False


class TestConcurrentStorageCacheManagement:
    """Test ConcurrentStorage cache management."""

    def test_clear_cache(self, tmp_path: Path):
        """Test clearing the cache."""
        storage = ConcurrentStorage(tmp_path)
        storage._cache["test_key"] = CacheEntry(value="test", timestamp=time.time())

        storage.clear_cache()

        assert len(storage._cache) == 0

    def test_invalidate_cache(self, tmp_path: Path):
        """Test invalidating a specific cache entry."""
        storage = ConcurrentStorage(tmp_path)
        storage._cache["key1"] = CacheEntry(value="test1", timestamp=time.time())
        storage._cache["key2"] = CacheEntry(value="test2", timestamp=time.time())

        storage.invalidate_cache("key1")

        assert "key1" not in storage._cache
        assert "key2" in storage._cache

    def test_get_cache_stats(self, tmp_path: Path):
        """Test getting cache statistics."""
        storage = ConcurrentStorage(tmp_path, cache_ttl=60.0)

        # Add fresh entry
        storage._cache["fresh"] = CacheEntry(value="test", timestamp=time.time())
        # Add expired entry
        storage._cache["expired"] = CacheEntry(value="test", timestamp=time.time() - 120)

        stats = storage.get_cache_stats()

        assert stats["total_entries"] == 2
        assert stats["expired_entries"] == 1
        assert stats["valid_entries"] == 1
