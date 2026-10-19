"""Read/write helpers for per-colony metadata.json.

A colony's metadata.json lives at ``{COLONIES_DIR}/{colony_id}/metadata.json``
and holds immutable provenance: the queen that created it, the forked
session id, creation/update timestamps, and the list of workers.

Mutable user-editable tool configuration lives in a sibling
``tools.json`` sidecar — see :mod:`framework.host.colony_tools_config`
— so identity and tool gating evolve independently.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from framework.config import COLONIES_DIR

logger = logging.getLogger(__name__)


def colony_metadata_path(colony_id: str) -> Path:
    """Return the on-disk path to a colony's metadata.json."""
    return COLONIES_DIR / colony_id / "metadata.json"


def load_colony_metadata(colony_id: str) -> dict[str, Any]:
    """Load metadata.json for ``colony_id``.

    Returns an empty dict if the file is missing or malformed — callers
    are expected to treat missing fields as defaults.
    """
    path = colony_metadata_path(colony_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read colony metadata at %s", path)
        return {}
    return data if isinstance(data, dict) else {}


def update_colony_metadata(colony_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge ``updates`` into metadata.json and persist.

    Returns the full updated dict. Raises ``FileNotFoundError`` if the
    colony does not exist. Writes atomically via ``os.replace`` to
    minimize the window where a reader could see a half-written file.
    """
    import os
    import tempfile

    path = colony_metadata_path(colony_id)
    if not path.parent.exists():
        raise FileNotFoundError(f"Colony '{colony_id}' not found")

    data = load_colony_metadata(colony_id) if path.exists() else {}
    for key, value in updates.items():
        data[key] = value

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=".metadata.",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return data


def list_colony_ids() -> list[str]:
    """Return the names of every colony that has a metadata.json on disk."""
    if not COLONIES_DIR.is_dir():
        return []
    names: list[str] = []
    for entry in sorted(COLONIES_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if (entry / "metadata.json").exists():
            names.append(entry.name)
    return names


def is_colony_soft_deleted(colony_id: str) -> bool:
    """True if ``colony_id`` exists on disk and is flagged deleted in metadata."""
    return bool(load_colony_metadata(colony_id).get("deleted"))


def vacate_soft_deleted_colony(colony_id: str) -> str | None:
    """Park a soft-deleted colony's directories aside so its name is free again.

    Soft-deleted colonies keep their directories on disk (only metadata.json's
    ``deleted`` flag is set) but are invisible everywhere and cannot be
    restored. That leftover directory still squats on the name, so a later
    rename or create targeting the same name collides with a colony the user
    can no longer see. This moves the dead colony — both its ``colonies/<id>``
    and sibling ``agents/<id>`` directories — under a unique parked name that
    contains a dot (a char valid colony names never use, so it can never
    re-collide), and returns that parked name.

    No-op — returns ``None`` — when ``colony_id`` has no colony on disk or the
    colony is still live, so callers can invoke it unconditionally before an
    open/create without disturbing live colonies.
    """
    if not is_colony_soft_deleted(colony_id):
        return None

    colonies_root = COLONIES_DIR
    agents_root = COLONIES_DIR.parent / "agents"

    # Pick a parked name free in BOTH roots so the colony and agent dirs stay
    # paired under the same suffix.
    n = 1
    while (colonies_root / f"{colony_id}.deleted.{n}").exists() or (agents_root / f"{colony_id}.deleted.{n}").exists():
        n += 1
    parked = f"{colony_id}.deleted.{n}"

    (colonies_root / colony_id).rename(colonies_root / parked)
    agent_dir = agents_root / colony_id
    if agent_dir.is_dir():
        try:
            agent_dir.rename(agents_root / parked)
        except OSError:
            # Roll back the colony move so we don't leave the colony half-parked
            # (colony dir gone but agent dir still under the live name).
            (colonies_root / parked).rename(colonies_root / colony_id)
            raise

    logger.info("Parked soft-deleted colony '%s' -> '%s'", colony_id, parked)
    return parked
