"""Agent CRUD and discovery routes."""

import logging
import time

from aiohttp import web

from framework.server.agent_manager import AgentManager

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> AgentManager:
    return request.app["manager"]


def _slot_to_dict(slot) -> dict:
    """Serialize an AgentSlot to a JSON-friendly dict."""
    info = slot.info
    return {
        "id": slot.id,
        "agent_path": str(slot.agent_path),
        "name": info.name if info else slot.id,
        "description": info.description if info else "",
        "goal": info.goal_name if info else "",
        "node_count": info.node_count if info else 0,
        "loaded_at": slot.loaded_at,
        "uptime_seconds": round(time.time() - slot.loaded_at, 1),
        "intro_message": getattr(slot.runner, "intro_message", "") or "",
    }


async def handle_queen_session(request: web.Request) -> web.Response:
    """POST /api/sessions/queen — start a queen-only session."""
    manager = _get_manager(request)
    body = await request.json() if request.can_read_body else {}
    model = body.get("model")
    session_id = body.get("session_id")

    try:
        slot = await manager.load_queen_session(session_id=session_id, model=model)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        logger.exception(f"Error starting queen session: {e}")
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(_slot_to_dict(slot), status=201)


async def handle_discover(request: web.Request) -> web.Response:
    """GET /api/discover — discover agents from filesystem."""
    from framework.tui.screens.agent_picker import discover_agents

    manager = _get_manager(request)
    loaded_paths = {str(slot.agent_path) for slot in manager.list_agents()}

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
    """GET /api/agents — list all loaded agents."""
    manager = _get_manager(request)
    agents = [_slot_to_dict(slot) for slot in manager.list_agents()]
    return web.json_response({"agents": agents})


async def handle_load_agent(request: web.Request) -> web.Response:
    """POST /api/agents — load an agent from disk.

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
        slot = await manager.load_agent(agent_path, agent_id=agent_id, model=model)
    except ValueError as e:
        from pathlib import Path

        resolved_id = agent_id or Path(agent_path).name
        msg = str(e)

        if "currently loading" in msg:
            # Agent is mid-load — tell frontend to poll until ready
            return web.json_response(
                {"error": msg, "id": resolved_id, "loading": True},
                status=409,
            )

        # Agent fully loaded — return its existing slot data
        existing = manager.get_agent(resolved_id)
        if existing:
            return web.json_response(
                {"error": msg, **_slot_to_dict(existing)},
                status=409,
            )
        return web.json_response({"error": msg}, status=409)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.exception(f"Error loading agent: {e}")
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(_slot_to_dict(slot), status=201)


async def handle_get_agent(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id} — get agent details."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        if manager.is_loading(agent_id):
            return web.json_response({"id": agent_id, "loading": True}, status=202)
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    data = _slot_to_dict(slot)

    # Add entry points
    if slot.runtime:
        data["entry_points"] = [
            {
                "id": ep.id,
                "name": ep.name,
                "entry_node": ep.entry_node,
                "trigger_type": ep.trigger_type,
            }
            for ep in slot.runtime.get_entry_points()
        ]
        data["graphs"] = slot.runtime.list_graphs()

    return web.json_response(data)


async def handle_unload_agent(request: web.Request) -> web.Response:
    """DELETE /api/agents/{agent_id} — unload an agent."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]

    removed = await manager.unload_agent(agent_id)
    if not removed:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    return web.json_response({"unloaded": agent_id})


async def handle_stats(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/stats — runtime statistics."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    stats = slot.runtime.get_stats() if slot.runtime else {}
    return web.json_response(stats)


async def handle_entry_points(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/entry-points — list entry points."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    eps = slot.runtime.get_entry_points() if slot.runtime else []
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
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    graphs = slot.runtime.list_graphs() if slot.runtime else []
    return web.json_response({"graphs": graphs})


def register_routes(app: web.Application) -> None:
    """Register agent CRUD routes on the application."""
    app.router.add_post("/api/sessions/queen", handle_queen_session)
    app.router.add_get("/api/discover", handle_discover)
    app.router.add_get("/api/agents", handle_list_agents)
    app.router.add_post("/api/agents", handle_load_agent)
    app.router.add_get("/api/agents/{agent_id}", handle_get_agent)
    app.router.add_delete("/api/agents/{agent_id}", handle_unload_agent)
    app.router.add_get("/api/agents/{agent_id}/stats", handle_stats)
    app.router.add_get("/api/agents/{agent_id}/entry-points", handle_entry_points)
    app.router.add_get("/api/agents/{agent_id}/graphs", handle_graphs)
