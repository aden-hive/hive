"""Per-scope skill override store.

Sits between :mod:`framework.skills.discovery` and
:class:`framework.skills.catalog.SkillCatalog`: records the user's
per-queen and per-colony decisions about which skills are enabled,
who created them (provenance), and any parameter tweaks.

Two well-known paths back this module:

* Queen scope:   ``~/.hive/agents/queens/{queen_id}/skills_overrides.json``
* Colony scope:  ``~/.hive/colonies/{colony_name}/skills_overrides.json``

The schema is intentionally small; see :class:`SkillOverrideStore` for
the JSON shape. Atomic writes mirror
:class:`framework.skills.trust.TrustedRepoStore` (tmp + rename).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = 1


class Provenance(StrEnum):
    """Where a skill came from.

    The override store is the authoritative provenance ledger for anything
    the UI or the queen tools touched. Framework / user-dropped /
    project-dropped skills don't need an entry unless they've been
    explicitly configured.
    """

    FRAMEWORK = "framework"
    PRESET = "preset"
    USER_DROPPED = "user_dropped"
    USER_UI_CREATED = "user_ui_created"
    QUEEN_CREATED = "queen_created"
    LEARNED_RUNTIME = "learned_runtime"
    PROJECT_DROPPED = "project_dropped"
    # Catch-all for skills with no recorded authorship: legacy rows from
    # before the override store existed, PATCHes that precede any CREATE,
    # etc. Keeps the ledger honest rather than forcing a guess.
    OTHER = "other"


@dataclass
class OverrideEntry:
    """Per-skill override record inside a scope's store."""

    enabled: bool | None = None
    provenance: Provenance = Provenance.FRAMEWORK
    trust: str | None = None
    param_overrides: dict[str, Any] = field(default_factory=dict)
    notes: str | None = None
    created_at: datetime | None = None
    created_by: str | None = None

    def clone(self) -> OverrideEntry:
        """Return a deep-enough copy (dict fields are re-allocated)."""
        return OverrideEntry(
            enabled=self.enabled,
            provenance=self.provenance,
            trust=self.trust,
            param_overrides=dict(self.param_overrides),
            notes=self.notes,
            created_at=self.created_at,
            created_by=self.created_by,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"provenance": str(self.provenance)}
        if self.enabled is not None:
            out["enabled"] = bool(self.enabled)
        if self.trust is not None:
            out["trust"] = self.trust
        if self.param_overrides:
            out["param_overrides"] = dict(self.param_overrides)
        if self.notes is not None:
            out["notes"] = self.notes
        if self.created_at is not None:
            out["created_at"] = self.created_at.isoformat()
        if self.created_by is not None:
            out["created_by"] = self.created_by
        return out

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> OverrideEntry:
        created_at_raw = raw.get("created_at")
        created_at: datetime | None = None
        if isinstance(created_at_raw, str):
            try:
                created_at = datetime.fromisoformat(created_at_raw)
            except ValueError:
                created_at = None
        provenance_raw = raw.get("provenance") or Provenance.FRAMEWORK
        try:
            provenance = Provenance(provenance_raw)
        except ValueError:
            logger.warning("override: unknown provenance %r; defaulting to framework", provenance_raw)
            provenance = Provenance.FRAMEWORK
        enabled = raw.get("enabled")
        return cls(
            enabled=enabled if isinstance(enabled, bool) else None,
            provenance=provenance,
            trust=raw.get("trust") if isinstance(raw.get("trust"), str) else None,
            param_overrides=dict(raw.get("param_overrides") or {}),
            notes=raw.get("notes") if isinstance(raw.get("notes"), str) else None,
            created_at=created_at,
            created_by=raw.get("created_by") if isinstance(raw.get("created_by"), str) else None,
        )


@dataclass
class SkillOverrideStore:
    """Persistent per-scope override file.

    The file is created lazily on first save; a missing file behaves like
    an empty store (all skills inherit defaults, no metadata recorded).
    """

    path: Path
    scope_label: str = ""
    version: int = _SCHEMA_VERSION
    all_defaults_disabled: bool = False
    overrides: dict[str, OverrideEntry] = field(default_factory=dict)
    deleted_ui_skills: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path, scope_label: str = "") -> SkillOverrideStore:
        """Load the store from disk; return an empty store if the file is absent.

        Permissive on parse errors: logs and returns an empty store rather
        than raising, so a corrupted file never takes down skill loading.
        """
        store = cls(path=path, scope_label=scope_label)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return store
        except Exception as exc:
            logger.warning("override: failed to read %s (%s); starting empty", path, exc)
            return store
        if not isinstance(raw, dict):
            logger.warning("override: %s is not an object; starting empty", path)
            return store

        store.version = int(raw.get("version", _SCHEMA_VERSION))
        store.all_defaults_disabled = bool(raw.get("all_defaults_disabled", False))
        raw_overrides = raw.get("overrides") or {}
        if isinstance(raw_overrides, dict):
            for name, entry_raw in raw_overrides.items():
                if not isinstance(name, str) or not isinstance(entry_raw, dict):
                    continue
                store.overrides[name] = OverrideEntry.from_dict(entry_raw)
        deleted = raw.get("deleted_ui_skills") or []
        if isinstance(deleted, list):
            store.deleted_ui_skills = {s for s in deleted if isinstance(s, str)}
        return store

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def upsert(self, skill_name: str, entry: OverrideEntry) -> None:
        """Insert or replace a skill's override entry."""
        self.overrides[skill_name] = entry
        # If we're explicitly managing this skill again, lift any tombstone.
        self.deleted_ui_skills.discard(skill_name)

    def set_enabled(self, skill_name: str, enabled: bool, *, provenance: Provenance | None = None) -> None:
        """Convenience: toggle enabled without rewriting other fields."""
        existing = self.overrides.get(skill_name)
        if existing is None:
            existing = OverrideEntry(
                enabled=enabled,
                provenance=provenance or Provenance.FRAMEWORK,
            )
        else:
            existing.enabled = enabled
            if provenance is not None:
                existing.provenance = provenance
        self.overrides[skill_name] = existing

    def remove(self, skill_name: str, *, tombstone: bool = True) -> None:
        """Drop a skill's override entry; optionally leave a tombstone.

        Tombstones matter for UI-created skills: if the user deletes a
        queen-scope skill via the UI, we rm-tree its directory, but the
        file watcher might lag or a background process might have an
        open handle. A tombstone ensures the loader treats the skill as
        gone even if a stale SKILL.md lingers.
        """
        self.overrides.pop(skill_name, None)
        if tombstone:
            self.deleted_ui_skills.add(skill_name)

    def is_disabled(self, skill_name: str, *, default_enabled: bool) -> bool:
        """Return True when this scope's override force-disables the skill."""
        if self.all_defaults_disabled and default_enabled:
            # Caller says "default enabled"; master switch flips it off unless
            # an explicit enabled=True override re-enables.
            entry = self.overrides.get(skill_name)
            if entry is not None and entry.enabled is True:
                return False
            return True
        entry = self.overrides.get(skill_name)
        if entry is None:
            return not default_enabled
        if entry.enabled is None:
            return not default_enabled
        return not entry.enabled

    def effective_enabled(self, skill_name: str, *, default_enabled: bool) -> bool:
        """The inverse of :meth:`is_disabled`, for readability at call sites."""
        return not self.is_disabled(skill_name, default_enabled=default_enabled)

    def get(self, skill_name: str) -> OverrideEntry | None:
        return self.overrides.get(skill_name)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Atomic write: tmp + rename. Creates the parent dir if needed."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload: dict[str, Any] = {
            "version": self.version,
            "all_defaults_disabled": self.all_defaults_disabled,
            "overrides": {name: entry.to_dict() for name, entry in sorted(self.overrides.items())},
        }
        if self.deleted_ui_skills:
            payload["deleted_ui_skills"] = sorted(self.deleted_ui_skills)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)


def utc_now() -> datetime:
    """Single source of truth for override timestamps."""
    return datetime.now(tz=UTC)
