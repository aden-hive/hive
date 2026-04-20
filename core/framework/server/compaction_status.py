"""Track fork-compaction status for freshly-forked colony queen sessions.

When ``create_colony`` forks a queen session into a colony, the
inherited DM transcript is compacted via an LLM call that can legitimately
exceed the default tool-call timeout (60s). To keep ``create_colony``
responsive we run that compaction in the background and record its
status on disk so a subsequent colony session-load can wait for it to
settle before reading the conversation files.

The status lives at ``<queen_dir>/compaction_status.json``:

    {"status": "in_progress", "started_at": "..."}
    {"status": "done", "completed_at": "...", "messages_compacted": N, "summary_chars": M}
    {"status": "failed", "completed_at": "...", "error": "..."}

Only present when a compaction was scheduled for this queen dir — absent
otherwise. All writes are fail-soft; a missing/corrupt file is treated
as "no compaction pending".
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_STATUS_FILENAME = "compaction_status.json"


def _status_path(queen_dir: Path) -> Path:
    return Path(queen_dir) / _STATUS_FILENAME


def mark_in_progress(queen_dir: Path) -> None:
    path = _status_path(queen_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "status": "in_progress",
                    "started_at": datetime.now(UTC).isoformat(),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.warning(
            "compaction_status: failed to write 'in_progress' at %s",
            path,
            exc_info=True,
        )


def mark_done(
    queen_dir: Path,
    *,
    messages_compacted: int = 0,
    summary_chars: int = 0,
) -> None:
    path = _status_path(queen_dir)
    try:
        path.write_text(
            json.dumps(
                {
                    "status": "done",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "messages_compacted": messages_compacted,
                    "summary_chars": summary_chars,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.warning(
            "compaction_status: failed to write 'done' at %s",
            path,
            exc_info=True,
        )


def mark_failed(queen_dir: Path, error: str) -> None:
    path = _status_path(queen_dir)
    try:
        path.write_text(
            json.dumps(
                {
                    "status": "failed",
                    "completed_at": datetime.now(UTC).isoformat(),
                    "error": (error or "")[:500],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        logger.warning(
            "compaction_status: failed to write 'failed' at %s",
            path,
            exc_info=True,
        )


def get_status(queen_dir: Path) -> dict | None:
    path = _status_path(queen_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


async def await_completion(
    queen_dir: Path,
    *,
    timeout: float = 180.0,
    poll: float = 0.5,
) -> dict | None:
    """Block until compaction leaves 'in_progress' state.

    Returns the final status dict, or ``None`` if no compaction marker
    exists for this dir. On timeout returns the last observed status
    (still 'in_progress') so the caller can decide whether to proceed
    with the raw transcript.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + max(0.0, timeout)
    last: dict | None = None
    while True:
        last = get_status(queen_dir)
        if last is None:
            return None
        if last.get("status") != "in_progress":
            return last
        if loop.time() >= deadline:
            logger.warning(
                "compaction_status: timed out after %.0fs waiting for %s (proceeding with raw transcript)",
                timeout,
                queen_dir,
            )
            return last
        await asyncio.sleep(poll)
