"""Path resolution for memory-tools.

Source layout (read-only, v3 — framework.config):
    $HIVE_HOME/queens/<queen_id>/sessions/<session>/
        events.jsonl
        data/<tool>_<n>.txt          # spilled tool result bodies
    $HIVE_HOME/colonies/<colony>/queens/<queen_id>/sessions/<session>/
        events.jsonl                 # the overseer queen's session; worker
        data/...                     # tool results are logged here too

A colony's sessions are the union of its overseer queens' session dirs.
Session ids are globally unique, so a session resolves by id alone.

Index layout (read/write — built lazily by index.sync_scope):
    $HIVE_HOME/.message_index/
        events/<scope>/<owner>/<session>/<NNNNNN>.<role>.txt
        data/<scope>/<owner>/<session>/<spill_filename>.txt
        meta/<scope>/<owner>/<session>/cursor.json
        meta/<scope>/<owner>/<session>/data_map.json

``<scope>`` is the literal string ``"queens"`` or ``"colonies"``.
``<owner>`` is the queen_id or colony name.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

Scope = Literal["queens", "colonies"]


def hive_home() -> Path:
    """Resolve $HIVE_HOME, mirroring framework.config:_resolve_hive_home."""
    override = os.environ.get("HIVE_HOME")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".hive"


def scope_root(scope: Scope) -> Path:
    """Source root for a given scope."""
    if scope == "queens":
        # v3 layout (framework.config.queen_sessions_dir). The v2
        # ``agents/queens`` tree is migrated away, so searching it finds
        # nothing on any current install.
        return hive_home() / "queens"
    return hive_home() / "colonies"


def owner_dir(scope: Scope, owner: str) -> Path:
    return scope_root(scope) / owner


def session_roots(scope: Scope, owner: str) -> list[Path]:
    """Directories holding *owner*'s ``session_*`` dirs.

    A queen has one; a colony has one per queen that has overseen it.
    """
    if scope == "queens":
        return [owner_dir(scope, owner) / "sessions"]
    queens = owner_dir(scope, owner) / "queens"
    if not queens.is_dir():
        return []
    return sorted(q / "sessions" for q in queens.iterdir() if (q / "sessions").is_dir())


def session_dir(scope: Scope, owner: str, session: str) -> Path:
    """The directory of one session (may not exist if the id is unknown)."""
    roots = session_roots(scope, owner)
    for root in roots:
        if (root / session).is_dir():
            return root / session
    return (roots[0] if roots else owner_dir(scope, owner) / "sessions") / session


def events_jsonl(scope: Scope, owner: str, session: str) -> Path:
    return session_dir(scope, owner, session) / "events.jsonl"


def session_data_dir(scope: Scope, owner: str, session: str) -> Path:
    return session_dir(scope, owner, session) / "data"


# ── Index paths ────────────────────────────────────────────────────────


def index_root() -> Path:
    return hive_home() / ".message_index"


def events_index_dir(scope: Scope, owner: str, session: str | None = None) -> Path:
    base = index_root() / "events" / scope / owner
    return base / session if session else base


def data_index_dir(scope: Scope, owner: str, session: str | None = None) -> Path:
    base = index_root() / "data" / scope / owner
    return base / session if session else base


def meta_dir(scope: Scope, owner: str, session: str) -> Path:
    return index_root() / "meta" / scope / owner / session


def cursor_path(scope: Scope, owner: str, session: str) -> Path:
    return meta_dir(scope, owner, session) / "cursor.json"


def data_map_path(scope: Scope, owner: str, session: str) -> Path:
    return meta_dir(scope, owner, session) / "data_map.json"


def session_lock_path(scope: Scope, owner: str, session: str) -> Path:
    return meta_dir(scope, owner, session) / ".lock"


# ── Owner / session enumeration ────────────────────────────────────────


def list_owners(scope: Scope) -> list[str]:
    """List queen ids or colony names that have at least one session.

    Filters out non-directory entries (e.g. orphaned ``session_*`` dirs
    that historically appeared at the colonies root).
    """
    root = scope_root(scope)
    if not root.exists():
        return []
    out: list[str] = []
    for entry in os.scandir(root):
        if not entry.is_dir():
            continue
        # Skip stray session_* dirs at top level (legacy layout).
        if entry.name.startswith("session_"):
            continue
        out.append(entry.name)
    return sorted(out)


_SESSION_TS_RE = re.compile(r"^session_(\d{8})_(\d{6})_")


def parse_session_started_at(session: str) -> datetime | None:
    """Parse ``session_YYYYMMDD_HHMMSS_<hash>`` → naive datetime."""
    m = _SESSION_TS_RE.match(session)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)}_{m.group(2)}", "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def list_sessions(
    scope: Scope,
    owner: str,
    *,
    session_filter: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[str]:
    """Return session ids under ``owner``, optionally filtered."""
    out: list[str] = []
    entries = [entry for root in session_roots(scope, owner) if root.exists() for entry in os.scandir(root)]
    for entry in entries:
        if not entry.is_dir() or not entry.name.startswith("session_"):
            continue
        if session_filter is not None and entry.name != session_filter:
            continue
        if since is not None or until is not None:
            ts = parse_session_started_at(entry.name)
            if ts is None:
                continue
            if since is not None and ts < since:
                continue
            if until is not None and ts >= until:
                continue
        out.append(entry.name)
    return sorted(out)
