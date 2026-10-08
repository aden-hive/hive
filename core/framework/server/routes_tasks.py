"""REST routes for task lists.

GET  /api/sessions/{session_id}/tasks                  -- snapshot of one list
POST /api/sessions/{session_id}/tasks/unarchive        -- restore archived tasks
POST /api/sessions/{session_id}/tasks/clear-completed  -- archive completed tasks
"""

from __future__ import annotations

import logging

from aiohttp import web

from framework.tasks import get_task_store
from framework.tasks.events import _serialize_record, emit_task_updated

logger = logging.getLogger(__name__)


async def handle_get_task_list(request: web.Request) -> web.Response:
    raw = request.match_info.get("session_id", "")
    if not raw:
        return web.json_response({"error": "session_id required"}, status=400)

    store = get_task_store()
    if not await store.list_exists(raw):
        return web.json_response(
            {"error": f"Task list for session {raw!r} not found", "session_id": raw, "tasks": []},
            status=404,
        )

    # Lazily sweep stale in_progress tasks → abandoned before serializing,
    # so the client always sees the post-sweep view. Emits task_updated SSE
    # for each flipped record so any other open viewers stay consistent.
    # Cheap (no-op when nothing is stale, single doc rewrite when something
    # is) — we don't need a separate background scheduler for this.
    try:
        swept = await store.sweep_idle_tasks(raw)
        for record in swept:
            await emit_task_updated(session_id=raw, record=record, fields=["status"])
    except Exception:
        logger.debug("sweep_idle_tasks failed for %s", raw, exc_info=True)

    meta = await store.get_meta(raw)
    records = await store.list_tasks(raw)
    return web.json_response(
        {
            "session_id": raw,
            "role": meta.role if meta else "session",
            "meta": meta.model_dump(mode="json") if meta else None,
            "tasks": [_serialize_record(r) for r in records],
        }
    )


async def _read_json_body(request: web.Request) -> dict:
    """Best-effort JSON body — an empty/malformed body is treated as {}."""
    if not request.can_read_body:
        return {}
    try:
        parsed = await request.json()
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


async def handle_unarchive_task_list(request: web.Request) -> web.Response:
    """Restore archived tasks to their pre-archive status (History "remove").

    Body ``{"task_ids": [int, ...]}``. Each restored task is put back
    where it was before archiving and re-enters the agent's working set;
    a ``task_updated`` event fires per restored record so open panels move
    it back into the live plan. Missing/non-archived ids are ignored.
    """
    raw = request.match_info.get("session_id", "")
    if not raw:
        return web.json_response({"error": "session_id required"}, status=400)

    body = await _read_json_body(request)
    task_ids = body.get("task_ids")
    if not isinstance(task_ids, list) or not all(isinstance(i, int) for i in task_ids):
        return web.json_response(
            {"error": "task_ids must be a list of integers", "session_id": raw},
            status=400,
        )

    store = get_task_store()
    restored_ids = await store.unarchive_tasks(raw, task_ids)
    if restored_ids:
        ids = set(restored_ids)
        records = [r for r in await store.list_tasks(raw) if r.id in ids]
        for record in records:
            await emit_task_updated(session_id=raw, record=record, fields=["status"])
    return web.json_response({"session_id": raw, "restored": restored_ids})


async def handle_clear_completed_tasks(request: web.Request) -> web.Response:
    """Archive every completed task on the plan (the "Clear done" button).

    Moves finished tasks out of the active plan and into History — the same
    non-destructive archive the agent does via ``task_update``
    status="archived", so they can be restored from History. A
    ``task_updated`` event fires per archived record so open panels drop them
    from the live plan immediately. No-op (empty ``archived``) when nothing is
    completed.
    """
    raw = request.match_info.get("session_id", "")
    if not raw:
        return web.json_response({"error": "session_id required"}, status=400)

    store = get_task_store()
    archived = await store.archive_completed_tasks(raw)
    for record in archived:
        await emit_task_updated(session_id=raw, record=record, fields=["status"])
    return web.json_response({"session_id": raw, "archived": [r.id for r in archived]})


def register_routes(app: web.Application) -> None:
    app.router.add_get("/api/sessions/{session_id}/tasks", handle_get_task_list)
    app.router.add_post("/api/sessions/{session_id}/tasks/unarchive", handle_unarchive_task_list)
    app.router.add_post(
        "/api/sessions/{session_id}/tasks/clear-completed",
        handle_clear_completed_tasks,
    )
