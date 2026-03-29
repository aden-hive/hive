"""
Concurrent Storage - Thread-safe storage backend with file locking.

Provides:
- Async file locking for atomic writes
- Write batching for performance
- Read caching for concurrent access
"""

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from weakref import WeakValueDictionary

from framework.schemas.run import Run, RunSummary
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Cached value with timestamp."""

    value: Any
    timestamp: float

    def is_expired(self, ttl: float) -> bool:
        return time.time() - self.timestamp > ttl


class ConcurrentStorage:
    """
    Thread-safe storage backend with file locking and batch writes.

    Provides:
    - Async file locking to prevent concurrent write corruption
    - Write batching to reduce I/O overhead
    - Read caching for frequently accessed data

    Example:
        storage = ConcurrentStorage("/path/to/storage")
        await storage.start()  # Start batch writer

        # Async save with locking
        await storage.save_run(run)

        # Cached read
        run = await storage.load_run(run_id)

        await storage.stop()  # Stop batch writer
    """

    def __init__(
        self,
        base_path: str | Path,
        cache_ttl: float = 60.0,
        batch_interval: float = 0.1,
        max_batch_size: int = 100,
        max_locks: int = 1000,
    ):
        """
        Initialize concurrent storage.

        Args:
            base_path: Base path for storage
            cache_ttl: Cache time-to-live in seconds
            batch_interval: Interval between batch flushes
            max_batch_size: Maximum items before forcing flush
            max_locks: Maximum number of active file locks to track strongly
        """
        self.base_path = Path(base_path)

        # Caching
        self._cache: dict[str, CacheEntry] = {}
        self._cache_ttl = cache_ttl

        # Batching
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._batch_interval = batch_interval
        self._max_batch_size = max_batch_size
        self._batch_task: asyncio.Task | None = None

        # Locking - Use WeakValueDictionary to allow unused locks to be GC'd
        self._file_locks: WeakValueDictionary = WeakValueDictionary()
        self._lru_tracking: OrderedDict = OrderedDict()
        self._max_locks = max_locks

        # State
        self._running = False

    async def start(self) -> None:
        """Start the batch writer background task."""
        if self._running:
            return

        self._running = True
        self._batch_task = asyncio.create_task(self._batch_writer())
        logger.info(f"ConcurrentStorage started: {self.base_path}")

    async def stop(self) -> None:
        """Stop the batch writer and flush pending writes."""
        if not self._running:
            return

        self._running = False

        # Flush remaining items
        await self._flush_pending()

        # Cancel batch task
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
            self._batch_task = None

        logger.info("ConcurrentStorage stopped")

    async def _get_lock(self, lock_key: str) -> asyncio.Lock:
        """Get or create a lock for a given key with safe eviction."""
        # 1. Check if lock exists
        lock = self._file_locks.get(lock_key)

        if lock is not None:
            # OPTIMIZATION: Only update LRU for "run" locks.
            # This prevents high-frequency "index" locks from flushing out
            # the actual run locks we want to keep cached.
            if lock_key.startswith("run:"):
                if lock_key in self._lru_tracking:
                    self._lru_tracking.move_to_end(lock_key)
            return lock

        # 2. Create new lock
        lock = asyncio.Lock()
        self._file_locks[lock_key] = lock

        # CRITICAL: Only add "run:" locks to the strong-ref LRU tracking.
        # Index locks live exclusively in WeakValueDictionary and are GC'd immediately.
        if lock_key.startswith("run:"):
            # Manage capacity only for run locks
            if len(self._lru_tracking) >= self._max_locks:
                # Remove oldest tracked lock (strong ref)
                # WeakValueDictionary will auto-remove the lock once no longer in use
                self._lru_tracking.popitem(last=False)

            # Add strong reference to keep run lock alive
            self._lru_tracking[lock_key] = lock

        return lock

    # === KEY VALIDATION ===

    @staticmethod
    def _validate_key(key: str) -> None:
        """Validate key to prevent path traversal attacks.

        Args:
            key: The key to validate

        Raises:
            ValueError: If key contains path traversal or dangerous patterns
        """
        if not key or key.strip() == "":
            raise ValueError("Key cannot be empty")

        if "/" in key or "\\" in key:
            raise ValueError(f"Invalid key format: path separators not allowed in '{key}'")

        if ".." in key or key.startswith("."):
            raise ValueError(f"Invalid key format: path traversal detected in '{key}'")

        if key.startswith("/") or (len(key) > 1 and key[1] == ":"):
            raise ValueError(f"Invalid key format: absolute paths not allowed in '{key}'")

        if "\x00" in key:
            raise ValueError("Invalid key format: null bytes not allowed")

        dangerous_chars = {"<", ">", "|", "&", "$", "`", "'", '"'}
        if any(char in key for char in dangerous_chars):
            raise ValueError(f"Invalid key format: contains dangerous characters in '{key}'")

    # === FILE OPERATIONS (formerly in FileStorage) ===

    def _save_run_sync(self, run: Run) -> None:
        """Persist a run to disk as ``runs/{run_id}.json``.

        Uses an atomic write (temp-file + rename) so a mid-write crash
        never leaves a partially written file on disk.
        """
        self._validate_key(run.id)
        runs_dir = self.base_path / "runs"
        runs_dir.mkdir(parents=True, exist_ok=True)
        run_path = runs_dir / f"{run.id}.json"
        with atomic_write(run_path) as f:
            f.write(run.model_dump_json(indent=2))

    def _load_run_sync(self, run_id: str) -> Run | None:
        """Load a run from storage."""
        run_path = self.base_path / "runs" / f"{run_id}.json"
        if not run_path.exists():
            return None
        with open(run_path, encoding="utf-8") as f:
            return Run.model_validate_json(f.read())

    def _load_summary_sync(self, run_id: str) -> RunSummary | None:
        """Load just the summary (faster than full run)."""
        self._validate_key(run_id)
        summary_path = self.base_path / "summaries" / f"{run_id}.json"
        if not summary_path.exists():
            run = self._load_run_sync(run_id)
            if run:
                return RunSummary.from_run(run)
            return None
        with open(summary_path, encoding="utf-8") as f:
            return RunSummary.model_validate_json(f.read())

    def _delete_run_sync(self, run_id: str) -> bool:
        """Delete a run from storage."""
        run_path = self.base_path / "runs" / f"{run_id}.json"
        summary_path = self.base_path / "summaries" / f"{run_id}.json"

        if not run_path.exists():
            return False

        run_path.unlink()
        if summary_path.exists():
            summary_path.unlink()

        return True

    def _list_all_runs_sync(self) -> list[str]:
        """List all run IDs."""
        runs_dir = self.base_path / "runs"
        if not runs_dir.exists():
            return []
        return [f.stem for f in runs_dir.glob("*.json")]

    # === RUN OPERATIONS (Async, Thread-Safe) ===

    async def save_run(self, run: Run, immediate: bool = False) -> None:
        """
        Save a run to storage.

        Args:
            run: Run to save
            immediate: If True, save immediately (bypasses batching)
        """
        # Invalidate summary cache since the run data is changing
        # This ensures load_summary() fetches fresh data after the save
        self._cache.pop(f"summary:{run.id}", None)

        if immediate or not self._running:
            await self._save_run_locked(run)
            # Update cache only after successful immediate write
            self._cache[f"run:{run.id}"] = CacheEntry(run, time.time())
        else:
            # For batched writes, cache will be updated in _flush_batch after successful write
            await self._write_queue.put(("run", run))

    async def _save_run_locked(self, run: Run) -> None:
        """Save a run with file locking."""
        lock_key = f"run:{run.id}"
        run_lock = await self._get_lock(lock_key)

        async with run_lock:

            async def perform_save():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._save_run_sync, run)

            await perform_save()

    async def load_run(self, run_id: str, use_cache: bool = True) -> Run | None:
        """
        Load a run from storage.

        Args:
            run_id: Run ID to load
            use_cache: Whether to use cached value if available

        Returns:
            Run object or None if not found

        Raises:
            ValueError: If run_id contains path traversal characters.
        """
        self._validate_key(run_id)
        if use_cache:
            cache_key = f"run:{run_id}"
            cached = self._cache.get(cache_key)
            if cached and not cached.is_expired(self._cache_ttl):
                # CRITICAL: Touch LRU even on cache hit
                lock_key = f"run:{run_id}"
                if lock_key in self._lru_tracking:
                    self._lru_tracking.move_to_end(lock_key)
                return cached.value

        # CRITICAL: Acquire lock to trigger LRU update
        lock_key = f"run:{run_id}"
        async with await self._get_lock(lock_key):
            loop = asyncio.get_event_loop()
            run = await loop.run_in_executor(None, self._load_run_sync, run_id)

        # Update cache
        if run:
            self._cache[f"run:{run_id}"] = CacheEntry(run, time.time())

        return run

    async def load_summary(self, run_id: str, use_cache: bool = True) -> RunSummary | None:
        """Load just the summary (faster than full run).

        Raises:
            ValueError: If run_id contains path traversal characters.
        """
        self._validate_key(run_id)
        cache_key = f"summary:{run_id}"

        # Check cache
        if use_cache and cache_key in self._cache:
            entry = self._cache[cache_key]
            if not entry.is_expired(self._cache_ttl):
                return entry.value

        # Load from storage
        lock_key = f"summary:{run_id}"
        async with await self._get_lock(lock_key):
            loop = asyncio.get_event_loop()
            summary = await loop.run_in_executor(None, self._load_summary_sync, run_id)

        # Update cache
        if summary:
            self._cache[cache_key] = CacheEntry(summary, time.time())

        return summary

    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from storage.

        Raises:
            ValueError: If run_id contains path traversal characters.
        """
        self._validate_key(run_id)
        lock_key = f"run:{run_id}"
        async with await self._get_lock(lock_key):
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._delete_run_sync, run_id)

        # Clear cache
        self._cache.pop(f"run:{run_id}", None)
        self._cache.pop(f"summary:{run_id}", None)

        return result

    async def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._list_all_runs_sync)

    # === BATCH OPERATIONS ===

    async def _batch_writer(self) -> None:
        """Background task that batches writes for performance."""
        batch: list[tuple[str, Any]] = []

        while self._running:
            try:
                # Collect items with timeout
                try:
                    item = await asyncio.wait_for(
                        self._write_queue.get(),
                        timeout=self._batch_interval,
                    )
                    batch.append(item)

                    # Keep collecting if more items available (up to max batch)
                    while len(batch) < self._max_batch_size:
                        try:
                            item = self._write_queue.get_nowait()
                            batch.append(item)
                        except asyncio.QueueEmpty:
                            break

                except TimeoutError:
                    pass

                # Flush batch if we have items
                if batch:
                    await self._flush_batch(batch)
                    batch = []

            except asyncio.CancelledError:
                # Flush remaining before exit
                if batch:
                    await self._flush_batch(batch)
                raise
            except Exception as e:
                logger.error(f"Batch writer error: {e}")
                # Continue running despite errors

    async def _flush_batch(self, batch: list[tuple[str, Any]]) -> None:
        """Flush a batch of writes."""
        if not batch:
            return

        logger.debug(f"Flushing batch of {len(batch)} items")

        for item_type, item in batch:
            try:
                if item_type == "run":
                    await self._save_run_locked(item)
                    # Update cache only after successful batched write
                    # This fixes the race condition where cache was updated before write completed
                    self._cache[f"run:{item.id}"] = CacheEntry(item, time.time())
            except Exception as e:
                logger.error(f"Failed to save {item_type}: {e}")
                # Cache is NOT updated on failure - prevents stale/inconsistent cache state

    async def _flush_pending(self) -> None:
        """Flush all pending writes."""
        batch = []
        while True:
            try:
                item = self._write_queue.get_nowait()
                batch.append(item)
            except asyncio.QueueEmpty:
                break

        if batch:
            await self._flush_batch(batch)

    # === CACHE MANAGEMENT ===

    def clear_cache(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

    def invalidate_cache(self, key: str) -> None:
        """Invalidate a specific cache entry."""
        self._cache.pop(key, None)

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        expired = sum(1 for entry in self._cache.values() if entry.is_expired(self._cache_ttl))
        return {
            "total_entries": len(self._cache),
            "expired_entries": expired,
            "valid_entries": len(self._cache) - expired,
        }

    # === UTILITY ===

    async def get_stats(self) -> dict:
        """Get storage statistics."""
        loop = asyncio.get_event_loop()
        all_runs = await loop.run_in_executor(None, self._list_all_runs_sync)

        return {
            "total_runs": len(all_runs),
            "storage_path": str(self.base_path),
            "cache": self.get_cache_stats(),
            "pending_writes": self._write_queue.qsize(),
            "running": self._running,
        }

    # === SYNC API (for backward compatibility) ===

    def save_run_sync(self, run: Run) -> None:
        """Synchronous save — persists a run to disk immediately."""
        self._validate_key(run.id)
        # Invalidate summary cache since the run data is changing
        self._cache.pop(f"summary:{run.id}", None)

        self._save_run_sync(run)

        # Refresh run cache
        self._cache[f"run:{run.id}"] = CacheEntry(run, time.time())

    def load_run_sync(self, run_id: str) -> Run | None:
        """Synchronous load.

        Raises:
            ValueError: If run_id contains path traversal characters.
        """
        self._validate_key(run_id)
        return self._load_run_sync(run_id)
