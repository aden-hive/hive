"""Home-message bootstrap routes.

- POST /api/messages/new -- classify a message, create a fresh queen session
"""

from aiohttp import web

from framework.agents.queen.queen_profiles import ensure_default_queens, select_queen
from framework.host.event_bus import AgentEvent, EventType
from framework.server.routes_queens import _stop_live_sessions


async def handle_new_message(request: web.Request) -> web.Response:
    """POST /api/messages/new -- bootstrap a fresh queen DM from a home prompt."""
    manager = request.app["manager"]
    body = await request.json() if request.can_read_body else {}
    message = body.get("message")
    if not isinstance(message, str) or not message.strip():
        return web.json_response({"error": "message is required"}, status=400)
    message = message.strip()

    ensure_default_queens()

    # Build LLM for classification
    llm = manager.build_llm()

    # Run queen selection - this is the slow part we can't avoid
    queen_id = await select_queen(message, llm)

    await _stop_live_sessions(manager)

    # Create session with pre-bound queen
    session = await manager.create_session(
        initial_prompt=message,
        queen_name=queen_id,
        initial_phase="independent",
    )

    await session.event_bus.publish(
        AgentEvent(
            type=EventType.CLIENT_INPUT_RECEIVED,
            stream_id="queen",
            node_id="queen",
            execution_id=session.id,
            data={"content": message, "image_count": 0},
        )
    )
    return web.json_response(
        {
            "queen_id": queen_id,
            "session_id": session.id,
        }
    )


def register_routes(app: web.Application) -> None:
    """Register home-message routes."""
    app.router.add_post("/api/messages/new", handle_new_message)
