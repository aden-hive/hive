"""Log and observability routes — agent logs, node-scoped logs."""

import json
import logging

from aiohttp import web

from framework.server.app import resolve_session

logger = logging.getLogger(__name__)


async def handle_logs(request: web.Request) -> web.Response:
    """Session-level logs.

    Query params:
        session_id: Scope to a specific worker session (optional).
        level: "summary" | "details" | "tools" (default: "summary").
        limit: Max results when listing summaries (default: 20).
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    log_store = getattr(session.worker_runtime, "_runtime_log_store", None)
    if log_store is None:
        return web.json_response({"error": "Logging not enabled for this agent"}, status=404)

    worker_session_id = request.query.get("session_id")
    level = request.query.get("level", "summary")
    try:
        limit = min(int(request.query.get("limit", "20")), 1000)
    except (ValueError, TypeError):
        limit = 20

    if not worker_session_id:
        summaries = await log_store.list_runs(limit=limit)
        return web.json_response(
            {"logs": [s.model_dump() for s in summaries]},
            dumps=lambda obj: json.dumps(obj, default=str),
        )

    if level == "details":
        details = await log_store.load_details(worker_session_id)
        if details is None:
            return web.json_response({"error": "No detail logs found"}, status=404)
        return web.json_response(
            {"session_id": worker_session_id, "nodes": [n.model_dump() for n in details.nodes]},
            dumps=lambda obj: json.dumps(obj, default=str),
        )
    elif level == "tools":
        tool_logs = await log_store.load_tool_logs(worker_session_id)
        if tool_logs is None:
            return web.json_response({"error": "No tool logs found"}, status=404)
        return web.json_response(
            {"session_id": worker_session_id, "steps": [s.model_dump() for s in tool_logs.steps]},
            dumps=lambda obj: json.dumps(obj, default=str),
        )
    else:
        summary = await log_store.load_summary(worker_session_id)
        if summary is None:
            return web.json_response({"error": "No summary log found"}, status=404)
        return web.json_response(
            summary.model_dump(),
            dumps=lambda obj: json.dumps(obj, default=str),
        )


async def handle_node_logs(request: web.Request) -> web.Response:
    """Node-scoped logs."""
    session, err = resolve_session(request)
    if err:
        return err

    node_id = request.match_info["node_id"]

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    log_store = getattr(session.worker_runtime, "_runtime_log_store", None)
    if log_store is None:
        return web.json_response({"error": "Logging not enabled"}, status=404)

    worker_session_id = request.query.get("session_id")
    if not worker_session_id:
        return web.json_response({"error": "session_id query param is required"}, status=400)

    level = request.query.get("level", "all")
    result: dict = {"session_id": worker_session_id, "node_id": node_id}

    if level in ("details", "all"):
        details = await log_store.load_details(worker_session_id)
        if details:
            result["details"] = [n.model_dump() for n in details.nodes if n.node_id == node_id]

    if level in ("tools", "all"):
        tool_logs = await log_store.load_tool_logs(worker_session_id)
        if tool_logs:
            result["tool_logs"] = [s.model_dump() for s in tool_logs.steps if s.node_id == node_id]

    return web.json_response(result, dumps=lambda obj: json.dumps(obj, default=str))


def register_routes(app: web.Application) -> None:
    """Register log routes."""
    # Session-primary routes
    app.router.add_get("/api/sessions/{session_id}/logs", handle_logs)
    app.router.add_get(
        "/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}/logs",
        handle_node_logs,
    )
