"""Queen identity profile routes.

- GET    /api/queen/profiles                -- list all queen profiles (id, name, title)
- GET    /api/queen/{queen_id}/profile      -- get full queen profile
- PATCH  /api/queen/{queen_id}/profile      -- update queen profile fields
- POST   /api/queen/initialize-preferences  -- materialize queens from /me preferences
  (called by Electron main before runtime "ready" is broadcast)
- POST   /api/queen/{queen_id}/avatar       -- upload queen avatar image
- GET    /api/queen/{queen_id}/avatar       -- serve queen avatar image
- POST   /api/queen/{queen_id}/session      -- get or create a persistent session for a queen
- POST   /api/queen/{queen_id}/session/select -- resume a specific session for a queen
- POST   /api/queen/{queen_id}/session/new  -- create a fresh session for a queen
"""

import json
import logging
from pathlib import Path
from typing import Any

import yaml
from aiohttp import web

from framework.agents.queen.queen_profiles import (
    DEFAULT_QUEENS,
    _materialize_default_queen,
    create_queen_profile,
    default_profile_persona,
    ensure_default_queens,
    list_queens,
    load_queen_profile,
    update_queen_profile,
)
from framework.cloud_sync_hooks import schedule_push
from framework.config import QUEENS_DIR

logger = logging.getLogger(__name__)


def _read_queen_session_meta(queen_id: str, session_id: str) -> dict[str, Any]:
    """Return persisted metadata for a queen session when available.

    Checks the DM-chat path first; if not present, walks every colony's
    ``queen/`` subdir looking for the session (a colony-queen session
    belonging to this queen).
    """
    from framework.server.session_manager import _find_queen_session_dir

    session_dir = _find_queen_session_dir(session_id)
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _session_belongs_to_queen(manager, session_id: str, queen_id: str) -> bool:
    """Check live or persisted ownership for a queen session (v3 layout).

    Recognised homes:
    - DM:       ``queens/<queen_id>/sessions/<session_id>/``
    - Overseer: ``colonies/<colony>/queens/<queen_id>/sessions/<session_id>/``

    Queen ownership is read directly from the path structure in both
    cases; ``meta.json`` is not consulted.
    """
    live_session = manager.get_session(session_id)
    if live_session is not None:
        return live_session.queen_name == queen_id

    from framework.server.session_manager import _find_queen_session_dir

    session_dir = _find_queen_session_dir(session_id)
    if not (session_dir.exists() and session_dir.is_dir()):
        return False
    # Both DM and overseer paths end in ``sessions/<sid>``; the queen id
    # is the grandparent of <sid>.
    if session_dir.parent.name == "sessions" and session_dir.parent.parent.name == queen_id:
        return True
    return False


async def _create_bound_queen_session(
    manager,
    queen_id: str,
    *,
    initial_prompt: str | None = None,
    initial_phase: str | None = None,
    resume_from: str | None = None,
):
    """Create or resume a session that is explicitly bound to a queen."""
    colony_id: str | None = None
    if resume_from:
        meta = _read_queen_session_meta(queen_id, resume_from)
        # Prefer the explicit colony_id in meta; fall back to deriving it
        # from a legacy agent_path basename for older sessions.
        candidate = meta.get("colony_id")
        if not (isinstance(candidate, str) and candidate):
            legacy_path = meta.get("agent_path")
            if isinstance(legacy_path, str) and legacy_path:
                candidate = Path(legacy_path).name
        if isinstance(candidate, str) and candidate:
            colony_id = candidate

    # Single dispatch — create_session decides bootstrap-vs-open based on
    # whether <COLONIES_DIR>/<colony_id>/metadata.json exists.
    return await manager.create_session(
        colony_id=colony_id,
        queen_resume_from=resume_from,
        initial_prompt=initial_prompt,
        queen_name=queen_id,
        initial_phase=initial_phase,
    )


async def handle_list_profiles(request: web.Request) -> web.Response:
    """GET /api/queen/profiles — list all queen profiles."""
    ensure_default_queens()
    queens = list_queens()
    return web.json_response({"queens": queens})


async def handle_create_queen(request: web.Request) -> web.Response:
    """POST /api/queen/create — create a custom queen from scratch.

    Body: ``{"name": "...", "title"?: "...", "persona"?: "...", "queen_id"?: "..."}``.
    ``queen_id`` is derived from the name when omitted. Returns 201 with the
    new catalog entry (``custom: true``), 400 on validation errors, 409 when
    the id is already taken (including built-in catalog ids).
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be an object"}, status=400)
    try:
        entry = create_queen_profile(
            name=str(body.get("name") or ""),
            title=str(body.get("title") or ""),
            persona=str(body.get("persona") or ""),
            queen_id=str(body.get("queen_id") or ""),
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    except FileExistsError as e:
        return web.json_response(
            {"error": f"queen id already exists: {e}"}, status=409
        )
    schedule_push()
    return web.json_response({"queen": entry}, status=201)


def _transform_profile_for_api(profile: dict) -> dict:
    """Transform internal profile format to API format expected by frontend.

    Maps YAML fields (core_traits, hidden_background, etc.) to display fields
    (summary, experience, skills, signature_achievement).
    """
    result: dict[str, Any] = {
        "name": profile.get("name", ""),
        "title": profile.get("title", ""),
    }

    # Build summary from core_traits + psychological_profile
    summary_parts = []
    if profile.get("core_traits"):
        summary_parts.append(profile["core_traits"])
    if profile.get("psychological_profile", {}).get("anti_stereotype"):
        summary_parts.append(profile["psychological_profile"]["anti_stereotype"])
    if summary_parts:
        result["summary"] = "\n\n".join(summary_parts)

    # Build experience from hidden_background
    experience = []
    hidden = profile.get("hidden_background", {})
    if hidden.get("past_wound") or hidden.get("deep_motive") or hidden.get("behavioral_mapping"):
        details = []
        if hidden.get("past_wound"):
            details.append(f"Background: {hidden['past_wound']}")
        if hidden.get("deep_motive"):
            details.append(f"Drive: {hidden['deep_motive']}")
        if hidden.get("behavioral_mapping"):
            details.append(f"Approach: {hidden['behavioral_mapping']}")
        experience.append({"role": f"{profile.get('title', 'Executive Advisor')}", "details": details})
    if experience:
        result["experience"] = experience

    # Skills from skills field
    if profile.get("skills"):
        result["skills"] = profile["skills"]

    # Signature achievement from world_lore
    world_lore = profile.get("world_lore", {})
    if world_lore.get("habitat"):
        result["signature_achievement"] = f"{world_lore['habitat']}. {world_lore.get('lexicon', '')}".strip()

    if profile.get("portrait"):
        result["portrait"] = profile["portrait"]

    return result


async def handle_get_profile(request: web.Request) -> web.Response:
    """GET /api/queen/{queen_id}/profile — get full queen profile."""
    queen_id = request.match_info["queen_id"]
    ensure_default_queens()
    try:
        profile = load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    api_profile = _transform_profile_for_api(profile)
    return web.json_response({"id": queen_id, "has_avatar": _has_avatar(queen_id), **api_profile})


def _has_avatar(queen_id: str) -> bool:
    """True iff an avatar.* file exists in the queen's profile directory."""
    queen_dir = QUEENS_DIR / queen_id
    if not queen_dir.is_dir():
        return False
    return any(queen_dir.glob("avatar.*"))


def _reverse_transform_for_yaml(body: dict) -> dict:
    """Map API-format fields back to YAML profile fields.

    The API exposes a simplified view (summary, skills, signature_achievement)
    that maps onto the underlying YAML structure (core_traits, hidden_background,
    psychological_profile, world_lore, etc.).
    """
    yaml_updates: dict[str, Any] = {}

    if "name" in body:
        yaml_updates["name"] = body["name"]
    if "title" in body:
        yaml_updates["title"] = body["title"]

    if "summary" in body:
        # Summary is displayed as core_traits + anti_stereotype joined by \n\n.
        # Store the full text in core_traits for simplicity.
        yaml_updates["core_traits"] = body["summary"]

    if "skills" in body:
        yaml_updates["skills"] = body["skills"]

    if "signature_achievement" in body:
        yaml_updates.setdefault("world_lore", {})["habitat"] = body["signature_achievement"]

    if "portrait" in body:
        yaml_updates["portrait"] = body["portrait"]

    return yaml_updates


async def _refresh_live_queen_identity(manager, queen_id: str, profile: dict[str, Any]) -> None:
    """Re-materialize the queen identity for every live session of ``queen_id``.

    A running queen bakes its name/title/core-traits into the *static* portion
    of its system prompt when the session is created. A profile edit only
    rewrites ``profile.yaml`` on disk, so without this refresh the queen keeps
    answering with its old identity (and the conversation header stays stale)
    until the app restarts and the session is resumed from disk.

    Re-running ``materialize_queen_identity`` rebuilds ``phase_state``'s identity
    prompt — picked up on the next AgentLoop turn — and re-publishes
    ``QUEEN_IDENTITY_SELECTED`` so the conversation UI updates its header name.
    """
    from framework.server.queen_orchestrator import materialize_queen_identity

    for session in manager.list_sessions():
        if session.queen_name != queen_id or session.phase_state is None:
            continue
        try:
            await materialize_queen_identity(session, session.phase_state, profile, session.event_bus)
        except Exception:
            logger.warning(
                "Failed to refresh live queen identity for session %s",
                session.id,
                exc_info=True,
            )


async def handle_update_profile(request: web.Request) -> web.Response:
    """PATCH /api/queen/{queen_id}/profile — update queen profile fields."""
    queen_id = request.match_info["queen_id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)

    yaml_updates = _reverse_transform_for_yaml(body)
    if not yaml_updates:
        return web.json_response({"error": "No valid fields to update"}, status=400)

    try:
        updated = update_queen_profile(queen_id, yaml_updates)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    schedule_push("queen_profile", queen_id)
    await _refresh_live_queen_identity(request.app["manager"], queen_id, updated)
    api_profile = _transform_profile_for_api(updated)
    return web.json_response({"id": queen_id, "has_avatar": _has_avatar(queen_id), **api_profile})


async def handle_initialize_preferences(request: web.Request) -> web.Response:
    """POST /api/queen/initialize-preferences — materialize queens from /me preferences.

    Called by Electron main after the runtime is healthy but BEFORE the
    "ready" event is broadcast to the renderer, so by the time the
    renderer's first ``GET /api/queen/profiles`` call lands every
    preferenced queen has its ``profile.yaml`` on disk with the user's
    custom name/bio/portrait already applied.

    Body: ``{"queens": {<queen_id>: {"n": <name>, "bio": <traits>, "p": <portrait>}}}``

    Idempotent and self-healing. A queen is overwritten with /me overrides
    iff the on-disk profile is either absent OR bit-for-bit identical to
    the hardcoded :data:`DEFAULT_QUEENS` entry — meaning a session route
    lazily materialized the default before this call arrived. Any real
    user edit (even a single field) is preserved untouched.
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    queens = body.get("queens")
    if not isinstance(queens, dict):
        return web.json_response({"error": "Body must include 'queens' map"}, status=400)

    initialized: list[str] = []
    skipped: list[str] = []
    for queen_id, override in queens.items():
        if not isinstance(override, dict):
            continue
        name = override.get("n")
        if not isinstance(name, str) or not name:
            continue
        if queen_id not in DEFAULT_QUEENS:
            skipped.append(queen_id)
            continue
        profile_path = QUEENS_DIR / queen_id / "profile.yaml"
        if profile_path.exists():
            # File exists doesn't mean "user customized" — a session route
            # (load_queen_profile) may have lazily materialized the
            # hardcoded default just before we got here, in which case the
            # /me overrides still need to be applied. Compare against the
            # persona-only default (what materialize writes; capability
            # config is stripped from profile.yaml): equal == untouched
            # default → fall through and overwrite; differs == real user
            # edit → skip.
            try:
                on_disk = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                on_disk = None
            if on_disk != default_profile_persona(queen_id):
                skipped.append(queen_id)
                continue
        materialized = _materialize_default_queen(queen_id)
        if materialized is None:
            skipped.append(queen_id)
            continue
        yaml_updates: dict[str, Any] = {"name": name}
        bio = override.get("bio")
        if isinstance(bio, str) and bio:
            yaml_updates["core_traits"] = bio
        portrait = override.get("p")
        if isinstance(portrait, dict):
            yaml_updates["portrait"] = portrait
        try:
            update_queen_profile(queen_id, yaml_updates)
            initialized.append(queen_id)
        except Exception:
            logger.warning("Failed to initialize queen %s from preferences", queen_id, exc_info=True)
            skipped.append(queen_id)

    return web.json_response({"initialized": initialized, "skipped": skipped})


async def handle_queen_session(request: web.Request) -> web.Response:
    """POST /api/queen/{queen_id}/session -- get or create a persistent session.

    If this queen already has a live session, return it.
    If not, find the most recent cold session and resume it.
    If no session exists at all, create a fresh one.

    The session is bound to this queen identity -- ``session.queen_name``
    is set so storage routes to ``~/.hive/queens/{queen_id}/sessions/``.
    """
    from framework.server.session_manager import SessionManager

    queen_id = request.match_info["queen_id"]
    manager: SessionManager = request.app["manager"]

    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    body = await request.json() if request.can_read_body else {}
    initial_prompt = body.get("initial_prompt")
    initial_phase = body.get("initial_phase")

    # 1. Check for an existing live DM session bound to this queen.
    # Skip colony sessions: a colony forked from this queen also carries
    # queen_name == queen_id, but it has a worker loaded (colony_id /
    # worker_path set) and is the colony's chat, not the queen's DM.
    # When multiple DM sessions for this queen are live at once (e.g. the
    # user created a new session, then navigated away and back), return
    # the most recently loaded one so we don't resurrect a stale older
    # session ahead of a freshly created one.
    live_matches = [
        s
        for s in manager.list_sessions()
        if s.queen_name == queen_id and s.colony_id is None and s.worker_path is None and not getattr(s, "superseded_by", None)
    ]
    if live_matches:
        latest = max(live_matches, key=lambda s: s.loaded_at)
        return web.json_response(
            {
                "session_id": latest.id,
                "queen_id": queen_id,
                "status": "live",
            }
        )

    # 2. Find the most recent cold DM session for this queen and resume it.
    # The DM vs colony-queen split is structural — colony overseer sessions
    # live under ``colonies/<c>/queens/<q>/sessions/<sid>/``, so we don't
    # have to filter them out by metadata anymore. ``colony_fork: true``
    # marker is still skipped (it tags fork duplicates).
    from framework.config import queen_sessions_dir as _queen_sessions_dir

    queen_sessions_dir = _queen_sessions_dir(queen_id)
    resume_from: str | None = None
    if queen_sessions_dir.exists():
        try:
            # Newest-*created* first. Session dirs are named
            # ``session_YYYYMMDD_HHMMSS_<hash>``, so a lexicographic sort on
            # the name is a creation-time sort — total and deterministic.
            # ``st_mtime`` was wrong here: events.jsonl is a direct child of
            # the session dir and is rewritten on every bit of activity, so
            # mtime tracks *last activity* — re-opening or any late write to
            # an older session would resurrect it ahead of a newer one.
            candidates = sorted(
                (d for d in queen_sessions_dir.iterdir() if d.is_dir()),
                key=lambda p: p.name,
                reverse=True,
            )
            for candidate in candidates:
                meta_path = candidate / "meta.json"
                meta: dict = {}
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        meta = {}
                # Skip colony-fork duplicates and sessions retired by a
                # task_create(new_session=true) fork — the successor
                # session is the one to resume.
                if meta.get("colony_fork") or meta.get("superseded_by"):
                    continue
                resume_from = candidate.name
                break
        except OSError:
            pass

    # 3. Create (or resume) the session, pre-bound to this queen
    if resume_from:
        session = await _create_bound_queen_session(
            manager,
            queen_id,
            initial_prompt=initial_prompt,
            initial_phase=initial_phase,
            resume_from=resume_from,
        )
        status = "resumed"
    else:
        session = await manager.create_session(
            initial_prompt=initial_prompt,
            queen_name=queen_id,
            initial_phase=initial_phase,
        )
        status = "created"

    return web.json_response(
        {
            "session_id": session.id,
            "queen_id": queen_id,
            "status": status,
        }
    )


async def handle_select_queen_session(request: web.Request) -> web.Response:
    """POST /api/queen/{queen_id}/session/select -- resume a specific queen session."""
    queen_id = request.match_info["queen_id"]
    manager = request.app["manager"]

    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    body = await request.json() if request.can_read_body else {}
    target_session_id = body.get("session_id")
    if not isinstance(target_session_id, str) or not target_session_id.strip():
        return web.json_response({"error": "session_id is required"}, status=400)
    target_session_id = target_session_id.strip()

    if not _session_belongs_to_queen(manager, target_session_id, queen_id):
        return web.json_response(
            {"error": f"Session '{target_session_id}' does not belong to queen '{queen_id}'"},
            status=404,
        )

    # Follow the supersession chain: a session forked via
    # task_create(new_session=true) is retired. Resolve forward to the
    # final successor so selecting a retired session in history lands the
    # user on the session that actually continues the work — never
    # re-animates a stopped one.
    seen: set[str] = {target_session_id}
    chain_meta = _read_queen_session_meta(queen_id, target_session_id)
    while isinstance(chain_meta.get("superseded_by"), str):
        successor = chain_meta["superseded_by"]
        if successor in seen:
            break  # defensive: cycle guard
        seen.add(successor)
        target_session_id = successor
        chain_meta = _read_queen_session_meta(queen_id, successor)

    # Colony overseer sessions are never adopted by the queen DM page:
    # resuming one without its colony binding used to materialize a
    # duplicate empty session dir under the queen DM tree (blank-history
    # bug). Hand the colony binding back so the client routes to the
    # colony page, which owns resuming this session.
    live_session = manager.get_session(target_session_id)
    if live_session is not None:
        if live_session.colony_id:
            return web.json_response(
                {
                    "session_id": live_session.id,
                    "queen_id": queen_id,
                    "status": "colony",
                    "colony_id": live_session.colony_id,
                }
            )
        return web.json_response(
            {
                "session_id": live_session.id,
                "queen_id": queen_id,
                "status": "live",
            }
        )

    from framework.server.session_manager import _derive_resume_colony_id

    resident_colony_id = _derive_resume_colony_id(target_session_id)
    if resident_colony_id:
        return web.json_response(
            {
                "session_id": target_session_id,
                "queen_id": queen_id,
                "status": "colony",
                "colony_id": resident_colony_id,
            }
        )

    meta = _read_queen_session_meta(queen_id, target_session_id)
    agent_path = meta.get("agent_path")
    # Colony resume (agent loaded) → "colony".
    # Standalone queen resume → "independent" (DM mode).
    initial_phase = "colony" if agent_path else "independent"
    session = await _create_bound_queen_session(
        manager,
        queen_id,
        initial_phase=initial_phase,
        resume_from=target_session_id,
    )
    return web.json_response(
        {
            "session_id": session.id,
            "queen_id": queen_id,
            "status": "resumed",
        }
    )


async def handle_new_queen_session(request: web.Request) -> web.Response:
    """POST /api/queen/{queen_id}/session/new -- create a fresh queen session."""
    from framework.tools.queen_lifecycle_tools import QUEEN_PHASES, normalize_legacy_phase

    queen_id = request.match_info["queen_id"]
    manager = request.app["manager"]

    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    if request.can_read_body:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Request body must be a JSON object"}, status=400)
    else:
        body = {}
    initial_prompt = body.get("initial_prompt")
    initial_phase = normalize_legacy_phase(body.get("initial_phase")) or "independent"
    # Bridge multi-session isolation: park_others=False keeps other live DM
    # sessions of this queen alive, so multiple groups / private chats can each
    # own an independent, concurrently-live session (routed by session_id).
    # Defaults to True to preserve the desktop single-active-session behavior.
    park_others = bool(body.get("park_others", True))
    if initial_phase not in QUEEN_PHASES:
        return web.json_response(
            {
                "error": f"Invalid initial_phase '{initial_phase}'",
                "valid": sorted(QUEEN_PHASES),
            },
            status=400,
        )

    # Park any previously-live DM sessions for this queen before minting a
    # fresh one. Without this, every click of "New Session" leaks a live
    # entry into manager._sessions and the session-switcher dropdown shows
    # duplicate "Live" badges for sessions whose UI has already moved on
    # (the SSE stream + URL follow the fresh session id; the old one is
    # orphaned in memory). Only DM sessions (no colony, no worker) are
    # parked — colony chats and worker-bound sessions are unrelated and
    # must not be touched. Predicate mirrors handle_queen_session's
    # live-DM detection above for symmetry.
    import shutil

    from framework.server.session_manager import _find_queen_session_dir
    from framework.storage import session_summary

    prior_live_dms = (
        [
            s
            for s in manager.list_sessions()
            if s.queen_name == queen_id and getattr(s, "colony_id", None) is None and getattr(s, "worker_path", None) is None
        ]
        if park_others
        else []
    )
    for prior in prior_live_dms:
        try:
            await manager.stop_session(prior.id)
        except Exception:
            # Don't fail the new-session create — leaking one prior is bad
            # but blocking the user from creating their requested session
            # is worse.
            logger.warning(
                "handle_new_queen_session: failed to stop prior live DM %s",
                prior.id,
                exc_info=True,
            )

        # If the prior session had zero messages, also delete its directory
        # so accidental double-clicks of New Session don't litter the
        # dropdown with empty ghosts. Sessions with any saved messages are
        # preserved on disk and remain navigable as "History".
        try:
            prior_dir = _find_queen_session_dir(prior.id)
            if prior_dir.exists():
                summary = session_summary.read_summary(prior_dir)
                msg_count = int((summary or {}).get("message_count") or 0)
                parts_dir = prior_dir / "conversations" / "parts"
                if msg_count == 0 and not parts_dir.exists():
                    shutil.rmtree(prior_dir, ignore_errors=True)
        except Exception:
            logger.warning(
                "handle_new_queen_session: empty-session cleanup failed for %s",
                prior.id,
                exc_info=True,
            )

    session = await manager.create_session(
        initial_prompt=initial_prompt,
        queen_name=queen_id,
        initial_phase=initial_phase,
        # Set only by the desktop's CRM doors ("Set up my CRM" / "Configure").
        # Nothing else in this request distinguishes a setup conversation: the
        # CRM's host queen is also the default queen and the auto-selection
        # fallback, so most sessions that reach here with `queen_growth` are
        # ordinary chats.
        crm_setup=bool(body.get("crm_setup")),
    )
    return web.json_response(
        {
            "session_id": session.id,
            "queen_id": queen_id,
            "status": "created",
        }
    )


MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB max after compression
# JPEG/PNG only — the cloud-sync backend sniffs magic bytes and rejects
# anything else (see hive-backend's queens.controller.ts/sniffImageMime),
# so accepting WebP locally would create avatars that silently fail to sync.
_ALLOWED_AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}


async def handle_upload_avatar(request: web.Request) -> web.Response:
    """POST /api/queen/{queen_id}/avatar — upload queen avatar image.

    Accepts multipart/form-data with a single file field named 'avatar'.
    Stores as avatar.{ext} in the queen's profile directory.
    """
    from framework.config import QUEENS_DIR

    queen_id = request.match_info["queen_id"]
    queen_dir = QUEENS_DIR / queen_id
    if not (queen_dir / "profile.yaml").exists():
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "avatar":
        return web.json_response({"error": "Expected a file field named 'avatar'"}, status=400)

    content_type = field.headers.get("Content-Type", "application/octet-stream")
    # Also check by content_type from the field
    if hasattr(field, "content_type"):
        content_type = field.content_type or content_type

    ext = _ALLOWED_AVATAR_TYPES.get(content_type)
    if not ext:
        return web.json_response(
            {"error": f"Unsupported image type: {content_type}. Use JPEG or PNG."},
            status=400,
        )

    # Read the file data with size limit
    data = bytearray()
    while True:
        chunk = await field.read_chunk(8192)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_AVATAR_BYTES:
            return web.json_response(
                {"error": f"Image too large. Maximum size is {MAX_AVATAR_BYTES // 1024 // 1024} MB."},
                status=400,
            )

    if not data:
        return web.json_response({"error": "Empty file"}, status=400)

    # Remove any existing avatar files
    for existing in queen_dir.glob("avatar.*"):
        existing.unlink(missing_ok=True)

    # Write the new avatar
    avatar_path = queen_dir / f"avatar{ext}"
    avatar_path.write_bytes(data)

    logger.info("Avatar uploaded for queen %s: %s (%d bytes)", queen_id, avatar_path.name, len(data))
    schedule_push("queen_avatar", queen_id)
    return web.json_response({"avatar_url": f"/api/queen/{queen_id}/avatar", "has_avatar": True})


async def handle_get_avatar(request: web.Request) -> web.Response:
    """GET /api/queen/{queen_id}/avatar — serve queen avatar image."""
    from framework.config import QUEENS_DIR

    queen_id = request.match_info["queen_id"]
    queen_dir = QUEENS_DIR / queen_id

    # Find avatar file with any supported extension
    for ext in _ALLOWED_AVATAR_TYPES.values():
        avatar_path = queen_dir / f"avatar{ext}"
        if avatar_path.exists():
            return web.FileResponse(
                avatar_path,
                headers={"Cache-Control": "public, max-age=3600"},
            )

    return web.json_response({"error": "No avatar found"}, status=404)


async def handle_delete_avatar(request: web.Request) -> web.Response:
    """DELETE /api/queen/{queen_id}/avatar — remove the queen's avatar.

    Idempotent — returns 200 even when nothing was on disk. ``schedule_push``
    fires regardless so the cloud row's ``avatar_deleted_at`` is set even if
    the local copy was already absent (e.g. user deleted on device A, then
    triggered delete again on device B before the pull tombstoned it).
    """
    from framework.config import QUEENS_DIR

    queen_id = request.match_info["queen_id"]
    queen_dir = QUEENS_DIR / queen_id
    removed = False
    if queen_dir.is_dir():
        for existing in queen_dir.glob("avatar.*"):
            existing.unlink(missing_ok=True)
            removed = True

    if removed:
        logger.info("Avatar deleted for queen %s", queen_id)
    schedule_push("queen_avatar", queen_id)
    return web.json_response({"has_avatar": False})


def register_routes(app: web.Application) -> None:
    """Register queen profile routes."""
    app.router.add_get("/api/queen/profiles", handle_list_profiles)
    app.router.add_get("/api/queen/{queen_id}/profile", handle_get_profile)
    app.router.add_patch("/api/queen/{queen_id}/profile", handle_update_profile)
    app.router.add_post("/api/queen/create", handle_create_queen)
    app.router.add_post("/api/queen/initialize-preferences", handle_initialize_preferences)
    app.router.add_post("/api/queen/{queen_id}/avatar", handle_upload_avatar)
    app.router.add_get("/api/queen/{queen_id}/avatar", handle_get_avatar)
    app.router.add_delete("/api/queen/{queen_id}/avatar", handle_delete_avatar)
    app.router.add_post("/api/queen/{queen_id}/session", handle_queen_session)
    app.router.add_post("/api/queen/{queen_id}/session/select", handle_select_queen_session)
    app.router.add_post("/api/queen/{queen_id}/session/new", handle_new_queen_session)
