"""One-time migration to the v3 ~/.hive/ directory structure.

v2 → v3 changes:

- ``agents/queens/<q>/``            → ``queens/<q>/``
- ``agents/queens/<q>/sessions/``   → either ``queens/<q>/sessions/<sid>/``
                                       (DM sessions) or
                                       ``colonies/<c>/queens/<q>/sessions/<sid>/``
                                       (overseer sessions, when meta.json
                                       binds the session to an existing
                                       colony via ``agent_path``).
- ``agents/<colony>/worker/conversations/`` → ``colonies/<c>/seed_conversation/``
- ``agents/<colony>/<worker_name>/``        → ``colonies/<c>/workers/<worker_name>/``
- ``colonies/<c>/data/tracker.db``  → ``colonies/<c>/tracker/tracker.db``

Memory layout (``memories/global/``, ``memories/agents/queens/<q>/``,
``memories/agents/<worker>/``) is **unchanged** and is not touched by
this migration.

Marker: ``$HIVE_HOME/.migrated-v3``, written only when a migration
actually runs (a fresh v3 install has nothing to migrate and gets no
marker). Idempotent; safe to re-run.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from framework.config import (
    COLONIES_DIR,
    HIVE_HOME,
    QUEENS_DIR,
)

logger = logging.getLogger(__name__)

_MIGRATION_MARKER = HIVE_HOME / ".migrated-v3"

# v2 paths (read sources)
_V2_AGENTS_DIR = HIVE_HOME / "agents"
_V2_QUEENS_DIR = _V2_AGENTS_DIR / "queens"


def needs_migration() -> bool:
    """True only when genuine v2 layout artifacts are present.

    Detection must be v2-*exclusive*: v3 reuses ``$HIVE_HOME/agents/``
    for live agent storage (e.g. ``agents/credential_tester/``, worker
    session dirs), so the bare existence of ``agents/`` is NOT a v2
    signal. v2 queens, however, always live at ``agents/queens/`` (v3
    uses ``queens/``) and v2 trackers at ``colonies/<c>/data/`` (v3 uses
    ``tracker/``) -- both are exclusive to v2 and safe to key on.
    """
    if _MIGRATION_MARKER.exists():
        return False
    return _V2_QUEENS_DIR.exists() or _has_v2_tracker_layout()


def _has_v2_tracker_layout() -> bool:
    if not COLONIES_DIR.exists():
        return False
    for cdir in COLONIES_DIR.iterdir():
        if (cdir / "data" / "tracker.db").exists():
            return True
    return False


def run_migration() -> None:
    """Run the full v2 → v3 migration. Idempotent.

    No-op for installs with nothing to migrate (a fresh v3 user has no
    v2 ``agents/`` tree or ``data/`` tracker dirs). In that case the
    marker is *not* written, leaving a first-time install's $HIVE_HOME
    untouched. The marker only appears once a real migration runs.
    """
    if not needs_migration():
        return

    logger.info("migrate_v3: starting layout migration")

    _migrate_queen_profiles()
    _migrate_queen_sessions()
    _migrate_agent_colony_subtrees()
    _migrate_tracker_dirs()
    _cleanup_empty_v2_dirs()

    HIVE_HOME.mkdir(parents=True, exist_ok=True)
    _MIGRATION_MARKER.write_text("1\n", encoding="utf-8")
    logger.info("migrate_v3: migration complete")


# ---------------------------------------------------------------------------
# Step 1 — queen profiles + non-session siblings
# ---------------------------------------------------------------------------


def _migrate_queen_profiles() -> None:
    """Move ``agents/queens/<q>/*`` → ``queens/<q>/*``.

    Walks every v2 queen dir and moves its top-level files / non-session
    dirs (profile.yaml, skills/, tools.json, skills_overrides.json,
    avatar.*, etc.) to the v3 home. The ``sessions/`` subdir is handled
    separately by :func:`_migrate_queen_sessions` (which has to dispatch
    each session to either chats/ or a colony's queen/).
    """
    if not _V2_QUEENS_DIR.exists():
        return
    moved_q = 0
    for queen_v2 in sorted(_V2_QUEENS_DIR.iterdir()):
        if not queen_v2.is_dir():
            continue
        queen_v3 = QUEENS_DIR / queen_v2.name
        queen_v3.mkdir(parents=True, exist_ok=True)
        for entry in sorted(queen_v2.iterdir()):
            if entry.name == "sessions":
                continue  # handled below
            target = queen_v3 / entry.name
            if target.exists():
                continue
            try:
                shutil.move(str(entry), str(target))
            except OSError as exc:
                logger.warning("migrate_v3: move queen entry %s -> %s failed: %s", entry, target, exc)
        moved_q += 1
    if moved_q:
        logger.info("migrate_v3: relocated %d queen profile tree(s) to queens/", moved_q)


# ---------------------------------------------------------------------------
# Step 2 — queen sessions: split DM vs colony-queen overseer
# ---------------------------------------------------------------------------


def _migrate_queen_sessions() -> None:
    """Move ``agents/queens/<q>/sessions/<sid>/`` to either
    ``queens/<q>/sessions/<sid>/`` (DM) or
    ``colonies/<c>/queens/<q>/sessions/<sid>/`` (overseer).

    Dispatch rule: read ``<sid>/meta.json``. If its ``agent_path``
    points at an existing colony directory, treat the session as an
    overseer session for that colony; otherwise DM.
    """
    if not _V2_QUEENS_DIR.exists():
        return
    import json as _json

    dm_moves = 0
    overseer_moves = 0
    for queen_v2 in sorted(_V2_QUEENS_DIR.iterdir()):
        sessions_dir = queen_v2 / "sessions"
        if not sessions_dir.exists():
            continue
        queen_id = queen_v2.name
        for session_dir in sorted(sessions_dir.iterdir()):
            if not session_dir.is_dir():
                continue
            sid = session_dir.name
            # Determine destination from meta.json's agent_path.
            colony_id: str | None = None
            meta_path = session_dir / "meta.json"
            if meta_path.exists():
                try:
                    meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                    raw = meta.get("agent_path") or ""
                    if raw:
                        candidate = Path(raw)
                        # Accept only paths that look like a colony dir
                        # under COLONIES_DIR (defensive vs stale meta).
                        try:
                            if candidate.exists() and candidate.is_dir():
                                if str(candidate.resolve()).startswith(str(COLONIES_DIR.resolve())):
                                    colony_id = candidate.name
                        except OSError:
                            pass
                except (OSError, _json.JSONDecodeError):
                    pass
            if colony_id:
                target = COLONIES_DIR / colony_id / "queens" / queen_id / "sessions" / sid
                kind = "overseer"
            else:
                target = QUEENS_DIR / queen_id / "sessions" / sid
                kind = "dm"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                continue
            try:
                shutil.move(str(session_dir), str(target))
                if kind == "dm":
                    dm_moves += 1
                else:
                    overseer_moves += 1
            except OSError as exc:
                logger.warning("migrate_v3: failed to move session %s -> %s: %s", session_dir, target, exc)

    if dm_moves or overseer_moves:
        logger.info(
            "migrate_v3: moved %d DM session(s) + %d overseer session(s)",
            dm_moves,
            overseer_moves,
        )


# ---------------------------------------------------------------------------
# Step 3 — agents/<colony>/ subtrees → colonies/<c>/{seed_conversation,workers}/
# ---------------------------------------------------------------------------


def _migrate_agent_colony_subtrees() -> None:
    """For each ``agents/<name>/`` that matches an existing colony,
    relocate its worker subdirs into the colony tree.

    ``agents/<colony>/worker/conversations/`` becomes
    ``colonies/<colony>/seed_conversation/``.

    Other worker-named subdirs (``agents/<colony>/<worker_name>/``)
    move to ``colonies/<colony>/workers/<worker_name>/``.
    """
    if not _V2_AGENTS_DIR.exists():
        return
    moved_seed = 0
    moved_workers = 0
    for agent_dir in sorted(_V2_AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir():
            continue
        if agent_dir.name == "queens":
            continue
        # Only relocate when the colony actually exists on disk; otherwise
        # this is an unrelated agent dir we should leave alone.
        colony_root = COLONIES_DIR / agent_dir.name
        if not colony_root.is_dir():
            continue

        for sub in sorted(agent_dir.iterdir()):
            if not sub.is_dir():
                continue
            if sub.name == "worker":
                # Move conversations/ as the seed transcript.
                src_conv = sub / "conversations"
                if src_conv.exists():
                    dst_conv = colony_root / "seed_conversation"
                    if not dst_conv.exists():
                        try:
                            shutil.move(str(src_conv), str(dst_conv))
                            moved_seed += 1
                        except OSError as exc:
                            logger.warning("migrate_v3: failed seed_conversation move for %s: %s", agent_dir, exc)
            else:
                target = colony_root / "workers" / sub.name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists():
                    try:
                        shutil.move(str(sub), str(target))
                        moved_workers += 1
                    except OSError as exc:
                        logger.warning("migrate_v3: failed worker move %s -> %s: %s", sub, target, exc)

    if moved_seed or moved_workers:
        logger.info(
            "migrate_v3: moved %d seed-conversation tree(s) + %d named-worker tree(s)",
            moved_seed,
            moved_workers,
        )


# ---------------------------------------------------------------------------
# Step 4 — tracker dir rename: data/ → tracker/
# ---------------------------------------------------------------------------


def _migrate_tracker_dirs() -> None:
    """Move every ``colonies/<c>/data/`` to ``colonies/<c>/tracker/``."""
    if not COLONIES_DIR.exists():
        return
    moved = 0
    for cdir in sorted(COLONIES_DIR.iterdir()):
        if not cdir.is_dir():
            continue
        old = cdir / "data"
        new = cdir / "tracker"
        if old.exists() and not new.exists():
            try:
                shutil.move(str(old), str(new))
                moved += 1
            except OSError as exc:
                logger.warning("migrate_v3: failed tracker rename for %s: %s", cdir, exc)
    if moved:
        logger.info("migrate_v3: renamed %d data/ -> tracker/ dir(s)", moved)


# ---------------------------------------------------------------------------
# Step 5 — drop the empty v2 agents/ tree
# ---------------------------------------------------------------------------


def _rmtree_if_empty(root: Path) -> None:
    """Bottom-up rmdir: descend, drop empty leaves, then drop ``root``
    if it becomes empty. Never deletes a directory that still has files."""
    if not root.is_dir():
        return
    for child in list(root.iterdir()):
        if child.is_dir():
            _rmtree_if_empty(child)
    try:
        if not any(root.iterdir()):
            root.rmdir()
    except OSError:
        pass


def _cleanup_empty_v2_dirs() -> None:
    """Remove ``agents/queens/<q>/sessions`` (now empty) and ``agents/``
    (entirely) if nothing was left behind. Best-effort: never deletes a
    non-empty directory."""
    if not _V2_AGENTS_DIR.exists():
        return

    # 5a — empty sessions/ dirs
    if _V2_QUEENS_DIR.exists():
        for queen_v2 in list(_V2_QUEENS_DIR.iterdir()):
            sessions_dir = queen_v2 / "sessions"
            if sessions_dir.exists():
                try:
                    if not any(sessions_dir.iterdir()):
                        sessions_dir.rmdir()
                except OSError:
                    pass
            # Then drop the queen v2 dir if it's now empty.
            try:
                if not any(queen_v2.iterdir()):
                    queen_v2.rmdir()
            except OSError:
                pass
        try:
            if not any(_V2_QUEENS_DIR.iterdir()):
                _V2_QUEENS_DIR.rmdir()
        except OSError:
            pass

    # 5b — recursively drop empty subdirs under each agents/<colony>/
    for agent_dir in list(_V2_AGENTS_DIR.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name == "queens":
            continue
        _rmtree_if_empty(agent_dir)

    # 5c — agents/ itself
    try:
        if _V2_AGENTS_DIR.exists() and not any(_V2_AGENTS_DIR.iterdir()):
            _V2_AGENTS_DIR.rmdir()
            logger.info("migrate_v3: removed empty agents/ root")
    except OSError:
        pass
