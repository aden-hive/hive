"""Session lifecycle and session info routes.

Session-primary routes:
- POST   /api/sessions                                — create session (with or without worker)
- GET    /api/sessions                                — list all active sessions
- GET    /api/sessions/{session_id}                   — session detail
- DELETE /api/sessions/{session_id}                   — stop session entirely
- POST   /api/sessions/{session_id}/colony            — load a colony into session
- DELETE /api/sessions/{session_id}/colony            — unload colony from session
- GET    /api/sessions/{session_id}/stats             — runtime statistics
- GET    /api/sessions/{session_id}/entry-points      — list entry points
- PATCH  /api/sessions/{session_id}/triggers/{id}    — update trigger task
- POST   /api/sessions/{session_id}/triggers/{id}/run — fire trigger once (manual)
- GET    /api/sessions/{session_id}/colonies          — list colony IDs
- GET    /api/sessions/{session_id}/events/history   — persisted eventbus log (for replay)

"""

import asyncio
import contextlib
import json
import logging
import shutil
import subprocess
import sys
import time
from pathlib import Path

from aiohttp import web

from framework.server.app import (
    MANAGER_KEY,
    resolve_session,
    validate_agent_path,
)
from framework.server.session_manager import SessionManager

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> SessionManager:
    return request.app[MANAGER_KEY]


def _session_to_live_dict(session) -> dict:
    """Serialize a live Session to the session-primary JSON shape."""
    from framework.llm.capabilities import supports_image_tool_results

    info = session.worker_info
    phase_state = getattr(session, "phase_state", None)
    queen_model: str = getattr(getattr(session, "runner", None), "model", "") or ""
    return {
        "session_id": session.id,
        "colony_id": session.colony_id,
        "colony_name": info.name if info else session.colony_id,
        "has_worker": session.colony_runtime is not None,
        "agent_path": str(session.worker_path) if session.worker_path else "",
        "description": info.description if info else "",
        "goal": info.goal_name if info else "",
        "node_count": info.node_count if info else 0,
        "loaded_at": session.loaded_at,
        "uptime_seconds": round(time.time() - session.loaded_at, 1),
        "intro_message": getattr(session.runner, "intro_message", "") or "",
        "queen_phase": phase_state.phase if phase_state else ("staging" if session.colony_runtime else "planning"),
        "queen_supports_images": supports_image_tool_results(queen_model) if queen_model else True,
        "queen_id": getattr(phase_state, "queen_id", None) if phase_state else None,
        "queen_name": (phase_state.queen_profile or {}).get("name") if phase_state else None,
        "colony_spawned": getattr(session, "colony_spawned", False),
        "spawned_colony_name": getattr(session, "spawned_colony_name", None),
    }


def _credential_error_response(exc: Exception, agent_path: str | None) -> web.Response | None:
    """If *exc* is a CredentialError, return a 424 with structured credential info.

    Returns None if *exc* is not a credential error (caller should handle it).
    Uses the CredentialValidationResult attached by validate_agent_credentials.
    """
    from framework.credentials.models import CredentialError

    if not isinstance(exc, CredentialError):
        return None

    from framework.server.routes_credentials import _status_to_dict

    # Prefer the structured validation result attached to the exception
    validation_result = getattr(exc, "validation_result", None)
    if validation_result is not None:
        required = [_status_to_dict(c) for c in validation_result.failed]
    else:
        # Fallback for exceptions without a validation result
        required = []

    return web.json_response(
        {
            "error": "credentials_required",
            "message": str(exc),
            "agent_path": agent_path or "",
            "required": required,
        },
        status=424,
    )


# ------------------------------------------------------------------
# Session lifecycle
# ------------------------------------------------------------------


async def handle_create_session(request: web.Request) -> web.Response:
    """POST /api/sessions — create a session.

    Body: {
        "agent_path": "..." (optional — if provided, creates session with colony),
        "agent_id": "..." (optional — colony ID override),
        "session_id": "..." (optional — custom session ID),
        "model": "..." (optional),
        "initial_prompt": "..." (optional — first user message for the queen),
        "initial_phase": "..." (optional — "independent" for standalone queen),
    }

    When agent_path is provided, creates a session with a colony in one step
    (equivalent to the old POST /api/agents). Otherwise creates a queen-only
    session that can later have a colony loaded via POST /sessions/{id}/colony.
    """
    from framework.agents.queen.queen_profiles import ensure_default_queens, load_queen_profile
    from framework.tools.queen_lifecycle_tools import QUEEN_PHASES

    manager = _get_manager(request)
    if request.can_read_body:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"error": "Invalid JSON body"}, status=400)
        if not isinstance(body, dict):
            return web.json_response({"error": "Request body must be a JSON object"}, status=400)
    else:
        body = {}
    agent_path = body.get("agent_path")
    agent_id = body.get("agent_id")
    session_id = body.get("session_id")
    model = body.get("model")
    initial_prompt = body.get("initial_prompt")
    queen_resume_from = body.get("queen_resume_from")
    queen_name = body.get("queen_name")
    initial_phase = body.get("initial_phase")
    worker_name = body.get("worker_name")

    if initial_phase is not None and initial_phase not in QUEEN_PHASES:
        return web.json_response(
            {
                "error": f"Invalid initial_phase '{initial_phase}'",
                "valid": sorted(QUEEN_PHASES),
            },
            status=400,
        )
    if queen_name:
        ensure_default_queens()
        try:
            load_queen_profile(queen_name)
        except FileNotFoundError:
            return web.json_response({"error": f"Queen '{queen_name}' not found"}, status=404)

    if agent_path:
        try:
            agent_path = str(validate_agent_path(agent_path))
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=400)

    try:
        if agent_path:
            session = await manager.create_session_with_worker_colony(
                agent_path,
                agent_id=agent_id,
                session_id=session_id,
                model=model,
                initial_prompt=initial_prompt,
                queen_resume_from=queen_resume_from,
                queen_name=queen_name,
                initial_phase=initial_phase,
                worker_name=worker_name,
            )
        else:
            # Queen-only session
            session = await manager.create_session(
                session_id=session_id,
                model=model,
                initial_prompt=initial_prompt,
                queen_resume_from=queen_resume_from,
                queen_name=queen_name,
                initial_phase=initial_phase,
            )
    except ValueError as e:
        msg = str(e)
        if "currently loading" in msg:
            resolved_id = agent_id or (Path(agent_path).name if agent_path else "")
            return web.json_response(
                {"error": msg, "colony_id": resolved_id, "loading": True},
                status=409,
            )
        return web.json_response({"error": msg}, status=409)
    except FileNotFoundError:
        return web.json_response(
            {"error": f"Agent not found: {agent_path or 'no path'}"},
            status=404,
        )
    except Exception as e:
        resp = _credential_error_response(e, agent_path)
        if resp is not None:
            return resp
        logger.exception("Error creating session: %s", e)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(_session_to_live_dict(session), status=201)


async def handle_list_live_sessions(request: web.Request) -> web.Response:
    """GET /api/sessions — list all active sessions."""
    manager = _get_manager(request)
    sessions = [_session_to_live_dict(s) for s in manager.list_sessions()]
    return web.json_response({"sessions": sessions})


async def handle_get_live_session(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id} — get session detail.

    Falls back to cold session metadata (HTTP 200 with ``cold: true``) when the
    session is not alive in memory but queen conversation files exist on disk.
    This lets the frontend detect a server restart and restore message history.
    """
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)

    if session is None:
        if manager.is_loading(session_id):
            return web.json_response(
                {"session_id": session_id, "loading": True},
                status=202,
            )
        # Check if conversation files survived on disk (post-restart scenario)
        cold_info = SessionManager.get_cold_session_info(session_id)
        if cold_info is not None:
            return web.json_response(cold_info)
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

    data = _session_to_live_dict(session)

    if session.colony_runtime:
        rt = session.colony_runtime
        data["entry_points"] = [
            {
                "id": ep.id,
                "name": ep.name,
                "entry_node": ep.entry_node,
                "trigger_type": ep.trigger_type,
                "trigger_config": ep.trigger_config,
                **({"next_fire_in": nf} if (nf := rt.get_timer_next_fire_in(ep.id)) is not None else {}),
            }
            for ep in rt.get_entry_points()
        ]
        # Append triggers from triggers.json (stored on session)
        runner = getattr(session, "runner", None)
        colony_entry = runner.graph.entry_node if runner else ""
        for t in getattr(session, "available_triggers", {}).values():
            entry = {
                "id": t.id,
                "name": t.description or t.id,
                "entry_node": colony_entry,
                "trigger_type": t.trigger_type,
                "trigger_config": t.trigger_config,
                "task": t.task,
            }
            mono = getattr(session, "trigger_next_fire", {}).get(t.id)
            if mono is not None:
                remaining = max(0.0, mono - time.monotonic())
                entry["next_fire_in"] = remaining
                entry["next_fire_at"] = int((time.time() + remaining) * 1000)
            stats = getattr(session, "trigger_fire_stats", {}).get(t.id)
            if stats:
                entry["fire_count"] = stats.get("fire_count", 0)
                if stats.get("last_fired_at") is not None:
                    entry["last_fired_at"] = stats["last_fired_at"]
            data["entry_points"].append(entry)
        data["colonies"] = session.colony_runtime.list_graphs()

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
# Colony lifecycle
# ------------------------------------------------------------------


async def handle_load_colony(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/colony — load a colony into a session.

    Body: {"agent_path": "...", "colony_id": "..." (optional), "model": "..." (optional)}
    """
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    body = await request.json()

    agent_path = body.get("agent_path")
    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    try:
        agent_path = str(validate_agent_path(agent_path))
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)

    colony_id = body.get("colony_id")
    model = body.get("model")

    try:
        session = await manager.load_colony(
            session_id,
            agent_path,
            colony_id=colony_id,
            model=model,
        )
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except FileNotFoundError:
        return web.json_response({"error": f"Agent not found: {agent_path}"}, status=404)
    except Exception as e:
        resp = _credential_error_response(e, agent_path)
        if resp is not None:
            return resp
        logger.exception("Error loading colony: %s", e)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(_session_to_live_dict(session))


async def handle_unload_colony(request: web.Request) -> web.Response:
    """DELETE /api/sessions/{session_id}/colony — unload colony, keep queen alive."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]

    removed = await manager.unload_colony(session_id)
    if not removed:
        session = manager.get_session(session_id)
        if session is None:
            return web.json_response(
                {"error": f"Session '{session_id}' not found"},
                status=404,
            )
        return web.json_response(
            {"error": "No colony loaded in this session"},
            status=409,
        )

    return web.json_response({"session_id": session_id, "colony_unloaded": True})


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

    stats = session.colony_runtime.get_stats() if session.colony_runtime else {}
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

    rt = session.colony_runtime
    eps = rt.get_entry_points() if rt else []
    entry_points = [
        {
            "id": ep.id,
            "name": ep.name,
            "entry_node": ep.entry_node,
            "trigger_type": ep.trigger_type,
            "trigger_config": ep.trigger_config,
            **({"next_fire_in": nf} if rt and (nf := rt.get_timer_next_fire_in(ep.id)) is not None else {}),
        }
        for ep in eps
    ]
    # Append triggers from triggers.json (stored on session)
    runner = getattr(session, "runner", None)
    colony_entry = runner.graph.entry_node if runner else ""
    for t in getattr(session, "available_triggers", {}).values():
        entry = {
            "id": t.id,
            "name": t.description or t.id,
            "entry_node": colony_entry,
            "trigger_type": t.trigger_type,
            "trigger_config": t.trigger_config,
            "task": t.task,
        }
        mono = getattr(session, "trigger_next_fire", {}).get(t.id)
        if mono is not None:
            remaining = max(0.0, mono - time.monotonic())
            entry["next_fire_in"] = remaining
            entry["next_fire_at"] = int((time.time() + remaining) * 1000)
        stats = getattr(session, "trigger_fire_stats", {}).get(t.id)
        if stats:
            entry["fire_count"] = stats.get("fire_count", 0)
            if stats.get("last_fired_at") is not None:
                entry["last_fired_at"] = stats["last_fired_at"]
        entry_points.append(entry)
    return web.json_response({"entry_points": entry_points})


async def handle_update_trigger_task(request: web.Request) -> web.Response:
    """PATCH /api/sessions/{session_id}/triggers/{trigger_id} — update trigger fields."""
    session, err = resolve_session(request)
    if err:
        return err

    trigger_id = request.match_info["trigger_id"]
    available = getattr(session, "available_triggers", {})
    tdef = available.get(trigger_id)
    if tdef is None:
        return web.json_response(
            {"error": f"Trigger '{trigger_id}' not found"},
            status=404,
        )

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    updates: dict[str, object] = {}

    if "task" in body:
        task = body.get("task")
        if not isinstance(task, str):
            return web.json_response({"error": "'task' must be a string"}, status=400)
        tdef.task = task
        updates["task"] = tdef.task

    trigger_config_update = body.get("trigger_config")
    if trigger_config_update is not None:
        if not isinstance(trigger_config_update, dict):
            return web.json_response(
                {"error": "'trigger_config' must be an object"},
                status=400,
            )
        merged_trigger_config = dict(tdef.trigger_config)
        merged_trigger_config.update(trigger_config_update)

        if tdef.trigger_type == "timer":
            cron_expr = merged_trigger_config.get("cron")
            interval = merged_trigger_config.get("interval_minutes")
            if cron_expr is not None and not isinstance(cron_expr, str):
                return web.json_response(
                    {"error": "'trigger_config.cron' must be a string"},
                    status=400,
                )
            if cron_expr:
                try:
                    from croniter import croniter

                    if not croniter.is_valid(cron_expr):
                        return web.json_response(
                            {"error": f"Invalid cron expression: {cron_expr}"},
                            status=400,
                        )
                except ImportError:
                    return web.json_response(
                        {"error": ("croniter package not installed — cannot validate cron expression.")},
                        status=500,
                    )
                merged_trigger_config.pop("interval_minutes", None)
            elif interval is None:
                return web.json_response(
                    {"error": ("Timer trigger needs 'cron' or 'interval_minutes' in trigger_config.")},
                    status=400,
                )
            elif not isinstance(interval, (int, float)) or interval <= 0:
                return web.json_response(
                    {"error": "'trigger_config.interval_minutes' must be > 0"},
                    status=400,
                )
        tdef.trigger_config = merged_trigger_config
        updates["trigger_config"] = tdef.trigger_config

    if not updates:
        return web.json_response(
            {"error": "Provide at least one of 'task' or 'trigger_config'"},
            status=400,
        )

    # Persist to session state and agent definition
    from framework.tools.queen_lifecycle_tools import (
        _persist_active_triggers,
        _save_trigger_to_agent,
        _start_trigger_timer,
        _start_trigger_webhook,
    )

    if "trigger_config" in updates and trigger_id in getattr(session, "active_trigger_ids", set()):
        task = session.active_timer_tasks.pop(trigger_id, None)
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        getattr(session, "trigger_next_fire", {}).pop(trigger_id, None)

        webhook_subs = getattr(session, "active_webhook_subs", {})
        if sub_id := webhook_subs.pop(trigger_id, None):
            with contextlib.suppress(Exception):
                session.event_bus.unsubscribe(sub_id)

        if tdef.trigger_type == "timer":
            await _start_trigger_timer(session, trigger_id, tdef)
        elif tdef.trigger_type == "webhook":
            await _start_trigger_webhook(session, trigger_id, tdef)

    if trigger_id in getattr(session, "active_trigger_ids", set()):
        session_id = request.match_info["session_id"]
        await _persist_active_triggers(session, session_id)

    _save_trigger_to_agent(session, trigger_id, tdef)

    # Emit SSE event so the frontend updates the colony and detail panel
    bus = getattr(session, "event_bus", None)
    if bus:
        from framework.host.event_bus import AgentEvent, EventType

        await bus.publish(
            AgentEvent(
                type=EventType.TRIGGER_UPDATED,
                stream_id="queen",
                data={
                    "trigger_id": trigger_id,
                    "task": tdef.task,
                    "trigger_config": tdef.trigger_config,
                    "trigger_type": tdef.trigger_type,
                    "name": tdef.description or trigger_id,
                    "entry_node": getattr(
                        getattr(getattr(session, "runner", None), "graph", None),
                        "entry_node",
                        None,
                    ),
                },
            )
        )

    return web.json_response(
        {
            "trigger_id": trigger_id,
            "task": tdef.task,
            "trigger_config": tdef.trigger_config,
        }
    )


async def handle_run_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/triggers/{trigger_id}/run — fire the trigger once.

    Manual invocation for testing. Works whether the trigger is active or
    inactive; does not change active state and does not reset the scheduled
    next-fire time of an active timer.
    """
    session, err = resolve_session(request)
    if err:
        return err

    trigger_id = request.match_info["trigger_id"]
    tdef = getattr(session, "available_triggers", {}).get(trigger_id)
    if tdef is None:
        return web.json_response(
            {"error": f"Trigger '{trigger_id}' not found"},
            status=404,
        )

    if getattr(session, "colony_runtime", None) is None:
        return web.json_response({"error": "Colony not loaded"}, status=409)

    executor = getattr(session, "queen_executor", None)
    queen_node = getattr(executor, "node_registry", {}).get("queen") if executor else None
    if queen_node is None:
        return web.json_response({"error": "Queen not ready"}, status=409)

    from framework.agent_loop.agent_loop import TriggerEvent

    try:
        await queen_node.inject_trigger(
            TriggerEvent(
                trigger_type=tdef.trigger_type,
                source_id=trigger_id,
                payload={
                    "task": tdef.task or "",
                    "trigger_config": tdef.trigger_config,
                    "forced": True,
                },
            )
        )
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": f"Failed to fire trigger: {exc}"},
            status=500,
        )

    from framework.tools.queen_lifecycle_tools import _emit_trigger_fired

    await _emit_trigger_fired(session, trigger_id, tdef.trigger_type)

    return web.json_response({"status": "fired", "trigger_id": trigger_id})


async def handle_activate_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/triggers/{trigger_id}/activate — start a trigger."""
    session, err = resolve_session(request)
    if err:
        return err

    trigger_id = request.match_info["trigger_id"]
    available = getattr(session, "available_triggers", {})
    tdef = available.get(trigger_id)
    if tdef is None:
        return web.json_response(
            {"error": f"Trigger '{trigger_id}' not found"},
            status=404,
        )

    if trigger_id in getattr(session, "active_trigger_ids", set()):
        return web.json_response({"status": "already_active", "trigger_id": trigger_id})

    from framework.tools.queen_lifecycle_tools import (
        _persist_active_triggers,
        _start_trigger_timer,
        _start_trigger_webhook,
    )

    try:
        if tdef.trigger_type == "timer":
            await _start_trigger_timer(session, trigger_id, tdef)
        elif tdef.trigger_type == "webhook":
            await _start_trigger_webhook(session, trigger_id, tdef)
        else:
            return web.json_response(
                {"error": f"Unsupported trigger type: {tdef.trigger_type}"},
                status=400,
            )
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"error": f"Failed to start trigger: {exc}"},
            status=500,
        )

    tdef.active = True
    session.active_trigger_ids.add(trigger_id)
    session_id = request.match_info["session_id"]
    await _persist_active_triggers(session, session_id)

    bus = getattr(session, "event_bus", None)
    if bus:
        from framework.host.event_bus import AgentEvent, EventType

        runner = getattr(session, "runner", None)
        colony_entry = runner.graph.entry_node if runner else None
        config_out = dict(tdef.trigger_config)
        mono = getattr(session, "trigger_next_fire", {}).get(trigger_id)
        if mono is not None:
            remaining = max(0.0, mono - time.monotonic())
            config_out["next_fire_in"] = remaining
            config_out["next_fire_at"] = int((time.time() + remaining) * 1000)
        stats = getattr(session, "trigger_fire_stats", {}).get(trigger_id)
        if stats:
            config_out["fire_count"] = stats.get("fire_count", 0)
            if stats.get("last_fired_at") is not None:
                config_out["last_fired_at"] = stats["last_fired_at"]
        await bus.publish(
            AgentEvent(
                type=EventType.TRIGGER_ACTIVATED,
                stream_id="queen",
                data={
                    "trigger_id": trigger_id,
                    "trigger_type": tdef.trigger_type,
                    "trigger_config": config_out,
                    "name": tdef.description or trigger_id,
                    **({"entry_node": colony_entry} if colony_entry else {}),
                },
            )
        )

    return web.json_response({"status": "activated", "trigger_id": trigger_id})


async def handle_deactivate_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/triggers/{trigger_id}/deactivate — stop a trigger.

    Cancels the running timer / webhook subscription but KEEPS the trigger
    definition in triggers.json so the user can re-activate later.
    """
    session, err = resolve_session(request)
    if err:
        return err

    trigger_id = request.match_info["trigger_id"]
    if trigger_id not in getattr(session, "active_trigger_ids", set()):
        return web.json_response({"status": "already_inactive", "trigger_id": trigger_id})

    task = session.active_timer_tasks.pop(trigger_id, None)
    if task and not task.done():
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    getattr(session, "trigger_next_fire", {}).pop(trigger_id, None)

    webhook_subs = getattr(session, "active_webhook_subs", {})
    if sub_id := webhook_subs.pop(trigger_id, None):
        with contextlib.suppress(Exception):
            session.event_bus.unsubscribe(sub_id)

    session.active_trigger_ids.discard(trigger_id)

    available = getattr(session, "available_triggers", {})
    tdef = available.get(trigger_id)
    if tdef:
        tdef.active = False

    from framework.tools.queen_lifecycle_tools import _persist_active_triggers

    session_id = request.match_info["session_id"]
    await _persist_active_triggers(session, session_id)

    bus = getattr(session, "event_bus", None)
    if bus:
        from framework.host.event_bus import AgentEvent, EventType

        await bus.publish(
            AgentEvent(
                type=EventType.TRIGGER_DEACTIVATED,
                stream_id="queen",
                data={
                    "trigger_id": trigger_id,
                    "name": (tdef.description or trigger_id) if tdef else trigger_id,
                },
            )
        )

    return web.json_response({"status": "deactivated", "trigger_id": trigger_id})


async def handle_session_colonies(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/colonies — list loaded colonies."""
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)

    if session is None:
        return web.json_response(
            {"error": f"Session '{session_id}' not found"},
            status=404,
        )

    colonies = session.colony_runtime.list_graphs() if session.colony_runtime else []
    return web.json_response({"colonies": colonies})


_EVENTS_HISTORY_DEFAULT_LIMIT = 2000
_EVENTS_HISTORY_MAX_LIMIT = 10000

# Files at or below this size use the simple forward-scan path (cheap enough
# that the seek-backward dance isn't worth it). Above this threshold we read
# the tail directly from end-of-file so a 50 MB log doesn't have to be paged
# through entirely just to surface the last 2000 lines.
_EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES = 1 << 20  # 1 MB
_EVENTS_HISTORY_REVERSE_TAIL_CHUNK_BYTES = 64 * 1024


def _read_events_tail(events_path: Path, limit: int) -> tuple[list[dict], int, bool]:
    """Read the tail of an append-only JSONL events log.

    Returns ``(events, total, truncated)``.  ``events`` is at most ``limit``
    lines, oldest-first.  ``total`` is the total number of non-blank lines in
    the file (exact for the small-file path, exact for the large-file path
    too — we do a separate fast newline-count pass).

    Two paths:
    - Small files (< ~1 MB): forward scan.  Cheap; gives an exact total for
      free.  Defers ``json.loads`` to the bounded deque so we never parse a
      line that's about to be dropped.
    - Large files: seek to EOF and read backward in 64 KB chunks until we have
      at least ``limit`` complete lines.  Parses only the tail.  ``total`` is
      counted by a separate forward byte-scan that just counts newlines —
      no JSON parse — so it stays cheap even for huge files.

    Without these optimizations, mounting the chat for a long-running queen
    with a ~50 k-event log used to spend most of its time inside ``json.loads``
    on the server thread (and block the event loop while doing it).
    """
    from collections import deque

    file_size = events_path.stat().st_size

    if file_size <= _EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES:
        tail_raw: deque[str] = deque(maxlen=limit)
        total = 0
        with open(events_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                total += 1
                tail_raw.append(line)
        events: list[dict] = []
        for raw in tail_raw:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return events, total, total > len(events)

    # Large-file path: read backward until we have enough lines.
    import os as _os

    chunk_size = _EVENTS_HISTORY_REVERSE_TAIL_CHUNK_BYTES
    pieces: list[bytes] = []
    newline_count = 0
    with open(events_path, "rb") as fb:
        fb.seek(0, _os.SEEK_END)
        pos = fb.tell()
        while pos > 0 and newline_count <= limit:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fb.seek(pos)
            chunk = fb.read(read_size)
            newline_count += chunk.count(b"\n")
            pieces.append(chunk)
    pieces.reverse()
    blob = b"".join(pieces)

    # Drop the leading partial line unless we read from offset 0.
    raw_lines = blob.split(b"\n")
    if pos > 0 and raw_lines:
        raw_lines = raw_lines[1:]
    decoded = [ln.decode("utf-8", errors="replace").strip() for ln in raw_lines]
    decoded = [ln for ln in decoded if ln]
    if len(decoded) > limit:
        decoded = decoded[-limit:]

    events = []
    for raw in decoded:
        try:
            events.append(json.loads(raw))
        except json.JSONDecodeError:
            continue

    # Separate fast pass for total: count newlines only, no JSON parse.
    total = 0
    with open(events_path, "rb") as fb:
        while True:
            chunk = fb.read(1 << 20)
            if not chunk:
                break
            total += chunk.count(b"\n")
    # File may end without a trailing newline; if so, the last non-empty line
    # was missed. Count it.
    if file_size > 0:
        with open(events_path, "rb") as fb:
            fb.seek(-1, _os.SEEK_END)
            if fb.read(1) != b"\n":
                total += 1

    return events, total, total > len(events)


async def handle_session_events_history(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/events/history — persisted eventbus log.

    Reads ``events.jsonl`` from the session directory on disk so it works for
    both live sessions and cold (post-server-restart) sessions.  The frontend
    replays these events through ``sseEventToChatMessage`` to fully reconstruct
    the UI state on resume.

    Query params:
        limit: maximum number of events to return (default 2000, max 10000).
            The TAIL of the file is returned — i.e. the most recent N events.
            Older events are dropped and ``truncated`` is set to True.

    Response shape::

        {
            "events": [...],          # up to ``limit`` events, oldest-first
            "session_id": "...",
            "total": 12345,           # total events in the file
            "returned": 2000,         # len(events)
            "truncated": true,        # total > returned
            "limit": 2000,            # the effective limit used
        }

    ``events.jsonl`` is append-only chronological, so "last N lines" == "most
    recent N events". Long-running colonies have produced files with 50k+
    events; before this cap, restoring on page-mount shipped the whole thing
    down the wire and blocked the UI for seconds.

    The actual file read runs in a worker thread via ``asyncio.to_thread`` so
    it doesn't block the event loop while other requests are in flight.
    """
    session_id = request.match_info["session_id"]

    try:
        limit = int(request.query.get("limit", str(_EVENTS_HISTORY_DEFAULT_LIMIT)))
    except ValueError:
        limit = _EVENTS_HISTORY_DEFAULT_LIMIT
    limit = max(1, min(limit, _EVENTS_HISTORY_MAX_LIMIT))

    from framework.server.session_manager import _find_queen_session_dir

    queen_dir = _find_queen_session_dir(session_id)
    events_path = queen_dir / "events.jsonl"
    if not events_path.exists():
        return web.json_response(
            {
                "events": [],
                "session_id": session_id,
                "total": 0,
                "returned": 0,
                "truncated": False,
                "limit": limit,
            }
        )

    try:
        events, total, truncated = await asyncio.to_thread(_read_events_tail, events_path, limit)
    except OSError:
        return web.json_response(
            {
                "events": [],
                "session_id": session_id,
                "total": 0,
                "returned": 0,
                "truncated": False,
                "limit": limit,
            }
        )

    return web.json_response(
        {
            "events": events,
            "session_id": session_id,
            "total": total,
            "returned": len(events),
            "truncated": truncated,
            "limit": limit,
        }
    )


async def handle_session_history(request: web.Request) -> web.Response:
    """GET /api/sessions/history — all queen sessions on disk (live + cold).

    Returns every queen session directory on disk, newest first.
    Live sessions have ``live: true, cold: false``; sessions that survived a
    server restart have ``live: false, cold: true``.
    """
    manager = _get_manager(request)
    live_sessions = {s.id: s for s in manager.list_sessions()}

    disk_sessions = SessionManager.list_cold_sessions()
    for s in disk_sessions:
        if s["session_id"] in live_sessions:
            live = live_sessions[s["session_id"]]
            s["cold"] = False
            s["live"] = True
            # Fill in agent_name from live memory if meta.json wasn't written yet
            if not s.get("agent_name") and live.worker_info:
                s["agent_name"] = live.worker_info.name
            if not s.get("agent_path") and live.worker_path:
                s["agent_path"] = str(live.worker_path)

    return web.json_response({"sessions": disk_sessions})


async def handle_delete_history_session(request: web.Request) -> web.Response:
    """DELETE /api/sessions/history/{session_id} — permanently remove a session.

    Stops the live session (if still running) and deletes the queen session
    directory from disk.
    This is the frontend 'delete from history' action.
    """
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]

    # Stop the live session if it exists (best-effort)
    if manager.get_session(session_id):
        await manager.stop_session(session_id)

    # Delete the queen session directory from disk
    from framework.server.session_manager import _find_queen_session_dir

    queen_session_dir = _find_queen_session_dir(session_id)
    if queen_session_dir.exists() and queen_session_dir.is_dir():
        try:
            shutil.rmtree(queen_session_dir)
        except OSError as e:
            logger.warning("Failed to delete session directory %s: %s", queen_session_dir, e)
            return web.json_response({"error": f"Failed to delete session: {e}"}, status=500)

    return web.json_response({"deleted": session_id})


# ------------------------------------------------------------------
# Agent discovery (not session-specific)
# ------------------------------------------------------------------


async def handle_discover(request: web.Request) -> web.Response:
    """GET /api/discover — discover agents from filesystem."""
    from framework.agents.discovery import discover_agents

    manager = _get_manager(request)
    loaded_paths = {str(s.worker_path) for s in manager.list_sessions() if s.worker_path}

    groups = discover_agents()
    result = {}
    for category, entries in groups.items():
        result[category] = [
            {
                "path": str(entry.path.resolve()),
                "name": entry.name,
                "description": entry.description,
                "category": entry.category,
                "session_count": entry.session_count,
                "run_count": entry.run_count,
                "node_count": entry.node_count,
                "tool_count": entry.tool_count,
                "tags": entry.tags,
                "last_active": entry.last_active,
                "created_at": entry.created_at,
                "icon": entry.icon,
                "is_loaded": str(entry.path.resolve()) in loaded_paths,
                "workers": [w.to_dict() for w in entry.workers],
            }
            for entry in entries
        ]
    return web.json_response(result)


async def handle_delete_agent(request: web.Request) -> web.Response:
    """DELETE /api/agents — permanently remove an agent from disk.

    Body: {"agent_path": "exports/my_agent"}

    Stops any live sessions for this agent, then deletes the agent
    directory so it no longer appears in /discover.
    """
    manager = _get_manager(request)
    body = await request.json()
    agent_path = body.get("agent_path")
    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    try:
        resolved = validate_agent_path(agent_path)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    # Reject deletion of framework agents ($HIVE_HOME/agents/) — those are internal
    from framework.config import HIVE_HOME

    hive_agents_dir = HIVE_HOME / "agents"
    if resolved.is_relative_to(hive_agents_dir):
        return web.json_response({"error": "Cannot delete framework agents"}, status=403)

    # Stop any live sessions that use this agent
    for session in list(manager.list_sessions()):
        if session.worker_path and str(session.worker_path) == str(resolved):
            try:
                await manager.stop_session(session.id)
            except Exception:
                pass

    # Delete the agent directory from disk
    if resolved.exists() and resolved.is_dir():
        try:
            shutil.rmtree(resolved)
        except OSError as e:
            return web.json_response({"error": f"Failed to delete agent directory: {e}"}, status=500)

    return web.json_response({"deleted": str(resolved)})


async def handle_reveal_session_folder(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/reveal — open session data folder in the OS file manager."""
    manager: SessionManager = request.app[MANAGER_KEY]
    session_id = request.match_info["session_id"]

    session = manager.get_session(session_id)
    storage_session_id = (session.queen_resume_from or session.id) if session else session_id
    if session:
        from framework.server.session_manager import _queen_session_dir

        folder = _queen_session_dir(storage_session_id, session.queen_name)
    else:
        from framework.server.session_manager import _find_queen_session_dir

        folder = _find_queen_session_dir(storage_session_id)
    folder.mkdir(parents=True, exist_ok=True)

    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)

    return web.json_response({"path": str(folder)})


async def handle_update_colony_metadata(request: web.Request) -> web.Response:
    """PATCH /api/agents/metadata — update colony metadata (e.g. icon).

    Body: {"agent_path": "...", "icon": "rocket"}
    """
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    agent_path = body.get("agent_path")
    if not agent_path:
        return web.json_response({"error": "agent_path is required"}, status=400)

    try:
        resolved = validate_agent_path(agent_path)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)

    metadata_path = resolved / "metadata.json"
    metadata: dict = {}
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    if "icon" in body:
        metadata["icon"] = body["icon"]

    metadata_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
    return web.json_response({"ok": True})


# ------------------------------------------------------------------
# Route registration
# ------------------------------------------------------------------


def register_routes(app: web.Application) -> None:
    """Register session routes."""
    # Discovery & agent management
    app.router.add_get("/api/discover", handle_discover)
    app.router.add_delete("/api/agents", handle_delete_agent)
    app.router.add_patch("/api/agents/metadata", handle_update_colony_metadata)

    # Session lifecycle
    app.router.add_post("/api/sessions", handle_create_session)
    app.router.add_get("/api/sessions", handle_list_live_sessions)
    # history must be registered before {session_id} so it takes priority
    app.router.add_get("/api/sessions/history", handle_session_history)
    app.router.add_delete("/api/sessions/history/{session_id}", handle_delete_history_session)
    app.router.add_get("/api/sessions/{session_id}", handle_get_live_session)
    app.router.add_delete("/api/sessions/{session_id}", handle_stop_session)

    # Colony lifecycle
    app.router.add_post("/api/sessions/{session_id}/colony", handle_load_colony)
    app.router.add_delete("/api/sessions/{session_id}/colony", handle_unload_colony)

    # Session info
    app.router.add_post("/api/sessions/{session_id}/reveal", handle_reveal_session_folder)
    app.router.add_get("/api/sessions/{session_id}/stats", handle_session_stats)
    app.router.add_get("/api/sessions/{session_id}/entry-points", handle_session_entry_points)
    app.router.add_patch("/api/sessions/{session_id}/triggers/{trigger_id}", handle_update_trigger_task)
    app.router.add_post(
        "/api/sessions/{session_id}/triggers/{trigger_id}/activate",
        handle_activate_trigger,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/triggers/{trigger_id}/deactivate",
        handle_deactivate_trigger,
    )
    app.router.add_post(
        "/api/sessions/{session_id}/triggers/{trigger_id}/run",
        handle_run_trigger,
    )
    app.router.add_get("/api/sessions/{session_id}/colonies", handle_session_colonies)

    app.router.add_get("/api/sessions/{session_id}/events/history", handle_session_events_history)
