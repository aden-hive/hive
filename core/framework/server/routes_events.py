"""SSE event streaming route."""

import asyncio
import logging

from aiohttp import web

from framework.runtime.event_bus import EventType
from framework.server.app import resolve_session

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
    EventType.NODE_ACTION_PLAN,
    EventType.EDGE_TRAVERSED,
    EventType.GOAL_PROGRESS,
    EventType.QUEEN_INTERVENTION_REQUESTED,
    EventType.WORKER_ESCALATION_TICKET,
    EventType.NODE_INTERNAL_OUTPUT,
    EventType.NODE_STALLED,
    EventType.NODE_RETRY,
    EventType.NODE_TOOL_DOOM_LOOP,
    EventType.CONTEXT_COMPACTED,
    EventType.WORKER_LOADED,
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
    """SSE event stream for a session.

    Query params:
        types: Comma-separated event type names to filter (optional).
    """
    session, err = resolve_session(request)
    if err:
        return err

    # Session always has an event_bus — no runtime guard needed
    event_bus = session.event_bus
    event_types = _parse_event_types(request.query.get("types"))

    # Per-client buffer queue
    queue: asyncio.Queue = asyncio.Queue(maxsize=1000)

    # Lifecycle events drive frontend state transitions and must never be lost.
    _CRITICAL_EVENTS = {
        "execution_started",
        "execution_completed",
        "execution_failed",
        "execution_paused",
        "client_input_requested",
        "node_loop_iteration",
        "node_loop_started",
    }

    async def on_event(event) -> None:
        """Push event dict into queue; drop non-critical events if full."""
        evt_dict = event.to_dict()
        if evt_dict.get("type") in _CRITICAL_EVENTS:
            await queue.put(evt_dict)  # block rather than drop
        else:
            try:
                queue.put_nowait(evt_dict)
            except asyncio.QueueFull:
                pass  # high-frequency events can be dropped; client will catch up

    # Subscribe to EventBus
    from framework.server.sse import SSEResponse

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
            except (ConnectionResetError, ConnectionError):
                break
            except Exception as exc:
                logger.debug("SSE stream closed: %s", exc)
                break
    except asyncio.CancelledError:
        pass
    finally:
        try:
            event_bus.unsubscribe(sub_id)
        except Exception:
            pass
        logger.debug("SSE client disconnected from session '%s'", session.id)

    return sse.response


def register_routes(app: web.Application) -> None:
    """Register SSE event streaming routes."""
    # Session-primary route
    app.router.add_get("/api/sessions/{session_id}/events", handle_events)
