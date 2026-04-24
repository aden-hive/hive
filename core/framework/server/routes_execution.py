"""Execution control routes — trigger, inject, chat, resume, stop, replay."""

import asyncio
import json
import logging
from datetime import UTC
from typing import Any

from aiohttp import web

from framework.agent_loop.conversation import LEGACY_RUN_ID
from framework.credentials.validation import validate_agent_credentials
from framework.host.execution_manager import ExecutionAlreadyRunningError
from framework.server.app import resolve_session, safe_path_segment, sessions_dir
from framework.server.routes_sessions import _credential_error_response

logger = logging.getLogger(__name__)

# Strong refs to background fork-finalize tasks (compaction + worker-conv
# copy) so asyncio doesn't GC them mid-run. fork_session_into_colony
# schedules into this set and the done-callback evicts on completion.
_BACKGROUND_FORK_TASKS: set[asyncio.Task[None]] = set()


def _load_checkpoint_run_id(cp_path) -> str | None:
    try:
        checkpoint = json.loads(cp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    run_id = checkpoint.get("run_id")
    if isinstance(run_id, str) and run_id:
        return run_id
    return LEGACY_RUN_ID


# Tool names the worker SHOULD inherit when a colony is forked. These are
# the "work-doing" primitives — anything else in a queen phase tool list is
# queen-lifecycle and must not flow into worker.json.
_WORKER_INHERITED_TOOLS: frozenset[str] = frozenset(
    {
        # File I/O
        "read_file",
        "write_file",
        "edit_file",
        "hashline_edit",
        "list_directory",
        "search_files",
        "undo_changes",
        # Shell
        "run_command",
        # Framework synthetics (always available to any AgentLoop node)
        "set_output",
        "escalate",
        "ask_user",
    }
)


# Queen-lifecycle tools that are registered into the queen's tool registry
# but NOT listed in any _QUEEN_*_TOOLS phase list (they're reachable only via
# explicit registration or as frontend-visible helpers, not phase-based
# gating). These must still be stripped from forked / parallel-spawned
# worker tool inventories.
_QUEEN_LIFECYCLE_EXTRAS: frozenset[str] = frozenset(
    {
        # Phase-transition wrappers (method variants are on QueenPhaseState
        # but the queen also sees them as tools).
        "switch_to_reviewing",
        "switch_to_independent",
        # Frontend helpers that live outside phase lists.
        "list_credentials",
        "get_worker_health_summary",
        "enqueue_task",
    }
)


def _resolve_queen_only_tools() -> frozenset[str]:
    """Compute the set of queen-lifecycle tool names to strip on fork.

    Derived from the queen phase tool lists in ``agents.queen.nodes``:
    any tool listed in any ``_QUEEN_*_TOOLS`` set that is NOT in
    :data:`_WORKER_INHERITED_TOOLS` is a queen-only tool. Browser and MCP
    tools are not in the queen phase lists (they're added dynamically),
    so they pass through untouched. Supplemented by
    :data:`_QUEEN_LIFECYCLE_EXTRAS` for tools registered without phase
    gating.

    Computed lazily so this module can be imported before the queen
    nodes package is loaded.
    """
    from framework.agents.queen.nodes import (
        _QUEEN_INDEPENDENT_TOOLS,
        _QUEEN_REVIEWING_TOOLS,
        _QUEEN_WORKING_TOOLS,
    )

    union: set[str] = set()
    for tool_list in (
        _QUEEN_INDEPENDENT_TOOLS,
        _QUEEN_WORKING_TOOLS,
        _QUEEN_REVIEWING_TOOLS,
    ):
        union.update(tool_list)
    derived = union - _WORKER_INHERITED_TOOLS
    return frozenset(derived | _QUEEN_LIFECYCLE_EXTRAS)


def _execution_already_running_response(exc: ExecutionAlreadyRunningError) -> web.Response:
    return web.json_response(
        {
            "error": str(exc),
            "stream_id": exc.stream_id,
            "active_execution_ids": exc.active_ids,
        },
        status=409,
    )


async def handle_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/trigger — start an execution.

    Body: {"entry_point_id": "default", "input_data": {...}, "session_state": {...}?}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

    # Validate credentials before running — deferred from load time to avoid
    # showing the modal before the user clicks Run.  Runs in executor because
    # validate_agent_credentials makes blocking HTTP health-check calls.
    if session.runner:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, lambda: validate_agent_credentials(session.runner.graph.nodes))
        except Exception as e:
            agent_path = str(session.worker_path) if session.worker_path else ""
            resp = _credential_error_response(e, agent_path)
            if resp is not None:
                return resp

        # Resync MCP servers if credentials were added since the worker loaded
        # (e.g. user connected an OAuth account mid-session via Aden UI).
        try:
            await loop.run_in_executor(None, lambda: session.runner._tool_registry.resync_mcp_servers_if_needed())
        except Exception as e:
            logger.warning("MCP resync failed: %s", e)

    body = await request.json()
    entry_point_id = body.get("entry_point_id", "default")
    input_data = body.get("input_data", {})
    session_state = body.get("session_state") or {}

    # Scope the worker execution to the live session ID
    if "resume_session_id" not in session_state:
        session_state["resume_session_id"] = session.id

    try:
        execution_id = await session.colony_runtime.trigger(
            entry_point_id,
            input_data,
            session_state=session_state,
        )
    except ExecutionAlreadyRunningError as exc:
        return _execution_already_running_response(exc)

    # Cancel queen's in-progress LLM turn so it picks up the phase change cleanly
    if session.queen_executor:
        node = session.queen_executor.node_registry.get("queen")
        if node and hasattr(node, "cancel_current_turn"):
            node.cancel_current_turn()

    # Switch queen to working phase — workers just started from the UI.
    if session.phase_state is not None:
        await session.phase_state.switch_to_working(source="frontend")

    return web.json_response({"execution_id": execution_id})


async def handle_inject(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/inject — inject input into a waiting node.

    Body: {"node_id": "...", "content": "...", "graph_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

    body = await request.json()
    node_id = body.get("node_id")
    content = body.get("content", "")
    colony_id = body.get("colony_id")

    if not node_id:
        return web.json_response({"error": "node_id is required"}, status=400)

    delivered = await session.colony_runtime.inject_input(node_id, content, graph_id=colony_id)
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

    # Sessions that have spawned a colony are locked: the user must compact +
    # fork into a fresh session before continuing the conversation. Frontend
    # surfaces this as a button instead of the textarea, but enforce server-
    # side too so the lock can't be bypassed by a stale tab or scripted call.
    if getattr(session, "colony_spawned", False):
        return web.json_response(
            {
                "error": "session_locked",
                "reason": "colony_spawned",
                "spawned_colony_name": getattr(session, "spawned_colony_name", None),
                "message": (
                    "This session is locked because a colony has been "
                    "spawned from it. Compact and start a new session "
                    "with the same queen to continue."
                ),
            },
            status=409,
        )

    body = await request.json()
    message = body.get("message", "")
    display_message = body.get("display_message")
    image_content = body.get("images") or None  # list[dict] | None

    logger.debug(
        "[handle_chat] session_id=%s, message_len=%d, has_images=%s",
        session.id,
        len(message),
        bool(image_content),
    )
    logger.debug("[handle_chat] session.queen_executor=%s", session.queen_executor)

    if not message and not image_content:
        return web.json_response({"error": "message is required"}, status=400)

    queen_executor = session.queen_executor
    if queen_executor is not None:
        logger.debug("[handle_chat] Queen executor exists, looking for 'queen' node...")
        logger.debug(
            "[handle_chat] node_registry type=%s, id=%s",
            type(queen_executor.node_registry),
            id(queen_executor.node_registry),
        )
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
            # Publish BEFORE inject_event so handlers (e.g. memory recall)
            # complete before the event loop unblocks and starts the LLM turn.
            from framework.host.event_bus import AgentEvent, EventType

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
            try:
                logger.debug("[handle_chat] Calling node.inject_event()...")
                await node.inject_event(message, is_client_input=True, image_content=image_content)
                logger.debug("[handle_chat] inject_event() completed successfully")
            except Exception as e:
                logger.exception("[handle_chat] inject_event() failed: %s", e)
                raise
            return web.json_response(
                {
                    "status": "queen",
                    "delivered": True,
                }
            )
        else:
            if node is None:
                logger.error(
                    "[handle_chat] CRITICAL: Queen node is None!"
                    " node_registry has %d keys: %s,"
                    " queen_task=%s, queen_task_done=%s",
                    len(queen_executor.node_registry),
                    list(queen_executor.node_registry.keys()),
                    session.queen_task,
                    session.queen_task.done() if session.queen_task else None,
                )
            else:
                logger.error(
                    "[handle_chat] CRITICAL: Queen node exists but missing inject_event! node_attrs=%s",
                    [a for a in dir(node) if not a.startswith("_")],
                )

    # Queen is dead — try to revive her
    logger.warning("[handle_chat] Queen is dead for session '%s', reviving on /chat request", session.id)
    manager: Any = request.app["manager"]
    try:
        logger.debug("[handle_chat] Calling manager.revive_queen()...")
        await manager.revive_queen(session)
        logger.debug("[handle_chat] revive_queen() completed successfully")
        # Inject the user's message into the revived queen's queue so the
        # event loop drains it and clears any restored pending_input_state.
        _revived_executor = session.queen_executor
        _revived_node = _revived_executor.node_registry.get("queen") if _revived_executor else None
        if _revived_node is not None and hasattr(_revived_node, "inject_event"):
            await _revived_node.inject_event(message, is_client_input=True, image_content=image_content)
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

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

    progress = await session.colony_runtime.get_goal_progress()
    return web.json_response(progress, dumps=lambda obj: json.dumps(obj, default=str))


async def handle_resume(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/resume — resume a paused execution.

    Body: {"session_id": "...", "checkpoint_id": "..." (optional)}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

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

    entry_points = session.colony_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    input_data = state.get("input_data", {})

    try:
        execution_id = await session.colony_runtime.trigger(
            entry_points[0].id,
            input_data=input_data,
            session_state=resume_session_state,
        )
    except ExecutionAlreadyRunningError as exc:
        return _execution_already_running_response(exc)

    return web.json_response(
        {
            "execution_id": execution_id,
            "resumed_from": worker_session_id,
            "checkpoint_id": checkpoint_id,
        }
    )


async def handle_pause(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/pause — pause the worker (queen stays alive).

    Mirrors the queen's stop_worker() tool: cancels all active worker
    executions, pauses timers so nothing auto-restarts, but does NOT
    touch the queen so she can observe and react to the pause.
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

    runtime = session.colony_runtime
    cancelled = []
    cancelling = []

    for colony_id in runtime.list_graphs():
        reg = runtime.get_graph_registration(colony_id)
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
                    outcome = await stream.cancel_execution(exec_id, reason="Execution paused by user")
                    if outcome == "cancelled":
                        cancelled.append(exec_id)
                    elif outcome == "cancelling":
                        cancelling.append(exec_id)
                except Exception:
                    pass

    # Pause timers so the next tick doesn't restart execution
    runtime.pause_timers()

    # Switch to reviewing — workers stopped, queen now helps the user
    # interpret whatever they produced and decide next steps.
    if session.phase_state is not None:
        await session.phase_state.switch_to_reviewing(source="frontend")

    return web.json_response(
        {
            "stopped": bool(cancelled) and not cancelling,
            "cancelled": cancelled,
            "cancelling": cancelling,
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

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

    body = await request.json()
    execution_id = body.get("execution_id")

    if not execution_id:
        return web.json_response({"error": "execution_id is required"}, status=400)

    for colony_id in session.colony_runtime.list_graphs():
        reg = session.colony_runtime.get_graph_registration(colony_id)
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

            outcome = await stream.cancel_execution(execution_id, reason="Execution stopped by user")

            if outcome == "cancelled":
                # Cancel queen's in-progress LLM turn
                if session.queen_executor:
                    node = session.queen_executor.node_registry.get("queen")
                    if node and hasattr(node, "cancel_current_turn"):
                        node.cancel_current_turn()

                # Switch to reviewing — worker stopped, queen helps the user
                # interpret what happened and decide next steps.
                if session.phase_state is not None:
                    await session.phase_state.switch_to_reviewing(source="frontend")

                return web.json_response(
                    {
                        "stopped": True,
                        "cancelling": False,
                        "execution_id": execution_id,
                    }
                )
            if outcome == "cancelling":
                return web.json_response(
                    {
                        "stopped": False,
                        "cancelling": True,
                        "execution_id": execution_id,
                    },
                    status=202,
                )

    return web.json_response({"stopped": False, "error": "Execution not found"}, status=404)


async def handle_replay(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/replay — re-run from a checkpoint.

    Body: {"session_id": "...", "checkpoint_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.colony_runtime:
        return web.json_response({"error": "No colony loaded in this session"}, status=503)

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

    entry_points = session.colony_runtime.get_entry_points()
    if not entry_points:
        return web.json_response({"error": "No entry points available"}, status=400)

    replay_session_state = {
        "resume_session_id": worker_session_id,
        "resume_from_checkpoint": checkpoint_id,
        "run_id": _load_checkpoint_run_id(cp_path),
    }

    try:
        execution_id = await session.colony_runtime.trigger(
            entry_points[0].id,
            input_data={},
            session_state=replay_session_state,
        )
    except ExecutionAlreadyRunningError as exc:
        return _execution_already_running_response(exc)

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


def persist_colony_spawn_lock(session: Any, colony_name: str) -> None:
    """Persist the colony-spawned lock on a queen session.

    Writes ``colony_spawned: true`` + ``spawned_colony_name`` + a timestamp
    into the queen session's ``meta.json`` and mirrors the same fields onto
    the live ``Session`` object so subsequent ``/chat`` calls in this
    process are rejected immediately without disk I/O.

    Shared by the HTTP route ``handle_mark_colony_spawned`` (frontend
    click on the colony-link card) and the in-process ``create_colony``
    tool path (when the queen forks while in ``incubating`` phase).

    Raises ``OSError`` if the meta.json write fails. Callers should catch
    and respond/log appropriately.
    """
    from datetime import datetime as _dt

    queen_dir = getattr(session, "queen_dir", None)
    if queen_dir is None:
        # Tool-side callers may invoke before the queen dir is available.
        # Still mirror onto the session so the in-process /chat guard
        # works; the meta.json write is just deferred until the next
        # session start writes the file (rare path).
        session.colony_spawned = True
        session.spawned_colony_name = colony_name
        return

    meta_path = queen_dir / "meta.json"
    meta: dict = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            meta = {}

    meta["colony_spawned"] = True
    meta["spawned_colony_name"] = colony_name
    meta["spawned_colony_at"] = _dt.now(UTC).isoformat()

    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    session.colony_spawned = True
    session.spawned_colony_name = colony_name


async def handle_mark_colony_spawned(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/mark-colony-spawned -- lock the queen DM.

    Called by the frontend the first time the user clicks the
    COLONY_CREATED system message. Thin wrapper around
    :func:`persist_colony_spawn_lock` — the heavy lifting (meta.json
    merge + Session cache) lives in the helper so the in-process
    ``create_colony`` path can reuse it without re-issuing an HTTP call.

    Body: ``{"colony_name": "..."}``
    """
    session, err = resolve_session(request)
    if err:
        return err

    body = await request.json() if request.can_read_body else {}
    colony_name = (body.get("colony_name") or "").strip()
    if not colony_name:
        return web.json_response({"error": "colony_name is required"}, status=400)

    try:
        persist_colony_spawn_lock(session, colony_name)
    except OSError as exc:
        logger.exception("mark_colony_spawned: failed to persist meta.json")
        return web.json_response({"error": f"failed to persist: {exc}"}, status=500)

    return web.json_response(
        {
            "session_id": session.id,
            "colony_spawned": True,
            "spawned_colony_name": colony_name,
        }
    )


async def _compact_queen_conversation_in_place(
    *,
    queen_dir: Any,
    queen_ctx: Any,
    queen_loop: Any,
    inherited_from: str | None = None,
) -> tuple[int, int, str] | None:
    """Compact ``queen_dir/conversations`` into one summary message in place.

    Reads ``parts/`` via :class:`FileConversationStore`, runs
    :func:`llm_compact` with ``preserve_user_messages=True``, wipes
    ``parts/`` + ``partials/`` and writes a single ``user``-role
    :class:`Message` (seq 0) tagged with ``inherited_from`` when provided,
    then resets ``cursor.json`` to ``next_seq=1``.  ``events.jsonl`` is
    NOT touched — callers decide whether to wipe it (compact-and-fork)
    or append a boundary marker (colony fork).

    Returns ``(messages_compacted, summary_chars, summary_text)`` on
    success, or ``None`` when there is nothing to do (no LLM ctx, no
    conversation directory, or no messages on disk).  Raises on LLM or
    filesystem failure so the caller can decide between user-facing
    error response (compact-and-fork) and silent fall-through (colony
    fork keeps the raw transcript).
    """
    import shutil as _shutil

    from framework.agent_loop.conversation import Message
    from framework.agent_loop.internals.compaction import llm_compact
    from framework.storage.conversation_store import FileConversationStore

    if queen_ctx is None or getattr(queen_ctx, "llm", None) is None:
        return None

    convs_dir = queen_dir / "conversations"
    if not convs_dir.exists():
        return None

    src_store = FileConversationStore(convs_dir)
    raw_parts = await src_store.read_parts()
    messages: list[Message] = []
    for part in raw_parts:
        try:
            messages.append(Message.from_storage_dict(part))
        except (KeyError, TypeError):
            # Skip malformed parts; the summary still covers everything else.
            logger.warning("compact_in_place: skipping malformed part %r", part)
            continue
    if not messages:
        return None

    max_ctx_tokens = 180_000
    loop_cfg = getattr(queen_loop, "_config", None)
    if loop_cfg is not None and getattr(loop_cfg, "max_context_tokens", None):
        max_ctx_tokens = int(loop_cfg.max_context_tokens)

    summary = await llm_compact(
        queen_ctx,
        messages,
        accumulator=None,
        max_context_tokens=max_ctx_tokens,
        preserve_user_messages=True,
    )

    parts_dir = convs_dir / "parts"
    partials_dir = convs_dir / "partials"

    def _wipe_stores() -> None:
        if parts_dir.exists():
            _shutil.rmtree(parts_dir)
        if partials_dir.exists():
            _shutil.rmtree(partials_dir)

    await asyncio.to_thread(_wipe_stores)

    summary_msg = Message(
        seq=0,
        role="user",
        content=summary,
        inherited_from=inherited_from,
    )
    dest_store = FileConversationStore(convs_dir)
    await dest_store.write_part(0, summary_msg.to_storage_dict())
    await dest_store.write_cursor({"next_seq": 1})

    return (len(messages), len(summary), summary)


async def handle_compact_and_fork(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/compact-and-fork -- compact + new session.

    The locked-by-colony-spawn UI calls this when the user clicks "compact
    + start a new session with the same queen". The flow:

    1. Mint a fresh session ID and copy the old queen-session dir to it.
    2. Run the shared :func:`_compact_queen_conversation_in_place` helper
       on the copy, which reads the parts, runs the LLM compactor with
       ``preserve_user_messages=True``, and replaces ``parts/`` with a
       single summary message.
    3. Wipe ``events.jsonl`` so the new session presents a clean SSE
       replay (the parent's events would otherwise show up in the new
       chat as ghost history).
    4. Update meta.json (clear the parent's lock, record provenance) and
       spin up the live session.

    The OLD session stays alive but locked; the user navigates to the
    new session via the response.
    """
    import shutil
    import time as _time
    from datetime import datetime as _dt

    from framework.agent_loop.types import AgentContext
    from framework.server.session_manager import (
        _generate_session_id,
        _queen_session_dir,
    )

    session, err = resolve_session(request)
    if err:
        return err

    queen_dir = getattr(session, "queen_dir", None)
    if queen_dir is None or not queen_dir.exists():
        return web.json_response(
            {"error": "queen session directory not found"},
            status=404,
        )

    queen_executor = getattr(session, "queen_executor", None)
    if queen_executor is None:
        return web.json_response({"error": "queen is not running"}, status=503)
    queen_node = queen_executor.node_registry.get("queen") if queen_executor else None
    queen_ctx: AgentContext | None = getattr(queen_node, "_last_ctx", None) if queen_node else None
    if queen_ctx is None or queen_ctx.llm is None:
        return web.json_response(
            {
                "error": (
                    "queen context not yet stamped (no LLM available for "
                    "compaction). Send a message to the queen and retry."
                )
            },
            status=503,
        )

    queen_name = session.queen_name or "default"

    new_session_id = _generate_session_id()
    new_dir = _queen_session_dir(new_session_id, queen_name)
    if new_dir.exists():
        # Defensively: same-second collision would clobber another session.
        return web.json_response(
            {"error": f"new session dir collision: {new_dir}"},
            status=500,
        )

    try:
        await asyncio.to_thread(shutil.copytree, queen_dir, new_dir)
    except OSError as exc:
        logger.exception("compact_and_fork: copytree failed")
        return web.json_response(
            {"error": f"failed to fork session dir: {exc}"},
            status=500,
        )

    # Compact in place against the COPY so the source DM is untouched.
    # Failures here are user-visible — the whole point of the action is
    # the compacted summary.
    try:
        result = await _compact_queen_conversation_in_place(
            queen_dir=new_dir,
            queen_ctx=queen_ctx,
            queen_loop=queen_node,
            inherited_from=None,  # this IS the new live session, not an inheritance
        )
    except Exception as exc:
        logger.exception("compact_and_fork: compaction failed")
        return web.json_response(
            {"error": f"compaction failed: {exc}"},
            status=500,
        )
    if result is None:
        return web.json_response(
            {"error": "queen conversation is empty -- nothing to compact"},
            status=400,
        )
    messages_compacted, summary_chars, _summary_text = result

    # Clean partials are already gone; also wipe events.jsonl so the new
    # session's SSE replay starts fresh (the helper deliberately leaves
    # events.jsonl alone so the colony-fork path can append a marker).
    new_events_path = new_dir / "events.jsonl"
    try:
        await asyncio.to_thread(lambda: new_events_path.exists() and new_events_path.unlink())
    except OSError:
        logger.warning("compact_and_fork: failed to wipe events.jsonl", exc_info=True)

    # Update meta.json: clear the lock and record provenance.
    new_meta_path = new_dir / "meta.json"
    new_meta: dict = {}
    if new_meta_path.exists():
        try:
            new_meta = json.loads(new_meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            new_meta = {}
    new_meta.pop("colony_spawned", None)
    new_meta.pop("spawned_colony_name", None)
    new_meta.pop("spawned_colony_at", None)
    new_meta["queen_id"] = queen_name
    new_meta["compacted_from"] = session.id
    new_meta["compacted_at"] = _dt.now(UTC).isoformat()
    new_meta["created_at"] = _time.time()
    try:
        new_meta_path.write_text(json.dumps(new_meta), encoding="utf-8")
    except OSError:
        logger.warning("compact_and_fork: failed to write new meta.json", exc_info=True)

    manager: Any = request.app["manager"]
    try:
        new_session = await manager.create_session(
            session_id=None,
            queen_resume_from=new_session_id,
            queen_name=queen_name,
            initial_phase="independent",
        )
    except Exception as exc:
        logger.exception("compact_and_fork: create_session failed for forked id %s", new_session_id)
        return web.json_response(
            {"error": f"failed to start forked session: {exc}"},
            status=500,
        )

    return web.json_response(
        {
            "new_session_id": new_session.id,
            "queen_id": queen_name,
            "compacted_from": session.id,
            "summary_chars": summary_chars,
            "messages_compacted": messages_compacted,
        }
    )


async def handle_colony_spawn(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/colony-spawn -- fork queen session into a colony.

    Body: {"colony_name": "...", "task": "..."}
    Returns: {"colony_path": "...", "colony_name": "...", "is_new": bool,
              "queen_session_id": "..."}
    """
    session, err = resolve_session(request)
    if err:
        return err

    if not session.queen_executor:
        return web.json_response(
            {"error": "Queen is not running in this session."},
            status=503,
        )

    body = await request.json()
    colony_name = body.get("colony_name", "").strip()
    task = body.get("task", "").strip()
    tasks = body.get("tasks")

    if not colony_name:
        return web.json_response({"error": "colony_name is required"}, status=400)

    import re

    if not re.match(r"^[a-z0-9_]+$", colony_name):
        return web.json_response(
            {"error": "colony_name must be lowercase alphanumeric with underscores"},
            status=400,
        )

    try:
        result = await fork_session_into_colony(
            session=session,
            colony_name=colony_name,
            task=task,
            tasks=tasks if isinstance(tasks, list) else None,
        )
    except Exception as e:
        logger.exception("colony_spawn fork failed")
        return web.json_response({"error": f"colony fork failed: {e}"}, status=500)

    return web.json_response(result)


async def _compact_inherited_conversation(
    *,
    dest_queen_dir: Any,
    queen_ctx: Any,
    queen_loop: Any,
    source_session_id: str,
) -> None:
    """Compact a freshly-forked colony's inherited transcript in place.

    Thin wrapper over :func:`_compact_queen_conversation_in_place` that
    tags the resulting summary message with ``inherited_from`` and
    appends a ``colony_fork_marker`` event to the colony's
    ``events.jsonl`` so the frontend can group + collapse everything
    that preceded the fork.

    Called from ``fork_session_into_colony`` after the parent queen
    session directory has been copied into the colony's queue dir.

    Fail-soft: any exception (compaction, write, marker append) logs a
    warning and leaves the directory as the raw copytree wrote it.  The
    colony still works; it just inherits the full DM transcript instead
    of the summary.
    """
    import json as _json
    from datetime import UTC as _UTC, datetime as _datetime

    try:
        result = await _compact_queen_conversation_in_place(
            queen_dir=dest_queen_dir,
            queen_ctx=queen_ctx,
            queen_loop=queen_loop,
            inherited_from=source_session_id,
        )
    except Exception:
        logger.warning(
            "compact_inherited: compaction failed; leaving raw transcript",
            exc_info=True,
        )
        return

    if result is None:
        # No queen ctx, no parts on disk, or empty conversation. Nothing
        # to compact and nothing to mark — the colony will just open with
        # an empty chat (or whatever raw state was copied).
        logger.info(
            "compact_inherited: nothing to compact for colony forked from %s",
            source_session_id,
        )
        return

    messages_compacted, summary_chars, summary_text = result

    # Append the boundary marker to the colony's events.jsonl so the
    # frontend can group + collapse everything that came before.  The
    # marker carries the parent session id and a short summary preview
    # so the collapsed widget has something to label itself with even
    # before the user expands it.
    fork_iso = _datetime.now(_UTC).isoformat()
    marker = {
        "type": "colony_fork_marker",
        "stream_id": "queen",
        "data": {
            "parent_session_id": source_session_id,
            "fork_time": fork_iso,
            "summary_preview": summary_text[:240],
            "inherited_message_count": messages_compacted,
        },
        "timestamp": fork_iso,
    }
    events_path = dest_queen_dir / "events.jsonl"

    def _append_marker() -> None:
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(marker) + "\n")

    try:
        await asyncio.to_thread(_append_marker)
    except OSError:
        logger.warning("compact_inherited: failed to append fork marker", exc_info=True)

    logger.info(
        "compact_inherited: compacted %d parent message(s) -> 1 summary (%d chars) for colony forked from %s",
        messages_compacted,
        summary_chars,
        source_session_id,
    )


async def fork_session_into_colony(
    *,
    session: Any,
    colony_name: str,
    task: str,
    tasks: list[dict] | None = None,
    concurrency_hint: int | None = None,
) -> dict:
    """Fork a queen session into a colony directory.

    Extracted from ``handle_colony_spawn`` so the queen-side
    ``create_colony`` tool can call it directly without going through
    HTTP. The caller is responsible for validating ``colony_name``
    against the lowercase-alphanumeric regex.

    The fork:
    1. Creates a colony directory with a single worker config (``worker.json``)
       holding the queen's current tools, prompts, skills, and loop config.
    2. Duplicates the queen's full session (conversations + events) into a new
       queen-session directory assigned to the colony so that cold-restoring
       the colony resumes with the queen's entire conversation history.
    3. Multiple independent sessions can be created against the same colony,
       giving parallel execution capacity without separate worker configs.
    4. Initializes (or ensures) ``data/progress.db`` — the colony's SQLite
       task queue + progress ledger. When *tasks* is provided, the queen-
       authored task batch is seeded into the queue in one transaction.
       The absolute DB path is threaded into the worker's ``input_data``
       so spawned workers see it in their first user message.

    Returns ``{"colony_path", "colony_name", "queen_session_id", "is_new",
              "db_path", "task_ids"}``.
    """
    import asyncio
    import json
    import shutil
    from datetime import datetime
    from pathlib import Path

    from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
    from framework.agent_loop.types import AgentContext
    from framework.host.progress_db import ensure_progress_db, seed_tasks
    from framework.server.session_manager import _queen_session_dir

    # Diagnostic capture: when the fork fails here we want to know which
    # piece of queen state was missing (executor cleared vs. node missing
    # vs. _last_ctx never stamped). Without this, callers only see
    # "'NoneType' object has no attribute 'node_registry'" with no hint
    # whether the queen loop exited, is mid-revive, or ran a different
    # path that never ran AgentLoop._execute_impl.
    queen_executor = getattr(session, "queen_executor", None)
    queen_task = getattr(session, "queen_task", None)
    phase_state_dbg = getattr(session, "phase_state", None)
    logger.info(
        "[fork_session_into_colony] session=%s colony=%s "
        "queen_executor=%s queen_task=%s queen_task_done=%s "
        "phase=%s queen_name=%s",
        session.id,
        colony_name,
        queen_executor,
        queen_task,
        queen_task.done() if queen_task is not None else None,
        getattr(phase_state_dbg, "phase", None),
        getattr(session, "queen_name", None),
    )

    if queen_executor is None:
        raise RuntimeError(
            f"queen_executor is None for session {session.id!r} — the "
            "queen loop isn't running right now. Wait for the queen to "
            "come back (or send her a chat message to revive her) and "
            "retry create_colony. The skill folder is already written, "
            "so the retry is free."
        )

    node_registry = getattr(queen_executor, "node_registry", None)
    if not isinstance(node_registry, dict) or "queen" not in node_registry:
        raise RuntimeError(
            f"queen node is missing from the executor's registry for "
            f"session {session.id!r} (registry keys="
            f"{list(node_registry.keys()) if isinstance(node_registry, dict) else type(node_registry).__name__}"
            "). The queen loop is in an initialization or teardown "
            "window; retry after a moment."
        )

    queen_loop: AgentLoop = node_registry["queen"]
    queen_ctx: AgentContext = getattr(queen_loop, "_last_ctx", None)
    if queen_ctx is None:
        logger.warning(
            "[fork_session_into_colony] queen_loop has no _last_ctx yet "
            "(session=%s) — falling back to empty tool/skill snapshot; "
            "the forked worker will inherit no tools.",
            session.id,
        )

    # "is_new" keys off worker.json, not bare dir existence: the queen's
    # create_colony tool now pre-creates colony_dir (so it can
    # materialize the colony-scoped skill folder BEFORE the fork), which
    # would wrongly flag every fresh colony as "already-exists" if we
    # used ``not colony_dir.exists()``. A colony is "new" until its
    # worker config has actually been written.
    colony_dir = Path.home() / ".hive" / "colonies" / colony_name
    worker_name = "worker"
    worker_config_path = colony_dir / f"{worker_name}.json"
    is_new = not worker_config_path.exists()
    colony_dir.mkdir(parents=True, exist_ok=True)
    (colony_dir / "data").mkdir(exist_ok=True)

    # ── 0. Ensure the colony's progress DB exists and seed tasks ──
    # Runs before worker.json is written so the DB path can be threaded
    # into input_data. Idempotent on reruns of the same colony name.
    db_path = await asyncio.to_thread(ensure_progress_db, colony_dir)
    seeded_task_ids: list[str] = []
    if tasks:
        seeded_task_ids = await asyncio.to_thread(seed_tasks, db_path, tasks, source="queen_create")
        logger.info(
            "progress_db: seeded %d task(s) into colony '%s'",
            len(seeded_task_ids),
            colony_name,
        )
    elif task and task.strip():
        # Phase 2 auto-seed: when the queen uses the simple single-task
        # form of create_colony (no explicit ``tasks=[{...}]`` list),
        # insert exactly one row so the first worker spawned into this
        # colony has something to claim. Without this the queue is
        # empty and the worker falls back to executing from the chat
        # spawn message, defeating the cross-run durability the tracker
        # exists for.
        try:
            seeded_task_ids = await asyncio.to_thread(
                seed_tasks,
                db_path,
                [{"goal": task.strip()}],
                source="create_colony_auto",
            )
            logger.info(
                "progress_db: auto-seeded 1 task into colony '%s' (task_id=%s, from single-task create_colony form)",
                colony_name,
                seeded_task_ids[0] if seeded_task_ids else "?",
            )
        except Exception as exc:
            logger.warning(
                "progress_db: auto-seed failed for colony '%s' (continuing without a pre-seeded row): %s",
                colony_name,
                exc,
            )

    # Fixed worker name and config path are already computed above so
    # ``is_new`` can be derived from worker.json rather than the colony
    # directory (see comment on the ``is_new`` block).

    # ── 1. Gather queen state ─────────────────────────────────────
    # Queen-lifecycle + agent-management tools are registered ONLY against
    # the queen's runtime (they need a live session + phase_state to
    # operate). Forking them into a worker config makes the worker fail
    # tool validation when its own runtime loads because those tools
    # aren't registered there. Strip them out of the snapshot.
    #
    # The blacklist is derived from the queen phase tool lists: any tool
    # that appears in any _QUEEN_*_TOOLS list but is NOT in the worker's
    # "work-doing" whitelist (file I/O + shell + undo) is queen-only.
    # This stays in sync automatically when new queen tools are added.
    queen_only_tools = _resolve_queen_only_tools()
    queen_tools: list = queen_ctx.available_tools if queen_ctx else []
    tool_names = [t.name for t in queen_tools if t.name not in queen_only_tools]

    phase_state = getattr(session, "phase_state", None)

    # Skills + protocols ARE inherited by the worker so it knows how to
    # use tools and follow operational conventions. These are NOT queen
    # identity data -- they are runtime-neutral guides.
    queen_skills_catalog = queen_ctx.skills_catalog_prompt if queen_ctx else ""
    queen_protocols = queen_ctx.protocols_prompt if queen_ctx else ""
    queen_skill_dirs = queen_ctx.skill_dirs if queen_ctx else []

    # Build a focused, worker-scoped system prompt. We deliberately do
    # NOT inherit the queen's identity_prompt or her phase-specific prompt
    # (building / running / etc.) -- those describe "how to be a queen"
    # and confuse the worker into greeting the user as Charlotte with no
    # memory. The worker is a task executor; give it a task-focused brief.
    worker_task = task or "Continue the work from the queen's current session."
    worker_system_prompt = (
        "You are a focused worker agent spawned by the queen to carry out "
        "one specific task. Read the goal carefully, use your available "
        "tools to make progress, and call set_output when complete. "
        "If you get stuck or need human judgement, call escalate to hand "
        "the question back to the queen.\n\n"
        f"Task: {worker_task}"
    )

    queen_lc_config: dict = {
        "max_iterations": 999_999,
        "max_tool_calls_per_turn": 30,
        "max_context_tokens": 180_000,
    }
    queen_config: LoopConfig | None = getattr(queen_loop, "_config", None)
    if queen_config is not None:
        queen_lc_config["max_iterations"] = queen_config.max_iterations
        queen_lc_config["max_tool_calls_per_turn"] = queen_config.max_tool_calls_per_turn
        queen_lc_config["max_context_tokens"] = queen_config.max_context_tokens
        queen_lc_config["max_tool_result_chars"] = queen_config.max_tool_result_chars

    # ── 2. Write worker.json (create or update) ──────────────────
    # identity_prompt and memory_prompt are intentionally EMPTY -- the
    # worker is not Charlotte / Alexandra / etc., it is a task executor.
    # Inheriting the queen's persona made the worker greet the user in
    # first person with no memory of the task it was actually given.
    # Thread the first seeded task_id into input_data so the worker's
    # first claim pins to a specific row (skill's assigned-task-id
    # branch). When multiple tasks were seeded we only pin the first —
    # subsequent workers (via run_agent_with_input or parallel spawns)
    # get their own task_id assigned at spawn time.
    _worker_input_data: dict[str, Any] = {
        "db_path": str(db_path),
        "colony_id": colony_name,
    }
    if seeded_task_ids:
        _worker_input_data["task_id"] = seeded_task_ids[0]

    worker_meta = {
        "name": worker_name,
        "version": "1.0.0",
        "description": f"Worker clone from queen session {session.id}",
        # Colony progress tracker: worker sees these in its first user
        # message via _format_spawn_task_message.  The colony-progress-
        # tracker default skill teaches the worker how to use them.
        "input_data": _worker_input_data,
        "goal": {
            "description": worker_task,
            "success_criteria": [],
            "constraints": [],
        },
        "system_prompt": worker_system_prompt,
        "tools": tool_names,
        "skills_catalog_prompt": queen_skills_catalog,
        "protocols_prompt": queen_protocols,
        "skill_dirs": list(queen_skill_dirs),
        "identity_prompt": "",
        "memory_prompt": "",
        "queen_phase": phase_state.phase if phase_state else "",
        "queen_id": getattr(phase_state, "queen_id", "") if phase_state else "",
        "loop_config": queen_lc_config,
        "spawned_from": session.id,
        "spawned_at": datetime.now(UTC).isoformat(),
    }
    # Concurrency advisory baked in at incubation time. Not enforced — the
    # progress.db queue is atomic regardless — but the colony queen reads
    # this when planning fan-outs (run_parallel_workers, trigger-fired
    # batches) so behavior matches what the user agreed to during
    # incubation.
    if isinstance(concurrency_hint, int) and concurrency_hint > 0:
        worker_meta["concurrency_hint"] = concurrency_hint
    worker_config_path.write_text(json.dumps(worker_meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 3. Duplicate queen session into colony ───────────────────
    # Copy the queen's full session directory (conversations, events,
    # meta) into a new queen-session dir assigned to this colony.
    # This is the "brain fork" -- the colony queen starts with the
    # full conversation history from the originating session.
    #
    # session.queen_dir is authoritative -- queen_orchestrator relocates
    # it from default/ to the selected queen's dir on identity selection.
    source_queen_dir = session.queen_dir
    # Extract queen identity from the dir path: .../queens/{name}/sessions/xxx
    queen_name = (
        source_queen_dir.parent.parent.name
        if source_queen_dir and source_queen_dir.exists()
        else (session.queen_name or "default")
    )

    # Generate a colony-specific session ID so the colony has its own
    # session identity while preserving the full conversation.
    from framework.server.session_manager import _generate_session_id

    colony_session_id = _generate_session_id()
    dest_queen_dir = _queen_session_dir(colony_session_id, queen_name)

    if source_queen_dir.exists():
        await asyncio.to_thread(shutil.copytree, source_queen_dir, dest_queen_dir, dirs_exist_ok=True)
        # Update the duplicated meta.json to point to the colony
        dest_meta_path = dest_queen_dir / "meta.json"
        dest_meta: dict = {}
        if dest_meta_path.exists():
            try:
                dest_meta = json.loads(dest_meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        dest_meta["agent_path"] = str(colony_dir)
        dest_meta["agent_name"] = colony_name.replace("_", " ").title()
        dest_meta["queen_id"] = queen_name
        dest_meta["forked_from"] = session.id
        dest_meta["colony_fork"] = True  # exclude from queen DM history
        # Clear any colony_spawned lock that came over from the parent meta —
        # it was the PARENT session that locked, not this freshly-forked one.
        dest_meta.pop("colony_spawned", None)
        dest_meta.pop("spawned_colony_name", None)
        dest_meta.pop("spawned_colony_at", None)
        dest_meta_path.write_text(json.dumps(dest_meta, ensure_ascii=False), encoding="utf-8")
        logger.info(
            "Duplicated queen session %s -> %s for colony '%s'",
            session.id,
            colony_session_id,
            colony_name,
        )

        # ── 3a. Compact the inherited conversation (fire-and-forget) ──
        # The colony queen doesn't need the full DM transcript — that
        # transcript was about REACHING the decision to fork, which is
        # now settled. Compaction replaces the copied parts with a
        # single summary message tagged ``inherited_from``.
        #
        # Compaction issues an LLM call that can legitimately exceed
        # the 60s tool-call timeout, so we schedule it (plus the
        # downstream worker-storage copy) as a background task and
        # return immediately. A compaction_status.json marker in
        # dest_queen_dir lets a subsequent colony session-load await
        # completion before reading the conversation files (see
        # session_manager.create_session_with_worker_colony).
        #
        # Fail-soft: any exception is logged and recorded in the
        # marker; the colony still works with the raw transcript.
        from framework.server import compaction_status

        compaction_status.mark_in_progress(dest_queen_dir)

        _worker_storage = Path.home() / ".hive" / "agents" / colony_name / worker_name
        _dest_queen_dir = dest_queen_dir
        _queen_ctx = queen_ctx
        _queen_loop = queen_loop
        _source_session_id = session.id

        # Wall-clock cap on the background compaction's LLM call.
        # Without this a hung/misbehaving model (seen with local
        # endpoints) leaves compaction_status="in_progress" forever and
        # the colony-open await_completion waste its full poll window
        # before giving up. When this fires we still fall through to
        # the worker-storage copy below so the colony opens with the
        # raw transcript instead of empty state.
        _COMPACTION_TIMEOUT_SECONDS = 180.0

        async def _finalize_fork() -> None:
            compaction_error: str | None = None
            try:
                await asyncio.wait_for(
                    _compact_inherited_conversation(
                        dest_queen_dir=_dest_queen_dir,
                        queen_ctx=_queen_ctx,
                        queen_loop=_queen_loop,
                        source_session_id=_source_session_id,
                    ),
                    timeout=_COMPACTION_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                compaction_error = (
                    f"compaction timed out after {_COMPACTION_TIMEOUT_SECONDS:.0f}s (falling back to raw transcript)"
                )
                logger.warning(
                    "fork_session_into_colony: %s for %s",
                    compaction_error,
                    _dest_queen_dir,
                )
            except Exception as exc:
                compaction_error = f"compaction failed: {exc}"
                logger.warning(
                    "fork_session_into_colony: %s for %s (falling back to raw transcript)",
                    compaction_error,
                    _dest_queen_dir,
                    exc_info=True,
                )

            # Worker storage copy runs regardless of the compaction
            # outcome. If compaction succeeded, the worker gets the
            # summary; if it failed / timed out, dest_queen_dir still
            # has the raw transcript from the earlier copytree and the
            # worker gets that. Without this copy-on-failure the worker
            # would open to empty state on every compaction hiccup.
            try:
                _worker_storage.mkdir(parents=True, exist_ok=True)
                worker_conv_dir = _worker_storage / "conversations"
                source_conv_dir = _dest_queen_dir / "conversations"
                if source_conv_dir.exists():
                    await asyncio.to_thread(
                        shutil.copytree,
                        source_conv_dir,
                        worker_conv_dir,
                        dirs_exist_ok=True,
                    )
                    logger.info(
                        "Copied queen conversations to worker storage %s",
                        worker_conv_dir,
                    )
            except Exception:
                logger.warning(
                    "fork_session_into_colony: worker-storage copy failed for %s",
                    _worker_storage,
                    exc_info=True,
                )

            if compaction_error:
                compaction_status.mark_failed(_dest_queen_dir, compaction_error)
            else:
                compaction_status.mark_done(_dest_queen_dir)

        _bg_task = asyncio.create_task(_finalize_fork())
        _BACKGROUND_FORK_TASKS.add(_bg_task)
        _bg_task.add_done_callback(_BACKGROUND_FORK_TASKS.discard)
    else:
        logger.warning(
            "Queen session dir %s not found, colony will start fresh",
            source_queen_dir,
        )

    # ── 4. Write metadata.json (queen provenance) ────────────────
    metadata_path = colony_dir / "metadata.json"
    metadata: dict = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    metadata["colony_name"] = colony_name
    metadata["queen_name"] = queen_name
    metadata["queen_session_id"] = colony_session_id
    metadata["source_session_id"] = session.id
    metadata.setdefault("created_at", datetime.now(UTC).isoformat())
    metadata["updated_at"] = datetime.now(UTC).isoformat()
    metadata.setdefault("workers", {})
    metadata["workers"][worker_name] = {
        "task": worker_task[:100],
        "spawned_at": datetime.now(UTC).isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── 4a. Inherit the queen's tool allowlist into the colony ───
    # A colony forked from a curated queen should start with the same
    # tool surface (otherwise the colony silently falls back to its own
    # "allow every MCP tool" default, undoing the parent's curation).
    # We copy the queen's LIVE effective allowlist so the snapshot
    # reflects whatever was in force the moment the user clicked "Create
    # Colony". Users can further narrow the colony via the Tool Library.
    # Skip the write when the queen is on allow-all (None) so the colony
    # keeps the same semantics without creating an inert sidecar.
    try:
        queen_enabled = getattr(
            getattr(session, "phase_state", None),
            "enabled_mcp_tools",
            None,
        )
        if isinstance(queen_enabled, list):
            from framework.host.colony_tools_config import update_colony_tools_config

            update_colony_tools_config(colony_name, list(queen_enabled))
            logger.info(
                "Inherited queen allowlist into colony '%s' (%d tools)",
                colony_name,
                len(queen_enabled),
            )
    except Exception:
        # Inheritance is best-effort — don't let a tools.json hiccup
        # abort colony creation.
        logger.warning(
            "Failed to inherit queen allowlist into colony '%s'",
            colony_name,
            exc_info=True,
        )

    # ── 5. Update source queen session meta.json ─────────────────
    # Link the originating session back to the colony for discovery.
    source_meta_path = source_queen_dir / "meta.json"
    if source_meta_path.exists():
        try:
            qmeta = json.loads(source_meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            qmeta = {}
    else:
        qmeta = {}
    qmeta["agent_path"] = str(colony_dir)
    qmeta["agent_name"] = colony_name.replace("_", " ").title()
    try:
        source_meta_path.parent.mkdir(parents=True, exist_ok=True)
        source_meta_path.write_text(json.dumps(qmeta, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

    logger.info(
        "Forked queen to colony '%s' (new=%s, tools=%d, session=%s)",
        colony_name,
        is_new,
        len(queen_tools),
        colony_session_id,
    )
    return {
        "colony_path": str(colony_dir),
        "colony_name": colony_name,
        "queen_session_id": colony_session_id,
        "is_new": is_new,
        "db_path": str(db_path),
        "task_ids": seeded_task_ids,
        # "in_progress" when a background compactor was scheduled above,
        # "skipped" when the source queen dir was missing (nothing to
        # compact). Frontend uses this to decide whether to display a
        # "preparing colony…" state while session-load blocks on the
        # compaction marker.
        "compaction_status": ("in_progress" if source_queen_dir.exists() else "skipped"),
    }


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
    app.router.add_post("/api/sessions/{session_id}/colony-spawn", handle_colony_spawn)
    app.router.add_post(
        "/api/sessions/{session_id}/mark-colony-spawned",
        handle_mark_colony_spawned,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/compact-and-fork",
        handle_compact_and_fork,
    )
