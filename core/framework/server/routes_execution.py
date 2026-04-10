"""Execution control routes — trigger, inject, chat, resume, stop, replay."""

import asyncio
import json
import logging
from typing import Any

from aiohttp import web

from framework.credentials.validation import validate_agent_credentials
from framework.agent_loop.conversation import LEGACY_RUN_ID
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
        "ask_user_multiple",
    }
)


# Queen-lifecycle tools that are registered into the queen's tool registry
# but NOT listed in any _QUEEN_*_TOOLS phase list (they're reachable only via
# explicit registration, not phase-based gating). These must still be stripped
# from forked worker configs.
_QUEEN_LIFECYCLE_EXTRAS: frozenset[str] = frozenset(
    {
        "start_worker",
        "stop_worker_and_plan",
        "stop_worker_and_review",
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
        _QUEEN_BUILDING_TOOLS,
        _QUEEN_EDITING_TOOLS,
        _QUEEN_INDEPENDENT_TOOLS,
        _QUEEN_PLANNING_TOOLS,
        _QUEEN_RUNNING_TOOLS,
        _QUEEN_STAGING_TOOLS,
    )

    union: set[str] = set()
    for tool_list in (
        _QUEEN_PLANNING_TOOLS,
        _QUEEN_BUILDING_TOOLS,
        _QUEEN_STAGING_TOOLS,
        _QUEEN_RUNNING_TOOLS,
        _QUEEN_EDITING_TOOLS,
        _QUEEN_INDEPENDENT_TOOLS,
    ):
        union.update(tool_list)
    derived = union - _WORKER_INHERITED_TOOLS
    return frozenset(derived | _QUEEN_LIFECYCLE_EXTRAS)


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

    execution_id = await session.colony_runtime.trigger(
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
        logger.debug(
            "[handle_chat] node_registry keys: %s", list(queen_executor.node_registry.keys())
        )
        node = queen_executor.node_registry.get("queen")
        logger.debug(
            "[handle_chat] node=%s, node_type=%s", node, type(node).__name__ if node else None
        )
        logger.debug(
            "[handle_chat] has_inject_event=%s", hasattr(node, "inject_event") if node else False
        )

        # Race condition: executor exists but node not created yet (still initializing)
        if node is None and session.queen_task is not None and not session.queen_task.done():
            logger.warning(
                "[handle_chat] Queen executor exists but node"
                " not ready yet (initializing). Waiting..."
            )
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
                    "[handle_chat] CRITICAL: Queen node exists"
                    " but missing inject_event!"
                    " node_attrs=%s",
                    [a for a in dir(node) if not a.startswith("_")],
                )

    # Queen is dead — try to revive her
    logger.warning(
        "[handle_chat] Queen is dead for session '%s', reviving on /chat request", session.id
    )
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
            await _revived_node.inject_event(
                message, is_client_input=True, image_content=image_content
            )
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

    execution_id = await session.colony_runtime.trigger(
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

    execution_id = await session.colony_runtime.trigger(
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


async def handle_colony_spawn(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/colony-spawn -- fork queen session into a colony.

    Body: {"colony_name": "...", "task": "..."}
    Returns: {"colony_path": "...", "colony_name": "...", "is_new": bool,
              "queen_session_id": "..."}

    The clone:
    1. Creates a colony directory with a single worker config (``worker.json``)
       holding the queen's current tools, prompts, skills, and loop config.
    2. Duplicates the queen's full session (conversations + events) into a new
       queen-session directory assigned to the colony so that cold-restoring
       the colony resumes with the queen's entire conversation history.
    3. Multiple independent sessions can be created against the same colony,
       giving parallel execution capacity without separate worker configs.
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

    if not colony_name:
        return web.json_response({"error": "colony_name is required"}, status=400)

    import re

    if not re.match(r"^[a-z0-9_]+$", colony_name):
        return web.json_response(
            {"error": "colony_name must be lowercase alphanumeric with underscores"},
            status=400,
        )

    import asyncio
    import json
    import shutil
    from datetime import datetime, timezone
    from pathlib import Path

    from framework.agent_loop.agent_loop import AgentLoop, LoopConfig
    from framework.agent_loop.types import AgentContext, AgentSpec
    from framework.server.session_manager import _queen_session_dir
    from framework.storage.conversation_store import FileConversationStore

    queen_loop: AgentLoop = session.queen_executor.node_registry["queen"]
    queen_ctx: AgentContext = getattr(queen_loop, "_last_ctx", None)

    colony_dir = Path.home() / ".hive" / "colonies" / colony_name
    is_new = not colony_dir.exists()
    colony_dir.mkdir(parents=True, exist_ok=True)
    (colony_dir / "data").mkdir(exist_ok=True)

    # Fixed worker name -- sessions are the unit of parallelism, not workers
    worker_name = "worker"

    worker_config_path = colony_dir / f"{worker_name}.json"

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

    system_prompt = ""
    phase_state = getattr(session, "phase_state", None)
    if phase_state is not None:
        try:
            system_prompt = phase_state.get_current_prompt()
        except Exception:
            pass
    if not system_prompt and queen_ctx:
        from framework.agent_loop.prompting import build_system_prompt_for_context

        try:
            system_prompt = build_system_prompt_for_context(queen_ctx)
        except Exception:
            pass

    queen_skills_catalog = queen_ctx.skills_catalog_prompt if queen_ctx else ""
    queen_protocols = queen_ctx.protocols_prompt if queen_ctx else ""
    queen_skill_dirs = queen_ctx.skill_dirs if queen_ctx else []
    queen_identity = ""
    queen_memory = ""
    if phase_state is not None:
        queen_identity = getattr(phase_state, "queen_identity_prompt", "") or ""
        queen_memory = getattr(phase_state, "_cached_global_recall_block", "") or ""

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

    worker_task = task or "Continue the work from the queen's current session."

    # ── 2. Write worker.json (create or update) ──────────────────
    worker_meta = {
        "name": worker_name,
        "version": "1.0.0",
        "description": f"Worker clone from queen session {session.id}",
        "goal": {
            "description": worker_task,
            "success_criteria": [],
            "constraints": [],
        },
        "system_prompt": system_prompt,
        "tools": tool_names,
        "skills_catalog_prompt": queen_skills_catalog,
        "protocols_prompt": queen_protocols,
        "skill_dirs": list(queen_skill_dirs),
        "identity_prompt": queen_identity,
        "memory_prompt": queen_memory,
        "queen_phase": phase_state.phase if phase_state else "",
        "queen_id": getattr(phase_state, "queen_id", "") if phase_state else "",
        "loop_config": queen_lc_config,
        "spawned_from": session.id,
        "spawned_at": datetime.now(timezone.utc).isoformat(),
    }
    worker_config_path.write_text(
        json.dumps(worker_meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )

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
        await asyncio.to_thread(
            shutil.copytree, source_queen_dir, dest_queen_dir, dirs_exist_ok=True
        )
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
        dest_meta_path.write_text(
            json.dumps(dest_meta, ensure_ascii=False), encoding="utf-8"
        )
        logger.info(
            "Duplicated queen session %s -> %s for colony '%s'",
            session.id,
            colony_session_id,
            colony_name,
        )
        # Copy queen conversations into worker storage so the worker
        # starts with the queen's full context.
        worker_storage = Path.home() / ".hive" / "agents" / colony_name / worker_name
        worker_storage.mkdir(parents=True, exist_ok=True)
        worker_conv_dir = worker_storage / "conversations"
        source_conv_dir = dest_queen_dir / "conversations"
        if source_conv_dir.exists():
            await asyncio.to_thread(
                shutil.copytree, source_conv_dir, worker_conv_dir, dirs_exist_ok=True
            )
            logger.info("Copied queen conversations to worker storage %s", worker_conv_dir)
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
    metadata.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
    metadata.setdefault("workers", {})
    metadata["workers"][worker_name] = {
        "task": worker_task[:100],
        "spawned_at": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

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
        source_meta_path.write_text(
            json.dumps(qmeta, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass

    logger.info(
        "Forked queen to colony '%s' (new=%s, tools=%d, session=%s)",
        colony_name,
        is_new,
        len(queen_tools),
        colony_session_id,
    )
    return web.json_response(
        {
            "colony_path": str(colony_dir),
            "colony_name": colony_name,
            "queen_session_id": colony_session_id,
            "is_new": is_new,
        }
    )


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
