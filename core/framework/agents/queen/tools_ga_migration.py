"""One-shot migration that appends newly-GA tools to existing agent sidecars.

Runs at runtime startup (see ``framework.server.app.create_app``). For each
queen/colony ``tools.json`` sidecar, grants any tool listed in
:data:`framework.agents.queen.queen_tools_defaults._CATEGORY_ADDITIONS` whose
category sits in the queen's role default AND whose GA-promotion version is
newer than the sidecar's ``saved_on_version``. Sidecars that gain tools are
rewritten atomically with ``saved_on_version`` advanced to the current app
version; unchanged sidecars are left alone so re-running is a no-op until
a new entry lands in ``_CATEGORY_ADDITIONS``.

Idempotency is per-sidecar via its own ``saved_on_version`` — no global
version stamp is needed. Custom queen IDs (not in ``QUEEN_DEFAULT_CATEGORIES``)
are skipped to avoid over-granting; the load-time fallback
``infer_category_additions`` still heals those in memory.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.agents.queen.queen_tools_defaults import (
    QUEEN_DEFAULT_CATEGORIES,
    _current_app_version,
    grant_role_default_additions,
)
from framework.config import COLONIES_DIR, QUEENS_DIR
from framework.host.colony_metadata import list_colony_ids, load_colony_metadata

logger = logging.getLogger(__name__)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic write — mirrors the helper in queen_tools_config."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        prefix=".tools.",
        suffix=".json.tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _apply_to_sidecar(path: Path, queen_id: str) -> list[str]:
    """Apply role-default grants to one sidecar; return newly added tools.

    Empty list means no change (either nothing to grant, or the sidecar
    was empty/null/malformed). Writes happen only when the saved list
    actually grew.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("ga_migration: unreadable sidecar at %s", path)
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("enabled_mcp_tools")
    # null (default-allow) and [] (explicit disable-all) carry no list to
    # grow — only an explicit allowlist is migrated.
    if not isinstance(raw, list) or not raw:
        return []
    if not all(isinstance(x, str) for x in raw):
        return []

    granted = grant_role_default_additions(queen_id, raw, data.get("saved_on_version"))
    added = sorted(set(granted) - set(raw))
    if not added:
        return []
    _atomic_write_json(
        path,
        {
            "enabled_mcp_tools": granted,
            "updated_at": datetime.now(UTC).isoformat(),
            "saved_on_version": _current_app_version(),
        },
    )
    return added


def migrate_queen_sidecars() -> dict[str, list[str]]:
    """Apply GA grants to every queen's ``tools.json`` under QUEENS_DIR.

    Returns ``{queen_id: [newly granted tools]}`` for queens that changed.
    Queens without a role default (custom IDs) are skipped — the helper
    returns the original list unchanged in that case.
    """
    results: dict[str, list[str]] = {}
    if not QUEENS_DIR.is_dir():
        return results
    for entry in sorted(QUEENS_DIR.iterdir()):
        if not entry.is_dir():
            continue
        queen_id = entry.name
        if queen_id not in QUEEN_DEFAULT_CATEGORIES:
            continue
        sidecar = entry / "tools.json"
        try:
            added = _apply_to_sidecar(sidecar, queen_id)
        except Exception:
            logger.exception("ga_migration: failed for queen %s", queen_id)
            continue
        if added:
            results[queen_id] = added
    return results


def migrate_colony_sidecars() -> dict[str, list[str]]:
    """Apply GA grants to every colony's ``tools.json`` under COLONIES_DIR.

    Resolves each colony's role categories via its ``metadata.json`` ->
    ``queen_name`` -> ``QUEEN_DEFAULT_CATEGORIES``. Colonies forked from
    custom queens are skipped for the same reason as the queen path.
    Returns ``{colony_id: [newly granted tools]}`` for colonies that changed.
    """
    results: dict[str, list[str]] = {}
    for colony_id in list_colony_ids():
        try:
            metadata = load_colony_metadata(colony_id)
        except Exception:
            logger.exception("ga_migration: failed to read metadata for colony %s", colony_id)
            continue
        queen_name = metadata.get("queen_name") if isinstance(metadata, dict) else None
        if not isinstance(queen_name, str) or queen_name not in QUEEN_DEFAULT_CATEGORIES:
            continue
        sidecar = COLONIES_DIR / colony_id / "tools.json"
        try:
            added = _apply_to_sidecar(sidecar, queen_name)
        except Exception:
            logger.exception("ga_migration: failed for colony %s", colony_id)
            continue
        if added:
            results[colony_id] = added
    return results


def run_ga_tool_migration() -> None:
    """Top-level entry: migrate queens then colonies, logging summaries.

    Never raises — per-sidecar errors are swallowed in the helpers so a
    single malformed file cannot block runtime boot.
    """
    try:
        queen_changes = migrate_queen_sidecars()
    except Exception:
        logger.exception("ga_migration: queen pass crashed")
        queen_changes = {}
    try:
        colony_changes = migrate_colony_sidecars()
    except Exception:
        logger.exception("ga_migration: colony pass crashed")
        colony_changes = {}

    if queen_changes:
        logger.info("ga_migration: granted tools to %d queen(s): %s", len(queen_changes), queen_changes)
    if colony_changes:
        logger.info("ga_migration: granted tools to %d colony(s): %s", len(colony_changes), colony_changes)
    if not queen_changes and not colony_changes:
        logger.debug("ga_migration: no sidecars required updates")
