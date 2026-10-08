"""One-shot migration: relocate stray ``colony_fork`` overseer sessions
into their canonical colony tree.

Background. ``fork_session_into_colony`` used to write the forked queen
session under ``queens/<q>/sessions/<sid>/`` (marked ``colony_fork:
true``) while the live colony queen wrote events + ongoing conversation
to ``colonies/<c>/queens/<q>/sessions/<sid>/``. Same ``session_id``, two
physical directories. That split-brain broke colony resume from the
sidebar (``list_cold_sessions`` filters out ``colony_fork`` entries and
``list_colony_sessions`` walks only the colony tree).

This migration consolidates each affected session into the colony tree:

* **Target missing** → ``shutil.move`` the queen-tree dir into the
  canonical location.
* **Target exists, no ``events.jsonl``** → take the queen-tree copy as
  source of truth (it has the inherited transcript). Move into target.
* **Target exists with ``events.jsonl``** → the colony-tree copy is the
  live session. Archive the queen-tree snapshot under
  ``colonies/<c>/legacy_fork_snapshots/<sid>/`` so it stays recoverable,
  then drop the queen-tree dir.

Idempotent. Marker file: ``COLONIES_DIR/.migrations/colony_sessions_v1``.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from framework.config import COLONIES_DIR, QUEENS_DIR

logger = logging.getLogger(__name__)

_MARKER = COLONIES_DIR / ".migrations" / "colony_sessions_v1"


def needs_migration() -> bool:
    if _MARKER.exists():
        return False
    return QUEENS_DIR.exists() or COLONIES_DIR.exists()


def run_migration() -> None:
    """Consolidate stray colony overseer sessions into the canonical
    ``colonies/<c>/queens/<q>/sessions/<sid>/`` layout.

    Two cleanup passes:

    1. **Queen-tree colony_fork copies** — left behind by the older
       ``fork_session_into_colony`` write target. Move into the colony
       tree, archiving any duplicate that would otherwise collide.
    2. **Legacy colony-tree shape** — ``colonies/<c>/queen/<sid>/`` (note
       the singular ``queen/`` with flat session dirs). Move each into
       ``colonies/<c>/queens/<queen_id>/sessions/<sid>/`` using the
       ``queen_id`` recorded in the session's own ``meta.json``.

    Safe to re-run; the marker short-circuits after the first
    successful pass.
    """
    if not needs_migration():
        return

    logger.info("migrate_colony_sessions: scanning for stray sessions")

    moved = 0
    overwrote = 0
    archived = 0
    skipped = 0

    # Pass 1: queen-tree colony_fork copies.
    if QUEENS_DIR.exists():
        for queen_root in sorted(QUEENS_DIR.iterdir()):
            if not queen_root.is_dir():
                continue
            sessions_dir = queen_root / "sessions"
            if not sessions_dir.exists():
                continue
            queen_id = queen_root.name
            for session_dir in sorted(sessions_dir.iterdir()):
                if not session_dir.is_dir():
                    continue
                outcome = _migrate_one(session_dir, queen_id)
                if outcome == "moved":
                    moved += 1
                elif outcome == "overwrote":
                    overwrote += 1
                elif outcome == "archived":
                    archived += 1
                elif outcome == "skipped":
                    skipped += 1

    # Pass 2: legacy ``colonies/<c>/queen/<sid>/`` layout.
    legacy_moved = _migrate_legacy_singular_queen_dirs()
    moved += legacy_moved

    _MARKER.parent.mkdir(parents=True, exist_ok=True)
    _MARKER.write_text("1\n", encoding="utf-8")

    if moved or overwrote or archived:
        logger.info(
            "migrate_colony_sessions: moved=%d overwrote_empty=%d archived_dup=%d skipped=%d",
            moved,
            overwrote,
            archived,
            skipped,
        )
    else:
        logger.info("migrate_colony_sessions: nothing to migrate")


def _migrate_legacy_singular_queen_dirs() -> int:
    """Move ``colonies/<c>/queen/<sid>/`` → ``colonies/<c>/queens/<q>/sessions/<sid>/``.

    The old layout used a single ``queen/`` subdir per colony with flat
    session subdirs and no per-queen nesting. The canonical layout pins
    each session under its overseeing queen, which the resume flow
    (``list_colony_sessions``) and the live ``_queen_session_dir``
    helper both rely on. Sessions whose ``meta.json`` has no ``queen_id``
    fall back to ``"default"`` so they're at least recoverable.
    """
    if not COLONIES_DIR.exists():
        return 0
    moved = 0
    for colony_dir in sorted(COLONIES_DIR.iterdir()):
        if not colony_dir.is_dir():
            continue
        legacy_root = colony_dir / "queen"
        if not legacy_root.exists() or not legacy_root.is_dir():
            continue
        # Skip anything that doesn't look like a session-id-bearing
        # dir; legacy_root might also contain non-session files in some
        # edge installs.
        for session_dir in sorted(legacy_root.iterdir()):
            if not session_dir.is_dir():
                continue
            if not session_dir.name.startswith("session_"):
                continue
            queen_id = "default"
            meta_path = session_dir / "meta.json"
            if meta_path.exists():
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    raw = meta.get("queen_id")
                    if isinstance(raw, str) and raw:
                        queen_id = raw
                except (OSError, json.JSONDecodeError):
                    pass
            target = colony_dir / "queens" / queen_id / "sessions" / session_dir.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                # Canonical copy already present — leave the legacy
                # path alone rather than risk merging two states. The
                # canonical copy is what the resume flow reads.
                continue
            try:
                shutil.move(str(session_dir), str(target))
                moved += 1
                logger.info(
                    "migrate_colony_sessions: relocated legacy %s -> %s",
                    session_dir,
                    target,
                )
            except OSError as exc:
                logger.warning(
                    "migrate_colony_sessions: failed legacy move %s -> %s: %s",
                    session_dir,
                    target,
                    exc,
                )

        # Drop the empty legacy ``queen/`` dir so it's not picked up
        # again on subsequent code that might mistake it for canonical.
        try:
            if not any(legacy_root.iterdir()):
                legacy_root.rmdir()
        except OSError:
            pass

    return moved


def _migrate_one(session_dir: Path, queen_id: str) -> str:
    """Process a single queen-tree session dir. Returns the outcome tag."""
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        return "skipped"

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "skipped"

    if not meta.get("colony_fork"):
        return "skipped"

    colony_id = _derive_colony_id(meta)
    if colony_id is None:
        # colony_fork:true but no usable agent_path. Leave it alone —
        # ``list_cold_sessions`` already filters it out of queen DM history,
        # so it's invisible but not harmful.
        return "skipped"

    target = COLONIES_DIR / colony_id / "queens" / queen_id / "sessions" / session_dir.name
    target.parent.mkdir(parents=True, exist_ok=True)

    # Case 1: target doesn't exist — straight move.
    if not target.exists():
        try:
            shutil.move(str(session_dir), str(target))
            logger.info(
                "migrate_colony_sessions: moved %s -> %s",
                session_dir,
                target,
            )
            return "moved"
        except OSError as exc:
            logger.warning(
                "migrate_colony_sessions: failed move %s -> %s: %s",
                session_dir,
                target,
                exc,
            )
            return "skipped"

    # Case 2: target exists but has no events.jsonl (never went live).
    # The queen-tree copy carries the inherited transcript and is the
    # source of truth. Replace the empty target.
    target_events = target / "events.jsonl"
    if not target_events.exists() or target_events.stat().st_size == 0:
        try:
            shutil.rmtree(target)
            shutil.move(str(session_dir), str(target))
            logger.info(
                "migrate_colony_sessions: overwrote empty %s with %s",
                target,
                session_dir,
            )
            return "overwrote"
        except OSError as exc:
            logger.warning(
                "migrate_colony_sessions: failed overwrite-empty %s <- %s: %s",
                target,
                session_dir,
                exc,
            )
            return "skipped"

    # Case 3: target has a live events.jsonl — the colony-tree copy is
    # authoritative. Archive the queen-tree snapshot for recovery and drop
    # the original to remove the split-brain.
    archive_root = COLONIES_DIR / colony_id / "legacy_fork_snapshots"
    archive_root.mkdir(parents=True, exist_ok=True)
    archive_target = archive_root / session_dir.name
    # If a prior partial migration already archived this id, pick a unique
    # suffix rather than clobber.
    suffix = 0
    while archive_target.exists():
        suffix += 1
        archive_target = archive_root / f"{session_dir.name}.{suffix}"
    try:
        shutil.move(str(session_dir), str(archive_target))
        logger.info(
            "migrate_colony_sessions: archived split-brain snapshot %s -> %s (colony-tree copy at %s is live)",
            session_dir,
            archive_target,
            target,
        )
        return "archived"
    except OSError as exc:
        logger.warning(
            "migrate_colony_sessions: failed archive %s -> %s: %s",
            session_dir,
            archive_target,
            exc,
        )
        return "skipped"


def _derive_colony_id(meta: dict) -> str | None:
    """Pull the colony directory name out of meta.json's ``agent_path``.

    Validates the path actually lives under ``COLONIES_DIR`` to avoid
    misreading a stale or malformed meta into the wrong filesystem
    location.
    """
    raw = meta.get("agent_path")
    if not raw or not isinstance(raw, str):
        return None
    try:
        candidate = Path(raw).resolve()
        colonies_root = COLONIES_DIR.resolve()
    except OSError:
        return None
    try:
        # candidate.parent == colonies_root means agent_path is exactly
        # COLONIES_DIR/<colony_id>. Be strict: anything deeper is suspect.
        if candidate.parent == colonies_root:
            return candidate.name
    except OSError:
        return None
    return None
