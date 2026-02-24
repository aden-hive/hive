"""Execution control routes — trigger, inject, chat, resume, stop, replay."""

import json
import logging

from aiohttp import web

from framework.server.agent_manager import AgentManager
from framework.server.app import safe_path_segment, sessions_dir

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> AgentManager:
    return request.app["manager"]


def _get_slot_or_404(request: web.Request):
    """Lookup agent slot; returns (slot, None) or (None, error_response)."""
    manager = _get_manager(request)
    agent_id = request.match_info["agent_id"]
    slot = manager.get_agent(agent_id)
    if slot is None:
        return None, web.json_response({"error": f"Agent '{agent_id}' not found"}, status=404)
    return slot, None


async def handle_trigger(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/trigger — start an execution.

    Body: {"entry_point_id": "default", "input_data": {...}, "session_state": {...}?}
    """
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    body = await request.json()
    entry_point_id = body.get("entry_point_id", "default")
    input_data = body.get("input_data", {})
    session_state = body.get("session_state")

    execution_id = await slot.runtime.trigger(
        entry_point_id,
        input_data,
        session_state=session_state,
    )

    return web.json_response({"execution_id": execution_id})


async def handle_inject(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/inject — inject input into a waiting node.

    Body: {"node_id": "...", "content": "...", "graph_id": "..."}
    """
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    body = await request.json()
    node_id = body.get("node_id")
    content = body.get("content", "")
    graph_id = body.get("graph_id")

    if not node_id:
        return web.json_response({"error": "node_id is required"}, status=400)

    delivered = await slot.runtime.inject_input(node_id, content, graph_id=graph_id)
    return web.json_response({"delivered": delivered})


async def handle_chat(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/chat — convenience endpoint.

    Auto-routes: inject if a node is awaiting input, else trigger.
    Body: {"message": "hello"}
    """
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    body = await request.json()
    message = body.get("message", "")

    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    # Check if any node is awaiting input
    node_id, graph_id = slot.runtime.find_awaiting_node()

    if node_id:
        delivered = await slot.runtime.inject_input(
            node_id,
            message,
            graph_id=graph_id,
            is_client_input=True,
        )
        return web.json_response(
            {
                "status": "injected",
                "node_id": node_id,
                "delivered": delivered,
            }
        )
    else:
        entry_points = slot.runtime.get_entry_points()
        ep_id = entry_points[0].id if entry_points else "default"
        execution_id = await slot.runtime.trigger(
            ep_id,
            {"user_request": message},
        )
        return web.json_response(
            {
                "status": "started",
                "execution_id": execution_id,
            }
        )


async def handle_goal_progress(request: web.Request) -> web.Response:
    """GET /api/agents/{agent_id}/goal-progress — evaluate goal progress."""
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    progress = await slot.runtime.get_goal_progress()
    return web.json_response(progress, dumps=lambda obj: json.dumps(obj, default=str))


async def handle_resume(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/resume — resume a paused execution.

    Body: {"session_id": "...", "checkpoint_id": "..." (optional)}

    Reads session state (and optionally a checkpoint), builds a
    session_state dict, and calls runtime.trigger() — same pattern as
    the TUI /resume command.
    """
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    body = await request.json()
    session_id = body.get("session_id")
    checkpoint_id = body.get("checkpoint_id")

    if not session_id:
        return web.json_response({"error": "session_id is required"}, status=400)

    session_id = safe_path_segment(session_id)
    if checkpoint_id:
        checkpoint_id = safe_path_segment(checkpoint_id)

    # Read session state
    session_dir = sessions_dir(slot) / session_id
    state_path = session_dir / "state.json"
    if not state_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return web.json_response({"error": f"Failed to read session: {e}"}, status=500)

    if checkpoint_id:
        # Checkpoint-based recovery (time-travel)
        resume_session_state = {
            "resume_session_id": session_id,
            "resume_from_checkpoint": checkpoint_id,
        }
    else:
        # Session-state resume (same as TUI /resume)
        progress = state.get("progress", {})
        paused_at = progress.get("paused_at") or progress.get("resume_from")
        resume_session_state = {
            "resume_session_id": session_id,
            "memory": state.get("memory", {}),
            "execution_path": progress.get("path", []),
            "node_visit_counts": progress.get("node_visit_counts", {}),
        }
        if paused_at:
            resume_session_state["paused_at"] = paused_at

    # Get entry point and original input data
    entry_points = slot.runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    input_data = state.get("input_data", {})

    execution_id = await slot.runtime.trigger(
        entry_points[0].id,
        input_data=input_data,
        session_state=resume_session_state,
    )

    return web.json_response(
        {
            "execution_id": execution_id,
            "resumed_from": session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


async def handle_stop(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/stop — cancel a running execution.

    Body: {"execution_id": "..."}

    Cancels the execution task via stream.cancel_execution(). The
    GraphExecutor catches CancelledError, saves state, and marks the
    session as paused — so the execution is resumable via /resume.
    Also mounted on /pause as an alias.
    """
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    body = await request.json()
    execution_id = body.get("execution_id")

    if not execution_id:
        return web.json_response({"error": "execution_id is required"}, status=400)

    # Search all graphs/streams for the execution and cancel it
    for graph_id in slot.runtime.list_graphs():
        reg = slot.runtime.get_graph_registration(graph_id)
        if reg is None:
            continue
        for _ep_id, stream in reg.streams.items():
            cancelled = await stream.cancel_execution(execution_id)
            if cancelled:
                return web.json_response(
                    {
                        "stopped": True,
                        "execution_id": execution_id,
                    }
                )

    return web.json_response({"stopped": False, "error": "Execution not found"}, status=404)


async def handle_replay(request: web.Request) -> web.Response:
    """POST /api/agents/{agent_id}/replay — re-run from a checkpoint.

    Body: {"session_id": "...", "checkpoint_id": "..."}

    Loads the specified checkpoint and triggers a new execution using
    the checkpoint's state. Unlike resume, this creates a fresh
    execution rather than continuing the paused one.
    """
    slot, err = _get_slot_or_404(request)
    if err:
        return err

    body = await request.json()
    session_id = body.get("session_id")
    checkpoint_id = body.get("checkpoint_id")

    if not session_id:
        return web.json_response({"error": "session_id is required"}, status=400)
    if not checkpoint_id:
        return web.json_response({"error": "checkpoint_id is required"}, status=400)

    session_id = safe_path_segment(session_id)
    checkpoint_id = safe_path_segment(checkpoint_id)

    # Verify checkpoint exists
    cp_path = sessions_dir(slot) / session_id / "checkpoints" / f"{checkpoint_id}.json"
    if not cp_path.exists():
        return web.json_response({"error": "Checkpoint not found"}, status=404)

    entry_points = slot.runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    # Use checkpoint-based recovery which creates a new execution
    replay_session_state = {
        "resume_session_id": session_id,
        "resume_from_checkpoint": checkpoint_id,
    }

    execution_id = await slot.runtime.trigger(
        entry_points[0].id,
        input_data={},
        session_state=replay_session_state,
    )

    return web.json_response(
        {
            "execution_id": execution_id,
            "replayed_from": session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


def register_routes(app: web.Application) -> None:
    """Register execution control routes."""
    app.router.add_post("/api/agents/{agent_id}/trigger", handle_trigger)
    app.router.add_post("/api/agents/{agent_id}/inject", handle_inject)
    app.router.add_post("/api/agents/{agent_id}/chat", handle_chat)
    app.router.add_post("/api/agents/{agent_id}/pause", handle_stop)  # alias
    app.router.add_post("/api/agents/{agent_id}/resume", handle_resume)
    app.router.add_post("/api/agents/{agent_id}/stop", handle_stop)
    app.router.add_post("/api/agents/{agent_id}/replay", handle_replay)
    app.router.add_get("/api/agents/{agent_id}/goal-progress", handle_goal_progress)
