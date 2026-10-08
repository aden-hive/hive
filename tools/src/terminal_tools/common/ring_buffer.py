"""Bounded byte ring buffer with absolute monotonic offsets.

The streaming primitive shared by jobs and PTY sessions. Writers push
bytes; readers ask for ``[since_offset, since_offset + N)`` and the
buffer either returns the data (if still in window) or signals how
many bytes were dropped from the floor. This lets the agent resume
after a missed poll without silent loss.

Thread-safe via a single lock — readers and writers can come from
different threads (a pump thread fills it, the MCP request thread
drains it).
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass


@dataclass(slots=True)
class ReadResult:
    data: bytes
    offset: int
    next_offset: int
    truncated_bytes_dropped: int  # bytes lost between since_offset and the buffer floor


class RingBuffer:
    """Capacity-bounded byte ring with absolute offsets.

    The total written count never resets; each call sees absolute
    offsets growing monotonically. The on-disk window slides forward
    once total_written exceeds capacity_bytes.
    """

    def __init__(self, capacity_bytes: int = 4 * 1024 * 1024):
        if capacity_bytes <= 0:
            raise ValueError("capacity_bytes must be positive")
        self._capacity = capacity_bytes
        self._chunks: deque[bytes] = deque()
        self._buffered_bytes = 0
        self._floor = 0  # absolute offset of the oldest byte still in buffer
        self._total_written = 0
        self._eof = False
        self._lock = threading.Lock()

    # ── Writer side ───────────────────────────────────────────────

    def write(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._chunks.append(data)
            self._buffered_bytes += len(data)
            self._total_written += len(data)
            self._evict_locked()

    def close(self) -> None:
        """Mark the stream as ended. Subsequent reads will see eof=True
        once they catch up to total_written."""
        with self._lock:
            self._eof = True

    def _evict_locked(self) -> None:
        while self._buffered_bytes > self._capacity and self._chunks:
            head = self._chunks[0]
            overshoot = self._buffered_bytes - self._capacity
            if len(head) <= overshoot:
                self._chunks.popleft()
                self._buffered_bytes -= len(head)
                self._floor += len(head)
            else:
                self._chunks[0] = head[overshoot:]
                self._buffered_bytes -= overshoot
                self._floor += overshoot

    # ── Reader side ───────────────────────────────────────────────

    @property
    def total_written(self) -> int:
        with self._lock:
            return self._total_written

    @property
    def floor(self) -> int:
        with self._lock:
            return self._floor

    @property
    def eof(self) -> bool:
        with self._lock:
            return self._eof

    def read(self, since_offset: int, max_bytes: int) -> ReadResult:
        """Read up to ``max_bytes`` starting at ``since_offset``.

        - If ``since_offset`` is past total_written, returns empty data
          (and ``next_offset == since_offset``, signaling caller to wait).
        - If ``since_offset`` is below the buffer floor, the missed
          bytes are reported as ``truncated_bytes_dropped`` and reading
          starts from the floor.
        """
        max_bytes = max(0, int(max_bytes))
        with self._lock:
            since = max(0, int(since_offset))
            dropped = 0
            if since < self._floor:
                dropped = self._floor - since
                since = self._floor

            available = self._total_written - since
            if available <= 0 or max_bytes == 0:
                return ReadResult(
                    data=b"",
                    offset=since,
                    next_offset=since,
                    truncated_bytes_dropped=dropped,
                )

            to_take = min(available, max_bytes)
            # Walk chunks to assemble [since, since+to_take)
            cursor = self._floor
            collected: list[bytes] = []
            remaining = to_take
            for chunk in self._chunks:
                chunk_end = cursor + len(chunk)
                if chunk_end <= since:
                    cursor = chunk_end
                    continue
                start_in_chunk = max(0, since - cursor)
                end_in_chunk = min(len(chunk), start_in_chunk + remaining)
                slice_ = chunk[start_in_chunk:end_in_chunk]
                collected.append(slice_)
                remaining -= len(slice_)
                cursor = chunk_end
                if remaining <= 0:
                    break

            data = b"".join(collected)
            return ReadResult(
                data=data,
                offset=since,
                next_offset=since + len(data),
                truncated_bytes_dropped=dropped,
            )

    def tail(self, max_bytes: int) -> ReadResult:
        """Read the last ``max_bytes`` (or as much as is buffered)."""
        with self._lock:
            start = max(self._floor, self._total_written - max(0, int(max_bytes)))
        return self.read(start, max_bytes)


__all__ = ["RingBuffer", "ReadResult"]
