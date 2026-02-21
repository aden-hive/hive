"""Graph and node inspection routes — node list, node detail, node criteria."""

import json
import logging

from aiohttp import web

from framework.server.agent_manager import AgentManager
from framework.server.app import safe_path_segment

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> AgentManager:
    return request.app["manager"]


def _get_graph_spec(slot, graph_id: str):
    """Get GraphSpec for a graph_id. Returns (graph_spec, None) or (None, error_response)."""
    reg = slot.runtime.get_graph_registration(graph_id)
    if reg is None:
        return None, web.json_response({"error": f"Graph '{graph_id}' not found"}, status=404)
    return reg.graph, None


def _node_to_dict(node) -> dict:
    """Serialize a NodeSpec to a JSON-friendly dict."""
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
    }


async def handle_list_nodes(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/graphs/{graph_id}/nodes — list nodes.

    Returns all nodes in the graph with their static spec. If a session_id
    query param is provided, enriches each node with runtime status from
    the session's progress data.
    """
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    graph_id = request.match_info["graph_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    graph, err = _get_graph_spec(slot, graph_id)
    if err:
        return err

    nodes = [_node_to_dict(n) for n in graph.nodes]

    # Optionally enrich with session progress
    session_id = request.query.get("session_id")
    if session_id:
        session_id = safe_path_segment(session_id)
        from pathlib import Path

        state_path = (
            Path.home()
            / ".hive"
            / "agents"
            / slot.agent_path.name
            / "sessions"
            / session_id
            / "state.json"
        )
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
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
                pass  # Skip enrichment on error

    return web.json_response({"nodes": nodes})


async def handle_get_node(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/graphs/{graph_id}/nodes/{node_id} — node detail."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    graph_id = request.match_info["graph_id"]
    node_id = request.match_info["node_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    graph, err = _get_graph_spec(slot, graph_id)
    if err:
        return err

    node_spec = graph.get_node(node_id)
    if node_spec is None:
        return web.json_response({"error": f"Node '{node_id}' not found"}, status=404)

    data = _node_to_dict(node_spec)

    # Include edges originating from this node
    edges = [
        {"target": e.target, "condition": e.condition, "priority": e.priority}
        for e in graph.edges
        if e.source == node_id
    ]
    data["edges"] = edges

    return web.json_response(data)


async def handle_node_criteria(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/graphs/{graph_id}/nodes/{node_id}/criteria

    Returns the success criteria for a node plus any judge verdicts from
    logs (if session_id is provided).
    """
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    graph_id = request.match_info["graph_id"]
    node_id = request.match_info["node_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    graph, err = _get_graph_spec(slot, graph_id)
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

    # If session_id provided, look for judge verdicts in logs
    session_id = request.query.get("session_id")
    if session_id:
        log_store = getattr(slot.runtime, "_runtime_log_store", None)
        if log_store:
            details = await log_store.load_details(session_id)
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


def register_routes(app: web.Application) -> None:
    """Register graph/node inspection routes."""
    app.router.add_get("/api/agents/{agent_id}/graphs/{graph_id}/nodes", handle_list_nodes)
    app.router.add_get("/api/agents/{agent_id}/graphs/{graph_id}/nodes/{node_id}", handle_get_node)
    app.router.add_get(
        "/api/agents/{agent_id}/graphs/{graph_id}/nodes/{node_id}/criteria",
        handle_node_criteria,
    )
