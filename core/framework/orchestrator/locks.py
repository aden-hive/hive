"""Async lock registry for per-key concurrency control.

Provides an async context manager for acquiring a per-key asyncio.Lock
to serialize check-then-write operations across concurrent workers.

This helps prevent TOCTOU races when multiple fan-out branches attempt to
claim the same buffer key concurrently.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Dict


class AsyncLockRegistry:
    """Registry of asyncio locks keyed by an arbitrary string.

    Use ``async with registry.lock(key):`` to acquire the per-key lock.
    The registry lazily creates locks and removes them when no longer held
    to avoid unbounded growth in long-running processes.
    """

    def __init__(self) -> None:
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, key: str):
        # Ensure a lock exists for the key
        async with self._global_lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock

        # Acquire the per-key lock
        await lock.acquire()
        try:
            yield
        finally:
            # Release and attempt cleanup
            lock.release()
            async with self._global_lock:
                # If nobody else reacquired it, drop the entry
                if not lock.locked() and self._locks.get(key) is lock:
                    try:
                        del self._locks[key]
                    except KeyError:
                        pass
