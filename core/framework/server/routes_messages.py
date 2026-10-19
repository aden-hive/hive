"""Home-message bootstrap routes.

- POST /api/messages/classify -- classify a user prompt and return the
  matched queen_id.  The frontend then creates a fresh queen session via
  /api/queen/{queen_id}/session/new and sends the first message through
  the normal chat path.
- POST /api/messages/classify-colony -- classify a user prompt into a queen
  *and* a colony name in a single LLM call. The frontend then spins up a
  colony session (initial_phase=colony) seeded with the prompt as its goal.
"""

from aiohttp import web

from framework.agents.queen.queen_profiles import (
    ensure_default_queens,
    select_queen,
    select_queen_and_colony,
)


async def handle_classify_message(request: web.Request) -> web.Response:
    """POST /api/messages/classify -- classify a home prompt to a queen_id."""
    import traceback as _tb

    try:
        manager = request.app["manager"]
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


async def handle_classify_colony(request: web.Request) -> web.Response:
    """POST /api/messages/classify-colony -- pick a queen AND a colony name.

    One LLM call (``select_queen_and_colony``). Returns both so the frontend
    can create a colony session in a single round-trip instead of a queen DM.
    """
    import traceback as _tb

    try:
        manager = request.app["manager"]
        body = await request.json() if request.can_read_body else {}
        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            return web.json_response({"error": "message is required"}, status=400)
        message = message.strip()

        # Active roster from the frontend (queens not decommissioned by the
        # user). Missing/malformed → None → selector uses the full catalog.
        raw_ids = body.get("active_queen_ids")
        active_queen_ids = [qid for qid in raw_ids if isinstance(qid, str)] if isinstance(raw_ids, list) else None

        ensure_default_queens()
        llm = manager.build_llm()
        selection = await select_queen_and_colony(message, llm, active_queen_ids=active_queen_ids)

        return web.json_response(
            {
                "queen_id": selection.queen_id,
                "colony_name": selection.colony_name,
                "reason": selection.reason,
            }
        )
    except Exception as e:
        _tb.print_exc()
        import logging

        logging.getLogger(__name__).exception("DETAILED error in handle_classify_colony: %s", e)
        return web.json_response({"error": str(e)}, status=500)


def register_routes(app: web.Application) -> None:
    """Register home-message routes."""
    app.router.add_post("/api/messages/classify", handle_classify_message)
    app.router.add_post("/api/messages/classify-colony", handle_classify_colony)
