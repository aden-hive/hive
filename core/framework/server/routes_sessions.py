"""Session lifecycle, info, and worker-session browsing routes.

Session-primary routes:
- POST   /api/sessions                               — create session (with or without worker)
- GET    /api/sessions                               — list all active sessions
- GET    /api/sessions/{session_id}                  — session detail
- DELETE /api/sessions/{session_id}                  — stop session entirely
- POST   /api/sessions/{session_id}/worker           — load a worker into session
- DELETE /api/sessions/{session_id}/worker           — unload worker from session
- GET    /api/sessions/{session_id}/stats            — runtime statistics
- GET    /api/sessions/{session_id}/entry-points     — list entry points
- GET    /api/sessions/{session_id}/graphs           — list graph IDs
- GET    /api/sessions/{session_id}/queen-messages   — queen conversation history

Worker session browsing (persisted execution runs on disk):
- GET    /api/sessions/{session_id}/worker-sessions                             — list
- GET    /api/sessions/{session_id}/worker-sessions/{ws_id}                     — detail
- DELETE /api/sessions/{session_id}/worker-sessions/{ws_id}                     — delete
- GET    /api/sessions/{session_id}/worker-sessions/{ws_id}/checkpoints         — list CPs
- POST   /api/sessions/{session_id}/worker-sessions/{ws_id}/checkpoints/{cp}/restore
- GET    /api/sessions/{session_id}/worker-sessions/{ws_id}/messages            — messages

"""

import json
import logging
import shutil
import time
from pathlib import Path

from aiohttp import web

from framework.server.app import resolve_session, safe_path_segment, sessions_dir
from framework.server.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> SessionManager:
    return request.app["manager"]


def _session_to_live_dict(session) -> dict:
    """Serialize a live Session to the session-primary JSON shape."""
    info = session.worker_info
    return {
        "session_id": session.id,
        "worker_id": session.worker_id,
        "worker_name": info.name if info else session.worker_id,
        "has_worker": session.worker_runtime is not None,
        "agent_path": str(session.worker_path) if session.worker_path else "",
        "description": info.description if info else "",
        "goal": info.goal_name if info else "",
        "node_count": info.node_count if info else 0,
        "loaded_at": session.loaded_at,
        "uptime_seconds": round(time.time() - session.loaded_at, 1),
        "intro_message": getattr(session.runner, "intro_message", "") or "",
    }


# ------------------------------------------------------------------
# Session lifecycle
# ------------------------------------------------------------------


async def handle_create_session(request: web.Request) -> web.Response:
    """POST /api/sessions — create a session.

    Body: {
        "agent_path": "..." (optional — if provided, creates session with worker),
        "agent_id": "..." (optional — worker ID override),
        "session_id": "..." (optional — custom session ID),
        "model": "..." (optional),
    }

    When agent_path is provided, creates a session with a worker in one step
    (equivalent to the old POST /api/agents). Otherwise creates a queen-only
    session that can later have a worker loaded via POST /sessions/{id}/worker.
    """
    manager = _get_manager(request)
    body = await request.json() if request.can_read_body else {}
    agent_path = body.get("agent_path")
    agent_id = body.get("agent_id")
    session_id = body.get("session_id")
    model = body.get("model")

    try:
        if agent_path:
            # One-step: create session + load worker
            session = await manager.create_session_with_worker(
                agent_path,
                agent_id=agent_id,
                model=model,
            )
        else:
            # Queen-only session
            session = await manager.create_session(
                session_id=session_id,
                model=model,
            )
    except ValueError as e:
        msg = str(e)
        if "currently loading" in msg:
            resolved_id = agent_id or (Path(agent_path).name if agent_path else "")
            return web.json_response(
                {"error": msg, "worker_id": resolved_id, "loading": True},
                status=409,
            )
        return web.json_response({"error": msg}, status=409)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.exception("Error creating session: %s", e)
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(_session_to_live_dict(session), status=201)


async def handle_list_live_sessions(request: web.Request) -> web.Response:
    """GET /api/sessions — list all active sessions."""
    manager = _get_manager(request)
    sessions = [_session_to_live_dict(s) for s in manager.list_sessions()]
    return web.json_response({"sessions": sessions})


async def handle_get_live_session(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id} — get session detail."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)

    if session is None:
        if manager.is_loading(session_id):
            return web.json_response(
                {"session_id": session_id, "loading": True},
                status=202,
            )
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

    data = _session_to_live_dict(session)

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


async def handle_stop_session(request: web.Request) -> web.Response:
    """DELETE /api/sessions/{session_id} — stop a session entirely."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]

    stopped = await manager.stop_session(session_id)
    if not stopped:
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

    return web.json_response({"session_id": session_id, "stopped": True})


# ------------------------------------------------------------------
# Worker lifecycle
# ------------------------------------------------------------------


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
            session_id,
            agent_path,
            worker_id=worker_id,
            model=model,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except FileNotFoundError as e:
        return web.json_response({"error": str(e)}, status=404)
    except Exception as e:
        logger.exception("Error loading worker: %s", e)
        return web.json_response({"error": str(e)}, status=500)

    return web.json_response(_session_to_live_dict(session))


async def handle_unload_worker(request: web.Request) -> web.Response:
    """DELETE /api/sessions/{session_id}/worker — unload worker, keep queen alive."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]

    removed = await manager.unload_worker(session_id)
    if not removed:
        session = manager.get_session(session_id)
        if session is None:
            return web.json_response(
                {"error": f"Session '{session_id}' not found"},
                status=404,
            )
        return web.json_response(
            {"error": "No worker loaded in this session"},
            status=409,
        )

    return web.json_response({"session_id": session_id, "worker_unloaded": True})


# ------------------------------------------------------------------
# Session info (worker details)
# ------------------------------------------------------------------


async def handle_session_stats(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/stats — runtime statistics."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)

    if session is None:
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

    stats = session.worker_runtime.get_stats() if session.worker_runtime else {}
    return web.json_response(stats)


async def handle_session_entry_points(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/entry-points — list entry points."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)

    if session is None:
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

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


async def handle_session_graphs(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/graphs — list loaded graphs."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)

    if session is None:
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

    graphs = session.worker_runtime.list_graphs() if session.worker_runtime else []
    return web.json_response({"graphs": graphs})


# ------------------------------------------------------------------
# Worker session browsing (persisted execution runs on disk)
# ------------------------------------------------------------------


async def handle_list_worker_sessions(request: web.Request) -> web.Response:
    """List worker sessions on disk."""
    session, err = resolve_session(request)
    if err:
        return err

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


async def handle_get_worker_session(request: web.Request) -> web.Response:
    """Get worker session detail from disk."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    # Support both URL param names: ws_id (new) or session_id (legacy)
    ws_id = request.match_info.get("ws_id") or request.match_info.get("session_id", "")
    ws_id = safe_path_segment(ws_id)

    state_path = sessions_dir(session) / ws_id / "state.json"
    if not state_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return web.json_response({"error": f"Failed to read session: {e}"}, status=500)

    return web.json_response(state)


async def handle_list_checkpoints(request: web.Request) -> web.Response:
    """List checkpoints for a worker session."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    ws_id = request.match_info.get("ws_id") or request.match_info.get("session_id", "")
    ws_id = safe_path_segment(ws_id)

    cp_dir = sessions_dir(session) / ws_id / "checkpoints"
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


async def handle_delete_worker_session(request: web.Request) -> web.Response:
    """Delete a worker session from disk."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    ws_id = request.match_info.get("ws_id") or request.match_info.get("session_id", "")
    ws_id = safe_path_segment(ws_id)

    session_path = sessions_dir(session) / ws_id
    if not session_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    shutil.rmtree(session_path)
    return web.json_response({"deleted": ws_id})


async def handle_restore_checkpoint(request: web.Request) -> web.Response:
    """Restore from a checkpoint."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    ws_id = request.match_info.get("ws_id") or request.match_info.get("session_id", "")
    ws_id = safe_path_segment(ws_id)
    checkpoint_id = safe_path_segment(request.match_info["checkpoint_id"])

    cp_path = sessions_dir(session) / ws_id / "checkpoints" / f"{checkpoint_id}.json"
    if not cp_path.exists():
        return web.json_response({"error": "Checkpoint not found"}, status=404)

    entry_points = session.worker_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    restore_session_state = {
        "resume_session_id": ws_id,
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
            "restored_from": ws_id,
            "checkpoint_id": checkpoint_id,
        }
    )


async def handle_messages(request: web.Request) -> web.Response:
    """Get messages for a worker session."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_path:
        return web.json_response({"error": "No worker loaded"}, status=503)

    ws_id = request.match_info.get("ws_id") or request.match_info.get("session_id", "")
    ws_id = safe_path_segment(ws_id)

    convs_dir = sessions_dir(session) / ws_id / "conversations"
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


async def handle_queen_messages(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/queen-messages — get queen conversation."""
    session, err = resolve_session(request)
    if err:
        return err

    queen_dir = Path.home() / ".hive" / "queen" / "session" / session.id
    convs_dir = queen_dir / "conversations"
    if not convs_dir.exists():
        return web.json_response({"messages": []})

    all_messages: list[dict] = []
    for node_dir in convs_dir.iterdir():
        if not node_dir.is_dir():
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

    # Filter to client-facing messages only
    all_messages = [
        m
        for m in all_messages
        if not m.get("is_transition_marker")
        and m["role"] != "tool"
        and not (m["role"] == "assistant" and m.get("tool_calls"))
    ]

    return web.json_response({"messages": all_messages})


# ------------------------------------------------------------------
# Agent discovery (not session-specific)
# ------------------------------------------------------------------


async def handle_discover(request: web.Request) -> web.Response:
    """GET /api/discover — discover agents from filesystem."""
    from framework.tui.screens.agent_picker import discover_agents

    manager = _get_manager(request)
    loaded_paths = {str(s.worker_path) for s in manager.list_sessions() if s.worker_path}

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


# ------------------------------------------------------------------
# Route registration
# ------------------------------------------------------------------


def register_routes(app: web.Application) -> None:
    """Register session routes."""
    # Discovery
    app.router.add_get("/api/discover", handle_discover)

    # Session lifecycle
    app.router.add_post("/api/sessions", handle_create_session)
    app.router.add_get("/api/sessions", handle_list_live_sessions)
    app.router.add_get("/api/sessions/{session_id}", handle_get_live_session)
    app.router.add_delete("/api/sessions/{session_id}", handle_stop_session)

    # Worker lifecycle
    app.router.add_post("/api/sessions/{session_id}/worker", handle_load_worker)
    app.router.add_delete("/api/sessions/{session_id}/worker", handle_unload_worker)

    # Session info
    app.router.add_get("/api/sessions/{session_id}/stats", handle_session_stats)
    app.router.add_get("/api/sessions/{session_id}/entry-points", handle_session_entry_points)
    app.router.add_get("/api/sessions/{session_id}/graphs", handle_session_graphs)
    app.router.add_get("/api/sessions/{session_id}/queen-messages", handle_queen_messages)

    # Worker session browsing (session-primary)
    app.router.add_get("/api/sessions/{session_id}/worker-sessions", handle_list_worker_sessions)
    app.router.add_get(
        "/api/sessions/{session_id}/worker-sessions/{ws_id}", handle_get_worker_session
    )
    app.router.add_delete(
        "/api/sessions/{session_id}/worker-sessions/{ws_id}", handle_delete_worker_session
    )
    app.router.add_get(
        "/api/sessions/{session_id}/worker-sessions/{ws_id}/checkpoints",
        handle_list_checkpoints,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/worker-sessions/{ws_id}/checkpoints/{checkpoint_id}/restore",
        handle_restore_checkpoint,
    )
    app.router.add_get(
        "/api/sessions/{session_id}/worker-sessions/{ws_id}/messages",
        handle_messages,
    )
