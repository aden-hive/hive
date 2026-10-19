"""The server's recent log, for the dashboard's Runtime logs drawer.

GET /api/runtime-logs?after=<seq>&boot=<boot>

Returns ``{"boot": ..., "entries": [{"seq", "stream", "text"}, ...]}`` with
the lines after ``after``. A ``boot`` from an earlier server process (or
none) gets the whole buffer, since its sequence numbers no longer apply.
The drawer polls this rather than holding a stream open: every open stream
takes one of the browser's few same-origin connections.
"""

from __future__ import annotations

from aiohttp import web

from framework.observability.logging import recent_logs

PATH = "/api/runtime-logs"


async def handle_runtime_logs(request: web.Request) -> web.Response:
    try:
        after = int(request.query.get("after", "0"))
    except ValueError:
        after = 0
    if request.query.get("boot") != recent_logs.boot:
        after = 0
    return web.json_response({"boot": recent_logs.boot, "entries": recent_logs.since(after)})


def register_routes(app: web.Application) -> None:
    app.router.add_get(PATH, handle_runtime_logs)
