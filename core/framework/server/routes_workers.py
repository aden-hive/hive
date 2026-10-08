"""Live worker control routes — stream the worker registry, stop workers."""

import json
import logging
import time

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError

from framework.server.app import resolve_session

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Live worker control — list / stop a specific worker / stop all
#
# All spawned workers (queen-overseer + run_worker fan-outs) live in
# ``session.colony`` (the unified ColonyRuntime) — the only runtime with a
# live worker registry.
# ---------------------------------------------------------------------------


def _build_live_workers_payload(colony) -> list[dict]:
    """Serialize the colony's current worker registry.

    Extracted so both the one-shot ``GET /workers`` handler and the SSE
    ``/workers/stream`` handler render the exact same shape.
    """
    if colony is None:
        return []

    now = time.monotonic()
    payload: list[dict] = []
    try:
        workers = list(colony._workers.values())  # type: ignore[attr-defined]
    except Exception:
        workers = []

    for w in workers:
        started_at = getattr(w, "_started_at", 0.0) or 0.0
        duration = (now - started_at) if started_at else 0.0
        result = getattr(w, "_result", None)
        payload.append(
            {
                "worker_id": w.id,
                "task": (w.task or "")[:400],
                "status": str(getattr(w, "status", "unknown")),
                "is_active": bool(getattr(w, "is_active", False)),
                "duration_seconds": round(duration, 1),
                "explicit_report": getattr(w, "_explicit_report", None),
                "result_status": (result.status if result else None),
                "result_summary": (result.summary if result else None),
            }
        )

    # Active workers first, then terminated, newest-started first within group.
    payload.sort(key=lambda r: (not r["is_active"], -(r["duration_seconds"] or 0)))
    return payload


def _payload_change_signature(payload: list[dict]) -> tuple:
    """Cheap fingerprint for change detection on the SSE stream.

    We intentionally exclude ``duration_seconds`` — it ticks every call
    and would make every poll look like a change, defeating the "only
    emit on change" optimisation. Everything else (status, result,
    explicit_report) actually reflects worker state transitions.
    """
    return tuple(
        (
            w["worker_id"],
            w["status"],
            w["is_active"],
            w["result_status"],
            w["result_summary"],
            bool(w["explicit_report"]),
        )
        for w in payload
    )


async def handle_live_workers_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/sessions/{session_id}/workers/stream — SSE feed.

    Emits a ``snapshot`` event immediately, then re-emits every time
    the worker registry changes (status transitions, new spawns, new
    reports). Polls the runtime every 2s internally — the colony's
    ``_workers`` dict is not observable otherwise. Clients disconnecting
    bubbles up as ConnectionResetError from ``resp.write``.
    """
    session, err = resolve_session(request)
    if err:
        return err

    import asyncio

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    async def _send(event: str, data) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        await resp.write(payload.encode("utf-8"))

    last_signature: tuple | None = None
    try:
        while True:
            colony = session.colony
            workers = _build_live_workers_payload(colony)
            signature = _payload_change_signature(workers)
            if signature != last_signature:
                await _send("snapshot", {"workers": workers})
                last_signature = signature
            await asyncio.sleep(2.0)
    except (asyncio.CancelledError, ConnectionResetError, ClientConnectionResetError):
        logger.debug("live workers stream: client disconnected")
    except Exception as exc:
        logger.warning("live workers stream error: %s", exc, exc_info=True)
    return resp


async def handle_stop_live_worker(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/workers/{worker_id}/stop — force-stop one worker.

    Routes through ``colony.stop_worker`` → ``stop_workers`` (the one cascade),
    so this is queued-aware and time-bounded: a worker still sitting in the
    pending queue is marked terminal and given a synthesised report instead of
    being silently left behind for the scheduler to start later. The worker's
    terminal SUBAGENT_REPORT still fires (preserving any _explicit_report) so
    the queen sees a `[WORKER_REPORT]` with ``status="stopped"``.
    """
    session, err = resolve_session(request)
    if err:
        return err

    worker_id = request.match_info.get("worker_id", "")
    if not worker_id:
        return web.json_response({"error": "worker_id required"}, status=400)

    colony = session.colony
    if colony is None:
        return web.json_response({"error": "No active colony on this session"}, status=503)

    worker = colony._workers.get(worker_id)  # type: ignore[attr-defined]
    if worker is None:
        return web.json_response({"error": f"Worker '{worker_id}' not found"}, status=404)
    if not worker.is_active:
        return web.json_response(
            {
                "stopped": False,
                "reason": "Worker already terminated",
                "worker_id": worker_id,
                "status": str(worker.status),
            }
        )

    try:
        summary = await colony.stop_worker(worker_id)
    except Exception as exc:
        logger.exception("stop_worker failed for %s", worker_id)
        return web.json_response(
            {"stopped": False, "error": str(exc), "worker_id": worker_id},
            status=500,
        )

    # Keep `stopped: true` as the boolean the client already relies on; the
    # cascade summary rides alongside it rather than clobbering it.
    return web.json_response({"stopped": True, "worker_id": worker_id, "detail": summary})


async def handle_stop_all_live_workers(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/workers/stop-all — force-stop every active worker.

    The persistent overseer (if any) is skipped — it is the queen itself
    and stopping it would end the session. Only ephemeral fan-out workers
    are targeted.
    """
    session, err = resolve_session(request)
    if err:
        return err

    colony = session.colony
    if colony is None:
        return web.json_response({"stopped": [], "error": "No active colony on this session"})

    # One cascade for everyone (see ColonyRuntime.stop_workers): cancels QUEUED
    # workers so the scheduler can't promote them back to life, stops the live
    # ones concurrently with a per-worker timeout so one wedged worker can't
    # hang the sweep, and reaps their browsers. This route used to hand-roll a
    # sequential, unbounded loop that did none of that.
    summary = await colony.stop_workers()
    return web.json_response(summary)


async def handle_worker_reap_timeline(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/workers/{worker_id}/reap-timeline.

    Returns the four lifecycle timestamps captured around worker shutdown
    plus a derived ``ordering_ok`` flag. Intended for end-to-end tests
    that need to confirm the queen-side report was emitted before the
    browser tab group was reaped:

        report_published_at  → done_callback_at  → reap_scheduled_at  → reap_completed_at

    All timestamps are ``time.monotonic()`` floats (process-local). Any
    field is ``null`` until its corresponding hook fires; for a fully
    terminated worker all four should be populated once the bridge
    round-trip in close_profile_context returns.
    """
    session, err = resolve_session(request)
    if err:
        return err

    worker_id = request.match_info.get("worker_id", "")
    if not worker_id:
        return web.json_response({"error": "worker_id required"}, status=400)

    colony = session.colony
    if colony is None:
        return web.json_response({"error": "No active colony on this session"}, status=503)

    worker = colony._workers.get(worker_id)  # type: ignore[attr-defined]
    if worker is None:
        return web.json_response({"error": f"Worker '{worker_id}' not found"}, status=404)

    report_at = getattr(worker, "_report_published_at", None)
    done_at = getattr(worker, "_done_callback_at", None)
    sched_at = getattr(worker, "_reap_scheduled_at", None)
    done_reap_at = getattr(worker, "_reap_completed_at", None)

    def _delta_ms(a: float | None, b: float | None) -> float | None:
        if a is None or b is None:
            return None
        return round((b - a) * 1000.0, 3)

    # Required invariant: report must publish first, then done-callback,
    # then reap scheduled, then reap completed. Any None means "not yet
    # reached" rather than a failure, so we only assert ordering for the
    # consecutive pairs that are both populated.
    pairs = [(report_at, done_at), (done_at, sched_at), (sched_at, done_reap_at)]
    ordering_ok = all(a is None or b is None or a <= b for a, b in pairs)

    return web.json_response(
        {
            "worker_id": worker_id,
            "status": str(getattr(worker, "status", "unknown")),
            "profile_name": worker_id,  # workers are 1:1 with their profile
            "timestamps": {
                "report_published_at": report_at,
                "done_callback_at": done_at,
                "reap_scheduled_at": sched_at,
                "reap_completed_at": done_reap_at,
            },
            "deltas_ms": {
                "report_to_done_callback": _delta_ms(report_at, done_at),
                "done_callback_to_reap_scheduled": _delta_ms(done_at, sched_at),
                "reap_scheduled_to_completed": _delta_ms(sched_at, done_reap_at),
                "report_to_reap_completed": _delta_ms(report_at, done_reap_at),
            },
            "ordering_ok": ordering_ok,
            "reap_result": getattr(worker, "_reap_result", None),
        }
    )


async def handle_browser_contexts(request: web.Request) -> web.Response:
    """GET /api/browser/contexts — process-global browser tab-group registry.

    Returns the in-memory ``lifecycle._contexts`` snapshot used by the
    reap-timeline tests to assert a worker's profile entry disappears
    after shutdown. Process-scoped, not session-scoped, because the
    registry is a single module-level dict shared by every colony.
    """
    try:
        from gcu.browser.tools.lifecycle import list_active_contexts
    except ImportError:
        return web.json_response({"available": False, "reason": "gcu browser tools not loaded", "contexts": []})

    contexts = list_active_contexts()
    return web.json_response({"available": True, "count": len(contexts), "contexts": contexts})


async def handle_browser_tabs(request: web.Request) -> web.Response:
    """GET /api/browser/tabs — every Chrome tab the extension can see.

    Diagnostic added 2026-07-05 alongside the v74 reaper hardening. The
    extension's LRU reaper (background.js) caps live-backed tabs at 3 and
    idles them out at 2 min; if a live sandbox reports N > 3 renderers on
    a "healthy" verdict, this endpoint is the way to inspect which specific
    tabs the reaper is failing to reap and why.

    Returns per-tab {id, windowId, groupId, isHiveGroup, url, title,
    discarded, active, audible, pinned}. Reaper-internal counters
    (hiveTabLastSeen ageMs, hiveDiscardFailCount) live in the extension's
    service-worker memory and aren't over the bridge protocol — the
    corresponding signal is the ``[hive.reaper.sweep]`` structured log line
    the reaper emits every 30 s to bridge_host stderr. Operators reading
    this endpoint should tail bridge_host stderr in parallel.

    Uses the same client-bridge init dance as ``_reap_browser_contexts`` at
    app.py:380 — safe when no gcu subprocess exists on this runtime.
    """
    try:
        from gcu.browser.bridge import get_bridge, init_bridge
    except ImportError:
        return web.json_response({"available": False, "reason": "gcu browser tools not loaded", "tabs": []})

    bridge = get_bridge()
    if bridge is None:
        try:
            bridge = init_bridge(mode="client")
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"available": False, "reason": f"bridge init failed: {exc}", "tabs": []})
    connect = getattr(bridge, "connect", None)
    if callable(connect) and not bridge.is_connected:
        try:
            await connect()
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"available": False, "reason": f"bridge connect failed: {exc}", "tabs": []})
    if not bridge.is_connected:
        return web.json_response({"available": False, "reason": "bridge not connected", "tabs": []})

    try:
        list_result = await bridge.list_tabs()
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"available": False, "reason": f"list_tabs failed: {exc}", "tabs": []})
    tabs = list(list_result.get("tabs") or [])

    # Which groupIds carry HIVE_GROUP_MARKER? Derived from list_active_contexts
    # (the same registry /api/browser/contexts returns). A tab whose groupId
    # is in this set is agent-controlled; anything else is either a user tab
    # or an ex-agent orphan the reaper's global cap should now be reaping.
    hive_group_ids: set[int] = set()
    try:
        from gcu.browser.tools.lifecycle import list_active_contexts

        for ctx in list_active_contexts():
            gid = ctx.get("groupId")
            if isinstance(gid, int):
                hive_group_ids.add(gid)
    except ImportError:
        pass

    enriched: list[dict] = []
    for t in tabs:
        gid = t.get("groupId")
        enriched.append(
            {
                "id": t.get("id"),
                "windowId": t.get("windowId"),
                "groupId": gid if isinstance(gid, int) and gid != -1 else None,
                "isHiveGroup": isinstance(gid, int) and gid in hive_group_ids,
                "url": t.get("url"),
                "title": t.get("title"),
                "discarded": bool(t.get("discarded")),
                "active": bool(t.get("active")),
                "audible": bool(t.get("audible")),
                "pinned": bool(t.get("pinned")),
            }
        )
    live_count = sum(1 for t in enriched if not t["discarded"])
    return web.json_response(
        {
            "available": True,
            "count": len(enriched),
            "live_count": live_count,
            "discarded_count": len(enriched) - live_count,
            "hive_group_count": len(hive_group_ids),
            "tabs": enriched,
        }
    )


async def handle_close_browser_context(request: web.Request) -> web.Response:
    """POST /api/browser/contexts/close — close a browser context (Chrome tab
    group) by profile, or all of them.

    Body: ``{"profile": "<profile>"}`` to close one, or ``{"all": true}`` to
    close every registered context. The profile of a queen DM session is its
    session id (see lifecycle ``_get_or_create_context``). Reuses the same
    ``close_profile_context`` teardown the worker/colony reapers use. Lets a
    caller that stops a session (e.g. the eval harness) release the session's
    tab group, which is otherwise leaked because plain queen-session stop does
    not reap the browser context.
    """
    try:
        from gcu.browser.tools.lifecycle import close_profile_context, list_active_contexts
    except ImportError:
        return web.json_response({"available": False, "reason": "gcu browser tools not loaded"}, status=200)

    body = await request.json() if request.can_read_body else {}
    profiles: list[str]
    if body.get("all"):
        profiles = [c.get("profile") for c in list_active_contexts() if c.get("profile")]
    else:
        profile = body.get("profile")
        if not isinstance(profile, str) or not profile:
            return web.json_response({"error": "profile (or all=true) is required"}, status=400)
        profiles = [profile]

    results = []
    for p in profiles:
        try:
            results.append(await close_profile_context(p, reason="api_close"))
        except Exception as e:  # noqa: BLE001
            results.append({"profile": p, "ok": False, "error": str(e)})
    return web.json_response({"closed": results})


def register_routes(app: web.Application) -> None:
    """Register live worker control routes."""
    # Live worker control. The GET /workers list endpoint lives in
    # routes_colony_workers.py — it reads from session.colony (the
    # unified ColonyRuntime where run_worker-spawned workers
    # actually live) and returns the WorkerSummary shape the frontend
    # types against. Registering a duplicate here shadowed it in
    # aiohttp's router and broke the Sessions tab.
    app.router.add_get("/api/sessions/{session_id}/workers/stream", handle_live_workers_stream)
    app.router.add_post(
        "/api/sessions/{session_id}/workers/stop-all",
        handle_stop_all_live_workers,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/workers/{worker_id}/stop",
        handle_stop_live_worker,
    )
    # Test/introspection endpoints for verifying the worker-shutdown →
    # browser-reap ordering end-to-end. Read-only.
    app.router.add_get(
        "/api/sessions/{session_id}/workers/{worker_id}/reap-timeline",
        handle_worker_reap_timeline,
    )
    app.router.add_get("/api/browser/contexts", handle_browser_contexts)
    app.router.add_get("/api/browser/tabs", handle_browser_tabs)
    app.router.add_post("/api/browser/contexts/close", handle_close_browser_context)
