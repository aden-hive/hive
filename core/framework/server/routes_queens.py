"""Queen identity profile routes.

- GET    /api/queen/profiles                -- list all queen profiles (id, name, title)
- GET    /api/queen/{queen_id}/profile      -- get full queen profile
- PATCH  /api/queen/{queen_id}/profile      -- update queen profile fields
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

from aiohttp import web

from framework.agents.queen.queen_profiles import (
    ensure_default_queens,
    list_queens,
    load_queen_profile,
    update_queen_profile,
)
from framework.config import QUEENS_DIR

logger = logging.getLogger(__name__)


def _read_queen_session_meta(queen_id: str, session_id: str) -> dict[str, Any]:
    """Return persisted metadata for a queen session when available."""
    session_dir = QUEENS_DIR / queen_id / "sessions" / session_id
    meta_path = session_dir / "meta.json"
    if not meta_path.exists():
        return {}
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _session_belongs_to_queen(manager, session_id: str, queen_id: str) -> bool:
    """Check live or persisted ownership for a queen session."""
    live_session = manager.get_session(session_id)
    if live_session is not None:
        return live_session.queen_name == queen_id

    from framework.server.session_manager import _find_queen_session_dir

    session_dir = _find_queen_session_dir(session_id)
    return (
        session_dir.exists()
        and session_dir.is_dir()
        and session_dir.parent.name == "sessions"
        and session_dir.parent.parent.name == queen_id
    )


async def _create_bound_queen_session(
    manager,
    queen_id: str,
    *,
    initial_prompt: str | None = None,
    initial_phase: str | None = None,
    resume_from: str | None = None,
):
    """Create or resume a session that is explicitly bound to a queen."""
    agent_path = None
    if resume_from:
        meta = _read_queen_session_meta(queen_id, resume_from)
        candidate = meta.get("agent_path")
        if isinstance(candidate, str) and candidate:
            agent_path = candidate

    if agent_path:
        try:
            from framework.server.app import validate_agent_path

            resolved_agent_path = str(validate_agent_path(agent_path))
            return await manager.create_session_with_worker_colony(
                resolved_agent_path,
                queen_resume_from=resume_from,
                initial_prompt=initial_prompt,
                queen_name=queen_id,
                initial_phase=initial_phase,
            )
        except Exception:
            logger.debug(
                "Failed to restore worker-backed queen session %s for %s; falling back to queen-only",
                resume_from,
                queen_id,
                exc_info=True,
            )

    return await manager.create_session(
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
    return web.json_response({"id": queen_id, **api_profile})


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

    return yaml_updates


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

    api_profile = _transform_profile_for_api(updated)
    return web.json_response({"id": queen_id, **api_profile})


async def handle_queen_session(request: web.Request) -> web.Response:
    """POST /api/queen/{queen_id}/session -- get or create a persistent session.

    If this queen already has a live session, return it.
    If not, find the most recent cold session and resume it.
    If no session exists at all, create a fresh one.

    The session is bound to this queen identity -- ``session.queen_name``
    is set so storage routes to ``~/.hive/agents/queens/{queen_id}/sessions/``.
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

    # 1. Check for an existing live session bound to this queen.
    for session in manager.list_sessions():
        if session.queen_name == queen_id:
            return web.json_response(
                {
                    "session_id": session.id,
                    "queen_id": queen_id,
                    "status": "live",
                }
            )

    # 2. Find the most recent cold session for this queen and resume it.
    # IMPORTANT: skip sessions that don't belong in the queen DM:
    #   - ``colony_fork: true`` -- duplicates created by handle_colony_spawn
    #   - sessions bound to a currently-existing colony -- those are the
    #     colony's chat, not the queen's DM. A session whose agent_path
    #     points to a deleted colony is freed up and may be resumed.
    queen_sessions_dir = QUEENS_DIR / queen_id / "sessions"
    resume_from: str | None = None
    if queen_sessions_dir.exists():
        try:
            candidates = sorted(
                (d for d in queen_sessions_dir.iterdir() if d.is_dir()),
                key=lambda p: p.stat().st_mtime,
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
                if meta.get("colony_fork"):
                    continue
                # Skip sessions bound to an existing colony -- those are
                # colony chats, not queen DMs.
                bound_colony = meta.get("agent_path")
                if bound_colony:
                    from pathlib import Path as _P

                    if _P(bound_colony).is_dir():
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

    live_session = manager.get_session(target_session_id)
    if live_session is not None:
        return web.json_response(
            {
                "session_id": live_session.id,
                "queen_id": queen_id,
                "status": "live",
            }
        )

    meta = _read_queen_session_meta(queen_id, target_session_id)
    agent_path = meta.get("agent_path")
    initial_phase = None if agent_path else "independent"
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
    queen_id = request.match_info["queen_id"]
    manager = request.app["manager"]

    ensure_default_queens()
    try:
        load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)

    body = await request.json() if request.can_read_body else {}
    initial_prompt = body.get("initial_prompt")
    initial_phase = body.get("initial_phase") or "independent"

    session = await manager.create_session(
        initial_prompt=initial_prompt,
        queen_name=queen_id,
        initial_phase=initial_phase,
    )
    return web.json_response(
        {
            "session_id": session.id,
            "queen_id": queen_id,
            "status": "created",
        }
    )


MAX_AVATAR_BYTES = 2 * 1024 * 1024  # 2 MB max after compression
_ALLOWED_AVATAR_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
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
            {"error": f"Unsupported image type: {content_type}. Use JPEG, PNG, or WebP."},
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
    return web.json_response({"avatar_url": f"/api/queen/{queen_id}/avatar"})


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


def register_routes(app: web.Application) -> None:
    """Register queen profile routes."""
    app.router.add_get("/api/queen/profiles", handle_list_profiles)
    app.router.add_get("/api/queen/{queen_id}/profile", handle_get_profile)
    app.router.add_patch("/api/queen/{queen_id}/profile", handle_update_profile)
    app.router.add_post("/api/queen/{queen_id}/avatar", handle_upload_avatar)
    app.router.add_get("/api/queen/{queen_id}/avatar", handle_get_avatar)
    app.router.add_post("/api/queen/{queen_id}/session", handle_queen_session)
    app.router.add_post("/api/queen/{queen_id}/session/select", handle_select_queen_session)
    app.router.add_post("/api/queen/{queen_id}/session/new", handle_new_queen_session)
