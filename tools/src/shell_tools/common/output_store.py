"""TTL-bounded output handle store.

When an exec produces more output than the inline cap (default 256 KB),
the surplus is kept here under a short-lived handle. The agent passes
the handle to ``shell_output_get`` to paginate the rest. Handles
expire after 5 minutes; total store size is capped at 64 MB with LRU
eviction so the server can't be DoS'd by a chatty subprocess.

Thread-safe — exec/job code paths populate; the MCP request thread
drains.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field

_DEFAULT_TTL_SEC = 300
_DEFAULT_TOTAL_CAP_BYTES = 64 * 1024 * 1024


@dataclass(slots=True)
class _Entry:
    data: bytes
    created_at: float
    last_accessed_at: float = field(default_factory=time.monotonic)


class OutputStore:
    """LRU-with-TTL byte store keyed by opaque handle."""

    def __init__(
        self,
        ttl_sec: int = _DEFAULT_TTL_SEC,
        total_cap_bytes: int = _DEFAULT_TOTAL_CAP_BYTES,
    ):
        self._ttl = ttl_sec
        self._cap = total_cap_bytes
        self._entries: dict[str, _Entry] = {}
        self._total_bytes = 0
        self._lock = threading.Lock()

    def put(self, data: bytes) -> str:
        """Store ``data``, return a fresh handle. Evicts older entries
        if the total cap would be exceeded."""
        if not data:
            # Empty payloads don't need a handle.
            return ""
        handle = "out_" + secrets.token_hex(8)
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            # Reserve room for new entry; evict LRU until it fits.
            while self._total_bytes + len(data) > self._cap and self._entries:
                self._pop_lru_locked()
            self._entries[handle] = _Entry(data=data, created_at=now, last_accessed_at=now)
            self._total_bytes += len(data)
        return handle

    def get(self, handle: str, since_offset: int = 0, max_bytes: int = 64 * 1024) -> dict:
        """Retrieve a slice of stored data.

        Returns ``{data, offset, next_offset, eof, expired}`` so the
        agent can paginate without separate calls. ``expired=True``
        when the handle is unknown or the TTL has lapsed.
        """
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            entry = self._entries.get(handle)
            if entry is None:
                return {
                    "data": "",
                    "offset": int(since_offset),
                    "next_offset": int(since_offset),
                    "eof": True,
                    "expired": True,
                }
            entry.last_accessed_at = now
            buf = entry.data

        since = max(0, int(since_offset))
        end = min(len(buf), since + max(0, int(max_bytes)))
        data_slice = buf[since:end]
        return {
            "data": data_slice.decode("utf-8", errors="replace"),
            "offset": since,
            "next_offset": end,
            "eof": end >= len(buf),
            "expired": False,
        }

    # ── Eviction ──────────────────────────────────────────────────

    def _evict_locked(self, now: float) -> None:
        # TTL eviction — anything past TTL goes.
        stale = [h for h, e in self._entries.items() if now - e.created_at > self._ttl]
        for h in stale:
            entry = self._entries.pop(h, None)
            if entry is not None:
                self._total_bytes -= len(entry.data)

    def _pop_lru_locked(self) -> None:
        if not self._entries:
            return
        oldest_handle = min(self._entries, key=lambda h: self._entries[h].last_accessed_at)
        entry = self._entries.pop(oldest_handle)
        self._total_bytes -= len(entry.data)


# Module-level singleton; the server has one instance per process.
_STORE = OutputStore()


def get_store() -> OutputStore:
    return _STORE


__all__ = ["OutputStore", "get_store"]
