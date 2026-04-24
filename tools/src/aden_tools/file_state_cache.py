"""Per-agent tracking of files the model has Read, so Edit can detect
staleness from external writes (e.g. the user saving the file in their
editor between a Read and an Edit).

The cache lives in the MCP server process and is keyed on
``(scope, absolute_path)`` where ``scope`` is the agent_id when available
(the normal case) or ``"__global__"`` as a last-resort fallback. That
keeps two agents running in the same MCP server process from sharing
(or corrupting) each other's read-state view.

Freshness is decided by ``(size, mtime_ns, sha256)``:
- If the file's ``size`` and ``mtime_ns`` both match the recorded values,
  we trust the read (fast path, no hashing).
- If either differs, we hash the current content and compare to the
  recorded sha. mtime preservation by some editors means mtime alone is
  unreliable; hashing only on a mismatch keeps the happy path cheap.

The cache is bounded (LRU, 256 entries per scope) so a chatty agent
cannot grow it without bound.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class FileReadRecord:
    size: int
    mtime_ns: int
    sha256: str


class Freshness(Enum):
    FRESH = "fresh"
    STALE = "stale"
    UNREAD = "unread"


@dataclass
class FreshResult:
    status: Freshness
    detail: str = ""


_MAX_ENTRIES_PER_SCOPE = 256

# scope -> ordered dict of absolute_path -> FileReadRecord.
# Ordered so we can evict least-recently-read entries.
_cache: dict[str, OrderedDict[str, FileReadRecord]] = {}
_lock = threading.Lock()


def _scope_key(agent_id: str | None) -> str:
    return agent_id or "__global__"


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(abs_path: str) -> str:
    h = hashlib.sha256()
    with open(abs_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def record_read(
    agent_id: str | None,
    abs_path: str,
    content_bytes: bytes | None = None,
) -> None:
    """Record that ``abs_path`` was just successfully read.

    If ``content_bytes`` is provided the hash is computed from that; this
    is the fast path and avoids a second open. Otherwise we re-open the
    file to hash it. Silently ignores files that disappear between the
    read and the record (race with concurrent deletion).
    """
    try:
        st = os.stat(abs_path)
    except OSError:
        return

    try:
        sha = _hash_bytes(content_bytes) if content_bytes is not None else _hash_file(abs_path)
    except OSError:
        return

    rec = FileReadRecord(size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=sha)
    scope = _scope_key(agent_id)
    with _lock:
        entries = _cache.setdefault(scope, OrderedDict())
        entries[abs_path] = rec
        entries.move_to_end(abs_path)
        while len(entries) > _MAX_ENTRIES_PER_SCOPE:
            entries.popitem(last=False)


def check_fresh(agent_id: str | None, abs_path: str) -> FreshResult:
    """Check whether ``abs_path`` is safe to edit.

    Returns FRESH if the file on disk matches the recorded read.
    Returns STALE if it was read previously but has since changed.
    Returns UNREAD if the agent has never read this path via read_file.
    """
    scope = _scope_key(agent_id)
    with _lock:
        entries = _cache.get(scope)
        rec = entries.get(abs_path) if entries else None
        if rec is not None and entries is not None:
            entries.move_to_end(abs_path)

    if rec is None:
        return FreshResult(Freshness.UNREAD)

    try:
        st = os.stat(abs_path)
    except FileNotFoundError:
        return FreshResult(Freshness.STALE, "file has been deleted since it was read")
    except OSError as e:
        return FreshResult(Freshness.STALE, f"stat failed: {e}")

    if st.st_size == rec.size and st.st_mtime_ns == rec.mtime_ns:
        return FreshResult(Freshness.FRESH)

    # mtime/size differ - fall through to a content hash so that editors
    # that rewrite the file with identical content don't trip a false
    # stale. This is the only path where we pay the O(file) hashing cost.
    try:
        current_sha = _hash_file(abs_path)
    except OSError as e:
        return FreshResult(Freshness.STALE, f"hash failed: {e}")

    if current_sha == rec.sha256:
        # Content is unchanged even though metadata differs (e.g. editor
        # rewrote with preserved content). Refresh the record so future
        # checks hit the fast path again.
        rec = FileReadRecord(size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=current_sha)
        with _lock:
            entries = _cache.setdefault(scope, OrderedDict())
            entries[abs_path] = rec
            entries.move_to_end(abs_path)
        return FreshResult(Freshness.FRESH)

    return FreshResult(
        Freshness.STALE,
        "content changed on disk since the last read (sha256 differs)",
    )


def forget(agent_id: str | None, abs_path: str) -> None:
    """Drop a single cache entry. Used in tests to force UNREAD."""
    scope = _scope_key(agent_id)
    with _lock:
        entries = _cache.get(scope)
        if entries is not None:
            entries.pop(abs_path, None)


def clear_scope(agent_id: str | None) -> None:
    """Drop all entries for one agent (used at session teardown)."""
    with _lock:
        _cache.pop(_scope_key(agent_id), None)


def reset_all() -> None:
    """Test hook: wipe every scope."""
    with _lock:
        _cache.clear()
