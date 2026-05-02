"""Home-message bootstrap routes.

- POST /api/messages/classify -- classify a user prompt and return the
  matched queen_id.  The frontend then creates a fresh queen session via
  /api/queen/{queen_id}/session/new and sends the first message through
  the normal chat path.
"""

from aiohttp import web

from framework.agents.queen.queen_profiles import ensure_default_queens, select_queen
from framework.server.app import MANAGER_KEY


async def handle_classify_message(request: web.Request) -> web.Response:
    """POST /api/messages/classify -- classify a home prompt to a queen_id."""
    import traceback as _tb

    try:
        manager = request.app[MANAGER_KEY]
        body = await request.json() if request.can_read_body else {}
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return web.json_response({"error": "message is required"}, status=400)
        message = message.strip()

        ensure_default_queens()
        llm = manager.build_llm()
        queen_id = await select_queen(message, llm)

        return web.json_response({"queen_id": queen_id})
    except Exception as e:
        _tb.print_exc()
        import logging

        logging.getLogger(__name__).exception("DETAILED error in handle_classify_message: %s", e)
        return web.json_response({"error": str(e)}, status=500)


def register_routes(app: web.Application) -> None:
    """Register home-message routes."""
    app.router.add_post("/api/messages/classify", handle_classify_message)
