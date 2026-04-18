"""Worker inspection routes — node list, node detail, node criteria, node tools."""

import json
import logging
import time

from aiohttp import web

from framework.server.app import resolve_session, safe_path_segment

logger = logging.getLogger(__name__)


def _get_worker_registration(session, colony_id: str):
    """Get _GraphRegistration for a colony_id. Returns (reg, None) or (None, error_response)."""
    if not session.colony_runtime:
        return None, web.json_response({"error": "No worker loaded in this session"}, status=503)
    reg = session.colony_runtime.get_graph_registration(colony_id)
    if reg is None:
        return None, web.json_response({"error": f"Colony '{colony_id}' not found"}, status=404)
    return reg, None


def _get_worker_spec(session, colony_id: str):
    """Get the agent spec for a colony_id. Returns (spec, None) or (None, error_response)."""
    reg, err = _get_worker_registration(session, colony_id)
    if err:
        return None, err
    return reg.graph, None


def _node_to_dict(node) -> dict:
    """Serialize a node spec to a JSON-friendly dict."""
    return {
        "id": node.id,
        "name": node.name,
        "description": node.description,
        "node_type": node.node_type,
        "input_keys": node.input_keys,
        "output_keys": node.output_keys,
        "nullable_output_keys": node.nullable_output_keys,
        "tools": node.tools,
        "routes": node.routes,
        "max_retries": node.max_retries,
        "max_node_visits": node.max_node_visits,
        "client_facing": node.client_facing,
        "success_criteria": node.success_criteria,
        "system_prompt": node.system_prompt or "",
        "sub_agents": getattr(node, "sub_agents", []),
    }


async def handle_list_nodes(request: web.Request) -> web.Response:
    """List nodes in a worker."""
    session, err = resolve_session(request)
    if err:
        return err

    colony_id = request.match_info["colony_id"]
    reg, err = _get_worker_registration(session, colony_id)
    if err:
        return err

    graph = reg.graph
    nodes = [_node_to_dict(n) for n in graph.nodes]

    worker_session_id = request.query.get("session_id")
    if worker_session_id and session.worker_path:
        worker_session_id = safe_path_segment(worker_session_id)
        from pathlib import Path

        state_path = (
            Path.home() / ".hive" / "agents" / session.worker_path.name / "sessions" / worker_session_id / "state.json"
        )
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                progress = state.get("progress", {})
                visit_counts = progress.get("node_visit_counts", {})
                failures = progress.get("nodes_with_failures", [])
                current = progress.get("current_node")
                path = progress.get("path", [])

                for node in nodes:
                    nid = node["id"]
                    node["visit_count"] = visit_counts.get(nid, 0)
                    node["has_failures"] = nid in failures
                    node["is_current"] = nid == current
                    node["in_path"] = nid in path
            except (json.JSONDecodeError, OSError):
                pass

    edges = [
        {"source": e.source, "target": e.target, "condition": e.condition, "priority": e.priority} for e in graph.edges
    ]
    rt = session.colony_runtime
    entry_points = [
        {
            "id": ep.id,
            "name": ep.name,
            "entry_node": ep.entry_node,
            "trigger_type": ep.trigger_type,
            "trigger_config": ep.trigger_config,
            **({"next_fire_in": nf} if rt and (nf := rt.get_timer_next_fire_in(ep.id)) is not None else {}),
        }
        for ep in reg.entry_points.values()
    ]
    for t in getattr(session, "available_triggers", {}).values():
        entry = {
            "id": t.id,
            "name": t.description or t.id,
            "entry_node": graph.entry_node,
            "trigger_type": t.trigger_type,
            "trigger_config": t.trigger_config,
            "task": t.task,
        }
        mono = getattr(session, "trigger_next_fire", {}).get(t.id)
        if mono is not None:
            entry["next_fire_in"] = max(0.0, mono - time.monotonic())
        entry_points.append(entry)
    return web.json_response(
        {
            "nodes": nodes,
            "edges": edges,
            "entry_node": graph.entry_node,
            "entry_points": entry_points,
        }
    )


async def handle_get_node(request: web.Request) -> web.Response:
    """Get node detail."""
    session, err = resolve_session(request)
    if err:
        return err

    colony_id = request.match_info["colony_id"]
    node_id = request.match_info["node_id"]

    graph, err = _get_worker_spec(session, colony_id)
    if err:
        return err

    node_spec = graph.get_node(node_id)
    if node_spec is None:
        return web.json_response({"error": f"Node '{node_id}' not found"}, status=404)

    data = _node_to_dict(node_spec)
    edges = [
        {"target": e.target, "condition": e.condition, "priority": e.priority}
        for e in graph.edges
        if e.source == node_id
    ]
    data["edges"] = edges

    return web.json_response(data)


async def handle_node_criteria(request: web.Request) -> web.Response:
    """Get node success criteria and last execution info."""
    session, err = resolve_session(request)
    if err:
        return err

    colony_id = request.match_info["colony_id"]
    node_id = request.match_info["node_id"]

    graph, err = _get_worker_spec(session, colony_id)
    if err:
        return err

    node_spec = graph.get_node(node_id)
    if node_spec is None:
        return web.json_response({"error": f"Node '{node_id}' not found"}, status=404)

    result: dict = {
        "node_id": node_id,
        "success_criteria": node_spec.success_criteria,
        "output_keys": node_spec.output_keys,
    }

    worker_session_id = request.query.get("session_id")
    if worker_session_id and session.colony_runtime:
        log_store = getattr(session.colony_runtime, "_runtime_log_store", None)
        if log_store:
            details = await log_store.load_details(worker_session_id)
            if details:
                node_details = [n for n in details.nodes if n.node_id == node_id]
                if node_details:
                    latest = node_details[-1]
                    result["last_execution"] = {
                        "success": latest.success,
                        "error": latest.error,
                        "retry_count": latest.retry_count,
                        "needs_attention": latest.needs_attention,
                        "attention_reasons": latest.attention_reasons,
                    }

    return web.json_response(result, dumps=lambda obj: json.dumps(obj, default=str))


async def handle_node_tools(request: web.Request) -> web.Response:
    """Get tools available to a node."""
    session, err = resolve_session(request)
    if err:
        return err

    colony_id = request.match_info["colony_id"]
    node_id = request.match_info["node_id"]

    graph, err = _get_worker_spec(session, colony_id)
    if err:
        return err

    node_spec = graph.get_node(node_id)
    if node_spec is None:
        return web.json_response({"error": f"Node '{node_id}' not found"}, status=404)

    tools_out = []
    registry = getattr(session.runner, "_tool_registry", None) if session.runner else None
    all_tools = registry.get_tools() if registry else {}

    for name in node_spec.tools:
        tool = all_tools.get(name)
        if tool:
            tools_out.append(
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                }
            )
        else:
            tools_out.append({"name": name, "description": "", "parameters": {}})

    return web.json_response({"tools": tools_out})


# ---------------------------------------------------------------------------
# Live worker control — list / stop a specific worker / stop all
# ---------------------------------------------------------------------------


def _active_colony(session):
    """Return the session's unified ColonyRuntime (``session.colony``) if present.

    All spawned workers (queen-overseer + run_parallel_workers fan-outs)
    are hosted here. ``session.colony_runtime`` is a different concept
    (loaded agent graph) and doesn't hold the live worker registry we
    need to enumerate / stop.
    """
    return getattr(session, "colony", None)


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
            colony = _active_colony(session)
            workers = _build_live_workers_payload(colony)
            signature = _payload_change_signature(workers)
            if signature != last_signature:
                await _send("snapshot", {"workers": workers})
                last_signature = signature
            await asyncio.sleep(2.0)
    except (asyncio.CancelledError, ConnectionResetError):
        raise
    except Exception as exc:
        logger.warning("live workers stream error: %s", exc, exc_info=True)
    return resp


async def handle_stop_live_worker(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/workers/{worker_id}/stop — force-stop one worker.

    Calls ``colony.stop_worker(worker_id)`` which cancels the worker's
    background task. The worker's terminal SUBAGENT_REPORT still fires
    (preserving any _explicit_report) so the queen sees a `[WORKER_REPORT]`
    with ``status="stopped"``.
    """
    session, err = resolve_session(request)
    if err:
        return err

    worker_id = request.match_info.get("worker_id", "")
    if not worker_id:
        return web.json_response({"error": "worker_id required"}, status=400)

    colony = _active_colony(session)
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
        await colony.stop_worker(worker_id)
    except Exception as exc:
        logger.exception("stop_worker failed for %s", worker_id)
        return web.json_response(
            {"stopped": False, "error": str(exc), "worker_id": worker_id},
            status=500,
        )

    return web.json_response({"stopped": True, "worker_id": worker_id})


async def handle_stop_all_live_workers(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/workers/stop-all — force-stop every active worker.

    The persistent overseer (if any) is skipped — it is the queen itself
    and stopping it would end the session. Only ephemeral fan-out workers
    are targeted.
    """
    session, err = resolve_session(request)
    if err:
        return err

    colony = _active_colony(session)
    if colony is None:
        return web.json_response({"stopped": [], "error": "No active colony on this session"})

    stopped: list[str] = []
    errors: list[dict] = []
    try:
        workers = list(colony._workers.values())  # type: ignore[attr-defined]
    except Exception:
        workers = []

    for w in workers:
        if not w.is_active:
            continue
        if getattr(w, "_persistent", False):
            # The overseer — don't kill the queen.
            continue
        try:
            await colony.stop_worker(w.id)
            stopped.append(w.id)
        except Exception as exc:
            logger.warning("stop-all: failed to stop %s: %s", w.id, exc)
            errors.append({"worker_id": w.id, "error": str(exc)})

    return web.json_response(
        {
            "stopped": stopped,
            "stopped_count": len(stopped),
            "errors": errors if errors else None,
        }
    )


def register_routes(app: web.Application) -> None:
    """Register worker inspection routes."""
    app.router.add_get("/api/sessions/{session_id}/colonies/{colony_id}/nodes", handle_list_nodes)
    app.router.add_get("/api/sessions/{session_id}/colonies/{colony_id}/nodes/{node_id}", handle_get_node)
    app.router.add_get(
        "/api/sessions/{session_id}/colonies/{colony_id}/nodes/{node_id}/criteria",
        handle_node_criteria,
    )
    app.router.add_get(
        "/api/sessions/{session_id}/colonies/{colony_id}/nodes/{node_id}/tools",
        handle_node_tools,
    )
    # Live worker control. The GET /workers list endpoint lives in
    # routes_colony_workers.py — it reads from session.colony (the
    # unified ColonyRuntime where run_parallel_workers-spawned workers
    # actually live) and returns the WorkerSummary shape the frontend
    # types against. Registering a duplicate here shadowed it in
    # aiohttp's router and broke the Sessions tab.
    app.router.add_get(
        "/api/sessions/{session_id}/workers/stream", handle_live_workers_stream
    )
    app.router.add_post(
        "/api/sessions/{session_id}/workers/stop-all",
        handle_stop_all_live_workers,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/workers/{worker_id}/stop",
        handle_stop_live_worker,
    )
