"""Read-only views of the queens run by Claude Code (``queen_mail.claude_code``), for the dashboard.

- GET /api/claude-code-queens -- each one, with her conversations
- GET /api/claude-code-queens/{queen_id}/conversations/{session_id} -- what was said and done in one
"""

from __future__ import annotations

from aiohttp import web


def _mail(request: web.Request):
    return request.app["manager"].queen_mail


async def handle_list(request: web.Request) -> web.Response:
    from framework.config import get_queen_mail_config

    config = get_queen_mail_config()
    mail = _mail(request)
    if not config.enabled or mail is None:
        return web.json_response({"queens": []})
    queens = [
        {
            "id": c.queen_id,
            "name": c.name,
            "title": c.title,
            "permission_mode": c.permission_mode,
            # How she pays (never the key itself): "api_key", or "subscription" at the user's own risk.
            "auth": c.auth,
            "model": c.model,
            "conversations": await mail.claude_code.conversations(c.queen_id),
        }
        for c in config.claude_code.values()
    ]
    return web.json_response({"queens": queens})


async def handle_transcript(request: web.Request) -> web.Response:
    mail = _mail(request)
    queen_id, session_id = request.match_info["queen_id"], request.match_info["session_id"]
    entries = await mail.claude_code.transcript(queen_id, session_id) if mail is not None else None
    if entries is None:
        return web.json_response({"error": f"No conversation {session_id!r} of {queen_id!r}"}, status=404)
    return web.json_response({"entries": entries})


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/claude-code-queens", handle_list)
    app.router.add_get("/api/claude-code-queens/{queen_id}/conversations/{session_id}", handle_transcript)
