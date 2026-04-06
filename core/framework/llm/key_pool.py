"""Thread-safe API key pool with round-robin rotation and health tracking.

When multiple API keys are configured, the pool rotates through them on each
request.  Keys that hit rate limits are temporarily cooled-down so the next
call automatically uses a healthy key -- no sleep required.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class KeyHealth:
    """Per-key health counters."""

    rate_limited_until: float = 0.0  # monotonic timestamp
    consecutive_errors: int = 0
    total_requests: int = 0
    total_successes: int = 0


class KeyPool:
    """Round-robin key pool with health tracking.

    Thread-safe: all mutations protected by a lock so concurrent LLM calls
    (e.g. parallel tool execution in EventLoopNode) don't race.
    """

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError("KeyPool requires at least one key")
        self._keys = list(keys)
        self._index = 0
        self._health: dict[str, KeyHealth] = {k: KeyHealth() for k in keys}
        self._lock = threading.Lock()

    @property
    def size(self) -> int:
        return len(self._keys)

    def get_key(self) -> str:
        """Return the next healthy key (round-robin).

        If every key is currently rate-limited, returns the one whose cooldown
        expires soonest so the caller can proceed with minimal delay.
        """
        with self._lock:
            now = time.monotonic()
            for _ in range(len(self._keys)):
                key = self._keys[self._index]
                self._index = (self._index + 1) % len(self._keys)
                health = self._health[key]
                if health.rate_limited_until <= now:
                    health.total_requests += 1
                    return key
            # All rate-limited -- pick the one that expires soonest.
            soonest = min(self._keys, key=lambda k: self._health[k].rate_limited_until)
            self._health[soonest].total_requests += 1
            return soonest

    def mark_rate_limited(self, key: str, retry_after: float = 60.0) -> None:
        """Mark *key* as rate-limited for *retry_after* seconds."""
        with self._lock:
            health = self._health.get(key)
            if health:
                health.rate_limited_until = time.monotonic() + retry_after
                health.consecutive_errors += 1
                logger.info(
                    "[key-pool] Key ...%s rate-limited for %.0fs (errors=%d)",
                    key[-6:],
                    retry_after,
                    health.consecutive_errors,
                )

    def mark_success(self, key: str) -> None:
        """Record a successful call on *key*."""
        with self._lock:
            health = self._health.get(key)
            if health:
                health.consecutive_errors = 0
                health.total_successes += 1

    def get_stats(self) -> dict[str, dict]:
        """Return health stats keyed by the last 6 chars of each key."""
        with self._lock:
            now = time.monotonic()
            return {
                f"...{k[-6:]}": {
                    "healthy": self._health[k].rate_limited_until <= now,
                    "requests": self._health[k].total_requests,
                    "successes": self._health[k].total_successes,
                    "consecutive_errors": self._health[k].consecutive_errors,
                }
                for k in self._keys
            }
