"""Tests for the storage module - FileStorage and ConcurrentStorage backends.

DEPRECATED: FileStorage and ConcurrentStorage are deprecated.
New sessions use unified storage at sessions/{session_id}/state.json.
These tests are kept for backward compatibility verification only.
"""

import json
import time
from pathlib import Path

import pytest

from framework.schemas.run import Run, RunMetrics, RunStatus
from framework.storage.backend import FileStorage
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


# === FILESTORAGE TESTS ===


@pytest.mark.skip(reason="FileStorage is deprecated - use unified session storage")
class TestFileStorageBasics:
    """Test basic FileStorage operations."""

    def test_init_creates_directories(self, tmp_path: Path):
        """FileStorage should create the directory structure on init."""
        FileStorage(tmp_path)

        assert (tmp_path / "runs").exists()
        assert (tmp_path / "summaries").exists()
        assert (tmp_path / "indexes" / "by_goal").exists()
        assert (tmp_path / "indexes" / "by_status").exists()
        assert (tmp_path / "indexes" / "by_node").exists()

    def test_init_with_string_path(self, tmp_path: Path):
        """FileStorage should accept string paths."""
        storage = FileStorage(str(tmp_path))
        assert storage.base_path == tmp_path


@pytest.mark.skip(reason="FileStorage is deprecated - use unified session storage")
class TestFileStorageRunOperations:
    """Test FileStorage run CRUD operations."""

    def test_save_and_load_run(self, tmp_path: Path):
        """Test saving and loading a run."""
        storage = FileStorage(tmp_path)
        run = create_test_run()

        storage.save_run(run)
        loaded = storage.load_run(run.id)

        assert loaded is not None
        assert loaded.id == run.id
        assert loaded.goal_id == run.goal_id
        assert loaded.status == run.status

    def test_load_nonexistent_run_returns_none(self, tmp_path: Path):
        """Loading a nonexistent run should return None."""
        storage = FileStorage(tmp_path)

        result = storage.load_run("nonexistent_id")
        assert result is None

    def test_save_creates_json_file(self, tmp_path: Path):
        """Saving a run should create a JSON file."""
        storage = FileStorage(tmp_path)
        run = create_test_run(run_id="my_run")

        storage.save_run(run)

        run_file = tmp_path / "runs" / "my_run.json"
        assert run_file.exists()

        # Verify it's valid JSON
        with open(run_file) as f:
            data = json.load(f)
        assert data["id"] == "my_run"

    def test_save_creates_summary(self, tmp_path: Path):
        """Saving a run should also create a summary file."""
        storage = FileStorage(tmp_path)
        run = create_test_run(run_id="my_run")

        storage.save_run(run)

        summary_file = tmp_path / "summaries" / "my_run.json"
        assert summary_file.exists()

    def test_load_summary(self, tmp_path: Path):
        """Test loading a run summary."""
        storage = FileStorage(tmp_path)
        run = create_test_run()

        storage.save_run(run)
        summary = storage.load_summary(run.id)

        assert summary is not None
        assert summary.run_id == run.id
        assert summary.goal_id == run.goal_id
        assert summary.status == run.status

    def test_load_summary_fallback_to_run(self, tmp_path: Path):
        """If summary file is missing, load_summary should compute from run."""
        storage = FileStorage(tmp_path)
        run = create_test_run()

        storage.save_run(run)

        # Delete the summary file
        summary_file = tmp_path / "summaries" / f"{run.id}.json"
        summary_file.unlink()

        # Should still work by computing from run
        summary = storage.load_summary(run.id)
        assert summary is not None
        assert summary.run_id == run.id

    def test_delete_run(self, tmp_path: Path):
        """Test deleting a run."""
        storage = FileStorage(tmp_path)
        run = create_test_run()

        storage.save_run(run)
        assert storage.load_run(run.id) is not None

        result = storage.delete_run(run.id)

        assert result is True
        assert storage.load_run(run.id) is None

    def test_delete_nonexistent_run_returns_false(self, tmp_path: Path):
        """Deleting a nonexistent run should return False."""
        storage = FileStorage(tmp_path)

        result = storage.delete_run("nonexistent")
        assert result is False


@pytest.mark.skip(reason="FileStorage is deprecated - use unified session storage")
class TestFileStorageIndexing:
    """Test FileStorage index operations."""

    def test_index_by_goal(self, tmp_path: Path):
        """Runs should be indexed by goal_id."""
        storage = FileStorage(tmp_path)

        run1 = create_test_run(run_id="run_1", goal_id="goal_a")
        run2 = create_test_run(run_id="run_2", goal_id="goal_a")
        run3 = create_test_run(run_id="run_3", goal_id="goal_b")

        storage.save_run(run1)
        storage.save_run(run2)
        storage.save_run(run3)

        goal_a_runs = storage.get_runs_by_goal("goal_a")
        goal_b_runs = storage.get_runs_by_goal("goal_b")

        assert len(goal_a_runs) == 2
        assert "run_1" in goal_a_runs
        assert "run_2" in goal_a_runs
        assert len(goal_b_runs) == 1
        assert "run_3" in goal_b_runs

    def test_index_by_status(self, tmp_path: Path):
        """Runs should be indexed by status."""
        storage = FileStorage(tmp_path)

        run1 = create_test_run(run_id="run_1", status=RunStatus.COMPLETED)
        run2 = create_test_run(run_id="run_2", status=RunStatus.FAILED)
        run3 = create_test_run(run_id="run_3", status=RunStatus.COMPLETED)

        storage.save_run(run1)
        storage.save_run(run2)
        storage.save_run(run3)

        completed = storage.get_runs_by_status(RunStatus.COMPLETED)
        failed = storage.get_runs_by_status(RunStatus.FAILED)

        assert len(completed) == 2
        assert len(failed) == 1

    def test_index_by_status_string(self, tmp_path: Path):
        """get_runs_by_status should accept string status."""
        storage = FileStorage(tmp_path)

        run = create_test_run(status=RunStatus.RUNNING)
        storage.save_run(run)

        runs = storage.get_runs_by_status("running")
        assert len(runs) == 1

    def test_index_by_node(self, tmp_path: Path):
        """Runs should be indexed by executed nodes."""
        storage = FileStorage(tmp_path)

        run1 = create_test_run(run_id="run_1", nodes_executed=["node_a", "node_b"])
        run2 = create_test_run(run_id="run_2", nodes_executed=["node_a", "node_c"])

        storage.save_run(run1)
        storage.save_run(run2)

        node_a_runs = storage.get_runs_by_node("node_a")
        node_b_runs = storage.get_runs_by_node("node_b")
        node_c_runs = storage.get_runs_by_node("node_c")

        assert len(node_a_runs) == 2
        assert len(node_b_runs) == 1
        assert len(node_c_runs) == 1

    def test_delete_removes_from_indexes(self, tmp_path: Path):
        """Deleting a run should remove it from all indexes."""
        storage = FileStorage(tmp_path)

        run = create_test_run(
            run_id="run_1",
            goal_id="goal_a",
            status=RunStatus.COMPLETED,
            nodes_executed=["node_1"],
        )
        storage.save_run(run)

        # Verify indexed
        assert "run_1" in storage.get_runs_by_goal("goal_a")
        assert "run_1" in storage.get_runs_by_status(RunStatus.COMPLETED)
        assert "run_1" in storage.get_runs_by_node("node_1")

        # Delete
        storage.delete_run("run_1")

        # Verify removed from indexes
        assert "run_1" not in storage.get_runs_by_goal("goal_a")
        assert "run_1" not in storage.get_runs_by_status(RunStatus.COMPLETED)
        assert "run_1" not in storage.get_runs_by_node("node_1")

    def test_empty_index_returns_empty_list(self, tmp_path: Path):
        """Querying an empty index should return empty list."""
        storage = FileStorage(tmp_path)

        assert storage.get_runs_by_goal("nonexistent") == []
        assert storage.get_runs_by_status("nonexistent") == []
        assert storage.get_runs_by_node("nonexistent") == []


@pytest.mark.skip(reason="FileStorage is deprecated - use unified session storage")
class TestFileStorageListOperations:
    """Test FileStorage list operations."""

    def test_list_all_runs(self, tmp_path: Path):
        """Test listing all run IDs."""
        storage = FileStorage(tmp_path)

        storage.save_run(create_test_run(run_id="run_1"))
        storage.save_run(create_test_run(run_id="run_2"))
        storage.save_run(create_test_run(run_id="run_3"))

        all_runs = storage.list_all_runs()

        assert len(all_runs) == 3
        assert set(all_runs) == {"run_1", "run_2", "run_3"}

    def test_list_all_goals(self, tmp_path: Path):
        """Test listing all goal IDs that have runs."""
        storage = FileStorage(tmp_path)

        storage.save_run(create_test_run(run_id="run_1", goal_id="goal_a"))
        storage.save_run(create_test_run(run_id="run_2", goal_id="goal_b"))
        storage.save_run(create_test_run(run_id="run_3", goal_id="goal_a"))

        all_goals = storage.list_all_goals()

        assert len(all_goals) == 2
        assert set(all_goals) == {"goal_a", "goal_b"}

    def test_get_stats(self, tmp_path: Path):
        """Test getting storage statistics."""
        storage = FileStorage(tmp_path)

        storage.save_run(create_test_run(run_id="run_1", goal_id="goal_a"))
        storage.save_run(create_test_run(run_id="run_2", goal_id="goal_b"))

        stats = storage.get_stats()

        assert stats["total_runs"] == 2
        assert stats["total_goals"] == 2
        assert stats["storage_path"] == str(tmp_path)


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


@pytest.mark.skip(reason="ConcurrentStorage is deprecated - wraps deprecated FileStorage")
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


@pytest.mark.skip(reason="ConcurrentStorage is deprecated - wraps deprecated FileStorage")
class TestConcurrentStorageRunOperations:
    """Test ConcurrentStorage run operations."""

    @pytest.mark.asyncio
    async def test_save_and_load_run(self, tmp_path: Path):
        """Test async save and load of a run."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run = create_test_run()
            await storage.save_run(run, immediate=True)

            loaded = await storage.load_run(run.id)

            assert loaded is not None
            assert loaded.id == run.id
            assert loaded.goal_id == run.goal_id
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_load_run_uses_cache(self, tmp_path: Path):
        """Second load should use cached value."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run = create_test_run()
            await storage.save_run(run, immediate=True)

            # First load
            loaded1 = await storage.load_run(run.id)
            # Second load (should use cache)
            loaded2 = await storage.load_run(run.id, use_cache=True)

            assert loaded1 is not None
            assert loaded2 is not None
            # Cache should return same object
            assert loaded1 is loaded2
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_load_run_bypass_cache(self, tmp_path: Path):
        """Load with use_cache=False should bypass cache."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run = create_test_run()
            await storage.save_run(run, immediate=True)

            loaded1 = await storage.load_run(run.id)
            loaded2 = await storage.load_run(run.id, use_cache=False)

            assert loaded1 is not None
            assert loaded2 is not None
            # Fresh load should be different object
            assert loaded1 is not loaded2
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_delete_run(self, tmp_path: Path):
        """Test async delete of a run."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run = create_test_run()
            await storage.save_run(run, immediate=True)

            result = await storage.delete_run(run.id)

            assert result is True
            loaded = await storage.load_run(run.id)
            assert loaded is None
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_delete_clears_cache(self, tmp_path: Path):
        """Deleting a run should clear it from cache."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run = create_test_run()
            await storage.save_run(run, immediate=True)

            # Load to populate cache
            await storage.load_run(run.id)
            assert f"run:{run.id}" in storage._cache

            # Delete
            await storage.delete_run(run.id)

            # Cache should be cleared
            assert f"run:{run.id}" not in storage._cache
        finally:
            await storage.stop()


@pytest.mark.skip(reason="ConcurrentStorage is deprecated - wraps deprecated FileStorage")
class TestConcurrentStorageQueryOperations:
    """Test ConcurrentStorage query operations."""

    @pytest.mark.asyncio
    async def test_get_runs_by_goal(self, tmp_path: Path):
        """Test async query by goal."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run1 = create_test_run(run_id="run_1", goal_id="goal_a")
            run2 = create_test_run(run_id="run_2", goal_id="goal_a")

            await storage.save_run(run1, immediate=True)
            await storage.save_run(run2, immediate=True)

            runs = await storage.get_runs_by_goal("goal_a")

            assert len(runs) == 2
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_get_runs_by_status(self, tmp_path: Path):
        """Test async query by status."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            run = create_test_run(status=RunStatus.FAILED)
            await storage.save_run(run, immediate=True)

            runs = await storage.get_runs_by_status(RunStatus.FAILED)

            assert len(runs) == 1
        finally:
            await storage.stop()

    @pytest.mark.asyncio
    async def test_list_all_runs(self, tmp_path: Path):
        """Test async list all runs."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            await storage.save_run(create_test_run(run_id="run_1"), immediate=True)
            await storage.save_run(create_test_run(run_id="run_2"), immediate=True)

            runs = await storage.list_all_runs()

            assert len(runs) == 2
        finally:
            await storage.stop()


@pytest.mark.skip(reason="ConcurrentStorage is deprecated - wraps deprecated FileStorage")
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


@pytest.mark.skip(reason="ConcurrentStorage is deprecated - wraps deprecated FileStorage")
class TestConcurrentStorageSyncAPI:
    """Test ConcurrentStorage synchronous API for backward compatibility."""

    def test_save_run_sync(self, tmp_path: Path):
        """Test synchronous save."""
        storage = ConcurrentStorage(tmp_path)
        run = create_test_run()

        storage.save_run_sync(run)

        # Verify saved
        loaded = storage.load_run_sync(run.id)
        assert loaded is not None
        assert loaded.id == run.id

    def test_load_run_sync(self, tmp_path: Path):
        """Test synchronous load."""
        storage = ConcurrentStorage(tmp_path)
        run = create_test_run()

        storage.save_run_sync(run)
        loaded = storage.load_run_sync(run.id)

        assert loaded is not None

    def test_load_run_sync_nonexistent(self, tmp_path: Path):
        """Synchronous load of nonexistent run returns None."""
        storage = ConcurrentStorage(tmp_path)

        loaded = storage.load_run_sync("nonexistent")
        assert loaded is None


@pytest.mark.skip(reason="ConcurrentStorage is deprecated - wraps deprecated FileStorage")
class TestConcurrentStorageStats:
    """Test ConcurrentStorage statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, tmp_path: Path):
        """Test getting async storage stats."""
        storage = ConcurrentStorage(tmp_path)
        await storage.start()

        try:
            await storage.save_run(create_test_run(), immediate=True)

            stats = await storage.get_stats()

            assert stats["total_runs"] == 1
            assert "cache" in stats
            assert "pending_writes" in stats
            assert stats["running"] is True
        finally:
            await storage.stop()
