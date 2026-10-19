"""Per-colony tool configuration sidecar (``tools.json``).

Lives at ``~/.hive/colonies/{colony_id}/tools.json`` alongside
``metadata.json``. Kept separate so provenance (queen_name,
created_at, workers) stays in metadata while the user-editable tool
allowlist gets its own file.

Schema::

    {
      "enabled_mcp_tools": ["pdf_read", ...] | null,
      "updated_at": "2026-04-21T12:34:56+00:00",
      "saved_on_version": "0.2.19"
    }

- ``null`` / missing file → default "allow every MCP tool".
- ``[]`` → explicitly disable every MCP tool.
- ``["foo", "bar"]`` → only those MCP tool names pass the filter.

``saved_on_version`` records the app version that wrote the sidecar so
the GA tool migration can grant additions a user couldn't have seen on
the version they last saved on. Missing field → treated as ``0.0.0``.

Atomic writes via ``os.replace`` mirror
``framework.host.colony_metadata.update_colony_metadata``.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from framework.config import COLONIES_DIR

logger = logging.getLogger(__name__)


def tools_config_path(colony_id: str) -> Path:
    """Return the on-disk path to a colony's ``tools.json``."""
    return COLONIES_DIR / colony_id / "tools.json"


def _metadata_path(colony_id: str) -> Path:
    return COLONIES_DIR / colony_id / "metadata.json"


def _make_sidecar_payload(enabled_mcp_tools: list[str] | None) -> dict[str, Any]:
    """Build a complete sidecar payload — keeps the version stamp in one place."""
    from framework.agents.queen.queen_tools_defaults import _current_app_version

    return {
        "enabled_mcp_tools": enabled_mcp_tools,
        "updated_at": datetime.now(UTC).isoformat(),
        "saved_on_version": _current_app_version(),
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
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


def _migrate_from_metadata_if_needed(colony_id: str) -> list[str] | None:
    """Hoist a legacy ``enabled_mcp_tools`` field out of ``metadata.json``.

    Returns the migrated value (or ``None`` if nothing to migrate). After
    migration the sidecar exists and ``metadata.json`` no longer contains
    ``enabled_mcp_tools``. Safe to call repeatedly.
    """
    meta_path = _metadata_path(colony_id)
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Could not read metadata.json during tools migration: %s", colony_id)
        return None
    if not isinstance(data, dict) or "enabled_mcp_tools" not in data:
        return None

    raw = data.pop("enabled_mcp_tools")
    enabled: list[str] | None
    if raw is None:
        enabled = None
    elif isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        enabled = raw
    else:
        logger.warning(
            "Legacy enabled_mcp_tools on colony %s had unexpected shape %r; dropping",
            colony_id,
            raw,
        )
        enabled = None

    # Sidecar first so a partial failure leaves the config recoverable.
    _atomic_write_json(
        tools_config_path(colony_id),
        _make_sidecar_payload(enabled),
    )
    _atomic_write_json(meta_path, data)
    logger.info(
        "Migrated enabled_mcp_tools for colony %s from metadata.json to tools.json",
        colony_id,
    )
    return enabled


def load_colony_tools_config(colony_id: str) -> list[str] | None:
    """Return the colony's MCP tool allowlist, or ``None`` for default-allow.

    Order of resolution:
    1. ``tools.json`` sidecar (authoritative).
    2. Legacy ``metadata.json`` field (migrated and deleted on first read).
    3. ``None`` — default "allow every MCP tool".
    """
    path = tools_config_path(colony_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Invalid %s; treating as default-allow", path)
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("enabled_mcp_tools")
        if raw is None:
            return None
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            return raw
        logger.warning("Unexpected enabled_mcp_tools shape in %s; ignoring", path)
        return None

    return _migrate_from_metadata_if_needed(colony_id)


def update_colony_tools_config(
    colony_id: str,
    enabled_mcp_tools: list[str] | None,
) -> list[str] | None:
    """Persist a colony's MCP allowlist to ``tools.json``.

    Raises ``FileNotFoundError`` if the colony's directory is missing.
    """
    colony_dir = COLONIES_DIR / colony_id
    if not colony_dir.exists():
        raise FileNotFoundError(f"Colony directory not found: {colony_id}")
    _atomic_write_json(
        tools_config_path(colony_id),
        _make_sidecar_payload(enabled_mcp_tools),
    )
    return enabled_mcp_tools
