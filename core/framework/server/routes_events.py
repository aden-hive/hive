"""SSE event streaming route."""

import asyncio
import logging

from aiohttp import web

from framework.runtime.event_bus import EventType
from framework.server.agent_manager import AgentManager
from framework.server.sse import SSEResponse

logger = logging.getLogger(__name__)

# Default event types streamed to clients
DEFAULT_EVENT_TYPES = [
    EventType.CLIENT_OUTPUT_DELTA,
    EventType.CLIENT_INPUT_REQUESTED,
    EventType.LLM_TEXT_DELTA,
    EventType.TOOL_CALL_STARTED,
    EventType.TOOL_CALL_COMPLETED,
    EventType.EXECUTION_STARTED,
    EventType.EXECUTION_COMPLETED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_PAUSED,
    EventType.NODE_LOOP_STARTED,
    EventType.NODE_LOOP_ITERATION,
    EventType.NODE_LOOP_COMPLETED,
    EventType.EDGE_TRAVERSED,
    EventType.GOAL_PROGRESS,
]

# Keepalive interval in seconds
KEEPALIVE_INTERVAL = 15.0


def _parse_event_types(query_param: str | None) -> list[EventType]:
    """Parse comma-separated event type names into EventType values.

    Falls back to DEFAULT_EVENT_TYPES if param is empty or invalid.
    """
    if not query_param:
        return DEFAULT_EVENT_TYPES

    result = []
    for name in query_param.split(","):
        name = name.strip()
        try:
            result.append(EventType(name))
        except ValueError:
            logger.warning(f"Unknown event type filter: {name}")

    return result or DEFAULT_EVENT_TYPES


async def handle_events(request: web.Request) -> web.StreamResponse:
    """GET /api/agents/{agent_id}/events — SSE event stream.

    Query params:
        types: Comma-separated event type names to filter (optional).
    """
    manager: AgentManager = request.app["manager"]
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not slot.runtime:
        return web.json_response({"error": "Agent runtime not started"}, status=503)

    event_bus = slot.runtime.event_bus
    event_types = _parse_event_types(request.query.get("types"))

    # Per-client buffer queue
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    async def on_event(event) -> None:
        """Push event dict into queue; drop if full."""
        try:
            queue.put_nowait(event.to_dict())
        except asyncio.QueueFull:
            pass  # Drop oldest-undelivered; client will catch up

    # Subscribe to EventBus
    sub_id = event_bus.subscribe(
        event_types=event_types,
        handler=on_event,
    )

    sse = SSEResponse()
    await sse.prepare(request)

    try:
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                await sse.send_event(data)
            except TimeoutError:
                await sse.send_keepalive()
            except ConnectionResetError:
                break
    except asyncio.CancelledError:
        pass
    finally:
        event_bus.unsubscribe(sub_id)
        logger.debug(f"SSE client disconnected from agent '{agent_id}'")

    return sse.response


def register_routes(app: web.Application) -> None:
    """Register SSE event streaming route."""
    app.router.add_get("/api/agents/{agent_id}/events", handle_events)
