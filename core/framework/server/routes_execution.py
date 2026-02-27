"""Execution control routes — trigger, inject, chat, resume, stop, replay."""

import asyncio
import json
import logging

from aiohttp import web

from framework.credentials.validation import validate_agent_credentials
from framework.server.app import resolve_session, safe_path_segment, sessions_dir
from framework.server.routes_sessions import _credential_error_response

logger = logging.getLogger(__name__)


async def handle_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/trigger — start an execution.

    Body: {"entry_point_id": "default", "input_data": {...}, "session_state": {...}?}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    # Validate credentials before running — deferred from load time to avoid
    # showing the modal before the user clicks Run.  Runs in executor because
    # validate_agent_credentials makes blocking HTTP health-check calls.
    if session.runner:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(
                None, lambda: validate_agent_credentials(session.runner.graph.nodes)
            )
        except Exception as e:
            agent_path = str(session.worker_path) if session.worker_path else ""
            resp = _credential_error_response(e, agent_path)
            if resp is not None:
                return resp

        # Resync MCP servers if credentials were added since the worker loaded
        # (e.g. user connected an OAuth account mid-session via Aden UI).
        try:
            await loop.run_in_executor(
                None, lambda: session.runner._tool_registry.resync_mcp_servers_if_needed()
            )
        except Exception as e:
            logger.warning("MCP resync failed: %s", e)

    body = await request.json()
    entry_point_id = body.get("entry_point_id", "default")
    input_data = body.get("input_data", {})
    session_state = body.get("session_state") or {}

    # Scope the worker execution to the live session ID
    if "resume_session_id" not in session_state:
        session_state["resume_session_id"] = session.id

    execution_id = await session.worker_runtime.trigger(
        entry_point_id,
        input_data,
        session_state=session_state,
    )

    return web.json_response({"execution_id": execution_id})


async def handle_inject(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/inject — inject input into a waiting node.

    Body: {"node_id": "...", "content": "...", "graph_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    body = await request.json()
    node_id = body.get("node_id")
    content = body.get("content", "")
    graph_id = body.get("graph_id")

    if not node_id:
        return web.json_response({"error": "node_id is required"}, status=400)

    delivered = await session.worker_runtime.inject_input(node_id, content, graph_id=graph_id)
    return web.json_response({"delivered": delivered})


async def handle_chat(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/chat — convenience endpoint.

    Routing priority:
    1. Worker awaiting input → inject into worker node
    2. Queen active → inject into queen conversation
    3. Error — no handler available

    Body: {"message": "hello"}
    """
    session, err = resolve_session(request)
    if err:
        return err

    body = await request.json()
    message = body.get("message", "")

    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    # 1. Check if worker is awaiting input → inject to worker
    if session.worker_runtime:
        node_id, graph_id = session.worker_runtime.find_awaiting_node()

        if node_id:
            delivered = await session.worker_runtime.inject_input(
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

    # 2. Queen active → inject into queen conversation
    queen_executor = session.queen_executor
    if queen_executor is not None:
        node = queen_executor.node_registry.get("queen")
        if node is not None and hasattr(node, "inject_event"):
            await node.inject_event(message, is_client_input=True)
            return web.json_response(
                {
                    "status": "queen",
                    "delivered": True,
                }
            )

    # 3. No queen or worker available
    return web.json_response({"error": "No worker or queen available"}, status=503)


async def handle_goal_progress(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/goal-progress — evaluate goal progress."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    progress = await session.worker_runtime.get_goal_progress()
    return web.json_response(progress, dumps=lambda obj: json.dumps(obj, default=str))


async def handle_resume(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/resume — resume a paused execution.

    Body: {"session_id": "...", "checkpoint_id": "..." (optional)}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    body = await request.json()
    worker_session_id = body.get("session_id")
    checkpoint_id = body.get("checkpoint_id")

    if not worker_session_id:
        return web.json_response({"error": "session_id is required"}, status=400)

    worker_session_id = safe_path_segment(worker_session_id)
    if checkpoint_id:
        checkpoint_id = safe_path_segment(checkpoint_id)

    # Read session state
    session_dir = sessions_dir(session) / worker_session_id
    state_path = session_dir / "state.json"
    if not state_path.exists():
        return web.json_response({"error": "Session not found"}, status=404)

    try:
        state = json.loads(state_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return web.json_response({"error": f"Failed to read session: {e}"}, status=500)

    if checkpoint_id:
        resume_session_state = {
            "resume_session_id": worker_session_id,
            "resume_from_checkpoint": checkpoint_id,
        }
    else:
        progress = state.get("progress", {})
        paused_at = progress.get("paused_at") or progress.get("resume_from")
        resume_session_state = {
            "resume_session_id": worker_session_id,
            "memory": state.get("memory", {}),
            "execution_path": progress.get("path", []),
            "node_visit_counts": progress.get("node_visit_counts", {}),
        }
        if paused_at:
            resume_session_state["paused_at"] = paused_at

    entry_points = session.worker_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    input_data = state.get("input_data", {})

    execution_id = await session.worker_runtime.trigger(
        entry_points[0].id,
        input_data=input_data,
        session_state=resume_session_state,
    )

    return web.json_response(
        {
            "execution_id": execution_id,
            "resumed_from": worker_session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


async def handle_stop(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/stop — cancel a running execution.

    Body: {"execution_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    body = await request.json()
    execution_id = body.get("execution_id")

    if not execution_id:
        return web.json_response({"error": "execution_id is required"}, status=400)

    for graph_id in session.worker_runtime.list_graphs():
        reg = session.worker_runtime.get_graph_registration(graph_id)
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
    """POST /api/sessions/{session_id}/replay — re-run from a checkpoint.

    Body: {"session_id": "...", "checkpoint_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.worker_runtime:
        return web.json_response({"error": "No worker loaded in this session"}, status=503)

    body = await request.json()
    worker_session_id = body.get("session_id")
    checkpoint_id = body.get("checkpoint_id")

    if not worker_session_id:
        return web.json_response({"error": "session_id is required"}, status=400)
    if not checkpoint_id:
        return web.json_response({"error": "checkpoint_id is required"}, status=400)

    worker_session_id = safe_path_segment(worker_session_id)
    checkpoint_id = safe_path_segment(checkpoint_id)

    cp_path = sessions_dir(session) / worker_session_id / "checkpoints" / f"{checkpoint_id}.json"
    if not cp_path.exists():
        return web.json_response({"error": "Checkpoint not found"}, status=404)

    entry_points = session.worker_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    replay_session_state = {
        "resume_session_id": worker_session_id,
        "resume_from_checkpoint": checkpoint_id,
    }

    execution_id = await session.worker_runtime.trigger(
        entry_points[0].id,
        input_data={},
        session_state=replay_session_state,
    )

    return web.json_response(
        {
            "execution_id": execution_id,
            "replayed_from": worker_session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


def register_routes(app: web.Application) -> None:
    """Register execution control routes."""
    # Session-primary routes
    app.router.add_post("/api/sessions/{session_id}/trigger", handle_trigger)
    app.router.add_post("/api/sessions/{session_id}/inject", handle_inject)
    app.router.add_post("/api/sessions/{session_id}/chat", handle_chat)
    app.router.add_post("/api/sessions/{session_id}/pause", handle_stop)
    app.router.add_post("/api/sessions/{session_id}/resume", handle_resume)
    app.router.add_post("/api/sessions/{session_id}/stop", handle_stop)
    app.router.add_post("/api/sessions/{session_id}/replay", handle_replay)
    app.router.add_get("/api/sessions/{session_id}/goal-progress", handle_goal_progress)
