"""Execution control routes — trigger, inject, chat, resume, stop, replay."""

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from framework.credentials.validation import validate_agent_credentials
from framework.graph.conversation import LEGACY_RUN_ID
from framework.server.app import resolve_session, safe_path_segment, sessions_dir
from framework.server.routes_sessions import _credential_error_response

logger = logging.getLogger(__name__)


def _load_checkpoint_run_id(cp_path) -> str | None:
    try:
        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    run_id = checkpoint.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    return LEGACY_RUN_ID


async def handle_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/trigger — start an execution.

    Body: {"entry_point_id": "default", "input_data": {...}, "session_state": {...}?}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

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

    execution_id = await session.graph_runtime.trigger(
        entry_point_id,
        input_data,
        session_state=session_state,
    )

    # Cancel queen's in-progress LLM turn so it picks up the phase change cleanly
    if session.queen_executor:
        node = session.queen_executor.node_registry.get("queen")
        if node and hasattr(node, "cancel_current_turn"):
            node.cancel_current_turn()

    # Switch queen to running phase (mirrors run_agent_with_input tool behavior)
    if session.phase_state is not None:
        await session.phase_state.switch_to_running(source="frontend")

    return web.json_response({"execution_id": execution_id})


async def handle_inject(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/inject — inject input into a waiting node.

    Body: {"node_id": "...", "content": "...", "graph_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

    body = await request.json()
    node_id = body.get("node_id")
    content = body.get("content", "")
    graph_id = body.get("graph_id")

    if not node_id:
        return web.json_response({"error": "node_id is required"}, status=400)

    delivered = await session.graph_runtime.inject_input(node_id, content, graph_id=graph_id)
    return web.json_response({"delivered": delivered})


async def handle_chat(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/chat — send a message to the queen.

    The input box is permanently connected to the queen agent, including
    replies to worker-originated questions. The queen decides whether to
    relay the user's answer back into the worker via inject_message().

    Body: {"message": "hello", "images": [{"type": "image_url", "image_url": {"url": "data:..."}}]}

    The optional ``images`` field accepts a list of OpenAI-format image_url
    content blocks.  The frontend encodes images as base64 data URIs.
    """
    session, err = resolve_session(request)
    if err:
        logger.debug("[handle_chat] Session resolution failed: %s", err)
        return err

    body = await request.json()
    message = body.get("message", "")
    display_message = body.get("display_message")
    image_content = body.get("images") or None  # list[dict] | None

    logger.debug("[handle_chat] session_id=%s, message_len=%d, has_images=%s", 
                 session.id, len(message), bool(image_content))
    logger.debug("[handle_chat] session.queen_executor=%s", session.queen_executor)

    if not message and not image_content:
        return web.json_response({"error": "message is required"}, status=400)

    queen_executor = session.queen_executor
    if queen_executor is not None:
        logger.debug("[handle_chat] Queen executor exists, looking for 'queen' node...")
        logger.debug("[handle_chat] node_registry type=%s, id=%s", type(queen_executor.node_registry), id(queen_executor.node_registry))
        logger.debug("[handle_chat] node_registry keys: %s", list(queen_executor.node_registry.keys()))
        node = queen_executor.node_registry.get("queen")
        logger.debug("[handle_chat] node=%s, node_type=%s", node, type(node).__name__ if node else None)
        logger.debug("[handle_chat] has_inject_event=%s", hasattr(node, "inject_event") if node else False)
        
        # Race condition: executor exists but node not created yet (still initializing)
        if node is None and session.queen_task is not None and not session.queen_task.done():
            logger.warning("[handle_chat] Queen executor exists but node not ready yet (initializing). Waiting...")
            # Wait a short time for initialization to progress
            import asyncio
            for _ in range(50):  # Max 5 seconds
                await asyncio.sleep(0.1)
                node = queen_executor.node_registry.get("queen")
                if node is not None:
                    logger.debug("[handle_chat] Node appeared after waiting")
                    break
            else:
                logger.error("[handle_chat] Node still not available after 5s wait")
        
        if node is not None and hasattr(node, "inject_event"):
            try:
                logger.debug("[handle_chat] Calling node.inject_event()...")
                await node.inject_event(message, is_client_input=True, image_content=image_content)
                logger.debug("[handle_chat] inject_event() completed successfully")
            except Exception as e:
                logger.exception("[handle_chat] inject_event() failed: %s", e)
                raise
            # Publish to EventBus so the session event log captures user messages
            from framework.runtime.event_bus import AgentEvent, EventType

            await session.event_bus.publish(
                AgentEvent(
                    type=EventType.CLIENT_INPUT_RECEIVED,
                    stream_id="queen",
                    node_id="queen",
                    execution_id=session.id,
                    data={
                        # Allow the UI to display a user-friendly echo while
                        # the queen receives a richer relay wrapper.
                        "content": display_message if display_message is not None else message,
                        "image_count": len(image_content) if image_content else 0,
                    },
                )
            )
            return web.json_response(
                {
                    "status": "queen",
                    "delivered": True,
                }
            )
        else:
            if node is None:
                logger.error("[handle_chat] CRITICAL: Queen node is None! node_registry has %d keys: %s, queen_task=%s, queen_task_done=%s", 
                             len(queen_executor.node_registry), list(queen_executor.node_registry.keys()),
                             session.queen_task, session.queen_task.done() if session.queen_task else None)
            else:
                logger.error("[handle_chat] CRITICAL: Queen node exists but missing inject_event! node_attrs=%s", 
                             [a for a in dir(node) if not a.startswith('_')])

    # Queen is dead — try to revive her
    logger.warning(
        "[handle_chat] Queen is dead for session '%s', reviving on /chat request", session.id
    )
    manager: Any = request.app["manager"]
    try:
        logger.debug("[handle_chat] Calling manager.revive_queen()...")
        await manager.revive_queen(session, initial_prompt=message)
        logger.debug("[handle_chat] revive_queen() completed successfully")
        return web.json_response(
            {
                "status": "queen_revived",
                "delivered": True,
            }
        )
    except Exception as e:
        logger.exception("[handle_chat] Failed to revive queen: %s", e)
        return web.json_response({"error": "Queen not available"}, status=503)


async def handle_queen_context(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/queen-context — queue context for the queen.

    Unlike /chat, this does NOT trigger an LLM response. The message is
    queued in the queen's injection queue and will be drained on her next
    natural iteration (prefixed with [External event]:).

    Body: {"message": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    body = await request.json()
    message = body.get("message", "")

    if not message:
        return web.json_response({"error": "message is required"}, status=400)

    queen_executor = session.queen_executor
    if queen_executor is not None:
        node = queen_executor.node_registry.get("queen")
        if node is not None and hasattr(node, "inject_event"):
            await node.inject_event(message, is_client_input=False)
            return web.json_response({"status": "queued", "delivered": True})

    # Queen is dead — try to revive her
    logger.warning(
        "Queen is dead for session '%s', reviving on /queen-context request",
        session.id,
    )
    manager: Any = request.app["manager"]
    try:
        await manager.revive_queen(session)
        # After revival, deliver the message
        queen_executor = session.queen_executor
        if queen_executor is not None:
            node = queen_executor.node_registry.get("queen")
            if node is not None and hasattr(node, "inject_event"):
                await node.inject_event(message, is_client_input=False)
                return web.json_response({"status": "queued_revived", "delivered": True})
    except Exception as e:
        logger.error("Failed to revive queen for context: %s", e)

    return web.json_response({"error": "Queen not available"}, status=503)


async def handle_goal_progress(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/goal-progress — evaluate goal progress."""
    session, err = resolve_session(request)
    if err:
        return err

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

    progress = await session.graph_runtime.get_goal_progress()
    return web.json_response(progress, dumps=lambda obj: json.dumps(obj, default=str))


async def handle_resume(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/resume — resume a paused execution.

    Body: {"session_id": "...", "checkpoint_id": "..." (optional)}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

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
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return web.json_response({"error": f"Failed to read session: {e}"}, status=500)

    if not checkpoint_id:
        return web.json_response(
            {"error": "checkpoint_id is required; non-checkpoint resume is no longer supported"},
            status=400,
        )

    cp_path = session_dir / "checkpoints" / f"{checkpoint_id}.json"
    if not cp_path.exists():
        return web.json_response({"error": "Checkpoint not found"}, status=404)

    resume_session_state = {
        "resume_session_id": worker_session_id,
        "resume_from_checkpoint": checkpoint_id,
        "run_id": _load_checkpoint_run_id(cp_path),
    }

    entry_points = session.graph_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    input_data = state.get("input_data", {})

    execution_id = await session.graph_runtime.trigger(
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


async def handle_pause(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/pause — pause the worker (queen stays alive).

    Mirrors the queen's stop_graph() tool: cancels all active worker
    executions, pauses timers so nothing auto-restarts, but does NOT
    touch the queen so she can observe and react to the pause.
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

    runtime = session.graph_runtime
    cancelled = []

    for graph_id in runtime.list_graphs():
        reg = runtime.get_graph_registration(graph_id)
        if reg is None:
            continue
        for _ep_id, stream in reg.streams.items():
            # Signal shutdown on active nodes to abort in-flight LLM streams
            for executor in stream._active_executors.values():
                for node in executor.node_registry.values():
                    if hasattr(node, "signal_shutdown"):
                        node.signal_shutdown()
                    if hasattr(node, "cancel_current_turn"):
                        node.cancel_current_turn()

            for exec_id in list(stream.active_execution_ids):
                try:
                    ok = await stream.cancel_execution(exec_id, reason="Execution paused by user")
                    if ok:
                        cancelled.append(exec_id)
                except Exception:
                    pass

    # Pause timers so the next tick doesn't restart execution
    runtime.pause_timers()

    # Switch to staging (agent still loaded, ready to re-run)
    if session.phase_state is not None:
        await session.phase_state.switch_to_staging(source="frontend")

    return web.json_response(
        {
            "stopped": bool(cancelled),
            "cancelled": cancelled,
            "timers_paused": True,
        }
    )


async def handle_stop(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/stop — cancel a running execution.

    Body: {"execution_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

    body = await request.json()
    execution_id = body.get("execution_id")

    if not execution_id:
        return web.json_response({"error": "execution_id is required"}, status=400)

    for graph_id in session.graph_runtime.list_graphs():
        reg = session.graph_runtime.get_graph_registration(graph_id)
        if reg is None:
            continue
        for _ep_id, stream in reg.streams.items():
            # Signal shutdown on active nodes to abort in-flight LLM streams
            for executor in stream._active_executors.values():
                for node in executor.node_registry.values():
                    if hasattr(node, "signal_shutdown"):
                        node.signal_shutdown()
                    if hasattr(node, "cancel_current_turn"):
                        node.cancel_current_turn()

            cancelled = await stream.cancel_execution(
                execution_id, reason="Execution stopped by user"
            )
            if cancelled:
                # Cancel queen's in-progress LLM turn
                if session.queen_executor:
                    node = session.queen_executor.node_registry.get("queen")
                    if node and hasattr(node, "cancel_current_turn"):
                        node.cancel_current_turn()

                # Switch to staging (agent still loaded, ready to re-run)
                if session.phase_state is not None:
                    await session.phase_state.switch_to_staging(source="frontend")

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

    if not session.graph_runtime:
        return web.json_response({"error": "No graph loaded in this session"}, status=503)

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

    entry_points = session.graph_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    replay_session_state = {
        "resume_session_id": worker_session_id,
        "resume_from_checkpoint": checkpoint_id,
        "run_id": _load_checkpoint_run_id(cp_path),
    }

    execution_id = await session.graph_runtime.trigger(
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


async def handle_cancel_queen(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/cancel-queen — cancel the queen's current LLM turn."""
    session, err = resolve_session(request)
    if err:
        return err
    queen_executor = session.queen_executor
    if queen_executor is None:
        return web.json_response({"cancelled": False, "error": "Queen not active"}, status=404)
    node = queen_executor.node_registry.get("queen")
    if node is None or not hasattr(node, "cancel_current_turn"):
        return web.json_response({"cancelled": False, "error": "Queen node not found"}, status=404)
    node.cancel_current_turn()
    return web.json_response({"cancelled": True})


def register_routes(app: web.Application) -> None:
    """Register execution control routes."""
    # Session-primary routes
    app.router.add_post("/api/sessions/{session_id}/trigger", handle_trigger)
    app.router.add_post("/api/sessions/{session_id}/inject", handle_inject)
    app.router.add_post("/api/sessions/{session_id}/chat", handle_chat)
    app.router.add_post("/api/sessions/{session_id}/queen-context", handle_queen_context)
    app.router.add_post("/api/sessions/{session_id}/pause", handle_pause)
    app.router.add_post("/api/sessions/{session_id}/resume", handle_resume)
    app.router.add_post("/api/sessions/{session_id}/stop", handle_stop)
    app.router.add_post("/api/sessions/{session_id}/cancel-queen", handle_cancel_queen)
    app.router.add_post("/api/sessions/{session_id}/replay", handle_replay)
    app.router.add_get("/api/sessions/{session_id}/goal-progress", handle_goal_progress)
