"""Session lifecycle and browsing routes.

New session-primary routes:
- POST /api/sessions — create a session (queen-only)
- GET  /api/sessions — list all sessions
- POST /api/sessions/{session_id}/worker — load a worker into session
- DELETE /api/sessions/{session_id}/worker — unload worker from session
- DELETE /api/sessions/{session_id} — stop session entirely

Legacy worker session browsing routes (backward compat):
- GET /api/agents/{agent_id}/sessions — list worker sessions on disk
- GET /api/agents/{agent_id}/sessions/{session_id} — session detail
- DELETE /api/agents/{agent_id}/sessions/{session_id} — delete session
- GET /api/agents/{agent_id}/sessions/{session_id}/checkpoints
- POST /api/agents/{agent_id}/sessions/{session_id}/checkpoints/{cp_id}/restore
- GET /api/agents/{agent_id}/sessions/{session_id}/messages
"""

import json
import logging
import shutil
import time

from aiohttp import web

from framework.server.app import safe_path_segment, sessions_dir
from framework.server.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> SessionManager:
    return request.app["manager"]


# ------------------------------------------------------------------
# New session-primary routes
# ------------------------------------------------------------------


async def handle_create_session(request: web.Request) -> web.Response:
    """POST /api/sessions — create a queen-only session.

    Body: {"session_id": "..." (optional), "model": "..." (optional)}
    """
    manager = _get_manager(request)
    body = await request.json() if request.can_read_body else {}
    session_id = body.get("session_id")
    model = body.get("model")

    try:
        session = await manager.create_session(session_id=session_id, model=model)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        logger.exception(f"Error creating session: {e}")
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(
        {
            "session_id": session.id,
            "has_worker": session.worker_runtime is not None,
            "loaded_at": session.loaded_at,
        },
        status=201,
    )


async def handle_list_live_sessions(request: web.Request) -> web.Response:
    """GET /api/sessions — list all active sessions."""
    manager = _get_manager(request)
    sessions = []
    for s in manager.list_sessions():
        sessions.append(
            {
                "session_id": s.id,
                "worker_id": s.worker_id,
                "has_worker": s.worker_runtime is not None,
                "loaded_at": s.loaded_at,
                "uptime_seconds": round(time.time() - s.loaded_at, 1),
            }
        )
    return web.json_response({"sessions": sessions})


async def handle_load_worker(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/worker — load a worker into a session.

    Body: {"agent_path": "...", "worker_id": "..." (optional), "model": "..." (optional)}
    """
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    body = await request.json()

    agent_path = body.get("agent_path")
    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    worker_id = body.get("worker_id")
    model = body.get("model")

    try:
        session = await manager.load_worker(
            session_id, agent_path, worker_id=worker_id, model=model,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.exception(f"Error loading worker: {e}")
        return web.json_response({"error": str(e)}, status=500)

    info = session.worker_info
    return web.json_response(
        {
            "session_id": session.id,
            "worker_id": session.worker_id,
            "worker_name": info.name if info else session.worker_id,
            "worker_description": info.description if info else "",
        }
    )


async def handle_unload_worker(request: web.Request) -> web.Response:
    """DELETE /api/sessions/{session_id}/worker — unload worker, keep queen alive."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]

    removed = await manager.unload_worker(session_id)
    if not removed:
        session = manager.get_session(session_id)
        if session is None:
            return web.json_response({"error": f"Session '{session_id}' not found"}, status=404)
        return web.json_response({"error": "No worker loaded in this session"}, status=409)

    return web.json_response({"session_id": session_id, "worker_unloaded": True})


async def handle_stop_session(request: web.Request) -> web.Response:
    """DELETE /api/sessions/{session_id} — stop a session entirely."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]

    stopped = await manager.stop_session(session_id)
    if not stopped:
        return web.json_response({"error": f"Session '{session_id}' not found"}, status=404)

    return web.json_response({"session_id": session_id, "stopped": True})


# ------------------------------------------------------------------
# Legacy worker session browsing routes (unchanged URLs)
# ------------------------------------------------------------------


async def handle_list_sessions(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/sessions — list worker sessions on disk."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not session.worker_path:
        return web.json_response({"sessions": []})

    sess_dir = sessions_dir(session)
    if not sess_dir.exists():
        return web.json_response({"sessions": []})

    sessions = []
    for d in sorted(sess_dir.iterdir(), reverse=True):
        if not d.is_dir() or not d.name.startswith("session_"):
            continue

        entry: dict = {"session_id": d.name}

        state_path = d / "state.json"
        if state_path.exists():
            try:
                state = json.loads(state_path.read_text())
                entry["status"] = state.get("status", "unknown")
                entry["started_at"] = state.get("started_at")
                entry["completed_at"] = state.get("completed_at")
                progress = state.get("progress", {})
                entry["steps"] = progress.get("steps_executed", 0)
                entry["paused_at"] = progress.get("paused_at")
            except (json.JSONDecodeError, OSError):
                entry["status"] = "error"

        cp_dir = d / "checkpoints"
        if cp_dir.exists():
            entry["checkpoint_count"] = sum(1 for f in cp_dir.iterdir() if f.suffix == ".json")
        else:
            entry["checkpoint_count"] = 0

        sessions.append(entry)

    return web.json_response({"sessions": sessions})


async def handle_get_session(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/sessions/{session_id} — session detail."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    worker_session_id = safe_path_segment(request.match_info["session_id"])
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    state_path = sessions_dir(session) / worker_session_id / "state.json"
    if not state_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return web.json_response({"error": f"Failed to read session: {e}"}, status=500)

    return web.json_response(state)


async def handle_list_checkpoints(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/sessions/{session_id}/checkpoints"""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    worker_session_id = safe_path_segment(request.match_info["session_id"])
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    cp_dir = sessions_dir(session) / worker_session_id / "checkpoints"
    if not cp_dir.exists():
        return web.json_response({"checkpoints": []})

    checkpoints = []
    for f in sorted(cp_dir.iterdir(), reverse=True):
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text())
            checkpoints.append(
                {
                    "checkpoint_id": f.stem,
                    "current_node": data.get("current_node"),
                    "next_node": data.get("next_node"),
                    "is_clean": data.get("is_clean", False),
                    "timestamp": data.get("timestamp"),
                }
            )
        except (json.JSONDecodeError, OSError):
            checkpoints.append({"checkpoint_id": f.stem, "error": "unreadable"})

    return web.json_response({"checkpoints": checkpoints})


async def handle_delete_session(request: web.Request) -> web.Response:
    """DELETE /api/agents/{agent_id}/sessions/{session_id} — delete a worker session."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    worker_session_id = safe_path_segment(request.match_info["session_id"])
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    session_path = sessions_dir(session) / worker_session_id
    if not session_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    shutil.rmtree(session_path)
    return web.json_response({"deleted": worker_session_id})


async def handle_restore_checkpoint(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/sessions/{session_id}/checkpoints/{checkpoint_id}/restore"""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    worker_session_id = safe_path_segment(request.match_info["session_id"])
    checkpoint_id = safe_path_segment(request.match_info["checkpoint_id"])
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    cp_path = sessions_dir(session) / worker_session_id / "checkpoints" / f"{checkpoint_id}.json"
    if not cp_path.exists():
        return web.json_response({"error": "Checkpoint not found"}, status=404)

    entry_points = session.worker_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    restore_session_state = {
        "resume_session_id": worker_session_id,
        "resume_from_checkpoint": checkpoint_id,
    }

    execution_id = await session.worker_runtime.trigger(
        entry_points[0].id,
        input_data={},
        session_state=restore_session_state,
    )

    return web.json_response(
        {
            "execution_id": execution_id,
            "restored_from": worker_session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


async def handle_messages(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/sessions/{session_id}/messages"""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    worker_session_id = safe_path_segment(request.match_info["session_id"])
    session = manager.get_session_for_agent(agent_id)

    if session is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    convs_dir = sessions_dir(session) / worker_session_id / "conversations"
    if not convs_dir.exists():
        return web.json_response({"messages": []})

    filter_node = request.query.get("node_id")
    all_messages = []

    for node_dir in convs_dir.iterdir():
        if not node_dir.is_dir():
            continue
        if filter_node and node_dir.name != filter_node:
            continue

        parts_dir = node_dir / "parts"
        if not parts_dir.exists():
            continue

        for part_file in sorted(parts_dir.iterdir()):
            if part_file.suffix != ".json":
                continue
            try:
                part = json.loads(part_file.read_text())
                part["_node_id"] = node_dir.name
                all_messages.append(part)
            except (json.JSONDecodeError, OSError):
                continue

    all_messages.sort(key=lambda m: m.get("seq", 0))

    client_only = request.query.get("client_only", "").lower() in ("true", "1")
    if client_only:
        client_facing_nodes: set[str] = set()
        if session.runner and hasattr(session.runner, "graph"):
            for node in session.runner.graph.nodes:
                if node.client_facing:
                    client_facing_nodes.add(node.id)

        if client_facing_nodes:
            all_messages = [
                m
                for m in all_messages
                if not m.get("is_transition_marker")
                and m["role"] != "tool"
                and not (m["role"] == "assistant" and m.get("tool_calls"))
                and (
                    (m["role"] == "user" and m.get("is_client_input"))
                    or (m["role"] == "assistant" and m.get("_node_id") in client_facing_nodes)
                )
            ]

    return web.json_response({"messages": all_messages})


def register_routes(app: web.Application) -> None:
    """Register session routes."""
    # New session-primary routes
    app.router.add_post("/api/sessions", handle_create_session)
    app.router.add_get("/api/sessions", handle_list_live_sessions)
    app.router.add_post("/api/sessions/{session_id}/worker", handle_load_worker)
    app.router.add_delete("/api/sessions/{session_id}/worker", handle_unload_worker)
    app.router.add_delete("/api/sessions/{session_id}", handle_stop_session)

    # Legacy worker session browsing routes
    app.router.add_get("/api/agents/{agent_id}/sessions", handle_list_sessions)
    app.router.add_get("/api/agents/{agent_id}/sessions/{session_id}", handle_get_session)
    app.router.add_delete("/api/agents/{agent_id}/sessions/{session_id}", handle_delete_session)
    app.router.add_get(
        "/api/agents/{agent_id}/sessions/{session_id}/checkpoints",
        handle_list_checkpoints,
    )
    app.router.add_post(
        "/api/agents/{agent_id}/sessions/{session_id}/checkpoints/{checkpoint_id}/restore",
        handle_restore_checkpoint,
    )
    app.router.add_get(
        "/api/agents/{agent_id}/sessions/{session_id}/messages",
        handle_messages,
    )
