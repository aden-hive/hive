"""Read/write helpers for per-colony metadata.json.

A colony's metadata.json lives at ``{COLONIES_DIR}/{colony_name}/metadata.json``
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


def colony_metadata_path(colony_name: str) -> Path:
    """Return the on-disk path to a colony's metadata.json."""
    return COLONIES_DIR / colony_name / "metadata.json"


def load_colony_metadata(colony_name: str) -> dict[str, Any]:
    """Load metadata.json for ``colony_name``.

    Returns an empty dict if the file is missing or malformed — callers
    are expected to treat missing fields as defaults.
    """
    path = colony_metadata_path(colony_name)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Failed to read colony metadata at %s", path)
        return {}
    return data if isinstance(data, dict) else {}


def update_colony_metadata(colony_name: str, updates: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge ``updates`` into metadata.json and persist.

    Returns the full updated dict. Raises ``FileNotFoundError`` if the
    colony does not exist. Writes atomically via ``os.replace`` to
    minimize the window where a reader could see a half-written file.
    """
    import os
    import tempfile

    path = colony_metadata_path(colony_name)
    if not path.parent.exists():
        raise FileNotFoundError(f"Colony '{colony_name}' not found")

    data = load_colony_metadata(colony_name) if path.exists() else {}
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


def list_colony_names() -> list[str]:
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
