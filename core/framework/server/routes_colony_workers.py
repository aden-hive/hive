"""Colony worker inspection routes.

These expose per-spawned-worker data (identified by worker_id) so the
frontend can render a colony-workers sidebar analogous to the queen
profile panel. Distinct from ``routes_workers.py``, which deals with
*graph nodes* inside a worker definition rather than live worker
instances.

- GET /api/sessions/{session_id}/workers  -- list live + completed workers
"""

import logging

from aiohttp import web

from framework.server.app import resolve_session

logger = logging.getLogger(__name__)


def _worker_info_to_dict(info) -> dict:
    """Serialize a WorkerInfo dataclass to a JSON-friendly dict."""
    result_dict = None
    if info.result is not None:
        r = info.result
        result_dict = {
            "status": r.status,
            "summary": r.summary,
            "error": r.error,
            "tokens_used": r.tokens_used,
            "duration_seconds": r.duration_seconds,
        }
    return {
        "worker_id": info.id,
        "task": info.task,
        "status": str(info.status),
        "started_at": info.started_at,
        "result": result_dict,
    }


async def handle_list_workers(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/workers -- list workers in a session's colony."""
    session, err = resolve_session(request)
    if err:
        return err

    runtime = session.colony_runtime
    if runtime is None:
        return web.json_response({"workers": []})

    workers = [_worker_info_to_dict(info) for info in runtime.list_workers()]
    return web.json_response({"workers": workers})


def register_routes(app: web.Application) -> None:
    """Register colony worker routes."""
    app.router.add_get("/api/sessions/{session_id}/workers", handle_list_workers)
