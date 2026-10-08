"""Append-only JSONL event log with self-healing writes.

Extracted from :class:`~framework.host.event_bus.EventBus` so that every log
the bus writes to gets the same recovery semantics. Today that is the queen's
``events.jsonl``; per-worker logs are next, and they must not have to
reimplement this.

The recovery path is load-bearing. Before it existed, a single failed write
left a closed handle in place and every subsequent event was silently dropped
for the rest of the session — ``parts/`` kept growing while the desktop's chat
view froze mid-session (the 2026-07-02 01:04:30 incident).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import IO

logger = logging.getLogger(__name__)


class EventLogFile:
    """A JSONL file that reopens itself once on a failed write.

    Opening happens eagerly in the constructor, so a caller that wants to
    treat "cannot open" as fatal can let the ``OSError`` propagate.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: IO[str] | None = None
        # True once a write has failed and the reopen also failed. Rate-limits
        # the WARN so a persistently broken handle doesn't spam the runtime log
        # on every publish. A successful reopen resets it.
        self._broken = False
        self._open()

    @property
    def broken(self) -> bool:
        return self._broken

    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a", encoding="utf-8")  # noqa: SIM115

    def _reopen(self) -> None:
        """Drop any dangling handle and reattach to the recorded path."""
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        self._open()

    def write(self, line: str) -> None:
        """Append ``line`` (newline added) and flush. Never raises."""
        if self._fh is None:
            return
        try:
            self._fh.write(line + "\n")
            self._fh.flush()
            return
        except (ValueError, OSError):
            # ValueError: I/O operation on closed file — the specific 01:04:30
            # symptom. OSError: EIO / ENOSPC / the file was rotated out from
            # under us. Both are recoverable by reopening at the same path.
            pass

        try:
            self._reopen()
            self._fh.write(line + "\n")  # type: ignore[union-attr]
            self._fh.flush()  # type: ignore[union-attr]
            if self._broken:
                logger.info("Event log recovered → %s", self.path)
            self._broken = False
        except (ValueError, OSError) as second_err:
            # Reopen failed too. NULL the handle so subsequent writes
            # short-circuit cleanly instead of raising on every event.
            self._fh = None
            if not self._broken:
                self._broken = True
                logger.warning("Event log reopen failed for %s: %s", self.path, second_err)

    def flush(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.flush()
        except Exception:
            pass

    def close(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.close()
        except Exception:
            pass
        finally:
            self._fh = None
