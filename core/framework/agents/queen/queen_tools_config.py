"""Per-queen tool configuration sidecar (``tools.json``).

Lives at ``~/.hive/agents/queens/{queen_id}/tools.json`` alongside
``profile.yaml``. Kept separate so identity (name, title, core traits)
stays human-authored and lean, while the machine-managed tool allowlist
can grow (per-tool overrides, audit timestamps, future per-phase rules)
without bloating the profile.

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
the version they last saved on. A missing field is treated as ``0.0.0``
(legacy sidecar) → every tracked GA addition is granted on first read.

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


def _make_sidecar_payload(enabled_mcp_tools: list[str] | None) -> dict[str, Any]:
    """Build a complete sidecar payload — keeps the version stamp in one place.

    Every writer in this module goes through here so a future tool-list
    write can't accidentally omit ``saved_on_version``.
    """
    from framework.agents.queen.queen_tools_defaults import _current_app_version

    return {
        "enabled_mcp_tools": enabled_mcp_tools,
        "updated_at": datetime.now(UTC).isoformat(),
        "saved_on_version": _current_app_version(),
    }


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
        _make_sidecar_payload(enabled),
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


def _augment_role_default_with_connected_oauth(
    role_default: list[str],
    mcp_catalog: dict[str, list[dict]] | None,
) -> list[str]:
    """Apply the "default-on for OAuth" policy to a role-default allowlist.

    When a queen is on the role-based default (no ``tools.json`` saved),
    every MCP tool whose OAuth provider currently has a live account is
    auto-enabled. Without this the role default deliberately strips OAuth
    tools — see ``resolve_queen_default_tools`` — so the queen runs with
    Gmail/Calendar/Slack/Notion missing even though the Tool Library and
    the GET /api/queen/{id}/tools snapshot promise they're enabled.

    Lookup uses ``CredentialStoreAdapter`` (same source as the queen-tools
    API endpoint and the registry's admission gate). The resulting tool
    set is intersected with the supplied catalog so we only add tools the
    queen's registry actually knows about — keeps allowlist entries from
    referencing nonexistent tool names.

    Returns the augmented list, or the original list if the credential
    store is unavailable or no providers are connected.
    """
    if not isinstance(role_default, list):
        return role_default
    catalog_names: set[str] = set()
    if mcp_catalog:
        for entries in mcp_catalog.values():
            for entry in entries or []:
                name = entry.get("name") if isinstance(entry, dict) else None
                if name:
                    catalog_names.add(name)

    try:
        from aden_tools.credentials.store_adapter import CredentialStoreAdapter

        adapter = CredentialStoreAdapter.default()
        tool_provider = adapter.get_tool_provider_map()
        connected = {a.get("provider", "") for a in adapter.get_all_account_info() if a.get("provider")}
    except Exception:
        logger.debug("OAuth augmentation skipped: credential adapter unavailable", exc_info=True)
        return role_default

    if not connected:
        return role_default

    additions: set[str] = set()
    for tool_name, provider in tool_provider.items():
        if not provider or provider not in connected:
            continue
        # Only augment with tools the registry actually has — the catalog
        # passed in here is either the full pre-credential-gate snapshot
        # (API path) or the post-admission boot catalog (queen_orchestrator).
        # Both are authoritative for "this tool name exists in this process".
        if catalog_names and tool_name not in catalog_names:
            continue
        additions.add(tool_name)

    if not additions:
        return role_default
    return sorted(set(role_default) | additions)


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
            # Heal frozen sidecars: grant tools added to a category after
            # this allowlist was last saved. Prefer the deterministic
            # role-default-based grant for known queens; fall back to the
            # baseline-coverage heuristic for custom queens.
            from framework.agents.queen.queen_tools_defaults import (
                QUEEN_DEFAULT_CATEGORIES,
                grant_role_default_additions,
                infer_category_additions,
            )

            saved_on_version = data.get("saved_on_version")
            if queen_id in QUEEN_DEFAULT_CATEGORIES:
                return grant_role_default_additions(queen_id, raw, saved_on_version)
            return infer_category_additions(raw, saved_on_version, mcp_catalog)
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
    # The role default deliberately strips OAuth-credentialed tools (see
    # resolve_queen_default_tools docstring); augment the result with every
    # tool whose provider is currently authorized so a freshly OAuthed
    # integration shows up in the queen's allowlist without requiring an
    # explicit save in the Tool Library. Once the user saves a sidecar,
    # this branch isn't taken and their explicit choices win.
    from framework.agents.queen.queen_tools_defaults import resolve_queen_default_tools

    role_default = resolve_queen_default_tools(queen_id, mcp_catalog)
    return _augment_role_default_with_connected_oauth(role_default, mcp_catalog)


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
        _make_sidecar_payload(enabled_mcp_tools),
    )
    return enabled_mcp_tools
