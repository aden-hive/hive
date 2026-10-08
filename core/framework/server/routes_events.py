"""SSE event streaming route."""

import asyncio
import logging

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError as _AiohttpConnReset

from framework.host.event_bus import (
    AgentEvent,
    EventType,
    collect_resolved_request_seqs,
    compute_session_snapshot,
    get_global_event_bus,
)
from framework.host.events_policy import WORKER_FANIN_TYPES, is_worker_local
from framework.server.app import resolve_session

logger = logging.getLogger(__name__)

# Default event types streamed to clients
DEFAULT_EVENT_TYPES = [
    EventType.SESSION_SNAPSHOT,
    EventType.CLIENT_OUTPUT_DELTA,
    EventType.CLIENT_INPUT_REQUESTED,
    EventType.CLIENT_INPUT_RECEIVED,
    # Marks where a steered/queued user message actually entered the
    # conversation. The renderer uses it to split the queen's bubble at the
    # injection point so the steer's reply sorts below it. Without it in the
    # live set, this only works after a refresh (disk history carries it) —
    # live streaming would leave the reply merged above the steer.
    EventType.CLIENT_INPUT_COMMITTED,
    EventType.LLM_TEXT_DELTA,
    # Thinking-model feedback: throttled reasoning stream while the model is
    # still silent, then the consolidated block. Without these a long native
    # think (minutes on deepseek/glm) renders as a dead page.
    EventType.LLM_REASONING_DELTA,
    EventType.CLIENT_REASONING,
    EventType.TOOL_CALL_STARTED,
    EventType.TOOL_CALL_COMPLETED,
    EventType.EXECUTION_STARTED,
    EventType.EXECUTION_COMPLETED,
    EventType.EXECUTION_FAILED,
    EventType.EXECUTION_PAUSED,
    EventType.PAYMENT_REQUIRED,
    EventType.NODE_LOOP_STARTED,
    EventType.NODE_LOOP_ITERATION,
    EventType.NODE_LOOP_COMPLETED,
    EventType.LLM_TURN_COMPLETE,
    EventType.GOAL_PROGRESS,
    EventType.NODE_INTERNAL_OUTPUT,
    EventType.NODE_STALLED,
    EventType.NODE_RETRY,
    EventType.NODE_TOOL_DOOM_LOOP,
    EventType.LOOP_STATE_CHANGED,
    EventType.CONTEXT_COMPACTION_STARTED,
    EventType.CONTEXT_COMPACTED,
    EventType.CONTEXT_USAGE_UPDATED,
    EventType.WORKER_COLONY_LOADED,
    EventType.COLONY_CREATED,
    EventType.COLONY_SUGGESTION_REQUESTED,
    EventType.CREDENTIALS_REQUIRED,
    # Agent called credentials(action="collect"): the frontend renders the
    # secure form. Must be in the live set or the form only appears after a
    # reload (and the queen stays parked in the meantime).
    EventType.CLIENT_CREDENTIAL_FORM_REQUESTED,
    EventType.SUBAGENT_REPORT,
    EventType.QUEEN_PHASE_CHANGED,
    EventType.TRIGGER_AVAILABLE,
    EventType.TRIGGER_ACTIVATED,
    EventType.TRIGGER_DEACTIVATED,
    EventType.TRIGGER_FIRED,
    EventType.TRIGGER_REMOVED,
    EventType.TRIGGER_UPDATED,
    # Task lifecycle — drives the Action Plan panel. The frontend opens
    # the panel on the first TASK_CREATED; without these in the default
    # set, an unfiltered session subscription (queen-DM's useMultiSSE)
    # never sees task events and the panel only appears after a reload.
    EventType.TASK_CREATED,
    EventType.TASK_UPDATED,
    EventType.TASK_DELETED,
    EventType.TASK_LIST_RESET,
    # Fork navigation — published on the OLD session's bus when the queen
    # calls task_create(new_session=true). The desktop's unfiltered
    # useMultiSSE subscription must receive it live so queen-dm.tsx can
    # swap the ?session= param to the successor. Without it the UI is
    # stranded on the retired session until a manual reload.
    EventType.SESSION_FORKED,
]

# Keepalive interval in seconds
KEEPALIVE_INTERVAL = 15.0

# Session-SSE worker filter: workers run outside the queen's DM
# chat. Worker activity is observable via the dedicated
# ``/api/workers/{worker_id}/events`` per-worker SSE route, not via
# the session chat. This keeps the queen↔user conversation clean of
# tool-call chatter regardless of whether the worker was spawned by
# ``run_agent_with_input`` (stream_id="worker") or
# ``run_worker`` (stream_id="worker:{uuid}").
#
# Lifecycle events the frontend needs for fan-in summaries
# (SUBAGENT_REPORT, EXECUTION_COMPLETED, EXECUTION_FAILED) are still
# allowed through so the queen can show "N workers done" surfaces
# without exposing the per-turn chatter.
#
# The predicate itself lives in ``framework.host.events_policy`` because the
# event log needs the identical answer when routing an event to the queen's
# log vs. the worker's own. Re-exported here under the original names.
_WORKER_EVENT_ALLOWLIST = WORKER_FANIN_TYPES


def _is_worker_noise(evt_dict: dict) -> bool:
    """True if the event belongs to a worker stream and should not
    surface in the queen DM chat.

    Thin adapter over :func:`framework.host.events_policy.is_worker_local`
    for the dict-shaped events the SSE layer works with.
    """
    return is_worker_local(evt_dict.get("stream_id"), evt_dict.get("type"))


def _parse_watch(raw: str | None) -> tuple[bool, set[str]]:
    """Parse the ``?watch=`` opt-in list into (watch_all, streams).

    ``"*"`` means every worker's chatter (debug / local dev). Otherwise a
    comma-separated list of stream ids, e.g. ``worker:<uuid>,worker:<uuid>``.
    """
    raw = (raw or "").strip()
    if raw == "*":
        return True, set()
    return False, {s.strip() for s in raw.split(",") if s.strip() and s.strip() != "*"}


def is_suppressed_for_client(evt_dict: dict, watch_all: bool, watched_streams: set[str]) -> bool:
    """True if this event must not reach *this* client.

    Queen events and worker META always pass — META is what renders the worker
    bubble, so a client that never opts in still sees every worker start,
    progress and finish. Only a worker's per-turn chatter is gated, and only to
    clients that explicitly asked to watch that worker.
    """
    if watch_all:
        return False
    if not is_worker_local(evt_dict.get("stream_id"), evt_dict.get("type")):
        return False
    return (evt_dict.get("stream_id") or "") not in watched_streams


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


def _authoritative_trigger_events(session: object) -> list[dict]:
    """Rebuild the full current trigger set as lifecycle-event dicts from the
    live session — the source of truth — for replay to a (re)connecting client.

    Why this exists: the UI reconstructs trigger cards ONLY from
    ``trigger_available`` / ``trigger_activated`` SSE events, replayed from the
    EventBus history ring buffer on connect. That buffer is bounded
    (``max_history``), so on a chatty colony a trigger's activation — published
    once at load — ages out of history before a client (re)connects, and only
    the most-recently-activated trigger survives the replay. The UI then shows
    ONE card when several triggers exist. Seeding from
    ``session.available_triggers`` (which always holds every trigger) makes every
    connect rehydrate the FULL set, independent of history retention. Events are
    idempotent on the frontend (keyed by ``trigger_id``), so this is safe
    alongside the ring-buffer replay. Emits ACTIVATED for active triggers (card
    renders "running") and AVAILABLE for inactive ones ("pending"), mirroring
    ``SessionManager._emit_trigger_events``.
    """
    from framework.host.triggers import build_trigger_view

    events: list[dict] = []
    for t in build_trigger_view(session):
        events.append(
            AgentEvent(
                type=EventType.TRIGGER_ACTIVATED if t["enabled"] else EventType.TRIGGER_AVAILABLE,
                stream_id="queen",
                data={
                    "trigger_id": t["trigger_id"],
                    "trigger_type": t["trigger_type"],
                    "trigger_config": t["trigger_config"],
                    "name": t["name"],
                },
            ).to_dict()
        )
    return events


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

    # Worker chatter is opt-in per worker. By default the queen's feed carries
    # only her own events plus each worker's META events (start / progress /
    # finish) — enough to render a worker bubble, and nothing more.
    #
    # A client that wants a specific worker's per-turn detail (text deltas,
    # tool calls) asks for it explicitly:
    #
    #     ?watch=worker:<uuid>            # one worker
    #     ?watch=worker:<a>,worker:<b>    # several
    #     ?watch=*                        # everything (debug / local dev)
    #
    # This replaces the old phase-aware filter, which shipped EVERY worker's
    # chatter to EVERY client the moment the queen entered colony phase. With
    # the runtime potentially on another machine, that firehose crosses the
    # network; a human can only look at one worker at a time, so we send one.
    watch_all, watched_streams = _parse_watch(request.query.get("watch"))

    def _is_suppressed(evt_dict: dict) -> bool:
        return is_suppressed_for_client(evt_dict, watch_all, watched_streams)

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
        # Gate keys: these are the ONLY events that clear the frontend's
        # isStreaming flag and flush its pending-message queue. Dropping
        # one under backpressure used to leave the composer stuck forever
        # (messages queued client-side, never posted, "fixed" only by a
        # page refresh). A visible disconnect + snapshot resync on
        # queue-full beats a silent dropped state transition.
        "llm_turn_complete",
        "loop_state_changed",
        "tool_call_completed",
    }

    client_disconnected = asyncio.Event()

    async def on_event(event) -> None:
        """Push event dict into queue; drop non-critical events if full."""
        if client_disconnected.is_set():
            return

        evt_dict = event.to_dict()
        if _is_suppressed(evt_dict):
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
    # A live UI client is now attached — Sentinel reads this to decide whether
    # a human is watching (so it escalates to messaging only when nobody is).
    session.sse_client_count = getattr(session, "sse_client_count", 0) + 1
    logger.info("SSE connected: session='%s', sub_id='%s', types=%d", session.id, sub_id, len(event_types))

    # Replay buffered events that were published before this SSE connected.
    # The EventBus keeps a history ring-buffer; we replay the subset that
    # produces visible chat messages so the frontend never misses early
    # queen output.  Execution/node lifecycle events are NOT replayed to
    # avoid duplicate state transitions (turn counter increments, etc.).
    #
    # Trigger lifecycle events ARE replayed: they're idempotent state
    # setters (this trigger exists / is active / was deactivated) and
    # they're published during session load — BEFORE the frontend's
    # SSE subscription is established. Without replay, a freshly-opened
    # colony would never see its own triggers.
    # Tool lifecycle and turn boundaries are now replayed too: without
    # them a queen mid-tool-call (e.g. a long browser scroll loop)
    # rendered as idle on revisit. ``replayState`` (queen-dm.tsx)
    # dedupes by event seq, see H1 in the plan.
    _REPLAY_TYPES = {
        EventType.CLIENT_OUTPUT_DELTA.value,
        EventType.EXECUTION_STARTED.value,
        EventType.EXECUTION_COMPLETED.value,
        EventType.LLM_TURN_COMPLETE.value,
        EventType.TOOL_CALL_STARTED.value,
        EventType.TOOL_CALL_COMPLETED.value,
        EventType.CLIENT_INPUT_REQUESTED.value,
        EventType.CLIENT_INPUT_RECEIVED.value,
        # Replayed on reconnect so a steer that landed just before the user
        # (re)subscribed still records its injection boundary in the live
        # replay state — otherwise an in-progress steered iteration would
        # re-merge its bubble until the next full refresh.
        EventType.CLIENT_INPUT_COMMITTED.value,
        EventType.TRIGGER_AVAILABLE.value,
        EventType.TRIGGER_ACTIVATED.value,
        EventType.TRIGGER_DEACTIVATED.value,
        EventType.TRIGGER_FIRED.value,
        EventType.TRIGGER_REMOVED.value,
        EventType.TRIGGER_UPDATED.value,
        # Task lifecycle — replayed so the Action Plan panel rehydrates on
        # a fresh connect (session open / fork swap) instead of depending
        # solely on a REST snapshot landing at the right moment. The
        # frontend reducer dedupes by task id, so replay + snapshot
        # converge. Without this a forked session's seeded plan (which
        # emits its task_created events before the user's stream
        # connects) never reaches the panel without a manual reload.
        EventType.TASK_CREATED.value,
        EventType.TASK_UPDATED.value,
        EventType.TASK_DELETED.value,
        EventType.TASK_LIST_RESET.value,
        # Replayed so a reconnect that lands after the fork was published
        # (SSE resubscribe race) still swaps to the successor session.
        # queen-dm.tsx handles session_forked ahead of its
        # seq<=snapshotSeq historical guard, so a replayed copy still
        # triggers navigation.
        EventType.SESSION_FORKED.value,
    }
    event_type_values = {et.value for et in event_types}
    replay_types = _REPLAY_TYPES & event_type_values

    # Inject the session snapshot first so the renderer rehydrates
    # "queen busy / current tool / awaiting input" instantly.
    snapshot_data = compute_session_snapshot(event_bus)
    snapshot_event = AgentEvent(
        type=EventType.SESSION_SNAPSHOT,
        stream_id="queen",
        node_id="queen",
        execution_id=snapshot_data.get("current_execution_id"),
        data=snapshot_data,
    )
    try:
        queue.put_nowait(snapshot_event.to_dict())
    except asyncio.QueueFull:
        pass

    # Suppress already-resolved client_input_requested entries.
    resolved_request_seqs = collect_resolved_request_seqs(event_bus)

    replayed = 0
    for past_event in event_bus._event_history:
        if past_event.type.value not in replay_types:
            continue
        if past_event.type == EventType.CLIENT_INPUT_REQUESTED and past_event.seq in resolved_request_seqs:
            continue
        past_dict = past_event.to_dict()
        if _is_suppressed(past_dict):
            continue
        try:
            queue.put_nowait(past_dict)
            replayed += 1
        except asyncio.QueueFull:
            break
    if replayed:
        logger.info(
            "SSE replayed %d buffered events for session='%s' (snapshot seq=%d, suppressed %d resolved questions)",
            replayed,
            session.id,
            snapshot_data.get("snapshot_seq", 0),
            len(resolved_request_seqs),
        )

    # Rehydrate the FULL trigger set from live session state. The ring-buffer
    # replay above can MISS triggers whose activation aged out of bounded
    # history on a chatty colony — surfacing only one card when several exist.
    # Sent AFTER the replay so current state is the final word; idempotent on
    # the client (keyed by trigger_id).
    for trig_evt in _authoritative_trigger_events(session):
        try:
            queue.put_nowait(trig_evt)
        except asyncio.QueueFull:
            break

    event_count = 0
    close_reason = "unknown"
    try:
        while not client_disconnected.is_set():
            try:
                data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                await sse.send_event(data)
                event_count += 1
                if event_count == 1:
                    logger.info("SSE first event: session='%s', type='%s'", session.id, data.get("type"))
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
        session.sse_client_count = max(0, getattr(session, "sse_client_count", 1) - 1)
        logger.info(
            "SSE disconnected: session='%s', events_sent=%d, reason='%s'",
            session.id,
            event_count,
            close_reason,
        )

    return sse.response


# Global SSE channel — cross-cutting events that aren't scoped to a
# session (credential connect/disconnect, tool catalog refreshes,
# tools-config edits in another tab/window). Subscribers are UI
# surfaces that need to refetch when these events fire (Tool Library,
# Integrations page). Lightweight: no replay, no filter, no worker
# noise — every published event reaches every subscriber.
_GLOBAL_EVENT_TYPES = [
    EventType.CREDENTIAL_PROVIDER_CONNECTED,
    EventType.CREDENTIAL_PROVIDER_DISCONNECTED,
    EventType.TOOL_CATALOG_REFRESHED,
    EventType.TOOLS_CONFIG_CHANGED,
    EventType.CRM_CHANGED,
]

# Grid entity slugs the CRM notification is allowed to name. The renderer keys
# its tabs by these, and the payload arrives from a subprocess, so it is
# validated rather than forwarded: an unknown slug would silently match no tab
# and read to the user as "the refresh is broken" — far harder to diagnose than
# the empty list, which the renderer already treats as "refresh everything".
_CRM_ENTITIES = frozenset({"people", "organizations", "opportunities", "interactions"})


async def handle_crm_changed(request: web.Request) -> web.Response:
    """POST /api/crm/changed — the `hive-crm` CLI reporting a write it landed.

    The CRM is written only by that CLI, straight to the cloud backend, so the
    renderer never sees a write happen and an open board stays frozen while the
    queen configures it. This is the one hop that closes the loop: the CLI pings
    here on success (framework.crm.notify) and we republish on the global SSE
    channel the renderer already holds open. No polling anywhere in the path.

    The body names WHICH entities moved so the renderer can ignore changes to a
    tab the user isn't looking at — a person reading People should not have
    their board reload because the queen touched Organizations.
    """
    from framework.host.event_bus import publish_global

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a malformed ping is not worth a 500
        body = {}
    if not isinstance(body, dict):
        body = {}

    raw = body.get("entities")
    entities = sorted({e for e in raw if isinstance(e, str) and e in _CRM_ENTITIES}) if isinstance(raw, list) else []

    await publish_global(
        AgentEvent(
            type=EventType.CRM_CHANGED,
            stream_id="global",
            data={"entities": entities, "schema": bool(body.get("schema"))},
        )
    )
    return web.json_response({"ok": True})


async def handle_global_events(request: web.Request) -> web.StreamResponse:
    """SSE event stream for app-wide events (no session scope).

    See ``_GLOBAL_EVENT_TYPES`` for the surface area. Used by the
    desktop renderer's ``useGlobalEvents`` hook to keep the Tool
    Library and integrations UI in sync without manual refresh.
    """
    from framework.server.sse import SSEResponse

    bus = get_global_event_bus()
    queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    client_disconnected = asyncio.Event()

    async def on_event(event: AgentEvent) -> None:
        if client_disconnected.is_set():
            return
        try:
            queue.put_nowait(event.to_dict())
        except asyncio.QueueFull:
            # Global events are infrequent; if the queue fills the
            # client is wedged. Drop and let it reconnect.
            client_disconnected.set()

    sub_id = bus.subscribe(event_types=_GLOBAL_EVENT_TYPES, handler=on_event)

    sse = SSEResponse()
    await sse.prepare(request)
    logger.info("Global SSE connected: sub_id='%s'", sub_id)

    close_reason = "unknown"
    try:
        while not client_disconnected.is_set():
            try:
                data = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL)
                await sse.send_event(data)
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
    except asyncio.CancelledError:
        close_reason = "cancelled"
    finally:
        try:
            bus.unsubscribe(sub_id)
        except Exception:
            pass
        logger.info("Global SSE disconnected: reason='%s'", close_reason)

    return sse.response


def register_routes(app: web.Application) -> None:
    """Register SSE event streaming routes."""
    # Session-primary route
    app.router.add_get("/api/sessions/{session_id}/events", handle_events)
    # Global cross-cutting channel (no session scope).
    app.router.add_get("/api/events/global", handle_global_events)
    # Ingress for the `hive-crm` CLI's post-write ping, republished on the
    # channel above. Lives here rather than with the CRM proxy routes because
    # it produces nothing but a global event.
    app.router.add_post("/api/crm/changed", handle_crm_changed)
