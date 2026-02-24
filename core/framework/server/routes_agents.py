"""Agent CRUD and discovery routes.

These routes provide backward compatibility with the frontend which addresses
agents by ID. Internally, all state is managed via SessionManager sessions.
"""

import logging
import time

from aiohttp import web

from framework.server.session_manager import Session, SessionManager

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> SessionManager:
    return request.app["manager"]


def _session_to_agent_dict(session: Session) -> dict:
    """Serialize a Session to the legacy agent JSON shape.

    The frontend expects agent responses with id, name, description, etc.
    This maps Session fields to that format for backward compat.
    """
    info = session.worker_info
    # Use worker_id if available (backward compat), otherwise session id
    agent_id = session.worker_id or session.id
    return {
        "id": agent_id,
        "agent_path": str(session.worker_path) if session.worker_path else "",
        "name": info.name if info else agent_id,
        "description": info.description if info else "",
        "goal": info.goal_name if info else "",
        "node_count": info.node_count if info else 0,
        "loaded_at": session.loaded_at,
        "uptime_seconds": round(time.time() - session.loaded_at, 1),
        "intro_message": getattr(session.runner, "intro_message", "") or "",
        "has_worker": session.worker_runtime is not None,
        "session_id": session.id,
    }


async def handle_discover(request: web.Request) -> web.Response:
    """GET /api/discover — discover agents from filesystem."""
    from framework.tui.screens.agent_picker import discover_agents

    manager = _get_manager(request)
    loaded_paths = {
        str(s.worker_path) for s in manager.list_sessions() if s.worker_path
    }

    groups = discover_agents()
    result = {}
    for category, entries in groups.items():
        result[category] = [
            {
                "path": str(entry.path),
                "name": entry.name,
                "description": entry.description,
                "category": entry.category,
                "session_count": entry.session_count,
                "node_count": entry.node_count,
                "tool_count": entry.tool_count,
                "tags": entry.tags,
                "last_active": entry.last_active,
                "is_loaded": str(entry.path) in loaded_paths,
            }
            for entry in entries
        ]
    return web.json_response(result)


async def handle_list_agents(request: web.Request) -> web.Response:
    """GET /api/agents — list all loaded agents (backward compat).

    Returns sessions that have a worker loaded.
    """
    manager = _get_manager(request)
    agents = [
        _session_to_agent_dict(s)
        for s in manager.list_sessions()
        if s.worker_runtime is not None
    ]
    return web.json_response({"agents": agents})


async def handle_load_agent(request: web.Request) -> web.Response:
    """POST /api/agents — load an agent from disk (backward compat).

    Creates a session with a worker in one step.
    Body: {"agent_path": "...", "agent_id": "...", "model": "..."}
    """
    manager = _get_manager(request)
    body = await request.json()

    agent_path = body.get("agent_path")
    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    agent_id = body.get("agent_id")
    model = body.get("model")

    try:
        session = await manager.create_session_with_worker(
            agent_path, agent_id=agent_id, model=model,
        )
    except ValueError as e:
        from pathlib import Path

        resolved_id = agent_id or Path(agent_path).name
        msg = str(e)

        if "currently loading" in msg:
            return web.json_response(
                {"error": msg, "id": resolved_id, "loading": True},
                status=409,
            )

        existing = manager.get_session_for_agent(resolved_id)
        if existing:
            return web.json_response(
                {"error": msg, **_session_to_agent_dict(existing)},
                status=409,
            )
        return web.json_response({"error": msg}, status=409)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.exception(f"Error loading agent: {e}")
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(_session_to_agent_dict(session), status=201)


async def handle_get_agent(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id} — get agent details."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        if manager.is_loading(agent_id):
            return web.json_response({"id": agent_id, "loading": True}, status=202)
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    data = _session_to_agent_dict(session)

    if session.worker_runtime:
        data["entry_points"] = [
            {
                "id": ep.id,
                "name": ep.name,
                "entry_node": ep.entry_node,
                "trigger_type": ep.trigger_type,
            }
            for ep in session.worker_runtime.get_entry_points()
        ]
        data["graphs"] = session.worker_runtime.list_graphs()

    return web.json_response(data)


async def handle_unload_agent(request: web.Request) -> web.Response:
    """DELETE /api/agents/{agent_id} — unload an agent (stops entire session)."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]

    # Find the session for this agent
    session = manager.get_session_for_agent(agent_id)
    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    await manager.stop_session(session.id)
    return web.json_response({"unloaded": agent_id})


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/stats — runtime statistics."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    stats = session.worker_runtime.get_stats() if session.worker_runtime else {}
    return web.json_response(stats)


async def handle_entry_points(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/entry-points — list entry points."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    eps = session.worker_runtime.get_entry_points() if session.worker_runtime else []
    return web.json_response(
        {
            "entry_points": [
                {
                    "id": ep.id,
                    "name": ep.name,
                    "entry_node": ep.entry_node,
                    "trigger_type": ep.trigger_type,
                }
                for ep in eps
            ]
        }
    )


async def handle_graphs(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/graphs — list loaded graphs."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    graphs = session.worker_runtime.list_graphs() if session.worker_runtime else []
    return web.json_response({"graphs": graphs})


def register_routes(app: web.Application) -> None:
    """Register agent CRUD routes on the application."""
    app.router.add_get("/api/discover", handle_discover)
    app.router.add_get("/api/agents", handle_list_agents)
    app.router.add_post("/api/agents", handle_load_agent)
    app.router.add_get("/api/agents/{agent_id}", handle_get_agent)
    app.router.add_delete("/api/agents/{agent_id}", handle_unload_agent)
    app.router.add_get("/api/agents/{agent_id}/stats", handle_stats)
    app.router.add_get("/api/agents/{agent_id}/entry-points", handle_entry_points)
    app.router.add_get("/api/agents/{agent_id}/graphs", handle_graphs)
