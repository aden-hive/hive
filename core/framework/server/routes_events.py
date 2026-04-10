"""SSE event streaming route."""

import asyncio
import logging

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError as _AiohttpConnReset

from framework.host.event_bus import EventType
from framework.server.app import resolve_session

logger = logging.getLogger(__name__)

# Default event types streamed to clients
DEFAULT_EVENT_TYPES = [
    EventType.CLIENT_OUTPUT_DELTA,
    EventType.CLIENT_INPUT_REQUESTED,
    EventType.CLIENT_INPUT_RECEIVED,
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
    EventType.LLM_TURN_COMPLETE,
    EventType.NODE_ACTION_PLAN,
    EventType.GOAL_PROGRESS,
    EventType.NODE_INTERNAL_OUTPUT,
    EventType.NODE_STALLED,
    EventType.NODE_RETRY,
    EventType.NODE_TOOL_DOOM_LOOP,
    EventType.CONTEXT_COMPACTED,
    EventType.CONTEXT_USAGE_UPDATED,
    EventType.WORKER_COLONY_LOADED,
    EventType.CREDENTIALS_REQUIRED,
    EventType.SUBAGENT_REPORT,
    EventType.QUEEN_PHASE_CHANGED,
    EventType.TRIGGER_AVAILABLE,
    EventType.TRIGGER_ACTIVATED,
    EventType.TRIGGER_DEACTIVATED,
    EventType.TRIGGER_FIRED,
    EventType.TRIGGER_REMOVED,
    EventType.TRIGGER_UPDATED,
]

# Keepalive interval in seconds
KEEPALIVE_INTERVAL = 15.0

# Phase 5 SSE filter: parallel-worker streams (stream_id="worker:{uuid}")
# publish high-frequency LLM deltas / tool calls that would flood the
# user's queen DM chat. We let only this small allowlist of worker
# events through to the queen-chat SSE so the frontend can render
# fan-out lifecycle and structured fan-in reports without seeing the
# raw worker chatter. Per-worker SSE panels (Phase 5b) bypass this
# filter via a dedicated /workers/{worker_id}/events route.
_WORKER_EVENT_ALLOWLIST = {
    EventType.SUBAGENT_REPORT.value,
    EventType.EXECUTION_COMPLETED.value,
    EventType.EXECUTION_FAILED.value,
}


def _is_worker_noise(evt_dict: dict) -> bool:
    """True if the event is a parallel-worker event we should drop."""
    stream_id = evt_dict.get("stream_id") or ""
    if not stream_id.startswith("worker:"):
        return False
    return evt_dict.get("type") not in _WORKER_EVENT_ALLOWLIST


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
        "client_input_received",
        "node_loop_iteration",
        "node_loop_started",
        "credentials_required",
        "worker_graph_loaded",
        "queen_phase_changed",
    }

    client_disconnected = asyncio.Event()

    async def on_event(event) -> None:
        """Push event dict into queue; drop non-critical events if full."""
        if client_disconnected.is_set():
            return

        evt_dict = event.to_dict()
        if _is_worker_noise(evt_dict):
            return
        if evt_dict.get("type") in _CRITICAL_EVENTS:
            try:
                queue.put_nowait(evt_dict)
            except asyncio.QueueFull:
                logger.warning(
                    "SSE client queue full on critical event; disconnecting session='%s'",
                    session.id,
                )
                client_disconnected.set()
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
    logger.info(
        "SSE connected: session='%s', sub_id='%s', types=%d", session.id, sub_id, len(event_types)
    )

    # Replay buffered events that were published before this SSE connected.
    # The EventBus keeps a history ring-buffer; we replay the subset that
    # produces visible chat messages so the frontend never misses early
    # queen output.  Lifecycle events are NOT replayed to avoid duplicate
    # state transitions (turn counter increments, etc.).
    _REPLAY_TYPES = {
        EventType.CLIENT_OUTPUT_DELTA.value,
        EventType.EXECUTION_STARTED.value,
        EventType.CLIENT_INPUT_REQUESTED.value,
        EventType.CLIENT_INPUT_RECEIVED.value,
    }
    event_type_values = {et.value for et in event_types}
    replay_types = _REPLAY_TYPES & event_type_values
    replayed = 0
    for past_event in event_bus._event_history:
        if past_event.type.value in replay_types:
            past_dict = past_event.to_dict()
            if _is_worker_noise(past_dict):
                continue
            try:
                queue.put_nowait(past_dict)
                replayed += 1
            except asyncio.QueueFull:
                break
    if replayed:
        logger.info("SSE replayed %d buffered events for session='%s'", replayed, session.id)

    # Live status is surfaced via the EventBus ring-buffer replay above
    # (executed earlier in this handler).  The old graph-executor snapshot
    # injection was removed when graph execution was retired -- the
    # AgentLoop publishes its own lifecycle events to the EventBus.

    event_count = 0
    close_reason = "unknown"
    try:
        while not client_disconnected.is_set():
            try:
                data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                await sse.send_event(data)
                event_count += 1
                if event_count == 1:
                    logger.info(
                        "SSE first event: session='%s', type='%s'", session.id, data.get("type")
                    )
            except TimeoutError:
                try:
                    await sse.send_keepalive()
                except (ConnectionResetError, ConnectionError, _AiohttpConnReset):
                    close_reason = "client_disconnected"
                    break
                except Exception as exc:
                    close_reason = f"keepalive_error: {exc}"
                    break
            except (ConnectionResetError, ConnectionError, _AiohttpConnReset):
                close_reason = "client_disconnected"
                break
            except RuntimeError as exc:
                if "closing transport" in str(exc).lower():
                    close_reason = "client_disconnected"
                else:
                    close_reason = f"error: {exc}"
                break
            except Exception as exc:
                close_reason = f"error: {exc}"
                break

        if client_disconnected.is_set() and close_reason == "unknown":
            close_reason = "slow_client"
    except asyncio.CancelledError:
        close_reason = "cancelled"
    finally:
        try:
            event_bus.unsubscribe(sub_id)
        except Exception:
            pass
        logger.info(
            "SSE disconnected: session='%s', events_sent=%d, reason='%s'",
            session.id,
            event_count,
            close_reason,
        )

    return sse.response


def register_routes(app: web.Application) -> None:
    """Register SSE event streaming routes."""
    # Session-primary route
    app.router.add_get("/api/sessions/{session_id}/events", handle_events)
