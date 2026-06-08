"""REST routes for task lists.

  GET /api/tasks/{task_list_id}                     -- snapshot of one list
  GET /api/colonies/{colony_id}/task_lists          -- helper for colony view
  GET /api/sessions/{session_id}/task_list_id       -- helper for session view

The task_list_id segment uses URL-encoded colons (``colony%3Aabc`` /
``session%3Aagent%3Asess``); aiohttp decodes them automatically.
"""

from __future__ import annotations

import logging

from aiohttp import web

from framework.tasks import get_task_store
from framework.tasks.scoping import (
    colony_task_list_id,
    session_task_list_id,
)

logger = logging.getLogger(__name__)


async def handle_get_task_list(request: web.Request) -> web.Response:
    raw = request.match_info.get("task_list_id", "")
    if not raw:
        return web.json_response({"error": "task_list_id required"}, status=400)

    store = get_task_store()
    if not await store.list_exists(raw):
        return web.json_response(
            {"error": f"Task list {raw!r} not found", "task_list_id": raw, "tasks": []},
            status=404,
        )

    meta = await store.get_meta(raw)
    records = await store.list_tasks(raw)
    return web.json_response(
        {
            "task_list_id": raw,
            "role": meta.role.value if meta else "session",
            "meta": meta.model_dump(mode="json") if meta else None,
            "tasks": [
                {
                    "id": r.id,
                    "subject": r.subject,
                    "description": r.description,
                    "active_form": r.active_form,
                    "owner": r.owner,
                    "status": r.status.value,
                    "blocks": list(r.blocks),
                    "blocked_by": list(r.blocked_by),
                    "metadata": dict(r.metadata),
                    "created_at": r.created_at,
                    "updated_at": r.updated_at,
                }
                for r in records
            ],
        }
    )


async def handle_get_colony_task_lists(request: web.Request) -> web.Response:
    """Return template_task_list_id and queen_session_task_list_id for a colony."""
    colony_id = request.match_info.get("colony_id", "")
    if not colony_id:
        return web.json_response({"error": "colony_id required"}, status=400)

    template_id = colony_task_list_id(colony_id)
    # Queen's session list — the queen-of-colony's session_id == the
    # browser-facing colony session id. The frontend already knows that
    # value; we surface what we have on disk for completeness.
    queen_session_id = request.query.get("queen_session_id")
    queen_list_id = session_task_list_id("queen", queen_session_id) if queen_session_id else None
    return web.json_response(
        {
            "template_task_list_id": template_id,
            "queen_session_task_list_id": queen_list_id,
        }
    )


async def handle_get_session_task_list_id(request: web.Request) -> web.Response:
    """Return task_list_id and picked_up_from for a session.

    The session_id is the queen's session id or a worker's session id;
    both follow the same path. The agent_id is read from the request query
    (passed by the frontend, which already knows which agent the session
    belongs to).
    """
    session_id = request.match_info.get("session_id", "")
    agent_id = request.query.get("agent_id", "queen")
    if not session_id:
        return web.json_response({"error": "session_id required"}, status=400)

    task_list_id = session_task_list_id(agent_id, session_id)
    store = get_task_store()
    exists = await store.list_exists(task_list_id)
    return web.json_response(
        {
            "task_list_id": task_list_id if exists else None,
            "picked_up_from": None,
        }
    )


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/tasks/{task_list_id}", handle_get_task_list)
    app.router.add_get("/api/colonies/{colony_id}/task_lists", handle_get_colony_task_lists)
    app.router.add_get("/api/sessions/{session_id}/task_list_id", handle_get_session_task_list_id)
