"""Queen identity profile routes.

- GET    /api/queen/profiles                — list all queen profiles (id, name, title)
- GET    /api/queen/{queen_id}/profile      — get full queen profile
- PATCH  /api/queen/{queen_id}/profile      — update queen profile fields
"""

import logging

from aiohttp import web

from framework.agents.queen.queen_profiles import (
    ensure_default_queens,
    list_queens,
    load_queen_profile,
    update_queen_profile,
)

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


def register_routes(app: web.Application) -> None:
    """Register queen profile routes."""
    app.router.add_get("/api/queen/profiles", handle_list_profiles)
    app.router.add_get("/api/queen/{queen_id}/profile", handle_get_profile)
    app.router.add_patch("/api/queen/{queen_id}/profile", handle_update_profile)
