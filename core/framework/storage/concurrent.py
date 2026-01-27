"""
Concurrent Storage - Thread-safe storage backend with file locking.

Wraps FileStorage with:
- Async file locking for atomic writes
- Write batching for performance
- Read caching for concurrent access
"""

import asyncio
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from framework.schemas.run import Run, RunStatus, RunSummary
from framework.storage.backend import FileStorage
from framework.security import LRUCache, ThreadSafeLockManager

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
    - LRU read caching for frequently accessed data
    - Compatible API with FileStorage
    - Enhanced error handling and recovery
    - Resource cleanup and monitoring

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
        cache_size: int = 1000,
    ):
        """
        Initialize concurrent storage.

        Args:
            base_path: Base path for storage
            cache_ttl: Cache time-to-live in seconds
            batch_interval: Interval between batch flushes
            max_batch_size: Maximum items before forcing flush
            cache_size: Maximum cache size
        """
        self.base_path = Path(base_path)
        self._base_storage = FileStorage(base_path)

        # LRU Caching with thread safety
        self._cache = LRUCache(max_size=cache_size, ttl=cache_ttl)

        # Batching
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._batch_interval = batch_interval
        self._max_batch_size = max_batch_size
        self._batch_task: asyncio.Task | None = None

        # Thread-safe lock manager
        self._lock_manager = ThreadSafeLockManager()
        self._global_lock = asyncio.Lock()

        # State and monitoring
        self._running = False
        self._start_time = time.time()
        self._stats = {
            "writes_queued": 0,
            "writes_completed": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "errors": 0
        }

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

        # Cancel batch task first to prevent queue competition
        if self._batch_task:
            self._batch_task.cancel()
            try:
                await self._batch_task
            except asyncio.CancelledError:
                pass
            self._batch_task = None

        # Now flush remaining items (batch task is stopped)
        await self._flush_pending()

        logger.info("ConcurrentStorage stopped")

    # === RUN OPERATIONS (Async, Thread-Safe) ===

    async def save_run(self, run: Run, immediate: bool = False) -> None:
        """
        Save a run to storage.

        Args:
            run: Run to save
            immediate: If True, save immediately (bypasses batching)
        """
        try:
            if immediate or not self._running:
                await self._save_run_locked(run)
            else:
                await self._write_queue.put(("run", run))
                self._stats["writes_queued"] += 1

            # Update cache
            self._cache.put(f"run:{run.id}", run)

        except Exception as e:
            self._stats["errors"] += 1
            logger.error(f"Error saving run {run.id}: {e}")
            raise

    async def _save_run_locked(self, run: Run) -> None:
        """Save a run with file locking."""
        lock_key = f"run:{run.id}"
        lock = self._lock_manager.get_lock(lock_key)
        async with lock:
            # Run in executor to avoid blocking event loop
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._base_storage.save_run, run)
            self._stats["writes_completed"] += 1

    async def load_run(self, run_id: str, use_cache: bool = True) -> Run | None:
        """
        Load a run from storage.

        Args:
            run_id: Run ID to load
            use_cache: Whether to use cached value if available

        Returns:
            Run object or None if not found
        """
        cache_key = f"run:{run_id}"

        # Check cache
        if use_cache:
            cached_run = self._cache.get(cache_key)
            if cached_run is not None:
                self._stats["cache_hits"] += 1
                return cached_run
            self._stats["cache_misses"] += 1

        # Load from storage
        lock_key = f"run:{run_id}"
        lock = self._lock_manager.get_lock(lock_key)
        async with lock:
            loop = asyncio.get_event_loop()
            run = await loop.run_in_executor(None, self._base_storage.load_run, run_id)

        # Update cache
        if run:
            self._cache.put(cache_key, run)

        return run

    async def load_summary(self, run_id: str, use_cache: bool = True) -> RunSummary | None:
        """Load just the summary (faster than full run)."""
        cache_key = f"summary:{run_id}"

        # Check cache
        if use_cache:
            cached_summary = self._cache.get(cache_key)
            if cached_summary is not None:
                return cached_summary

        # Load from storage
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(None, self._base_storage.load_summary, run_id)

        # Update cache
        if summary:
            self._cache.put(cache_key, summary)

        return summary

    async def delete_run(self, run_id: str) -> bool:
        """Delete a run from storage."""
        lock_key = f"run:{run_id}"
        lock = self._lock_manager.get_lock(lock_key)
        async with lock:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._base_storage.delete_run, run_id)

        # Clear cache
        self._cache.invalidate(f"run:{run_id}")
        self._cache.invalidate(f"summary:{run_id}")

        return result

    # === QUERY OPERATIONS (Async, with Locking) ===

    async def get_runs_by_goal(self, goal_id: str) -> list[str]:
        """Get all run IDs for a goal."""
        lock_key = f"index:by_goal:{goal_id}"
        lock = self._lock_manager.get_lock(lock_key)
        async with lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._base_storage.get_runs_by_goal, goal_id)

    async def get_runs_by_status(self, status: str | RunStatus) -> list[str]:
        """Get all run IDs with a status."""
        if isinstance(status, RunStatus):
            status = status.value
        lock_key = f"index:by_status:{status}"
        lock = self._lock_manager.get_lock(lock_key)
        async with lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._base_storage.get_runs_by_status, status)

    async def get_runs_by_node(self, node_id: str) -> list[str]:
        """Get all run IDs that executed a node."""
        lock_key = f"index:by_node:{node_id}"
        lock = self._lock_manager.get_lock(lock_key)
        async with lock:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._base_storage.get_runs_by_node, node_id)

    async def list_all_runs(self) -> list[str]:
        """List all run IDs."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._base_storage.list_all_runs)

    async def list_all_goals(self) -> list[str]:
        """List all goal IDs that have runs."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._base_storage.list_all_goals)

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
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"Failed to save {item_type}: {e}")

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
        self._cache.invalidate(key)

    def get_cache_stats(self) -> dict:
        """Get cache statistics."""
        return self._cache.get_stats()

    # === UTILITY ===

    async def get_stats(self) -> dict:
        """Get storage statistics."""
        loop = asyncio.get_event_loop()
        base_stats = await loop.run_in_executor(None, self._base_storage.get_stats)

        uptime = time.time() - self._start_time

        return {
            **base_stats,
            "cache": self.get_cache_stats(),
            "lock_manager": self._lock_manager.get_stats(),
            "pending_writes": self._write_queue.qsize(),
            "running": self._running,
            "uptime_seconds": uptime,
            "performance": {
                "writes_per_second": self._stats["writes_completed"] / uptime if uptime > 0 else 0,
                "cache_hit_rate": (
                    self._stats["cache_hits"] / 
                    (self._stats["cache_hits"] + self._stats["cache_misses"])
                    if (self._stats["cache_hits"] + self._stats["cache_misses"]) > 0 else 0
                ),
                "error_rate": (
                    self._stats["errors"] / max(1, self._stats["writes_completed"])
                )
            },
            "operations": self._stats
        }

    # === SYNC API (for backward compatibility) ===

    def save_run_sync(self, run: Run) -> None:
        """Synchronous save (uses base storage directly)."""
        try:
            self._base_storage.save_run(run)
            self._stats["writes_completed"] += 1
        except Exception as e:
            self._stats["errors"] += 1
            raise

    def load_run_sync(self, run_id: str) -> Run | None:
        """Synchronous load (uses base storage directly)."""
        return self._base_storage.load_run(run_id)

    # === RESOURCE CLEANUP ===

    async def cleanup(self) -> None:
        """Cleanup resources and stop background tasks."""
        if self._running:
            await self.stop()
        
        # Clear locks
        self._lock_manager.clear_all()
        
        # Clear cache
        self._cache.clear()
        
        logger.info("ConcurrentStorage cleanup completed")
