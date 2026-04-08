"""One-time migration to the v2 ~/.hive/ directory structure.

Moves:
- exports/{name}/ -> ~/.hive/colonies/{name}/
- ~/.hive/queen/session/{id}/ -> ~/.hive/agents/queens/default/sessions/{id}/
- ~/.hive/queen/global_memory/ -> ~/.hive/memories/global/

Runs automatically on first startup when the marker file is absent.
Safe to re-run (skips already-migrated items).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from framework.config import COLONIES_DIR, HIVE_HOME, MEMORIES_DIR, QUEENS_DIR

logger = logging.getLogger(__name__)

_MIGRATION_MARKER = HIVE_HOME / ".migrated-v2"


def needs_migration() -> bool:
    """Return True if the v2 migration has not yet run."""
    return not _MIGRATION_MARKER.exists()


def run_migration(*, exports_dir: Path | None = None) -> None:
    """Run the full v2 migration. Idempotent and safe to re-run."""
    if not needs_migration():
        return

    logger.info("migrate_v2: starting ~/.hive structure migration")

    _migrate_colonies(exports_dir or Path("exports"))
    _migrate_queen_sessions()
    _migrate_memories()
    _cleanup_old_queen_dir()

    # Write marker
    HIVE_HOME.mkdir(parents=True, exist_ok=True)
    _MIGRATION_MARKER.write_text("1\n", encoding="utf-8")
    logger.info("migrate_v2: migration complete")


def _migrate_colonies(exports_dir: Path) -> None:
    """Copy exports/{name}/ -> ~/.hive/colonies/{name}/."""
    if not exports_dir.exists():
        return

    COLONIES_DIR.mkdir(parents=True, exist_ok=True)
    migrated = 0

    for agent_dir in sorted(exports_dir.iterdir()):
        if not agent_dir.is_dir() or agent_dir.name.startswith("."):
            continue
        target = COLONIES_DIR / agent_dir.name
        if target.exists():
            continue
        try:
            shutil.copytree(agent_dir, target)
            migrated += 1
        except OSError:
            logger.warning("migrate_v2: failed to copy %s", agent_dir, exc_info=True)

    if migrated:
        logger.info("migrate_v2: copied %d agent(s) from exports/ to colonies/", migrated)


def _migrate_queen_sessions() -> None:
    """Move ~/.hive/queen/session/{id}/ -> ~/.hive/agents/queens/default/sessions/{id}/."""
    old_sessions = HIVE_HOME / "queen" / "session"
    if not old_sessions.exists():
        return

    new_sessions = QUEENS_DIR / "default" / "sessions"
    new_sessions.mkdir(parents=True, exist_ok=True)
    migrated = 0

    for session_dir in sorted(old_sessions.iterdir()):
        if not session_dir.is_dir():
            continue
        target = new_sessions / session_dir.name
        if target.exists():
            continue
        try:
            session_dir.rename(target)
            migrated += 1
        except OSError:
            logger.warning(
                "migrate_v2: failed to move session %s", session_dir, exc_info=True
            )

    if migrated:
        logger.info("migrate_v2: moved %d queen session(s) to new path", migrated)


def _migrate_memories() -> None:
    """Move ~/.hive/queen/global_memory/ -> ~/.hive/memories/global/."""
    old_global = HIVE_HOME / "queen" / "global_memory"
    if not old_global.exists():
        return

    new_global = MEMORIES_DIR / "global"
    if new_global.exists():
        # Already has content -- merge individual files
        merged = 0
        for f in old_global.iterdir():
            if f.is_file() and not (new_global / f.name).exists():
                try:
                    shutil.copy2(f, new_global / f.name)
                    merged += 1
                except OSError:
                    pass
        if merged:
            logger.info("migrate_v2: merged %d memory file(s) into global/", merged)
        return

    new_global.mkdir(parents=True, exist_ok=True)
    migrated = 0
    for f in old_global.iterdir():
        if f.is_file():
            try:
                shutil.copy2(f, new_global / f.name)
                migrated += 1
            except OSError:
                pass

    if migrated:
        logger.info("migrate_v2: copied %d memory file(s) to memories/global/", migrated)


def _cleanup_old_queen_dir() -> None:
    """Remove ~/.hive/queen/ after all content has been migrated."""
    old_queen = HIVE_HOME / "queen"
    if not old_queen.exists():
        return
    try:
        shutil.rmtree(old_queen)
        logger.info("migrate_v2: removed old ~/.hive/queen/ directory")
    except OSError:
        logger.debug("migrate_v2: could not remove old queen dir", exc_info=True)
