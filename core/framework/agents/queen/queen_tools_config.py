"""Per-queen tool configuration sidecar (``tools.json``).

Lives at ``~/.hive/agents/queens/{queen_id}/tools.json`` alongside
``profile.yaml``. Kept separate so identity (name, title, core traits)
stays human-authored and lean, while the machine-managed tool allowlist
can grow (per-tool overrides, audit timestamps, future per-phase rules)
without bloating the profile.

Schema::

    {
      "enabled_mcp_tools": ["read_file", ...] | null,
      "updated_at": "2026-04-21T12:34:56+00:00"
    }

- ``null`` / missing file → default "allow every MCP tool".
- ``[]`` → explicitly disable every MCP tool.
- ``["foo", "bar"]`` → only those MCP tool names pass the filter.

Atomic writes via ``os.replace`` follow the same pattern as
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

import yaml

from framework.config import QUEENS_DIR

logger = logging.getLogger(__name__)


def tools_config_path(queen_id: str) -> Path:
    """Return the on-disk path to a queen's ``tools.json``."""
    return QUEENS_DIR / queen_id / "tools.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    """Write ``data`` to ``path`` atomically via tempfile + replace."""
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


def _migrate_from_profile_if_needed(queen_id: str) -> list[str] | None:
    """Hoist a legacy ``enabled_mcp_tools`` field out of ``profile.yaml``.

    Returns the migrated value (or ``None`` if nothing to migrate). After
    migration the sidecar exists on disk and the profile YAML no longer
    contains ``enabled_mcp_tools``. Safe to call repeatedly.
    """
    profile_path = QUEENS_DIR / queen_id / "profile.yaml"
    if not profile_path.exists():
        return None
    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):
        logger.warning("Could not read profile.yaml during tools migration: %s", queen_id)
        return None
    if not isinstance(data, dict):
        return None
    if "enabled_mcp_tools" not in data:
        return None

    raw = data.pop("enabled_mcp_tools")
    enabled: list[str] | None
    if raw is None:
        enabled = None
    elif isinstance(raw, list) and all(isinstance(x, str) for x in raw):
        enabled = raw
    else:
        logger.warning(
            "Legacy enabled_mcp_tools on queen %s had unexpected shape %r; dropping",
            queen_id,
            raw,
        )
        enabled = None

    # Write sidecar first, then rewrite profile — if the second step
    # fails we still have the config available and won't re-migrate.
    _atomic_write_json(
        tools_config_path(queen_id),
        {
            "enabled_mcp_tools": enabled,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    profile_path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    logger.info(
        "Migrated enabled_mcp_tools for queen %s from profile.yaml to tools.json",
        queen_id,
    )
    return enabled


def tools_config_exists(queen_id: str) -> bool:
    """Return True when the queen has a persisted ``tools.json`` sidecar.

    Used by callers that need to tell an explicit user save apart from a
    fallthrough to the role-based default (both can return the same
    value from ``load_queen_tools_config``).
    """
    return tools_config_path(queen_id).exists()


def delete_queen_tools_config(queen_id: str) -> bool:
    """Delete the queen's ``tools.json`` sidecar if present.

    Returns ``True`` if a file was removed, ``False`` if none existed.
    The next ``load_queen_tools_config`` call falls through to the
    role-based default (or allow-all for unknown queens).
    """
    path = tools_config_path(queen_id)
    if not path.exists():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        logger.warning("Failed to delete %s", path, exc_info=True)
        return False


def load_queen_tools_config(
    queen_id: str,
    mcp_catalog: dict[str, list[dict]] | None = None,
) -> list[str] | None:
    """Return the queen's MCP tool allowlist, or ``None`` for default-allow.

    Order of resolution:
    1. ``tools.json`` sidecar (authoritative; user has saved).
    2. Legacy ``profile.yaml`` field (migrated and deleted on first read).
    3. Role-based default from ``queen_tools_defaults`` when the queen
       is in the known persona table. ``mcp_catalog`` lets the helper
       expand ``@server:NAME`` shorthands; without it, shorthand entries
       are dropped.
    4. ``None`` — default "allow every MCP tool".
    """
    path = tools_config_path(queen_id)
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

    migrated = _migrate_from_profile_if_needed(queen_id)
    if migrated is not None:
        return migrated
    # If migration just hoisted an explicit ``null`` out of profile.yaml,
    # a sidecar with allow-all semantics now exists on disk. Honor that
    # over the role default so an explicit user choice wins.
    if tools_config_path(queen_id).exists():
        return None

    # No sidecar, nothing to migrate — fall back to role-based default.
    from framework.agents.queen.queen_tools_defaults import resolve_queen_default_tools

    return resolve_queen_default_tools(queen_id, mcp_catalog)


def update_queen_tools_config(
    queen_id: str,
    enabled_mcp_tools: list[str] | None,
) -> list[str] | None:
    """Persist the queen's MCP allowlist to ``tools.json``.

    Raises ``FileNotFoundError`` if the queen's directory is missing —
    we refuse to silently create a sidecar for a queen that doesn't
    exist.
    """
    queen_dir = QUEENS_DIR / queen_id
    if not queen_dir.exists():
        raise FileNotFoundError(f"Queen directory not found: {queen_id}")
    _atomic_write_json(
        tools_config_path(queen_id),
        {
            "enabled_mcp_tools": enabled_mcp_tools,
            "updated_at": datetime.now(UTC).isoformat(),
        },
    )
    return enabled_mcp_tools
