"""Cache build / sync for memory-tools.

The ``search_messages`` tool searches a derived **mirror cache** rather
than the raw session storage. This module owns building and incremental
syncing of that cache.

Why a mirror cache?
    1. Scope correctness — the cache writer extracts ONLY the in-scope
       text (user content / assistant prose / tool result body). Fields
       outside scope (tool_name, tool_input, reasoning_*, finish_reason,
       token_count, timestamps, correlation ids) never enter the cache,
       so the matcher physically cannot match them.
    2. Performance — append-only ``events.jsonl`` lets us resume from a
       byte offset on every sync; rg-class search runs over a flat tree
       of small text files in single-digit ms warm.

Source ↔ cache mapping (one cache file per in-scope message):
    events/<scope>/<owner>/<session>/<NNNNNN>.<role>.txt
        body = data.content (user)
             | last data.snapshot per (iteration, inner_turn) (assistant)
             | data.result (tool, small)
             | spilled body from <session>/data/<file>.txt (tool, large)

    data/<scope>/<owner>/<session>/<spill_filename>.txt
        body = hardlink (or capped copy) of <session>/data/<file>.txt

Cursor invariants:
    * events.jsonl is strictly append-only by the runtime, so resuming
      from cursor.events_byte_offset only sees genuinely new content.
    * If file size < cursor offset, the file was wiped (compact-and-fork
      on a forked session). We reset the cursor and start over.
    * Trailing pending assistant (a turn still streaming deltas at EOF)
      is NOT flushed; we stash it in cursor.pending_assistant and resume
      next sync once a non-delta event arrives.
"""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

# fcntl is POSIX-only; on Windows we fall back to msvcrt.locking. Both back
# the _flock helper below.
if os.name == "nt":
    import msvcrt

    fcntl = None  # type: ignore[assignment]
else:
    import fcntl  # type: ignore[no-redef]

    msvcrt = None  # type: ignore[assignment]

from memory_tools import paths as P


def _flock_exclusive(fd: int) -> None:
    """Acquire an exclusive advisory lock on ``fd``, blocking until granted."""
    if os.name == "nt":
        # msvcrt.locking blocks for up to ~10s per call before raising; loop
        # so we behave like fcntl.flock(LOCK_EX) and wait indefinitely.
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                return
            except OSError as e:
                # EDEADLK / 36 means the 10s wait elapsed; try again.
                if e.errno not in (errno.EDEADLK, 36):
                    raise
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _flock_release(fd: int) -> None:
    """Release the advisory lock on ``fd``."""
    if os.name == "nt":
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            # Releasing a lock we don't hold isn't fatal here — close() will
            # drop any remaining lock anyway.
            pass
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)


logger = logging.getLogger(__name__)


# Cap each spilled tool-result body when copy-fallback is used (no hardlink).
# Hardlinks impose no cap. Default 1 MiB; oversize results get head-truncated
# with a marker so search still hits the head, and the original is on disk.
DEFAULT_MAX_SPILL_COPY_BYTES = 1 * 1024 * 1024

# Match the placeholder header that tool_result_handler writes for large
# results. The first line is the header sentence; the path appears after
# "Full result saved at: ". See tool_result_handler.py:343.
_SPILL_PLACEHOLDER_HEADER = re.compile(r"^Tool `[^`]+` returned [\d,]+ characters")
_SPILL_PATH_RE = re.compile(r"Full result saved at:\s*(\S+)")


@dataclass
class Cursor:
    events_byte_offset: int = 0
    next_ordinal: int = 0
    pending_assistant: dict | None = None  # {iteration, inner_turn, snapshot}

    def to_dict(self) -> dict:
        return {
            "events_byte_offset": self.events_byte_offset,
            "next_ordinal": self.next_ordinal,
            "pending_assistant": self.pending_assistant,
        }

    @classmethod
    def from_dict(cls, d: dict) -> Cursor:
        return cls(
            events_byte_offset=int(d.get("events_byte_offset", 0)),
            next_ordinal=int(d.get("next_ordinal", 0)),
            pending_assistant=d.get("pending_assistant"),
        )


@dataclass
class SyncStats:
    sessions_visited: int = 0
    sessions_synced: int = 0  # i.e. produced at least one new cache file
    ordinals_added: int = 0
    spills_indexed: int = 0
    elapsed_ms: int = 0
    errors: list[str] = field(default_factory=list)


# ── Persistence helpers ────────────────────────────────────────────────


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


def _atomic_write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    tmp.replace(path)


@contextmanager
def _session_lock(scope: P.Scope, owner: str, session: str):
    """Advisory file lock per session — serializes concurrent syncs."""
    lock_path = P.session_lock_path(scope, owner, session)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _flock_exclusive(fd)
        yield
    finally:
        try:
            _flock_release(fd)
        finally:
            os.close(fd)


# ── Cache writers ──────────────────────────────────────────────────────


def _ordinal_filename(ordinal: int, role: str) -> str:
    return f"{ordinal:06d}.{role}.txt"


def _flush_pending_assistant(
    *,
    cursor: Cursor,
    events_dir: Path,
    stats: SyncStats,
) -> None:
    """Write the buffered assistant snapshot (if any) and bump the ordinal."""
    pa = cursor.pending_assistant
    if not pa:
        return
    snapshot = pa.get("snapshot") or ""
    if not snapshot:
        cursor.pending_assistant = None
        return
    out = events_dir / _ordinal_filename(cursor.next_ordinal, "assistant")
    _atomic_write_text(out, snapshot)
    cursor.next_ordinal += 1
    stats.ordinals_added += 1
    cursor.pending_assistant = None


def _write_message(
    *,
    role: Literal["user", "tool"],
    content: str,
    cursor: Cursor,
    events_dir: Path,
    stats: SyncStats,
) -> int:
    """Write a non-assistant message; returns its ordinal."""
    ordinal = cursor.next_ordinal
    out = events_dir / _ordinal_filename(ordinal, role)
    _atomic_write_text(out, content)
    cursor.next_ordinal += 1
    stats.ordinals_added += 1
    return ordinal


# ── Spillover handling ─────────────────────────────────────────────────


def _detect_spill_path(result_text: str) -> Path | None:
    """Return the absolute path encoded in a placeholder, else None."""
    if not result_text or not _SPILL_PLACEHOLDER_HEADER.match(result_text):
        return None
    m = _SPILL_PATH_RE.search(result_text)
    if not m:
        return None
    return Path(m.group(1))


def _resolve_tool_content(result_text: str, *, max_copy_bytes: int) -> tuple[str, Path | None]:
    """Resolve the body to cache for a tool_call_completed event.

    Returns (cached_content, spill_path_if_any).
    For small results (no placeholder), passes through unchanged.
    For placeholders, reads the spilled file (capped to max_copy_bytes).
    If the spilled file is missing, falls back to the placeholder text.
    """
    spill_path = _detect_spill_path(result_text)
    if spill_path is None:
        return result_text, None
    try:
        if not spill_path.exists():
            return result_text, spill_path  # caller still records the name in data_map
        st = spill_path.stat()
        if st.st_size <= max_copy_bytes:
            return spill_path.read_text(encoding="utf-8", errors="replace"), spill_path
        # Read head only.
        with spill_path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(max_copy_bytes)
        marker = f"\n\n…[truncated to {max_copy_bytes} bytes — full body at {spill_path}]…\n"
        return head + marker, spill_path
    except OSError as exc:
        logger.warning("memory_tools: failed reading spill %s: %s", spill_path, exc)
        return result_text, spill_path


def _mirror_data_dir(
    *,
    scope: P.Scope,
    owner: str,
    session: str,
    max_copy_bytes: int,
    stats: SyncStats,
) -> None:
    """Mirror new spillover files from <session>/data/ into the data index.

    Hardlinks when possible (zero copy). Falls back to capped copies on
    cross-filesystem or platforms without hardlink support.
    """
    src_dir = P.session_data_dir(scope, owner, session)
    if not src_dir.exists():
        return
    dst_dir = P.data_index_dir(scope, owner, session)
    dst_dir.mkdir(parents=True, exist_ok=True)

    for entry in os.scandir(src_dir):
        if not entry.is_file():
            continue
        # Only mirror text-shaped spills; the spill writer always pretty-prints
        # JSON or plain text, so .txt is the canonical extension. Skip others
        # (binary blobs that would just bloat rg time without yielding hits).
        if not entry.name.endswith(".txt"):
            continue
        dst = dst_dir / entry.name
        if dst.exists():
            continue  # already mirrored
        src_path = Path(entry.path)
        try:
            os.link(src_path, dst)
            stats.spills_indexed += 1
            continue
        except OSError as exc:
            if exc.errno not in (errno.EXDEV, errno.EPERM, errno.EOPNOTSUPP):
                logger.warning("memory_tools: hardlink failed for %s: %s", src_path, exc)
        # Fallback: capped copy.
        try:
            size = src_path.stat().st_size
            if size <= max_copy_bytes:
                shutil.copyfile(src_path, dst)
            else:
                with src_path.open("r", encoding="utf-8", errors="replace") as f:
                    head = f.read(max_copy_bytes)
                marker = f"\n\n…[truncated to {max_copy_bytes} bytes — full body at {src_path}]…\n"
                dst.write_text(head + marker, encoding="utf-8")
            stats.spills_indexed += 1
        except OSError as exc:
            logger.warning("memory_tools: copy failed for %s: %s", src_path, exc)
            stats.errors.append(f"copy {src_path}: {exc}")


# ── Per-session sync ───────────────────────────────────────────────────


def sync_session(
    scope: P.Scope,
    owner: str,
    session: str,
    *,
    max_spill_copy_bytes: int = DEFAULT_MAX_SPILL_COPY_BYTES,
) -> SyncStats:
    """Sync the cache for one session. Idempotent and resumable."""
    stats = SyncStats(sessions_visited=1)
    t0 = time.monotonic()

    events_path = P.events_jsonl(scope, owner, session)
    if not events_path.exists():
        # No events file — nothing to do. Don't even create cache dirs.
        stats.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return stats

    with _session_lock(scope, owner, session):
        cursor_p = P.cursor_path(scope, owner, session)
        cursor = Cursor.from_dict(_read_json(cursor_p))

        # Wipe detection: file shrank since last sync.
        try:
            file_size = events_path.stat().st_size
        except OSError as exc:
            stats.errors.append(f"stat {events_path}: {exc}")
            stats.elapsed_ms = int((time.monotonic() - t0) * 1000)
            return stats

        if file_size < cursor.events_byte_offset:
            logger.info(
                "memory_tools: events.jsonl wiped for %s/%s/%s — resetting cache",
                scope,
                owner,
                session,
            )
            _reset_session_cache(scope, owner, session)
            cursor = Cursor()

        events_dir = P.events_index_dir(scope, owner, session)
        events_dir.mkdir(parents=True, exist_ok=True)

        # Load data_map (filename → ordinal) so spill mirror hits can be
        # mapped back to a turn ordinal.
        data_map_p = P.data_map_path(scope, owner, session)
        data_map = _read_json(data_map_p)

        before_ordinal = cursor.next_ordinal

        # Stream new events from the cursor.
        try:
            with events_path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(cursor.events_byte_offset)
                for line in f:
                    raw_len = len(line.encode("utf-8", errors="replace"))
                    cursor.events_byte_offset += raw_len
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    _process_event(
                        event,
                        cursor=cursor,
                        events_dir=events_dir,
                        data_map=data_map,
                        max_spill_copy_bytes=max_spill_copy_bytes,
                        stats=stats,
                    )
        except OSError as exc:
            stats.errors.append(f"read {events_path}: {exc}")
            stats.elapsed_ms = int((time.monotonic() - t0) * 1000)
            return stats

        # Persist cursor + data_map AFTER processing.
        _atomic_write_json(cursor_p, cursor.to_dict())
        _atomic_write_json(data_map_p, data_map)

        # Mirror spilled data files (independent of events processing —
        # the spilled file may already exist before its event lands, or
        # vice versa).
        _mirror_data_dir(
            scope=scope,
            owner=owner,
            session=session,
            max_copy_bytes=max_spill_copy_bytes,
            stats=stats,
        )

    if cursor.next_ordinal > before_ordinal:
        stats.sessions_synced = 1
    stats.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return stats


def _reset_session_cache(scope: P.Scope, owner: str, session: str) -> None:
    """Move stale cache aside under .stale/<ts>/ for safety, then clear."""
    base_meta = P.meta_dir(scope, owner, session)
    stale_root = base_meta / ".stale" / datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    stale_root.mkdir(parents=True, exist_ok=True)
    for src in (
        P.events_index_dir(scope, owner, session),
        P.data_index_dir(scope, owner, session),
    ):
        if src.exists():
            try:
                shutil.move(str(src), str(stale_root / src.name))
            except OSError:
                # Best-effort; if move fails just delete.
                shutil.rmtree(src, ignore_errors=True)
    for f in (P.cursor_path(scope, owner, session), P.data_map_path(scope, owner, session)):
        if f.exists():
            f.unlink(missing_ok=True)


def _process_event(
    event: dict,
    *,
    cursor: Cursor,
    events_dir: Path,
    data_map: dict,
    max_spill_copy_bytes: int,
    stats: SyncStats,
) -> None:
    """Update cursor / write cache files based on one event."""
    etype = event.get("type")
    data = event.get("data") or {}

    if etype == "client_input_received":
        _flush_pending_assistant(cursor=cursor, events_dir=events_dir, stats=stats)
        content = data.get("content") or ""
        if content:
            _write_message(
                role="user",
                content=content,
                cursor=cursor,
                events_dir=events_dir,
                stats=stats,
            )
        return

    if etype == "client_output_delta":
        iteration = data.get("iteration")
        inner_turn = data.get("inner_turn")
        snapshot = data.get("snapshot") or ""
        pa = cursor.pending_assistant
        if pa and pa.get("iteration") == iteration and pa.get("inner_turn") == inner_turn:
            pa["snapshot"] = snapshot
        else:
            _flush_pending_assistant(cursor=cursor, events_dir=events_dir, stats=stats)
            cursor.pending_assistant = {
                "iteration": iteration,
                "inner_turn": inner_turn,
                "snapshot": snapshot,
            }
        return

    if etype == "tool_call_completed":
        # Any tool result implicitly closes the assistant turn that
        # produced it.
        _flush_pending_assistant(cursor=cursor, events_dir=events_dir, stats=stats)
        result = data.get("result")
        if not isinstance(result, str):
            # Some result shapes may be dicts; serialize for searchability.
            try:
                result = json.dumps(result, ensure_ascii=False)
            except (TypeError, ValueError):
                result = ""
        if data.get("is_error"):
            # Errors are still in scope (they are tool results the model saw).
            pass
        cached, spill = _resolve_tool_content(result, max_copy_bytes=max_spill_copy_bytes)
        ordinal = _write_message(
            role="tool",
            content=cached,
            cursor=cursor,
            events_dir=events_dir,
            stats=stats,
        )
        if spill is not None:
            data_map[spill.name] = ordinal
        return

    # Other event types are intentionally ignored — they're outside the
    # search scope (tool_call_started, llm_turn_complete, judge_verdict,
    # context_compacted, queen_identity_selected, etc.).


# ── Scope-level sync ───────────────────────────────────────────────────


def sync_scope(
    scope: P.Scope,
    owner: str,
    *,
    session_filter: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    max_workers: int = 8,
    max_spill_copy_bytes: int = DEFAULT_MAX_SPILL_COPY_BYTES,
) -> SyncStats:
    """Sync every session matching the filters, in parallel."""
    aggregate = SyncStats()
    t0 = time.monotonic()

    sessions = P.list_sessions(scope, owner, session_filter=session_filter, since=since, until=until)
    if not sessions:
        aggregate.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return aggregate

    if len(sessions) == 1 or max_workers <= 1:
        for s in sessions:
            stats = sync_session(scope, owner, s, max_spill_copy_bytes=max_spill_copy_bytes)
            _accumulate(aggregate, stats)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    sync_session,
                    scope,
                    owner,
                    s,
                    max_spill_copy_bytes=max_spill_copy_bytes,
                ): s
                for s in sessions
            }
            for fut in as_completed(futures):
                try:
                    stats = fut.result()
                except Exception as exc:  # noqa: BLE001
                    aggregate.errors.append(f"session {futures[fut]}: {exc}")
                    continue
                _accumulate(aggregate, stats)

    aggregate.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return aggregate


def _accumulate(agg: SyncStats, one: SyncStats) -> None:
    agg.sessions_visited += one.sessions_visited
    agg.sessions_synced += one.sessions_synced
    agg.ordinals_added += one.ordinals_added
    agg.spills_indexed += one.spills_indexed
    agg.errors.extend(one.errors)


__all__ = [
    "Cursor",
    "SyncStats",
    "sync_session",
    "sync_scope",
    "DEFAULT_MAX_SPILL_COPY_BYTES",
]
