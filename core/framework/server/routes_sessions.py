"""Session browsing routes — list, inspect, delete, restore, messages."""

import json
import logging
import shutil

from aiohttp import web

from framework.server.agent_manager import AgentManager
from framework.server.app import safe_path_segment, sessions_dir

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> AgentManager:
    return request.app["manager"]


async def handle_list_sessions(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/sessions — list sessions."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    sess_dir = sessions_dir(slot)
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

        # Count checkpoints
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
    session_id = safe_path_segment(request.match_info["session_id"])
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    state_path = sessions_dir(slot) / session_id / "state.json"
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
    session_id = safe_path_segment(request.match_info["session_id"])
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    cp_dir = sessions_dir(slot) / session_id / "checkpoints"
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
    """DELETE /api/agents/{agent_id}/sessions/{session_id} — delete a session."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session_id = safe_path_segment(request.match_info["session_id"])
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    session_path = sessions_dir(slot) / session_id
    if not session_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    shutil.rmtree(session_path)
    return web.json_response({"deleted": session_id})


async def handle_restore_checkpoint(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/sessions/{session_id}/checkpoints/{checkpoint_id}/restore

    Restore execution from a specific checkpoint. Triggers a new execution
    using the checkpoint state — same mechanism as the replay endpoint but
    scoped under the session/checkpoint path.
    """
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session_id = safe_path_segment(request.match_info["session_id"])
    checkpoint_id = safe_path_segment(request.match_info["checkpoint_id"])
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    # Verify checkpoint exists
    cp_path = sessions_dir(slot) / session_id / "checkpoints" / f"{checkpoint_id}.json"
    if not cp_path.exists():
        return web.json_response({"error": "Checkpoint not found"}, status=404)

    entry_points = slot.runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    restore_session_state = {
        "resume_session_id": session_id,
        "resume_from_checkpoint": checkpoint_id,
    }

    execution_id = await slot.runtime.trigger(
        entry_points[0].id,
        input_data={},
        session_state=restore_session_state,
    )

    return web.json_response(
        {
            "execution_id": execution_id,
            "restored_from": session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


async def handle_messages(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/sessions/{session_id}/messages

    Retrieve chat message history for a session. Reads per-node conversation
    files, merges by sequence number, and returns a unified message list.

    Query params:
        node_id: Scope to a specific node's conversation (optional).
        client_only: When "true", filter to only user-facing messages
            (drops tool results, transition markers, internal nodes, and
            assistant messages that are just tool-call invocations).
    """
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    session_id = safe_path_segment(request.match_info["session_id"])
    slot = manager.get_agent(agent_id)

    if slot is None:
        return web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)

    convs_dir = sessions_dir(slot) / session_id / "conversations"
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

    # Sort by sequence number
    all_messages.sort(key=lambda m: m.get("seq", 0))

    # Optionally filter to client-facing messages only.
    # When the graph spec isn't available (runner not loaded / session ended),
    # we can't determine which nodes are client-facing, so we skip the filter
    # and return all messages rather than silently returning an empty list.
    client_only = request.query.get("client_only", "").lower() in ("true", "1")
    if client_only:
        client_facing_nodes: set[str] = set()
        if slot.runner and hasattr(slot.runner, "graph"):
            for node in slot.runner.graph.nodes:
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
    """Register session browsing routes."""
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
