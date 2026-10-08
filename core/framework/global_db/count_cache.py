"""Reusable cache of table row-counts + last-updated time, with dirty
invalidation.

Built for the cloud global DB — where each count is a *network* call, so the
system-reminder can't just re-fetch on every tool turn — but the
:class:`TableCountCache` itself is generic: hand it any async fetcher.

Three actors, by design:
  * **writers** call ``mark_dirty()`` — the next read refreshes;
  * a **known-fresh source** (e.g. the CRM list endpoint the desktop hits)
    calls ``record()`` to populate the cache for free with counts it already
    fetched — so a user opening the CRM view also refreshes the reminder;
  * **readers** (the system-reminder) call ``snapshot()`` — returns cached
    counts, refreshing lazily only when dirty or older than the TTL.

The cache is per-runtime-process (in-memory). It reflects this user's writes
and CRM views immediately; a *teammate's* write elsewhere surfaces within the
TTL (the staleness bound). Good enough for an advisory reminder; not a
consistency mechanism.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

CountsFetcher = Callable[[], Awaitable[list[tuple[str, int]]]]


@dataclass(frozen=True)
class CountSnapshot:
    """Point-in-time view returned by :meth:`TableCountCache.snapshot`."""

    tables: list[tuple[str, int]]
    updated_at: datetime  # wall-clock of the last refresh/record
    age_seconds: float  # seconds since that refresh


class TableCountCache:
    """Generic ``table -> row count`` cache with last-updated + invalidation."""

    def __init__(self, fetcher: CountsFetcher, *, ttl_seconds: float = 60.0) -> None:
        self._fetcher = fetcher
        self._ttl = ttl_seconds
        self._counts: list[tuple[str, int]] | None = None
        self._mono: float | None = None  # monotonic stamp (for age/TTL)
        self._wall: datetime | None = None  # wall stamp (for display)
        self._dirty = True
        self._lock = asyncio.Lock()

    def mark_dirty(self) -> None:
        """A write happened — force a refresh on the next read."""
        self._dirty = True

    def record(self, counts: list[tuple[str, int]]) -> None:
        """Populate from counts a caller already fetched (no extra round-trip)."""
        self._counts = list(counts)
        self._stamp()

    def _stamp(self) -> None:
        self._mono = time.monotonic()
        self._wall = datetime.now(UTC)
        self._dirty = False

    def _fresh(self) -> bool:
        return self._counts is not None and self._mono is not None and not self._dirty and (time.monotonic() - self._mono) <= self._ttl

    async def snapshot(self, *, force: bool = False) -> CountSnapshot | None:
        """Return current counts, refreshing lazily when dirty/stale/forced.

        Returns ``None`` only when there is nothing cached *and* the fetch
        fails (e.g. not signed in) — callers treat ``None`` as "skip". A failed
        refresh with prior data falls back to the last-known counts.
        """
        if force or not self._fresh():
            async with self._lock:
                # Re-check under the lock — another coroutine may have refreshed.
                if force or not self._fresh():
                    try:
                        counts = await self._fetcher()
                    except Exception as e:
                        logger.debug("TableCountCache refresh failed: %s", e)
                        if self._counts is None:
                            return None  # nothing to show
                        # else: fall through with stale last-known
                    else:
                        self._counts = list(counts)
                        self._stamp()
        if self._counts is None or self._wall is None or self._mono is None:
            return None
        return CountSnapshot(
            tables=list(self._counts),
            updated_at=self._wall,
            age_seconds=max(0.0, time.monotonic() - self._mono),
        )


# ---------------------------------------------------------------------------
# Global-DB wiring: one shared instance + helpers used across the runtime.
# ---------------------------------------------------------------------------


async def _fetch_global_counts() -> list[tuple[str, int]]:
    """Fetch row counts for the team's global-DB tables via the cloud client."""
    from framework.global_db import client as gdb

    resp = await gdb.list_tables()
    tables = resp.get("tables") if isinstance(resp, dict) else None
    out: list[tuple[str, int]] = []
    for t in tables or []:
        name = t.get("name")
        if name:
            out.append((name, int(t.get("row_count") or 0)))
    return out


global_count_cache = TableCountCache(_fetch_global_counts, ttl_seconds=60.0)

# Whether the agent has touched the global DB at all this process. The reminder
# gates on this so colonies that never do GTM work aren't nagged (and we don't
# make needless network calls for them).
_global_used = False


def note_global_used() -> None:
    """Mark that a global-scope tracker tool was used (read or write)."""
    global _global_used
    _global_used = True


def global_was_used() -> bool:
    return _global_used


def record_global_tables(tables: list[dict]) -> None:
    """Refresh the cache from a ``/v1/global-db/tables`` response (UI path)."""
    counts = [(t["name"], int(t.get("row_count") or 0)) for t in tables if t.get("name")]
    global_count_cache.record(counts)


__all__ = [
    "CountSnapshot",
    "TableCountCache",
    "global_count_cache",
    "global_was_used",
    "note_global_used",
    "record_global_tables",
]
