"""Queen identity profile routes.

- GET    /api/queen/profiles                -- list all queen profiles (id, name, title)
- GET    /api/queen/{queen_id}/profile      -- get full queen profile
- PATCH  /api/queen/{queen_id}/profile      -- update queen profile fields
- POST   /api/queen/{queen_id}/session      -- get or create a persistent session for a queen
"""

import json
import logging

from aiohttp import web

from framework.agents.queen.queen_profiles import (
    ensure_default_queens,
    list_queens,
    load_queen_profile,
    update_queen_profile,
)
from framework.config import QUEENS_DIR

logger = logging.getLogger(__name__)


async def handle_list_profiles(request: web.Request) -> web.Response:
    """GET /api/queen/profiles — list all queen profiles."""
    ensure_default_queens()
    queens = list_queens()
    return web.json_response({"queens": queens})


async def handle_get_profile(request: web.Request) -> web.Response:
    """GET /api/queen/{queen_id}/profile — get full queen profile."""
    queen_id = request.match_info["queen_id"]
    ensure_default_queens()
    try:
        profile = load_queen_profile(queen_id)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)
    return web.json_response({"id": queen_id, **profile})


async def handle_update_profile(request: web.Request) -> web.Response:
    """PATCH /api/queen/{queen_id}/profile — update queen profile fields."""
    queen_id = request.match_info["queen_id"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)
    if not isinstance(body, dict):
        return web.json_response({"error": "Body must be a JSON object"}, status=400)
    try:
        updated = update_queen_profile(queen_id, body)
    except FileNotFoundError:
        return web.json_response({"error": f"Queen '{queen_id}' not found"}, status=404)
    return web.json_response({"id": queen_id, **updated})


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
    #    Stop any live sessions bound to a *different* queen so only one
    #    queen is active at a time.
    other_sessions: list[str] = []
    for session in manager.list_sessions():
        if session.queen_name == queen_id:
            return web.json_response({
                "session_id": session.id,
                "queen_id": queen_id,
                "status": "live",
            })
        other_sessions.append(session.id)

    for sid in other_sessions:
        try:
            await manager.stop_session(sid)
        except Exception:
            logger.debug("Failed to stop session %s during queen switch", sid)

    # 2. Find the most recent cold session for this queen and resume it
    queen_sessions_dir = QUEENS_DIR / queen_id / "sessions"
    resume_from: str | None = None
    if queen_sessions_dir.exists():
        try:
            candidates = sorted(
                (d for d in queen_sessions_dir.iterdir() if d.is_dir()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                resume_from = candidates[0].name
        except OSError:
            pass

    # 3. Create (or resume) the session, pre-bound to this queen
    if resume_from:
        # Check if the cold session had a worker loaded
        meta_path = queen_sessions_dir / resume_from / "meta.json"
        agent_path = None
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                agent_path = meta.get("agent_path")
            except (json.JSONDecodeError, OSError):
                pass

        if agent_path:
            try:
                from framework.server.app import validate_agent_path

                agent_path = str(validate_agent_path(agent_path))
                session = await manager.create_session_with_worker_graph(
                    agent_path,
                    queen_resume_from=resume_from,
                    initial_prompt=initial_prompt,
                    queen_name=queen_id,
                    initial_phase=initial_phase,
                )
            except Exception:
                session = await manager.create_session(
                    queen_resume_from=resume_from,
                    initial_prompt=initial_prompt,
                    queen_name=queen_id,
                    initial_phase=initial_phase,
                )
        else:
            session = await manager.create_session(
                queen_resume_from=resume_from,
                initial_prompt=initial_prompt,
                queen_name=queen_id,
                initial_phase=initial_phase,
            )
        status = "resumed"
    else:
        session = await manager.create_session(
            initial_prompt=initial_prompt,
            queen_name=queen_id,
            initial_phase=initial_phase,
        )
        status = "created"

    return web.json_response({
        "session_id": session.id,
        "queen_id": queen_id,
        "status": status,
    })


def register_routes(app: web.Application) -> None:
    """Register queen profile routes."""
    app.router.add_get("/api/queen/profiles", handle_list_profiles)
    app.router.add_get("/api/queen/{queen_id}/profile", handle_get_profile)
    app.router.add_patch("/api/queen/{queen_id}/profile", handle_update_profile)
    app.router.add_post("/api/queen/{queen_id}/session", handle_queen_session)
