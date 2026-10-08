"""HTTP routes for per-queen skill control + aggregated library.

Two surfaces:

1. Per-queen routes
   GET    /api/queen/{queen_id}/skills
   POST   /api/queen/{queen_id}/skills
   PATCH  /api/queen/{queen_id}/skills/{skill_name}
   GET    /api/queen/{queen_id}/skills/{skill_name}/body
   PUT    /api/queen/{queen_id}/skills/{skill_name}/body
   POST   /api/queen/{queen_id}/skills/{skill_name}/rename
   DELETE /api/queen/{queen_id}/skills/{skill_name}
   POST   /api/queen/{queen_id}/skills/reload

2. Aggregated library (powers the Skills Library page)
   GET   /api/skills           -- full catalog + inversion (visible_to.*)
   GET   /api/skills/{name}    -- full body + file listing for drawer view
   GET   /api/skills/scopes    -- {queens: [...], colonies: [...]}
   POST  /api/skills/upload    -- multipart (.md or .zip) into a named scope

Skills are configured per queen only. Colonies inherit their owning
queen's override store; colony-authored skills (written by
``create_colony`` / ``write_skill`` into ``{colony_dir}/skills``) still
surface via the ``colony_ui`` extra scope, but there is no per-colony
override store anymore.

Live managers are reloaded when an override mutation occurs so in-flight
queens/workers pick up the new catalog on their next iteration via the
dynamic-prompt providers wired in ``colony_runtime`` and
``queen_orchestrator``.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aiohttp import web

from framework.cloud_sync_hooks import schedule_push
from framework.config import COLONIES_DIR, QUEENS_DIR
from framework.skills.discovery import DiscoveryConfig, ExtraScope, SkillDiscovery
from framework.skills.manager import SkillsManager, SkillsManagerConfig
from framework.skills.overrides import (
    OverrideEntry,
    Provenance,
    SkillOverrideStore,
    utc_now,
)
from framework.skills.parser import ParsedSkill
from framework.skills.skill_writer import (
    build_draft,
    remove_skill as authoring_remove_skill,
    validate_skill_name,
    write_skill,
)

logger = logging.getLogger(__name__)

# Cap uploaded payloads to avoid the aiohttp multipart reader pulling
# megabytes into memory. 2 MB is generous for a SKILL.md + a handful
# of supporting files.
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
_ZIP_MAGIC = b"PK\x03\x04"


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


@dataclass
class SkillScope:
    """Everything a handler needs to mutate a scope's skill surface."""

    kind: str  # "queen"
    target_id: str  # queen_id
    write_dir: Path  # where SKILL.md folders live
    overrides_path: Path  # where the JSON store lives
    store: SkillOverrideStore
    # Live runtimes whose SkillsManager must be reloaded on mutation.
    affected_runtimes: list = field(default_factory=list)
    # The SkillsManager used by GET to enumerate skills. When no runtime
    # is live we build an ad-hoc manager.
    manager: SkillsManager | None = None


def _ensure_queens_known() -> None:
    """Materialize default queen profiles so GET works on a cold install."""
    from framework.agents.queen.queen_profiles import ensure_default_queens

    try:
        ensure_default_queens()
    except Exception:
        logger.debug("ensure_default_queens failed (non-fatal)", exc_info=True)


class _ManagerReloadAdapter:
    """Makes a bare ``SkillsManager`` look like a runtime to ``_reload_scope``.

    ``_reload_scope`` calls ``await rt.reload_skills()`` on every entry in
    ``affected_runtimes``. Live queen DM sessions expose their manager on
    ``phase_state.skills_manager`` but don't have a runtime wrapper, so
    we provide this thin shim so PATCHes reach them with the same call.
    """

    def __init__(self, skills_manager: SkillsManager) -> None:
        self._mgr = skills_manager

    @property
    def skills_manager(self) -> SkillsManager:
        return self._mgr

    async def reload_skills(self) -> dict[str, Any]:
        async with self._mgr.mutation_lock:
            self._mgr.reload()
        return {"catalog_chars": len(self._mgr.skills_catalog_prompt)}


def _queen_scope(manager: Any, queen_id: str) -> SkillScope | None:
    _ensure_queens_known()
    queen_home = QUEENS_DIR / queen_id
    if not queen_home.is_dir():
        # queen_profiles only creates dirs for *known* queen ids. An unknown
        # id means the caller typed something wrong.
        return None
    overrides_path = queen_home / "skills_overrides.json"
    store = SkillOverrideStore.load(overrides_path, scope_label=f"queen:{queen_id}")
    write_dir = queen_home / "skills"

    # Always build a fresh admin manager for GET so enumeration reflects
    # the current disk state (including newly-installed preset skills).
    # The live queen-session manager caches ``_all_skills`` at load time
    # and only refreshes on explicit reload or file-watch event — reusing
    # it here means newly-bundled skills stay invisible until a restart.
    admin_manager = _build_admin_manager(queen_id=queen_id)

    runtimes: list = []
    try:
        for colony in manager.iter_colony_runtimes(queen_id=queen_id):  # type: ignore[union-attr]
            runtimes.append(colony)
        # Also collect live DM-session managers as reload targets so a
        # PATCH reaches running queens, even though we enumerate from
        # the admin manager.
        for session in manager.iter_queen_sessions(queen_id):  # type: ignore[union-attr]
            phase_state = getattr(session, "phase_state", None)
            if phase_state is None:
                continue
            skills_mgr = getattr(phase_state, "skills_manager", None)
            if isinstance(skills_mgr, SkillsManager):
                runtimes.append(_ManagerReloadAdapter(skills_mgr))
    except Exception:
        logger.debug("queen scope: live manager lookup failed", exc_info=True)

    return SkillScope(
        kind="queen",
        target_id=queen_id,
        write_dir=write_dir,
        overrides_path=overrides_path,
        store=store,
        affected_runtimes=runtimes,
        manager=admin_manager,
    )


def _all_scope_extras() -> list[ExtraScope]:
    """ExtraScopes covering every queen_ui and colony_ui skills dir.

    Mirrors the scope set built inline by ``handle_list_all_skills`` so that a
    skill surfaced in the aggregated catalog is also resolvable by name in the
    detail endpoint. Keep the two in sync.
    """
    _ensure_queens_known()
    extras: list[ExtraScope] = []
    if QUEENS_DIR.is_dir():
        for qid in sorted(p.name for p in QUEENS_DIR.glob("*") if (p / "profile.yaml").exists()):
            extras.append(ExtraScope(directory=QUEENS_DIR / qid / "skills", label="queen_ui", priority=2))
    if COLONIES_DIR.is_dir():
        for cn in sorted(p.name for p in COLONIES_DIR.iterdir() if p.is_dir()):
            extras.append(ExtraScope(directory=COLONIES_DIR / cn / "skills", label="colony_ui", priority=3))
            extras.append(ExtraScope(directory=COLONIES_DIR / cn / ".hive" / "skills", label="colony_ui", priority=3))
    return extras


def _build_admin_manager(
    *,
    queen_id: str | None = None,
    extra_scopes: list[ExtraScope] | None = None,
) -> SkillsManager:
    """Build a read-only SkillsManager for GET when no live session exists."""
    extras: list[ExtraScope] = list(extra_scopes or [])
    queen_overrides_path: Path | None = None
    if queen_id:
        queen_home = QUEENS_DIR / queen_id
        queen_overrides_path = queen_home / "skills_overrides.json"
        extras.append(ExtraScope(directory=queen_home / "skills", label="queen_ui", priority=2))
    cfg = SkillsManagerConfig(
        queen_id=queen_id,
        queen_overrides_path=queen_overrides_path,
        extra_scope_dirs=extras,
        project_root=None,
        skip_community_discovery=True,
        interactive=False,
    )
    mgr = SkillsManager(cfg)
    mgr.load()
    return mgr


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


_EDITABLE_PROVENANCE = {
    Provenance.USER_UI_CREATED,
    Provenance.QUEEN_CREATED,
    Provenance.LEARNED_RUNTIME,
}


def _resolve_provenance(
    skill: ParsedSkill,
    queen_store: SkillOverrideStore | None,
) -> tuple[Provenance, OverrideEntry | None]:
    """Override-store entry wins, otherwise fall back to source_scope inference.

    ``OTHER`` entries carry toggle/notes state but don't claim an
    origin — we still return the inferred provenance for those so the
    UI shows something meaningful instead of a generic badge.
    """
    # Collect the entry (if any) before deciding which provenance to report.
    # A FRAMEWORK-stamped entry on a skill that doesn't actually live in the
    # framework scope was written by the old buggy PATCH handler; treat it
    # like OTHER so the inference below reports an honest provenance.
    store_entry: OverrideEntry | None = None
    if queen_store is not None:
        entry = queen_store.get(skill.name)
        if entry is not None:
            store_entry = entry
            stamped = entry.provenance
            # Heal a FRAMEWORK stamp that doesn't match the actual scope —
            # preset/user/colony skills got stamped FRAMEWORK by the old
            # PATCH default. Leave a legit framework-scoped skill alone.
            if stamped == Provenance.FRAMEWORK and skill.source_scope not in {"framework"}:
                stamped = Provenance.OTHER
            if stamped != Provenance.OTHER:
                return stamped, entry
    # Infer from scope label. ``colony_ui`` with no informative entry
    # is only reachable via create_colony() since the UI POST path
    # always stamps USER_UI_CREATED.
    if skill.source_scope == "framework":
        return Provenance.FRAMEWORK, store_entry
    if skill.source_scope == "preset":
        return Provenance.PRESET, store_entry
    if skill.source_scope == "user":
        return Provenance.USER_DROPPED, store_entry
    if skill.source_scope == "queen_ui":
        return Provenance.USER_UI_CREATED, store_entry
    if skill.source_scope == "colony_ui":
        return Provenance.QUEEN_CREATED, store_entry
    return Provenance.PROJECT_DROPPED, store_entry


def _effective_enabled(
    skill: ParsedSkill,
    queen_store: SkillOverrideStore | None,
) -> bool:
    # Mirrors ``SkillsManager._apply_overrides`` so the UI's "enabled" column
    # matches what the queen actually sees in her prompt. An explicit entry
    # wins over preset-off-by-default and over the ``all_defaults_disabled``
    # master switch.
    if queen_store is not None:
        entry = queen_store.get(skill.name)
        if entry is not None and entry.enabled is not None:
            return entry.enabled
    # Preset-scope capability packs ship OFF; they only appear in the queen's
    # catalog after an explicit per-queen opt-in.
    if skill.source_scope == "preset":
        return False
    if queen_store is not None and queen_store.all_defaults_disabled and skill.source_scope == "framework":
        return False
    return True


def _serialize_skill(
    skill: ParsedSkill,
    *,
    queen_store: SkillOverrideStore | None,
) -> dict[str, Any]:
    provenance, entry = _resolve_provenance(skill, queen_store)
    editable = provenance in _EDITABLE_PROVENANCE
    return {
        "name": skill.name,
        "description": skill.description,
        "source_scope": skill.source_scope,
        "provenance": str(provenance),
        "enabled": _effective_enabled(skill, queen_store),
        "editable": editable,
        "deletable": editable,
        "location": skill.location,
        "base_dir": skill.base_dir,
        "visibility": skill.visibility,
        "trust": entry.trust if entry else None,
        "created_at": entry.created_at.isoformat() if (entry and entry.created_at) else None,
        "created_by": entry.created_by if entry else None,
        "notes": entry.notes if entry else None,
        "param_overrides": dict(entry.param_overrides) if entry else {},
    }


# ---------------------------------------------------------------------------
# GET handlers
# ---------------------------------------------------------------------------


async def handle_list_queen_skills(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": f"queen '{queen_id}' not found"}, status=404)
    mgr = scope.manager
    assert mgr is not None
    skills = [_serialize_skill(s, queen_store=scope.store) for s in mgr.enumerate_skills_with_source()]
    skills.sort(key=lambda r: r["name"])
    return web.json_response(
        {
            "queen_id": queen_id,
            "all_defaults_disabled": scope.store.all_defaults_disabled,
            "skills": skills,
        }
    )


# ---------------------------------------------------------------------------
# Aggregated library
# ---------------------------------------------------------------------------


async def handle_list_all_skills(request: web.Request) -> web.Response:
    """Global catalog: every skill in every scope + inversion ``visible_to``."""
    # Enumerate queens and colonies by walking the standard dirs.
    _ensure_queens_known()
    queen_ids = sorted(p.name for p in QUEENS_DIR.glob("*") if (p / "profile.yaml").exists()) if QUEENS_DIR.is_dir() else []
    colony_ids: list[str] = []
    if COLONIES_DIR.is_dir():
        colony_ids = sorted(p.name for p in COLONIES_DIR.iterdir() if p.is_dir())

    # Build one admin manager that covers every scope — expensive on cold
    # boot but cached thanks to the parser's per-file reads being cheap.
    extras: list[ExtraScope] = []
    for qid in queen_ids:
        extras.append(ExtraScope(directory=QUEENS_DIR / qid / "skills", label="queen_ui", priority=2))
    # We intentionally don't plumb every colony's project_root into one
    # manager — discovery only allows a single project_root. For the
    # aggregator we scan every colony's skills/ (and the legacy nested
    # .hive/skills/ for pre-flatten colonies) as tagged extra scopes
    # instead. That keeps the xml-catalog-per-scope invariant intact
    # without requiring N managers.
    for cn in colony_ids:
        extras.append(
            ExtraScope(
                directory=COLONIES_DIR / cn / "skills",
                label="colony_ui",
                priority=3,
            )
        )
        extras.append(
            ExtraScope(
                directory=COLONIES_DIR / cn / ".hive" / "skills",
                label="colony_ui",
                priority=3,
            )
        )

    # Raw discovery (no override filtering) — we apply per-scope stores
    # below when computing ``visible_to``.
    # Off-loop: discover() recursively walks every scope root (framework +
    # ~/.agents + external_skills + HIVE_HOME + one/two per queen/colony)
    # with a stat per entry and a file read per skill — in-loop it stalled
    # every SSE stream for the duration on each Skills Library load.
    discovery = SkillDiscovery(DiscoveryConfig(project_root=None, skip_framework_scope=False, extra_scopes=extras))
    discovered = await asyncio.to_thread(discovery.discover)

    # Load all stores once. Colonies have no store of their own — they
    # inherit their owning queen's, so visibility is queen-level only.
    queen_stores: dict[str, SkillOverrideStore] = {
        qid: SkillOverrideStore.load(QUEENS_DIR / qid / "skills_overrides.json", scope_label=f"queen:{qid}") for qid in queen_ids
    }
    colony_queens: dict[str, str | None] = {}
    for cn in colony_ids:
        try:
            from framework.host.colony_metadata import load_colony_metadata

            colony_queens[cn] = load_colony_metadata(cn).get("queen_name") or None
        except Exception:
            colony_queens[cn] = None

    rows: list[dict[str, Any]] = []

    # Owner mapping for queen_ui / colony_ui scopes: the dir path encodes
    # which queen/colony the skill belongs to.
    def _owner_for(skill: ParsedSkill) -> dict[str, str] | None:
        base = Path(skill.base_dir)
        parts = base.parts
        try:
            idx_q = parts.index("queens")
            if skill.source_scope == "queen_ui" and idx_q + 1 < len(parts):
                qid = parts[idx_q + 1]
                return {"type": "queen", "id": qid, "name": qid}
        except ValueError:
            pass
        try:
            idx_c = parts.index("colonies")
            if skill.source_scope == "colony_ui" and idx_c + 1 < len(parts):
                cn = parts[idx_c + 1]
                return {"type": "colony", "id": cn, "name": cn}
        except ValueError:
            pass
        return None

    for skill in sorted(discovered, key=lambda s: s.name):
        visible_queens: list[str] = []
        visible_colonies: list[str] = []
        for qid, qstore in queen_stores.items():
            if _effective_enabled(skill, qstore):
                visible_queens.append(qid)
        # A colony sees whatever its owning queen sees.
        for cn, qid in colony_queens.items():
            qstore = queen_stores.get(qid or "", None)
            if _effective_enabled(skill, qstore):
                visible_colonies.append(cn)

        # Provenance: choose the owning queen's store record if any.
        owner = _owner_for(skill)
        prov_store: SkillOverrideStore | None = None
        if owner and owner["type"] == "queen":
            prov_store = queen_stores.get(owner["id"])
        provenance, entry = _resolve_provenance(skill, prov_store)
        editable = provenance in _EDITABLE_PROVENANCE
        rows.append(
            {
                "name": skill.name,
                "description": skill.description,
                "source_scope": skill.source_scope,
                "provenance": str(provenance),
                "owner": owner,
                "visible_to": {"queens": sorted(visible_queens), "colonies": sorted(visible_colonies)},
                "enabled_by_default": True,
                "editable": editable,
                "deletable": editable,
                "location": skill.location,
                "visibility": skill.visibility,
            }
        )

    return web.json_response(
        {
            "skills": rows,
            "queens": [{"id": q, "name": q} for q in queen_ids],
            "colonies": [{"name": c, "queen_id": colony_queens.get(c)} for c in colony_ids],
        }
    )


async def handle_get_skill_detail(request: web.Request) -> web.Response:
    """GET /api/skills/{skill_name} — full body for the detail drawer."""
    skill_name = request.match_info["skill_name"]
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return web.json_response({"error": err}, status=400)
    # Scan every scope (framework/preset/user + all queen_ui/colony_ui dirs) so
    # that skills authored into a queen or colony — which appear in the catalog
    # listing — are also resolvable here. Without the extra scopes this 404s.
    manager = _build_admin_manager(extra_scopes=_all_scope_extras())
    for s in manager.enumerate_skills_with_source():
        if s.name == name:
            # Re-read body so we get the freshest content (the cached
            # ParsedSkill.body was stamped at load time).
            try:
                body = Path(s.location).read_text(encoding="utf-8")
            except OSError as exc:
                return web.json_response({"error": f"failed to read {s.location}: {exc}"}, status=500)
            return web.json_response(
                {
                    "name": s.name,
                    "description": s.description,
                    "source_scope": s.source_scope,
                    "location": s.location,
                    "base_dir": s.base_dir,
                    "body": body,
                    "visibility": s.visibility,
                }
            )
    return web.json_response({"error": f"skill '{name}' not found"}, status=404)


async def handle_list_scopes(request: web.Request) -> web.Response:
    """GET /api/skills/scopes — enumerate queens and colonies for the UI picker."""
    _ensure_queens_known()
    queens = []
    if QUEENS_DIR.is_dir():
        for p in sorted(QUEENS_DIR.glob("*/profile.yaml")):
            queens.append({"id": p.parent.name, "name": p.parent.name})
    colonies = []
    if COLONIES_DIR.is_dir():
        for p in sorted(x for x in COLONIES_DIR.iterdir() if x.is_dir()):
            queen_id = None
            try:
                from framework.host.colony_metadata import load_colony_metadata

                queen_id = load_colony_metadata(p.name).get("queen_name") or None
            except Exception:
                pass
            colonies.append({"name": p.name, "queen_id": queen_id})
    return web.json_response({"queens": queens, "colonies": colonies})


# ---------------------------------------------------------------------------
# Mutations (shared body)
# ---------------------------------------------------------------------------


async def _reload_scope(scope: SkillScope) -> None:
    """Reload the primary manager and every live runtime affected by the scope."""
    import asyncio

    async def _reload_one(rt) -> None:
        try:
            await rt.reload_skills()
        except Exception:
            logger.warning("reload_skills failed for runtime %r", rt, exc_info=True)

    # The primary manager (often the queen's) gets reloaded too.
    if scope.manager is not None:
        async with scope.manager.mutation_lock:
            try:
                scope.manager.reload()
            except Exception:
                logger.warning("primary manager reload failed", exc_info=True)
    # Runtimes in parallel — each has its own mutation lock.
    if scope.affected_runtimes:
        await asyncio.gather(*[_reload_one(rt) for rt in scope.affected_runtimes], return_exceptions=True)


async def _handle_create(scope: SkillScope, payload: dict[str, Any], user_id: str) -> web.Response:
    draft, err = build_draft(
        skill_name=payload.get("name"),
        skill_description=payload.get("description"),
        skill_body=payload.get("body"),
        skill_files=payload.get("files"),
    )
    if err or draft is None:
        return web.json_response({"error": err}, status=400)
    replace_existing = bool(payload.get("replace_existing", False))
    installed, wrote_err, replaced = write_skill(draft, target_root=scope.write_dir, replace_existing=replace_existing)
    if wrote_err is not None or installed is None:
        status = 409 if "already exists" in (wrote_err or "") else 500
        return web.json_response({"error": wrote_err}, status=status)
    enabled = bool(payload.get("enabled", True))
    scope.store.upsert(
        draft.name,
        OverrideEntry(
            enabled=enabled,
            provenance=Provenance.USER_UI_CREATED,
            created_at=utc_now(),
            created_by=user_id,
            notes=payload.get("notes") if isinstance(payload.get("notes"), str) else None,
        ),
    )
    scope.store.save()
    await _reload_scope(scope)
    return web.json_response(
        {
            "name": draft.name,
            "installed_path": str(installed),
            "replaced": replaced,
            "enabled": enabled,
            "provenance": str(Provenance.USER_UI_CREATED),
        },
        status=201,
    )


async def _handle_patch(scope: SkillScope, skill_name: str, payload: dict[str, Any]) -> web.Response:
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return web.json_response({"error": err}, status=400)
    # A PATCH can't know who originally authored the skill — it only
    # stores the user's toggle. Use OTHER rather than stamping a guess
    # (FRAMEWORK, USER_UI_CREATED, etc.) that would then outrank the
    # source_scope inference on subsequent reads.
    existing = scope.store.get(name) or OverrideEntry(provenance=Provenance.OTHER)
    if "enabled" in payload:
        enabled_raw = payload["enabled"]
        if not isinstance(enabled_raw, bool):
            return web.json_response({"error": "'enabled' must be a bool"}, status=400)
        existing.enabled = enabled_raw
    if "param_overrides" in payload:
        po = payload["param_overrides"]
        if not isinstance(po, dict):
            return web.json_response({"error": "'param_overrides' must be an object"}, status=400)
        existing.param_overrides = dict(po)
    if "notes" in payload:
        notes = payload["notes"]
        existing.notes = notes if isinstance(notes, str) or notes is None else existing.notes
    if "all_defaults_disabled" in payload and isinstance(payload["all_defaults_disabled"], bool):
        scope.store.all_defaults_disabled = payload["all_defaults_disabled"]
    scope.store.upsert(name, existing)
    scope.store.save()
    await _reload_scope(scope)
    return web.json_response({"name": name, "enabled": existing.enabled, "ok": True})


async def _handle_put_body(scope: SkillScope, skill_name: str, payload: dict[str, Any]) -> web.Response:
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return web.json_response({"error": err}, status=400)
    entry = scope.store.get(name)
    provenance = entry.provenance if entry else Provenance.FRAMEWORK
    if provenance not in _EDITABLE_PROVENANCE:
        return web.json_response({"error": f"skill '{name}' is not editable (provenance={provenance})"}, status=403)
    description = payload.get("description")
    body = payload.get("body")
    if not isinstance(body, str) or not body.strip():
        return web.json_response({"error": "'body' is required"}, status=400)
    # If the caller omitted description, keep whatever's in the current SKILL.md.
    current_desc = None
    if description is None:
        current_path = scope.write_dir / name / "SKILL.md"
        if current_path.exists():
            match = re.search(r"^description:\s*(.+)$", current_path.read_text(encoding="utf-8"), re.MULTILINE)
            if match:
                current_desc = match.group(1).strip().strip("\"'")
    final_desc = description if isinstance(description, str) else (current_desc or "")
    draft, derr = build_draft(
        skill_name=name,
        skill_description=final_desc,
        skill_body=body,
        skill_files=payload.get("files"),
    )
    if derr or draft is None:
        return web.json_response({"error": derr}, status=400)
    installed, werr, _ = write_skill(draft, target_root=scope.write_dir, replace_existing=True)
    if werr or installed is None:
        return web.json_response({"error": werr}, status=500)
    # Touch created_at? No — keep the original author. Just refresh notes/overrides.
    await _reload_scope(scope)
    return web.json_response({"name": name, "installed_path": str(installed)})


async def _handle_get_body(scope: SkillScope, skill_name: str) -> web.Response:
    """Return the queen's *own* copy of a skill (frontmatter-stripped body).

    ``handle_get_skill_detail`` is scope-less and returns the first name match
    across every scope, so it can surface a different queen's copy. Edit/rename
    must operate on THIS queen's file, so we enumerate the queen-scoped manager
    (framework/preset/user + only this queen's dir) instead. The ``body`` is the
    parsed markdown (no frontmatter) so it round-trips cleanly through
    ``PUT .../body`` (which re-adds frontmatter via ``build_draft``).
    """
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return web.json_response({"error": err}, status=400)
    for s in scope.manager.enumerate_skills_with_source():
        if s.name == name:
            provenance, _ = _resolve_provenance(s, scope.store)
            return web.json_response(
                {
                    "name": s.name,
                    "description": s.description,
                    "source_scope": s.source_scope,
                    "location": s.location,
                    "base_dir": s.base_dir,
                    "body": s.body,
                    "visibility": s.visibility,
                    "editable": provenance in _EDITABLE_PROVENANCE,
                }
            )
    return web.json_response({"error": f"skill '{name}' not found"}, status=404)


async def _handle_rename(scope: SkillScope, skill_name: str, payload: dict[str, Any]) -> web.Response:
    """Rename this queen's copy of a skill (dir + frontmatter ``name``).

    Only renames THIS queen's file; the same-named skill on other queens is a
    separate copy and is left untouched (the UI warns about this). Preserves the
    override entry's metadata (provenance/created_at/created_by) by cloning it
    under the new key rather than delete+recreate.
    """
    old, err = validate_skill_name(skill_name)
    if err or old is None:
        return web.json_response({"error": err}, status=400)
    new, err = validate_skill_name(payload.get("new_name"))
    if err or new is None:
        return web.json_response({"error": err}, status=400)
    if new == old:
        return web.json_response({"error": "new_name matches the current name"}, status=400)

    # Only editable (user/queen-authored) skills live in the queen's write_dir
    # and can be renamed. Framework/preset/user-dropped skills are shared and
    # read-only.
    entry = scope.store.get(old)
    provenance = entry.provenance if entry else Provenance.FRAMEWORK
    if provenance not in _EDITABLE_PROVENANCE:
        return web.json_response({"error": f"skill '{old}' is not editable (provenance={provenance})"}, status=403)

    old_dir = scope.write_dir / old
    new_dir = scope.write_dir / new
    if not old_dir.is_dir():
        return web.json_response({"error": f"skill '{old}' has no editable copy for this queen"}, status=404)
    if new_dir.exists():
        return web.json_response({"error": f"skill '{new}' already exists"}, status=409)

    # Move the directory (preserves sub-files), then patch the frontmatter
    # ``name`` so it stays consistent with the directory name.
    try:
        old_dir.rename(new_dir)
    except OSError as e:
        return web.json_response({"error": f"failed to rename skill folder: {e}"}, status=500)
    skill_md = new_dir / "SKILL.md"
    try:
        text = skill_md.read_text(encoding="utf-8")
        patched, n = re.subn(r"^name:\s*.+$", f"name: {new}", text, count=1, flags=re.MULTILINE)
        if n:
            skill_md.write_text(patched, encoding="utf-8")
    except OSError as e:
        # Best-effort roll back the directory move so we don't leave a
        # dir/frontmatter mismatch behind.
        try:
            new_dir.rename(old_dir)
        except OSError:
            pass
        return web.json_response({"error": f"failed to update SKILL.md: {e}"}, status=500)

    # Carry the override entry (enabled state + provenance + authorship) to the
    # new key; drop the old key without a tombstone (rename, not delete).
    if entry is not None:
        scope.store.upsert(new, entry.clone())
        scope.store.remove(old, tombstone=False)
        scope.store.save()
    await _reload_scope(scope)
    return web.json_response({"old_name": old, "new_name": new, "ok": True})


async def _handle_delete(scope: SkillScope, skill_name: str) -> web.Response:
    name, err = validate_skill_name(skill_name)
    if err or name is None:
        return web.json_response({"error": err}, status=400)
    entry = scope.store.get(name)
    provenance = entry.provenance if entry else None
    if provenance is not None and provenance not in _EDITABLE_PROVENANCE:
        return web.json_response({"error": f"skill '{name}' is not deletable (provenance={provenance})"}, status=403)
    removed, rerr = authoring_remove_skill(scope.write_dir, name)
    if rerr:
        return web.json_response({"error": rerr}, status=500)
    scope.store.remove(name, tombstone=True)
    scope.store.save()
    await _reload_scope(scope)
    return web.json_response({"name": name, "removed": removed})


async def _handle_reload(scope: SkillScope) -> web.Response:
    await _reload_scope(scope)
    return web.json_response({"ok": True, "target": scope.target_id, "kind": scope.kind})


# ---------------------------------------------------------------------------
# HTTP handlers (thin wrappers that resolve the scope then delegate)
# ---------------------------------------------------------------------------


def _requester_id(request: web.Request) -> str:
    # The UI surfaces a user email via the shell's CLAUDE.md; production
    # deployments should replace this with authenticated session state.
    return request.headers.get("X-User", "ui")


def _push_skill_override(response: web.Response, queen_id: str) -> web.Response:
    """Mirror a queen's skills_overrides.json to the cloud after a successful
    skill mutation. Pass-through on the response so call sites stay terse."""
    if response.status < 400:
        schedule_push("skill_override", f"queen:{queen_id}")
    return response


async def handle_create_queen_skill(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    return _push_skill_override(await _handle_create(scope, payload, _requester_id(request)), queen_id)


async def handle_patch_queen_skill(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    return _push_skill_override(await _handle_patch(scope, request.match_info["skill_name"], payload), queen_id)


async def handle_put_queen_skill_body(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    return _push_skill_override(await _handle_put_body(scope, request.match_info["skill_name"], payload), queen_id)


async def handle_get_queen_skill_body(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    return await _handle_get_body(scope, request.match_info["skill_name"])


async def handle_rename_queen_skill(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    return _push_skill_override(await _handle_rename(scope, request.match_info["skill_name"], payload), queen_id)


async def handle_delete_queen_skill(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    queen_id = request.match_info["queen_id"]
    scope = _queen_scope(manager, queen_id)
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    return _push_skill_override(await _handle_delete(scope, request.match_info["skill_name"]), queen_id)


async def handle_reload_queen_skills(request: web.Request) -> web.Response:
    manager = request.app.get("manager")
    scope = _queen_scope(manager, request.match_info["queen_id"])
    if scope is None:
        return web.json_response({"error": "queen not found"}, status=404)
    return await _handle_reload(scope)


# ---------------------------------------------------------------------------
# Upload handler (multipart: SKILL.md OR .zip)
# ---------------------------------------------------------------------------


async def handle_upload_skill(request: web.Request) -> web.Response:
    """POST /api/skills/upload — accept a single SKILL.md or a .zip bundle.

    Form fields:
      ``file`` (required)           — the .md / .zip payload
      ``scope`` (required)          — "user" | "queen"
      ``target_id`` (queen)         — queen_id for that scope
      ``enabled`` (optional)        — "true"/"false" (defaults true)
      ``replace_existing``          — "true"/"false" (defaults false)
      ``name``                      — optional override for single-.md uploads
    """
    manager = request.app.get("manager")
    if not request.content_type.startswith("multipart/"):
        return web.json_response({"error": "expected multipart/form-data"}, status=400)

    reader = await request.multipart()
    upload_bytes: bytes | None = None
    upload_filename: str | None = None
    form: dict[str, str] = {}

    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            buf = io.BytesIO()
            while True:
                chunk = await part.read_chunk(size=65536)
                if not chunk:
                    break
                buf.write(chunk)
                if buf.tell() > _MAX_UPLOAD_BYTES:
                    return web.json_response({"error": f"upload exceeds {_MAX_UPLOAD_BYTES} bytes"}, status=413)
            upload_bytes = buf.getvalue()
            upload_filename = part.filename or ""
        else:
            form[part.name or ""] = (await part.text()).strip()

    if upload_bytes is None:
        return web.json_response({"error": "missing 'file' part"}, status=400)

    scope_kind = form.get("scope", "").lower()
    if scope_kind not in {"user", "queen"}:
        return web.json_response({"error": "scope must be user|queen"}, status=400)
    target_id = form.get("target_id", "").strip()
    if scope_kind == "queen" and not target_id:
        return web.json_response({"error": f"target_id required for scope={scope_kind}"}, status=400)
    enabled = form.get("enabled", "true").lower() != "false"
    replace_existing = form.get("replace_existing", "false").lower() == "true"
    name_override = form.get("name", "").strip() or None

    # Resolve the write target
    if scope_kind == "user":
        from framework.config import HIVE_HOME

        write_dir = HIVE_HOME / "skills"
        overrides_path: Path | None = None
        store: SkillOverrideStore | None = None
        affected_runtimes: list = []
    else:  # queen
        scope = _queen_scope(manager, target_id)
        if scope is None:
            return web.json_response({"error": "queen not found"}, status=404)
        write_dir = scope.write_dir
        overrides_path = scope.overrides_path
        store = scope.store
        affected_runtimes = scope.affected_runtimes

    # Extract into a draft
    draft: Any
    if upload_bytes.startswith(_ZIP_MAGIC) or (upload_filename or "").endswith(".zip"):
        draft_name, draft_desc, draft_body, draft_files, err = _extract_from_zip(upload_bytes, name_hint=name_override)
        if err:
            return web.json_response({"error": err}, status=400)
    else:
        draft_name, draft_desc, draft_body, draft_files, err = _extract_from_md(upload_bytes, filename=upload_filename, name_hint=name_override)
        if err:
            return web.json_response({"error": err}, status=400)

    draft, derr = build_draft(
        skill_name=draft_name,
        skill_description=draft_desc,
        skill_body=draft_body,
        skill_files=draft_files,
    )
    if derr or draft is None:
        return web.json_response({"error": derr}, status=400)

    installed, werr, replaced = write_skill(draft, target_root=write_dir, replace_existing=replace_existing)
    if werr or installed is None:
        status = 409 if "already exists" in (werr or "") else 500
        return web.json_response({"error": werr}, status=status)

    if store is not None and overrides_path is not None:
        store.upsert(
            draft.name,
            OverrideEntry(
                enabled=enabled,
                provenance=Provenance.USER_UI_CREATED,
                created_at=utc_now(),
                created_by=_requester_id(request),
            ),
        )
        store.save()

    # Reload affected runtimes (queen scope only). For user scope,
    # changes take effect the next time a runtime reloads — usually on
    # the next queen boot.
    for rt in affected_runtimes:
        try:
            await rt.reload_skills()
        except Exception:
            logger.warning("runtime reload after upload failed", exc_info=True)

    return web.json_response(
        {
            "name": draft.name,
            "installed_path": str(installed),
            "replaced": replaced,
            "scope": scope_kind,
            "target_id": target_id or None,
            "enabled": enabled,
        },
        status=201,
    )


def _extract_from_md(
    raw: bytes,
    *,
    filename: str | None,
    name_hint: str | None,
) -> tuple[str, str, str, list[dict], str | None]:
    """Parse a lone SKILL.md upload. Returns (name, desc, body, files, error)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return "", "", "", [], "upload is not valid UTF-8"
    name, desc, body, err = _parse_skill_md_text(text)
    if err:
        return "", "", "", [], err
    if name_hint:
        name = name_hint
    if not name and filename:
        stem = Path(filename).stem
        if stem and stem.lower() != "skill":
            name = stem.lower()
    if not name:
        return "", "", "", [], "could not determine skill name (pass 'name' form field)"
    return name, desc, body, [], None


def _extract_from_zip(
    raw: bytes,
    *,
    name_hint: str | None,
) -> tuple[str, str, str, list[dict], str | None]:
    """Parse a .zip bundle. SKILL.md must be at root (not inside a folder)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return "", "", "", [], "invalid zip file"

    names = z.namelist()
    skill_mds = [n for n in names if n == "SKILL.md" or n.endswith("/SKILL.md")]
    if not skill_mds:
        return "", "", "", [], "zip must contain SKILL.md at root"
    # Prefer the shallowest SKILL.md; multiple is usually an authoring mistake
    skill_mds.sort(key=lambda p: p.count("/"))
    root_skill_md = skill_mds[0]
    root_prefix = root_skill_md[: -len("SKILL.md")] if root_skill_md != "SKILL.md" else ""

    skill_text = z.read(root_skill_md).decode("utf-8", errors="replace")
    name, desc, body, err = _parse_skill_md_text(skill_text)
    if err:
        return "", "", "", [], err
    if name_hint:
        name = name_hint
    if not name and root_prefix:
        name = root_prefix.strip("/")
    if not name:
        return "", "", "", [], "could not determine skill name from zip"

    files: list[dict] = []
    for entry_name in names:
        if entry_name == root_skill_md or entry_name.endswith("/"):
            continue
        if not entry_name.startswith(root_prefix):
            continue
        rel = entry_name[len(root_prefix) :]
        if not rel or rel == "SKILL.md":
            continue
        content_bytes = z.read(entry_name)
        try:
            content = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return "", "", "", [], f"binary file '{rel}' not supported yet"
        files.append({"path": rel, "content": content})
    return name, desc, body, files, None


def _parse_skill_md_text(text: str) -> tuple[str, str, str, str | None]:
    """Lightweight frontmatter split so uploads can be validated offline.

    Full parsing happens inside :mod:`framework.skills.parser` when
    discovery runs; this only needs ``name``, ``description`` and the
    body so we can hand off to ``build_draft``.
    """
    if not text.startswith("---"):
        return "", "", "", "SKILL.md must start with '---' frontmatter"
    try:
        _, fm, body = text.split("---", 2)
    except ValueError:
        return "", "", "", "SKILL.md frontmatter is malformed"
    name = ""
    description = ""
    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().strip("\"'")
        elif line.startswith("description:"):
            description = line.split(":", 1)[1].strip().strip("\"'")
    return name, description, body.lstrip("\n"), None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_routes(app: web.Application) -> None:
    r = app.router

    # Per-queen
    r.add_get("/api/queen/{queen_id}/skills", handle_list_queen_skills)
    r.add_post("/api/queen/{queen_id}/skills", handle_create_queen_skill)
    r.add_patch("/api/queen/{queen_id}/skills/{skill_name}", handle_patch_queen_skill)
    r.add_get("/api/queen/{queen_id}/skills/{skill_name}/body", handle_get_queen_skill_body)
    r.add_put("/api/queen/{queen_id}/skills/{skill_name}/body", handle_put_queen_skill_body)
    r.add_post("/api/queen/{queen_id}/skills/{skill_name}/rename", handle_rename_queen_skill)
    r.add_delete("/api/queen/{queen_id}/skills/{skill_name}", handle_delete_queen_skill)
    r.add_post("/api/queen/{queen_id}/skills/reload", handle_reload_queen_skills)

    # Aggregated library (powers the Skills Library page)
    r.add_get("/api/skills", handle_list_all_skills)
    r.add_get("/api/skills/scopes", handle_list_scopes)
    r.add_post("/api/skills/upload", handle_upload_skill)
    r.add_get("/api/skills/{skill_name}", handle_get_skill_detail)
