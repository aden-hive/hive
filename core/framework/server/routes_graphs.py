"""Graph and node inspection routes — node list, node detail, node criteria."""

import json
import logging
import time

from aiohttp import web

from framework.server.app import resolve_session, safe_path_segment

logger = logging.getLogger(__name__)


def _get_graph_registration(session, graph_id: str):
    """Get _GraphRegistration for a graph_id. Returns (reg, None) or (None, error_response)."""
    if not session.graph_runtime:
        return None, web.json_response({"error": "No worker loaded in this session"}, status=503)
    reg = session.graph_runtime.get_graph_registration(graph_id)
    if reg is None:
        return None, web.json_response({"error": f"Graph '{graph_id}' not found"}, status=404)
    return reg, None


def _get_graph_spec(session, graph_id: str):
    """Get GraphSpec for a graph_id. Returns (graph_spec, None) or (None, error_response)."""
    reg, err = _get_graph_registration(session, graph_id)
    if err:
        return None, err
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
        "system_prompt": node.system_prompt or "",
        "sub_agents": getattr(node, "sub_agents", []),
    }


async def handle_list_nodes(request: web.Request) -> web.Response:
    """List nodes in a graph."""
    session, err = resolve_session(request)
    if err:
        return err

    graph_id = request.match_info["graph_id"]
    reg, err = _get_graph_registration(session, graph_id)
    if err:
        return err

    graph = reg.graph
    nodes = [_node_to_dict(n) for n in graph.nodes]

    # Optionally enrich with session progress
    worker_session_id = request.query.get("session_id")
    if worker_session_id and session.worker_path:
        worker_session_id = safe_path_segment(worker_session_id)
        from pathlib import Path

        state_path = (
            Path.home()
            / ".hive"
            / "agents"
            / session.worker_path.name
            / "sessions"
            / worker_session_id
            / "state.json"
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
        {"source": e.source, "target": e.target, "condition": e.condition, "priority": e.priority}
        for e in graph.edges
    ]
    rt = session.graph_runtime
    entry_points = [
        {
            "id": ep.id,
            "name": ep.name,
            "entry_node": ep.entry_node,
            "trigger_type": ep.trigger_type,
            "trigger_config": ep.trigger_config,
            **(
                {"next_fire_in": nf}
                if rt and (nf := rt.get_timer_next_fire_in(ep.id)) is not None
                else {}
            ),
        }
        for ep in reg.entry_points.values()
    ]
    # Append triggers from triggers.json (stored on session)
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

    graph_id = request.match_info["graph_id"]
    node_id = request.match_info["node_id"]

    graph, err = _get_graph_spec(session, graph_id)
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

    graph_id = request.match_info["graph_id"]
    node_id = request.match_info["node_id"]

    graph, err = _get_graph_spec(session, graph_id)
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
    if worker_session_id and session.graph_runtime:
        log_store = getattr(session.graph_runtime, "_runtime_log_store", None)
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

    graph_id = request.match_info["graph_id"]
    node_id = request.match_info["node_id"]

    graph, err = _get_graph_spec(session, graph_id)
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


async def handle_draft_graph(request: web.Request) -> web.Response:
    """Return the current draft graph from planning phase (if any)."""
    session, err = resolve_session(request)
    if err:
        return err

    phase_state = getattr(session, "phase_state", None)
    if phase_state is None or phase_state.draft_graph is None:
        return web.json_response({"draft": None})

    return web.json_response({"draft": phase_state.draft_graph})


async def handle_flowchart_map(request: web.Request) -> web.Response:
    """Return the flowchart→runtime node mapping and the original (pre-dissolution) draft.

    Available after confirm_and_build() dissolves decision nodes, or loaded
    from the agent's flowchart.json file, or synthesized from the runtime graph.
    """
    session, err = resolve_session(request)
    if err:
        return err

    phase_state = getattr(session, "phase_state", None)

    # Fast path: already in memory
    if phase_state is not None and phase_state.original_draft_graph is not None:
        return web.json_response(
            {
                "map": phase_state.flowchart_map,
                "original_draft": phase_state.original_draft_graph,
            }
        )

    # Try loading from flowchart.json in the agent folder
    worker_path = getattr(session, "worker_path", None)
    if worker_path is not None:
        from pathlib import Path

        target = Path(worker_path) / "flowchart.json"
        if target.is_file():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                original_draft = data.get("original_draft")
                fmap = data.get("flowchart_map")
                # Cache in phase_state for future requests
                if phase_state is not None and original_draft:
                    phase_state.original_draft_graph = original_draft
                    phase_state.flowchart_map = fmap
                return web.json_response(
                    {
                        "map": fmap,
                        "original_draft": original_draft,
                    }
                )
            except Exception:
                logger.warning("Failed to read flowchart.json from %s", worker_path)

    return web.json_response({"map": None, "original_draft": None})


def register_routes(app: web.Application) -> None:
    """Register graph/node inspection routes."""
    # Draft graph (planning phase — visual only, no loaded worker required)
    app.router.add_get("/api/sessions/{session_id}/draft-graph", handle_draft_graph)
    # Flowchart map (post-dissolution — maps runtime nodes to original draft nodes)
    app.router.add_get("/api/sessions/{session_id}/flowchart-map", handle_flowchart_map)
    # Session-primary routes
    app.router.add_get("/api/sessions/{session_id}/graphs/{graph_id}/nodes", handle_list_nodes)
    app.router.add_get(
        "/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}", handle_get_node
    )
    app.router.add_get(
        "/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}/criteria",
        handle_node_criteria,
    )
    app.router.add_get(
        "/api/sessions/{session_id}/graphs/{graph_id}/nodes/{node_id}/tools",
        handle_node_tools,
    )
