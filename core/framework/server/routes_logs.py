"""Log and observability routes — agent logs, node-scoped logs."""

import json
import logging
from pathlib import Path

from aiohttp import web

from framework.server.agent_manager import AgentManager

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> AgentManager:
    return request.app["manager"]


def _storage_path(slot) -> Path:
    """Resolve the storage root for an agent slot."""
    agent_name = slot.agent_path.name
    return Path.home() / ".hive" / "agents" / agent_name


async def handle_logs(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/logs — agent-level logs.

    Query params:
        session_id: Scope to a specific session (optional).
        level: "summary" | "details" | "tools" (default: "summary").
        limit: Max results when listing summaries (default: 20).

    Without session_id: returns list of run summaries.
    With session_id: returns the requested log level for that session.
    """
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    log_store = getattr(slot.runtime, "_runtime_log_store", None)
    if log_store is None:
        return web.json_response({"error": "Logging not enabled for this agent"}, status=404)

    session_id = request.query.get("session_id")
    level = request.query.get("level", "summary")
    limit = int(request.query.get("limit", "20"))

    if not session_id:
        # List run summaries across all sessions
        summaries = await log_store.list_runs(limit=limit)
        return web.json_response(
            {"logs": [s.model_dump() for s in summaries]},
            dumps=lambda obj: json.dumps(obj, default=str),
        )

    # Scoped to a specific session
    if level == "details":
        details = await log_store.load_details(session_id)
        if details is None:
            return web.json_response({"error": "No detail logs found"}, status=404)
        return web.json_response(
            {"session_id": session_id, "nodes": [n.model_dump() for n in details.nodes]},
            dumps=lambda obj: json.dumps(obj, default=str),
        )
    elif level == "tools":
        tool_logs = await log_store.load_tool_logs(session_id)
        if tool_logs is None:
            return web.json_response({"error": "No tool logs found"}, status=404)
        return web.json_response(
            {"session_id": session_id, "steps": [s.model_dump() for s in tool_logs.steps]},
            dumps=lambda obj: json.dumps(obj, default=str),
        )
    else:
        # Default: summary
        summary = await log_store.load_summary(session_id)
        if summary is None:
            return web.json_response({"error": "No summary log found"}, status=404)
        return web.json_response(
            summary.model_dump(),
            dumps=lambda obj: json.dumps(obj, default=str),
        )


async def handle_node_logs(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/graphs/{graph_id}/nodes/{node_id}/logs

    Node-scoped logs. Returns detail and tool log entries filtered to the
    specified node.

    Query params:
        session_id: Required — which session's logs to read.
        level: "details" | "tools" | "all" (default: "all").
    """
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    node_id = request.match_info["node_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    log_store = getattr(slot.runtime, "_runtime_log_store", None)
    if log_store is None:
        return web.json_response({"error": "Logging not enabled"}, status=404)

    session_id = request.query.get("session_id")
    if not session_id:
        return web.json_response({"error": "session_id query param is required"}, status=400)

    level = request.query.get("level", "all")
    result: dict = {"session_id": session_id, "node_id": node_id}

    if level in ("details", "all"):
        details = await log_store.load_details(session_id)
        if details:
            result["details"] = [n.model_dump() for n in details.nodes if n.node_id == node_id]

    if level in ("tools", "all"):
        tool_logs = await log_store.load_tool_logs(session_id)
        if tool_logs:
            result["tool_logs"] = [s.model_dump() for s in tool_logs.steps if s.node_id == node_id]

    return web.json_response(result, dumps=lambda obj: json.dumps(obj, default=str))


def register_routes(app: web.Application) -> None:
    """Register log routes."""
    app.router.add_get("/api/agents/{agent_id}/logs", handle_logs)
    app.router.add_get(
        "/api/agents/{agent_id}/graphs/{graph_id}/nodes/{node_id}/logs",
        handle_node_logs,
    )
