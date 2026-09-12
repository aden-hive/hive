"""Session lifecycle and session info routes.

Session-primary routes:
- POST   /api/sessions                                — create session (with or without worker)
- GET    /api/sessions                                — list all active sessions
- GET    /api/sessions/{session_id}                   — session detail
- DELETE /api/sessions/{session_id}                   — stop session entirely
- POST   /api/sessions/{session_id}/colony            — load a colony into session
- DELETE /api/sessions/{session_id}/colony            — unload colony from session
- GET    /api/sessions/{session_id}/stats             — runtime statistics
- PATCH  /api/sessions/{session_id}/triggers/{id}    — update trigger task
- POST   /api/sessions/{session_id}/triggers/{id}/run — fire trigger once (manual)
- GET    /api/sessions/{session_id}/events/history   — persisted eventbus log (for replay)

"""

import asyncio
import concurrent.futures
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from aiohttp.client_exceptions import ClientConnectionResetError as _AiohttpConnReset

from framework.config import COLONIES_DIR
from framework.server.app import (
    resolve_session,
    validate_agent_path,
)
from framework.server.session_manager import SessionManager
from framework.utils.text import humanize_slug

logger = logging.getLogger(__name__)


def _get_manager(request: web.Request) -> SessionManager:
    return request.app["manager"]


def _session_to_live_dict(session) -> dict:
    """Serialize a live Session to the session-primary JSON shape."""
    from framework.llm.capabilities import supports_image_tool_results

    phase_state = getattr(session, "phase_state", None)
    queen_model: str = getattr(getattr(session, "llm", None), "model", "") or ""
    # A colony is "loaded" when the session is bound to one (colony_id set).
    has_worker = session.colony_id is not None
    return {
        "session_id": session.id,
        "colony_id": session.colony_id,
        "has_worker": has_worker,
        "agent_path": str(session.worker_path) if session.worker_path else "",
        "description": "",
        "goal": "",
        "node_count": 0,
        "loaded_at": session.loaded_at,
        "uptime_seconds": round(time.time() - session.loaded_at, 1),
        "queen_phase": phase_state.phase if phase_state else ("staging" if has_worker else "planning"),
        "queen_supports_images": supports_image_tool_results(queen_model) if queen_model else True,
        "queen_id": getattr(phase_state, "queen_id", None) if phase_state else None,
        "queen_name": (phase_state.queen_profile or {}).get("name") if phase_state else None,
        "colony_spawned": getattr(session, "colony_spawned", False),
        "spawned_colony_id": getattr(session, "spawned_colony_id", None),
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
        "colony_id": "..." (optional — bind the session to this colony;
            resolves to <COLONIES_DIR>/<colony_id>/),
        "session_id": "..." (optional — custom session ID),
        "model": "..." (optional),
        "initial_prompt": "..." (optional — first user message for the queen),
        "initial_phase": "..." (optional — "independent" for standalone queen),
        "queen_resume_from": "..." (optional — resume from this session's queen),
        "queen_name": "..." (optional — pre-bind to this queen profile),
        "source_session_id": "..." (optional — when paired with colony_id and
            the colony doesn't exist yet, forks this independent queen session
            into the new colony, compacting the source conversation into the
            queen seed and locking the source session. Used by the frontend's
            "Create Colony" popup driven by suggest_colony.),
    }

    Colony dispatch (all routed through ``create_session``):

    - **colony_id + dir exists** → open existing colony (full AgentLoader)
    - **colony_id + dir missing + source_session_id** → fork-into-new-colony
      (the "Create Colony popup" path; source session compacted + locked,
      response carries the new live colony queen-session)
    - **colony_id + dir missing** → bootstrap minimal colony, queen in colony phase
    - **no colony_id** → queen-only DM session
    """
    from framework.agents.queen.queen_profiles import ensure_default_queens, load_queen_profile
    from framework.tools.queen_lifecycle_tools import QUEEN_PHASES, normalize_legacy_phase

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
    colony_id = body.get("colony_id")
    session_id = body.get("session_id")
    model = body.get("model")
    initial_prompt = body.get("initial_prompt")
    queen_resume_from = body.get("queen_resume_from")
    queen_name = body.get("queen_name")
    initial_phase = normalize_legacy_phase(body.get("initial_phase"))
    source_session_id = body.get("source_session_id")

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

    # ── Frontend "Create Colony" popup path ────────────────────────────
    # When both colony_id and source_session_id are set AND the colony
    # doesn't exist yet on disk, fork the source independent queen
    # session into a new colony. (If the colony directory already
    # exists, fall through to the standard open-existing path.)
    # If a soft-deleted (invisible, unrecoverable) colony is squatting on this
    # name, park it aside first so the routing below sees a free name and the
    # fork-from-source path runs — instead of resurrecting the dead colony.
    if colony_id and source_session_id:
        from framework.host.colony_metadata import vacate_soft_deleted_colony

        try:
            vacate_soft_deleted_colony(colony_id)
        except OSError as exc:
            return web.json_response(
                {"error": f"failed to clear soft-deleted colony '{colony_id}': {exc}"},
                status=500,
            )
    if colony_id and source_session_id:
        # Deduplicate the slug when a live colony already occupies the name
        # so the fork always lands in a fresh colony.
        if (COLONIES_DIR / colony_id / "metadata.json").exists():
            from framework.server.session_manager import _deduplicate_colony_id

            colony_id = _deduplicate_colony_id(colony_id)
        try:
            session = await _create_colony_from_source(
                request,
                manager=manager,
                source_session_id=source_session_id,
                colony_id=colony_id,
                queen_name=queen_name,
                model=model,
                initial_phase=initial_phase,
            )
        except _ColonyForkError as exc:
            return web.json_response({"error": exc.message}, status=exc.status)
        except Exception as exc:
            logger.exception("Error forking source session into colony: %s", exc)
            return web.json_response({"error": "Internal server error"}, status=500)
        return web.json_response(_session_to_live_dict(session), status=201)

    try:
        session = await manager.create_session(
            colony_id=colony_id,
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
            return web.json_response(
                {"error": msg, "colony_id": colony_id or "", "loading": True},
                status=409,
            )
        return web.json_response({"error": msg}, status=409)
    except FileNotFoundError:
        return web.json_response(
            {"error": f"Colony not found: {colony_id or 'no colony_id'}"},
            status=404,
        )
    except Exception as e:
        resp = _credential_error_response(e, colony_id)
        if resp is not None:
            return resp
        logger.exception("Error creating session: %s", e)
        return web.json_response({"error": "Internal server error"}, status=500)

    return web.json_response(_session_to_live_dict(session), status=201)


class _ColonyForkError(Exception):
    """Raised by ``_create_colony_from_source`` to carry an HTTP status."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


async def _create_colony_from_source(
    request: web.Request,
    *,
    manager: SessionManager,
    source_session_id: str,
    colony_id: str,
    queen_name: str | None,
    model: str | None,
    initial_phase: str | None,
):
    """Fork an independent queen session into a new colony.

    Backs the "Create Colony" popup that the frontend opens in response
    to a ``COLONY_SUGGESTION_REQUESTED`` event from ``suggest_colony``.

    Steps:
      1. Resolve the source session (must be live + in independent phase).
      2. Validate ``colony_id`` slug.
      3. Call ``fork_session_into_colony`` — writes worker.json, copies
         the queen's session dir into the colony, schedules background
         compaction, returns the new colony queen-session id.
      4. ``persist_colony_spawn_lock`` on the source session so the next
         /chat is rejected.
      5. Inject a system-flavoured user message into the source so the
         blocked ``suggest_colony`` tool call unblocks.
      6. Publish ``COLONY_CREATED`` on the source session's bus.
      7. Resume the colony session live via ``create_session(colony_id=...)``
         and return it.

    Raises ``_ColonyForkError`` on validation or resolution failures.
    """
    import re as _re

    from framework.host.event_bus import AgentEvent, EventType
    from framework.server.routes_execution import (
        fork_session_into_colony,
        persist_colony_spawn_lock,
    )

    _COLONY_NAME_RE = _re.compile(r"^[a-z0-9_]+$")

    cn = (colony_id or "").strip()
    if not _COLONY_NAME_RE.match(cn):
        raise _ColonyForkError(
            "colony_id must be lowercase alphanumeric with underscores",
            status=400,
        )

    source_session = manager.get_session(source_session_id)
    if source_session is None:
        raise _ColonyForkError(
            f"source_session_id '{source_session_id}' is not a live session",
            status=404,
        )

    phase_state = getattr(source_session, "phase_state", None)
    source_phase = getattr(phase_state, "phase", None)
    pending_pivot = getattr(source_session, "pending_colony_pivot", None)

    # Colony-source branch: a colony-phase queen called
    # task_create(new_colony=true), the popup opened with the slug
    # blank, the user just confirmed it. Take the lean-handoff path —
    # NO transcript copy, NO compaction, NO spawn-lock on the source.
    # The source colony stays alive and the user navigates to the new
    # one. Driven entirely by the pending_colony_pivot payload the
    # source queen's handler stashed on the session.
    if source_phase == "colony":
        if pending_pivot is None:
            raise _ColonyForkError(
                ("source colony has no pending new_colony pivot — the popup must be opened via task_create(new_colony=true) first."),
                status=409,
            )
        return await _create_sibling_colony_from_colony(
            manager=manager,
            source_session=source_session,
            colony_id=cn,
            model=model,
            initial_phase=initial_phase,
            pivot=pending_pivot,
        )

    if source_phase != "independent":
        raise _ColonyForkError(
            (f"source session must be in 'independent' or 'colony' phase to fork into a colony (currently '{source_phase}')."),
            status=409,
        )

    if getattr(source_session, "colony_spawned", False):
        raise _ColonyForkError(
            "source session already spawned a colony — cannot fork again.",
            status=409,
        )

    # Fork: writes ~/.hive/colonies/<cn>/worker.json + copies queen
    # session into the colony dir + schedules background compaction.
    try:
        fork_result = await fork_session_into_colony(
            session=source_session,
            colony_id=cn,
            task="",
        )
    except RuntimeError as exc:
        raise _ColonyForkError(str(exc), status=503) from exc

    # Lock the source session so the next /chat is rejected with the
    # "compact and start a new session" UX. Mirrors the persist call
    # the in-agent create_colony tool used to make.
    try:
        persist_colony_spawn_lock(source_session, fork_result.get("colony_id", cn))
    except OSError:
        logger.warning(
            "_create_colony_from_source: persist_colony_spawn_lock failed",
            exc_info=True,
        )

    # Unblock the source queen's suggest_colony tool call by injecting
    # a synthetic user message. The injection sets _input_ready so the
    # blocked _await_user_input wakes up; the queen sees the message in
    # her next turn and ends the chat cleanly (the session is locked, so
    # there is no subsequent user turn).
    try:
        await _inject_colony_confirmation(source_session, colony_id=cn)
    except Exception:
        logger.warning(
            "_create_colony_from_source: failed to inject confirmation",
            exc_info=True,
        )

    # Publish COLONY_CREATED on the source bus so the source session's
    # UI renders the system-message link to the new colony.
    bus = getattr(source_session, "event_bus", None)
    if bus is not None:
        try:
            await bus.publish(
                AgentEvent(
                    type=EventType.COLONY_CREATED,
                    stream_id="queen",
                    data={
                        "colony_id": fork_result.get("colony_id", cn),
                        "colony_path": fork_result.get("colony_path"),
                        "queen_session_id": fork_result.get("queen_session_id"),
                        "is_new": fork_result.get("is_new", True),
                        "compaction_status": fork_result.get("compaction_status", "in_progress"),
                    },
                )
            )
        except Exception:
            logger.warning(
                "_create_colony_from_source: COLONY_CREATED publish failed",
                exc_info=True,
            )

    # Resume the colony session live so the frontend has something to
    # navigate to. ``queen_resume_from`` picks up the forked queen-session
    # dir written by fork_session_into_colony.
    colony_queen_session_id = fork_result.get("queen_session_id")
    if not colony_queen_session_id:
        raise _ColonyForkError(
            "fork_session_into_colony did not return a queen_session_id",
            status=500,
        )

    session = await manager.create_session(
        colony_id=cn,
        session_id=colony_queen_session_id,
        model=model,
        queen_resume_from=colony_queen_session_id,
        queen_name=queen_name or getattr(source_session, "queen_name", None),
        initial_phase=initial_phase or "colony",
    )
    return session


async def _create_sibling_colony_from_colony(
    *,
    manager: SessionManager,
    source_session: Any,
    colony_id: str,
    model: str | None,
    initial_phase: str | None,
    pivot: dict,
) -> Any:
    """Fork a colony-phase queen session into a new sibling colony.

    Lean-handoff path: the new colony's queen seed is built from scratch
    using ONLY the queen-authored ``handoff`` brief and the seeded task
    plan (``goal`` + ``tasks``) the source queen stashed on
    ``session.pending_colony_pivot``. Nothing from the source colony's
    conversation is copied or compacted. The source colony stays alive
    (no spawn lock); the user is navigated to the new colony.

    Resolves the source queen's blocked ``pivot_result_future`` with
    success so the source queen's ``task_create(new_colony=true)`` tool
    call unblocks and returns. The source queen end-turns afterward per
    its prompt and stays idle on its existing task list.
    """
    import json as _json
    from datetime import UTC as _UTC, datetime as _dt

    from framework.agent_loop.agent_loop import AgentLoop
    from framework.agent_loop.types import AgentContext
    from framework.agents.queen.worker_definition import (
        build_input_data,
        build_meta,
    )
    from framework.config import COLONIES_DIR
    from framework.host.colony_binding import ColonyBinding
    from framework.host.event_bus import AgentEvent, EventType
    from framework.host.tracker_db import ensure_tracker_db
    from framework.server.routes_execution import (
        _resolve_queen_only_tools,
        _write_seed_message,
    )
    from framework.server.session_manager import (
        _generate_session_id,
        _queen_session_dir,
    )
    from framework.tasks import get_task_store
    from framework.tasks.events import emit_task_created

    queen_executor = getattr(source_session, "queen_executor", None)
    if queen_executor is None:
        raise _ColonyForkError(
            "source colony queen isn't running — cannot spawn a sibling colony right now.",
            status=503,
        )
    node_registry = getattr(queen_executor, "node_registry", None)
    if not isinstance(node_registry, dict) or "queen" not in node_registry:
        raise _ColonyForkError(
            "source colony queen executor is initializing or tearing down — retry in a moment.",
            status=503,
        )
    queen_loop: AgentLoop = node_registry["queen"]
    queen_ctx: AgentContext | None = getattr(queen_loop, "_last_ctx", None)

    goal = (pivot.get("goal") or "").strip()
    handoff = (pivot.get("handoff") or "").strip()
    task_specs = list(pivot.get("tasks") or [])
    queen_name = pivot.get("queen_name") or getattr(source_session, "queen_name", None) or "default"

    if not goal:
        raise _ColonyForkError("pending pivot is missing `goal`", status=409)
    if not handoff:
        raise _ColonyForkError("pending pivot is missing `handoff`", status=409)
    if not task_specs:
        raise _ColonyForkError("pending pivot is missing `tasks`", status=409)

    colony_dir = COLONIES_DIR / colony_id
    worker_name = "worker"
    worker_config_path = colony_dir / f"{worker_name}.json"
    # Park aside any soft-deleted colony squatting on this name (invisible and
    # unrecoverable to the user) so the slug is free again. No-op for a live
    # colony, which still trips the 409 below.
    from framework.host.colony_metadata import vacate_soft_deleted_colony

    try:
        vacate_soft_deleted_colony(colony_id)
    except OSError as exc:
        raise _ColonyForkError(
            f"failed to clear soft-deleted colony '{colony_id}': {exc}",
            status=500,
        ) from exc
    if worker_config_path.exists() or (colony_dir / "metadata.json").exists():
        raise _ColonyForkError(
            f"colony '{colony_id}' already exists — pick a different slug",
            status=409,
        )
    colony_dir.mkdir(parents=True, exist_ok=True)

    # Provision tracker.db before worker.json so the path can be threaded
    # into input_data.
    tracker_db_path = await asyncio.to_thread(ensure_tracker_db, colony_dir)
    binding = ColonyBinding(name=colony_id, dir=colony_dir, tracker_db=tracker_db_path)

    # Inherit the source queen's tool surface, skills, protocols, and
    # loop config so the new colony's queen has the same operating
    # capabilities. queen-only lifecycle tools are stripped — they need
    # a live queen runtime to register against.
    queen_only_tools = _resolve_queen_only_tools()
    queen_tools = queen_ctx.available_tools if queen_ctx else []
    tool_names = [t.name for t in queen_tools if t.name not in queen_only_tools]
    queen_skills_catalog = queen_ctx.skills_catalog_prompt if queen_ctx else ""
    queen_protocols = queen_ctx.protocols_prompt if queen_ctx else ""
    queen_skill_dirs = queen_ctx.skill_dirs if queen_ctx else []
    queen_config = getattr(queen_loop, "_config", None)
    source_phase_state = getattr(source_session, "phase_state", None)

    worker_meta = build_meta(
        worker_name=worker_name,
        source_session_id=source_session.id,
        task="",
        tool_names=tool_names,
        skills_catalog_prompt=queen_skills_catalog,
        protocols_prompt=queen_protocols,
        skill_dirs=list(queen_skill_dirs),
        queen_loop_config=queen_config,
        queen_phase=source_phase_state.phase if source_phase_state else "colony",
        queen_id=getattr(source_phase_state, "queen_id", "") if source_phase_state else "",
        input_data=build_input_data(binding=binding),
    )
    worker_config_path.write_text(
        _json.dumps(worker_meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Build a fresh queen-session dir in the colony tree — no copytree.
    colony_session_id = _generate_session_id()
    dest_queen_dir = _queen_session_dir(colony_session_id, queen_name, colony_id=colony_id)
    await asyncio.to_thread(lambda: dest_queen_dir.mkdir(parents=True, exist_ok=False))

    # Seed the new queen's conversation with the handoff brief alone —
    # the new queen opens to "User: [Session handoff] ..." as seq 0 and
    # works from there. Goal + plan land in tasks.json (below).
    await _write_seed_message(dest_queen_dir, f"[Session handoff]\n{handoff}")

    dest_meta: dict[str, Any] = {
        "agent_path": str(colony_dir),
        "agent_name": humanize_slug(colony_id),
        "queen_id": queen_name,
        "forked_from": source_session.id,
        "colony_fork": True,
        "phase": "colony",
        "created_at": time.time(),
    }
    (dest_queen_dir / "meta.json").write_text(
        _json.dumps(dest_meta, ensure_ascii=False),
        encoding="utf-8",
    )

    # Seed the new colony queen's task list with goal + plan before the
    # session goes live — the queen resumes onto an existing plan rather
    # than calling task_create on its kickoff turn.
    forked_task_records: list[Any] = []
    try:
        forked_task_records = await get_task_store().create_tasks_batch(
            colony_session_id,
            task_specs,
            goal=goal,
        )
    except Exception as exc:
        logger.exception("_create_sibling_colony_from_colony: failed to seed task plan")
        raise _ColonyForkError(
            f"failed to seed task plan in new colony: {exc}",
            status=500,
        ) from exc

    # Colony metadata.json — provenance only. No source-colony parent
    # link is recorded (per the design choice: new colony is treated as
    # a fresh root, not lineage-linked to the source).
    metadata_path = colony_dir / "metadata.json"
    metadata: dict[str, Any] = {
        "colony_id": colony_id,
        "queen_name": queen_name,
        "queen_session_id": colony_session_id,
        "source_session_id": source_session.id,
        "created_at": _dt.now(_UTC).isoformat(),
        "updated_at": _dt.now(_UTC).isoformat(),
        "workers": {
            worker_name: {
                "task": "",
                "spawned_at": _dt.now(_UTC).isoformat(),
            },
        },
    }
    metadata_path.write_text(
        _json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Inherit the source queen's MCP allowlist into the new colony
    # (mirrors fork_session_into_colony — keeps tool curation consistent
    # across sibling colonies). Best-effort; allow-all on the source
    # leaves the new colony on the default.
    try:
        queen_enabled = getattr(source_phase_state, "enabled_mcp_tools", None)
        if isinstance(queen_enabled, list):
            from framework.host.colony_tools_config import update_colony_tools_config

            update_colony_tools_config(colony_id, list(queen_enabled))
    except Exception:
        logger.warning(
            "_create_sibling_colony_from_colony: failed to inherit allowlist into '%s'",
            colony_id,
            exc_info=True,
        )

    # Bring up the new colony queen session. fork_kickoff_pending=True
    # on the new session guards against immediate re-pivot on its
    # synthetic kickoff turn — clears on the first genuine user message.
    new_session = await manager.create_session(
        colony_id=colony_id,
        session_id=colony_session_id,
        model=model,
        queen_resume_from=colony_session_id,
        queen_name=queen_name,
        initial_phase=initial_phase or "colony",
    )
    new_session.fork_kickoff_pending = True

    # Emit task_created on the NEW session's bus so the Action Plan
    # panel populates from the seeded plan the moment the user lands
    # there. (The records were written straight to tasks.json before
    # the session went live, so no events fired during creation.)
    new_bus = getattr(new_session, "event_bus", None)
    for rec in forked_task_records:
        try:
            await emit_task_created(
                session_id=colony_session_id,
                record=rec,
                bus=new_bus,
            )
        except Exception:
            logger.warning(
                "_create_sibling_colony_from_colony: failed to emit seeded task_created",
                exc_info=True,
            )

    # Publish COLONY_CREATED on the SOURCE colony's bus so the source's
    # UI renders a system-message link to the spawned colony. The user
    # is navigated to the new colony by the HTTP response, but if they
    # ever return to the source they see the link.
    src_bus = getattr(source_session, "event_bus", None)
    if src_bus is not None:
        try:
            await src_bus.publish(
                AgentEvent(
                    type=EventType.COLONY_CREATED,
                    stream_id="queen",
                    data={
                        "colony_id": colony_id,
                        "colony_path": str(colony_dir),
                        "queen_session_id": colony_session_id,
                        "is_new": True,
                        "compaction_status": "skipped",
                        "source_phase": "colony",
                    },
                )
            )
        except Exception:
            logger.warning(
                "_create_sibling_colony_from_colony: COLONY_CREATED publish failed",
                exc_info=True,
            )

    # Wake the source queen. She is parked awaiting user input after
    # the task_create(new_colony=true) synthetic intercept set
    # user_input_requested=True; injecting a synthetic user message
    # sets ``_input_ready`` so the blocked ``_await_user_input`` wakes
    # up. The queen reads the confirmation on her next turn and per
    # her prompt end-turns immediately, staying idle on this colony's
    # existing plan.
    try:
        await _inject_new_colony_confirmation(
            source_session,
            new_colony_id=colony_id,
            new_queen_session_id=colony_session_id,
            task_count=len(forked_task_records),
        )
    except Exception:
        logger.warning(
            "_create_sibling_colony_from_colony: failed to inject confirmation",
            exc_info=True,
        )

    # Clear the pivot stash so a follow-up new_colony request from this
    # queen later in the session opens a fresh popup instead of trying
    # to read the now-stale payload.
    source_session.pending_colony_pivot = None

    return new_session


async def _inject_new_colony_confirmation(
    source_session,
    *,
    new_colony_id: str,
    new_queen_session_id: str,
    task_count: int,
) -> None:
    """Inject a system-flavoured user message that wakes the source queen.

    Mirrors :func:`_inject_colony_confirmation` but for the colony→colony
    pivot. The message is informational (the queen sees it on her next
    turn); its load-bearing role is calling ``inject_event(is_client_input=True)``
    which sets ``_input_ready`` on the queen's AgentLoop. Unlike the
    DM→colony case, the source colony is NOT locked — the queen end-turns
    and stays idle on her existing plan, ready to resume on the user's
    next genuine message.
    """
    msg = (
        f"[New colony '{new_colony_id}' created with {task_count} task(s) "
        f"(queen session {new_queen_session_id}). The user has been "
        "navigated there; the off-goal plan now lives in the new "
        "colony, not here. This colony's existing plan is untouched. "
        "End your turn now — the new colony's queen takes over the "
        "pivoted work; you stay idle here for the user's next message.]"
    )
    queen_executor = getattr(source_session, "queen_executor", None)
    if queen_executor is None:
        return
    node_registry = getattr(queen_executor, "node_registry", None)
    if not isinstance(node_registry, dict):
        return
    queen_loop = node_registry.get("queen")
    if queen_loop is None or not hasattr(queen_loop, "inject_event"):
        return
    try:
        await queen_loop.inject_event(msg, is_client_input=True)
    except Exception:
        logger.warning(
            "_inject_new_colony_confirmation: inject_event failed",
            exc_info=True,
        )


async def handle_dismiss_colony_pivot(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/dismiss-colony-pivot — close popup.

    Called by the frontend when the user dismisses the "Create Colony"
    popup that was opened by a colony-phase queen's
    ``task_create(new_colony=true)``. The source queen is parked in
    ``_await_user_input`` after the synthetic intercept set
    ``user_input_requested=True``; injecting a synthetic user message
    wakes the queen via ``inject_event(is_client_input=True)``. The
    queen reads the dismissal on her next turn and per the design
    contract MUST call ``ask_user`` for explicit direction — silently
    absorbing the off-goal work into this colony defeats the whole
    point of the pivot prompt.
    """
    session, err = resolve_session(request)
    if err:
        return err

    if getattr(session, "pending_colony_pivot", None) is None:
        # No-op: the popup was already resolved (accept landed first,
        # or this is a stale fire from a closed popup). Frontend may
        # double-fire on rapid clicks; treat gracefully so the user
        # doesn't see an error toast for a benign race.
        return web.json_response({"dismissed": False, "reason": "no_pending_pivot"})

    queen_executor = getattr(session, "queen_executor", None)
    queen_loop = None
    if queen_executor is not None:
        node_registry = getattr(queen_executor, "node_registry", None)
        if isinstance(node_registry, dict):
            queen_loop = node_registry.get("queen")

    if queen_loop is not None and hasattr(queen_loop, "inject_event"):
        msg = (
            "[User dismissed the 'Create Colony' popup. The off-goal "
            "work was NOT added to this colony's task list — adding it "
            "silently would defeat the pivot prompt. Call ask_user "
            "right now with a question like 'You dismissed the new "
            "colony — should I do this work here in the current "
            "colony, or drop it?' so the user decides explicitly. Do "
            "NOT just resume work or add tasks without their explicit "
            "answer.]"
        )
        try:
            await queen_loop.inject_event(msg, is_client_input=True)
        except Exception:
            logger.warning(
                "handle_dismiss_colony_pivot: inject_event failed",
                exc_info=True,
            )

    session.pending_colony_pivot = None
    return web.json_response({"dismissed": True})


async def _inject_colony_confirmation(source_session, *, colony_id: str) -> None:
    """Inject a synthetic user message that unblocks a waiting suggest_colony call.

    The message itself is informational (the queen sees it on her next
    turn); its load-bearing role is calling ``inject_event(is_client_input=True)``
    which sets the ``_input_ready`` event on the queen's AgentLoop.
    """
    msg = f"[Colony '{colony_id}' created — this session is now locked. The new colony queen takes over from here.]"
    queen_executor = getattr(source_session, "queen_executor", None)
    if queen_executor is None:
        return
    node_registry = getattr(queen_executor, "node_registry", None)
    if not isinstance(node_registry, dict):
        return
    queen_loop = node_registry.get("queen")
    if queen_loop is None or not hasattr(queen_loop, "inject_event"):
        return
    await queen_loop.inject_event(msg, is_client_input=True)


async def handle_list_live_sessions(request: web.Request) -> web.Response:
    """GET /api/sessions — list all active sessions."""
    manager = _get_manager(request)
    sessions = [_session_to_live_dict(s) for s in manager.list_sessions()]
    return web.json_response({"sessions": sessions})


def _active_worker_count(session) -> int:
    """How many of this session's colony workers are still in flight.

    The overseer parks its own loop while it waits for dispatched workers to
    report, so ``is_executing`` alone goes False during a fan-out and the UI
    reads the colony as "parked" while its workers are in fact hard at work.
    Counting the workers that are still QUEUED/PENDING/RUNNING lets the UI say
    "active" whenever the colony is actually doing something.

    ``ColonyRuntime._workers`` is NOT pruned on termination (finished workers
    stay in the map), so filter on status rather than counting entries.
    """
    colony = getattr(session, "colony", None)
    if colony is None:
        return 0
    from framework.host.worker import WorkerStatus

    in_flight = {WorkerStatus.QUEUED, WorkerStatus.PENDING, WorkerStatus.RUNNING}
    try:
        return sum(1 for w in colony.list_workers() if w.status in in_flight)
    except Exception:  # noqa: BLE001 — a status probe must never break the feed
        return 0


def _live_session_summary(session) -> dict:
    """Per-session row for the multi-queen sidebar feed.

    Combines stable session metadata with the live snapshot derived
    from the per-session ring buffer.  Mirror of the canonical
    helper; keep the two in sync.
    """
    from framework.host.event_bus import compute_session_snapshot

    phase_state = getattr(session, "phase_state", None)
    snap = compute_session_snapshot(session.event_bus) if getattr(session, "event_bus", None) else {}
    tools = snap.get("current_tool_calls") or []
    primary_tool = tools[0]["name"] if tools else None
    return {
        "session_id": session.id,
        "colony_id": session.colony_id,
        "queen_id": getattr(phase_state, "queen_id", None) if phase_state else None,
        "queen_name": (phase_state.queen_profile or {}).get("name") if phase_state else None,
        "phase": phase_state.phase if phase_state else None,
        "is_executing": bool(snap.get("is_executing")),
        "awaiting_input": bool(snap.get("awaiting_input")),
        "interrupted": bool(snap.get("interrupted")),
        "interrupt_cause": snap.get("interrupt_cause"),
        "queen_busy_reason": snap.get("queen_busy_reason"),
        "park_reason": snap.get("park_reason"),
        "current_tool_name": primary_tool,
        "current_tool_count": len(tools),
        # Workers still in flight for this session's colony. The sidebar /
        # org-chart use this to keep a colony "active" while its overseer is
        # parked waiting on dispatched workers.
        "active_worker_count": _active_worker_count(session),
        "last_event_at": snap.get("last_event_at"),
        "snapshot_seq": snap.get("snapshot_seq", 0),
    }


async def handle_live_sessions_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/sessions/live — SSE feed of every live session's snapshot.

    Drives the multi-queen sidebar dot indicators and the away-queen
    attention badge. Emits a coalesced ``snapshot`` event whenever any
    session's state field changes; heartbeats every 30 s.
    """
    import asyncio
    import json as _json

    manager = _get_manager(request)
    from framework.server.sse import SSEResponse

    sse = SSEResponse()
    await sse.prepare(request)

    from framework.host.runtime_health import get_runtime_network

    last_signature: str | None = None
    last_emit_ts = 0.0
    POLL_SEC = 2.5
    HEARTBEAT_SEC = 30.0

    try:
        while True:
            rows = [_live_session_summary(s) for s in manager.list_sessions()]
            rows.sort(key=lambda r: r["session_id"])
            network = get_runtime_network()
            sig = _json.dumps(
                [
                    (
                        r["session_id"],
                        r["is_executing"],
                        r["awaiting_input"],
                        r["interrupted"],
                        r["current_tool_name"],
                        r["queen_busy_reason"],
                        r["park_reason"],
                        # Must be in the signature: while the overseer sits
                        # parked, this is the ONLY field that moves as workers
                        # start/finish. Leave it out and the feed wouldn't
                        # re-emit until the 30s heartbeat, so the sidebar would
                        # stay stale through a whole fan-out.
                        r["active_worker_count"],
                    )
                    for r in rows
                ]
                + [("__network__", network["degraded"], network["reason"])]
            )
            now = time.monotonic()
            if sig != last_signature or (now - last_emit_ts) > HEARTBEAT_SEC:
                await sse.send_event(
                    {"sessions": rows, "network": network},
                    event="snapshot",
                )
                last_signature = sig
                last_emit_ts = now
            await asyncio.sleep(POLL_SEC)
    except (asyncio.CancelledError, ConnectionResetError, _AiohttpConnReset):
        pass
    except Exception as exc:
        logger.warning("live sessions stream error: %s", exc)

    return sse.response  # type: ignore[return-value]


async def handle_get_session_snapshot(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/snapshot — the same state projection a
    fresh SSE subscribe injects as ``session_snapshot``.

    Poll target for the frontend's stall watchdog: when the gate-clearing
    SSE events are lost (backpressure disconnect, silently dead TCP path),
    the UI reconciles its isStreaming / pending-queue state against this
    instead of staying stuck until a manual page refresh.
    """
    from framework.host.event_bus import compute_session_snapshot

    manager = _get_manager(request)
    session = manager.get_session(request.match_info["session_id"])
    if session is None or getattr(session, "event_bus", None) is None:
        return web.json_response({"error": "session not found"}, status=404)
    return web.json_response(compute_session_snapshot(session.event_bus))


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

    # Entry points are now purely the session's activated triggers — the
    # legacy graph-runtime entry points were removed with colony_runtime.
    data["entry_points"] = []
    for t in getattr(session, "available_triggers", {}).values():
        entry = {
            "id": t.id,
            "name": t.description or t.id,
            "entry_node": "",
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

    Body: {"colony_id": "...", "model": "..." (optional)}
    """
    manager = _get_manager(request)
    session_id = request.match_info["session_id"]
    body = await request.json()

    colony_id = body.get("colony_id")
    if not colony_id:
        return web.json_response({"error": "colony_id is required"}, status=400)

    if not (COLONIES_DIR / colony_id / "metadata.json").exists():
        return web.json_response({"error": f"Colony not found: {colony_id}"}, status=404)

    model = body.get("model")

    try:
        session = await manager.load_colony(session_id, colony_id=colony_id, model=model)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=409)
    except Exception as e:
        resp = _credential_error_response(e, colony_id)
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

    stats = session.colony.get_stats() if session.colony else {}
    return web.json_response(stats)


def _slugify_trigger_id(name: str, existing: set[str]) -> str:
    """Derive a stable, collision-free trigger_id from a user-supplied name.

    ``user-`` prefix keeps UI-created triggers visually distinct from the
    template/queen-authored ones in triggers.json; a numeric suffix is added
    only when the slug already exists in the session.
    """
    base = "".join(c if c.isalnum() else "-" for c in name.lower())
    while "--" in base:
        base = base.replace("--", "-")
    base = base.strip("-")[:40] or "schedule"
    candidate = f"user-{base}"
    if candidate not in existing:
        return candidate
    i = 2
    while f"{candidate}-{i}" in existing:
        i += 1
    return f"{candidate}-{i}"


async def handle_list_triggers(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/triggers — the colony's full trigger set.

    The authoritative source for the UI's trigger cards: the durable triggers
    (from the colony's triggers.json, hydrated into ``available_triggers``) plus
    live status (enabled / next-fire / fire stats). The frontend seeds its cards
    from this on colony load instead of reconstructing them from SSE events,
    which can age out of the bounded event ring buffer on a busy colony (the
    "only one / none show up" bug). SSE trigger_* events then layer live deltas
    on top.
    """
    session, err = resolve_session(request)
    if err:
        return err
    from framework.host.triggers import build_trigger_view

    return web.json_response({"triggers": build_trigger_view(session)})


async def handle_create_trigger(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/triggers — create a timer trigger and activate it.

    User-facing schedule creation from the desktop. Mirrors the timer branch of
    the queen's ``set_trigger`` tool: validate, build a TriggerDefinition, start
    its timer, persist to triggers.json, and broadcast TRIGGER_ACTIVATED (with
    next-fire fields) so the colony page renders a live card immediately.
    """
    session, err = resolve_session(request)
    if err:
        return err

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON body"}, status=400)

    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        return web.json_response({"error": "'name' is required"}, status=400)
    task = body.get("task")
    if not isinstance(task, str) or not task.strip():
        return web.json_response({"error": "'task' is required"}, status=400)

    trigger_type = body.get("trigger_type", "timer")
    if trigger_type != "timer":
        return web.json_response({"error": "Only 'timer' schedules can be created here."}, status=400)

    raw_config = body.get("trigger_config")
    if not isinstance(raw_config, dict):
        return web.json_response({"error": "'trigger_config' must be an object"}, status=400)

    # Validate + normalize: exactly one of cron / interval_minutes. Mirrors the
    # checks in handle_update_trigger_task for consistent error messages.
    cron_expr = raw_config.get("cron")
    interval = raw_config.get("interval_minutes")
    if cron_expr is not None and not isinstance(cron_expr, str):
        return web.json_response({"error": "'trigger_config.cron' must be a string"}, status=400)
    if cron_expr:
        try:
            from croniter import croniter

            if not croniter.is_valid(cron_expr):
                return web.json_response({"error": f"Invalid cron expression: {cron_expr}"}, status=400)
        except ImportError:
            return web.json_response(
                {"error": "croniter package not installed — cannot validate cron expression."},
                status=500,
            )
        trigger_config: dict = {"cron": cron_expr}
    elif interval is None:
        return web.json_response(
            {"error": "Timer trigger needs 'cron' or 'interval_minutes' in trigger_config."},
            status=400,
        )
    elif not isinstance(interval, (int, float)) or interval <= 0:
        return web.json_response({"error": "'trigger_config.interval_minutes' must be > 0"}, status=400)
    else:
        trigger_config = {"interval_minutes": interval}

    available = getattr(session, "available_triggers", {})
    trigger_id = _slugify_trigger_id(name, set(available.keys()))

    from framework.host.triggers import TriggerDefinition
    from framework.tools.queen_lifecycle_tools import (
        _persist_active_triggers,
        _save_trigger_to_agent,
        _start_trigger_timer,
    )

    tdef = TriggerDefinition(
        id=trigger_id,
        trigger_type="timer",
        trigger_config=trigger_config,
        description=name.strip(),
        task=task.strip(),
    )
    available[trigger_id] = tdef

    try:
        await _start_trigger_timer(session, trigger_id, tdef)
    except Exception as exc:  # noqa: BLE001
        # Roll back the half-registered definition so a failed start doesn't
        # leave a dangling inactive trigger behind.
        available.pop(trigger_id, None)
        return web.json_response({"error": f"Failed to start trigger timer: {exc}"}, status=500)

    tdef.enabled = True
    session.active_trigger_ids.add(trigger_id)
    session_id = request.match_info["session_id"]
    await _persist_active_triggers(session, session_id)
    _save_trigger_to_agent(session, trigger_id, tdef)

    bus = getattr(session, "event_bus", None)
    if bus:
        from framework.host.event_bus import AgentEvent, EventType

        config_out = dict(tdef.trigger_config)
        mono = getattr(session, "trigger_next_fire", {}).get(trigger_id)
        if mono is not None:
            remaining = max(0.0, mono - time.monotonic())
            config_out["next_fire_in"] = remaining
            config_out["next_fire_at"] = int((time.time() + remaining) * 1000)
        await bus.publish(
            AgentEvent(
                type=EventType.TRIGGER_ACTIVATED,
                stream_id="queen",
                data={
                    "trigger_id": trigger_id,
                    "trigger_type": "timer",
                    "trigger_config": config_out,
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
            "name": tdef.description,
            "trigger_type": "timer",
            "trigger_config": tdef.trigger_config,
        }
    )


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

    if session.colony_id is None:
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


# ------------------------------------------------------------------
# Missed-trigger handshake
# ------------------------------------------------------------------


async def handle_resolve_missed_triggers(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/colony/resolve_missed — apply
    the user's decision after a ``MISSED_TRIGGERS`` event fires on
    session load.

    Body: ``{"decisions": {"<trigger_id>": "fire_latest" | "skip" | "reschedule", ...}}``

    Returns a per-trigger result map (``"fired"``, ``"skipped"``,
    ``"rescheduled"``, ``"unknown_trigger"``, or ``"invalid_decision:..."``).
    """
    session, err = resolve_session(request)
    if err:
        return err

    if getattr(session, "colony_id", None) is None:
        return web.json_response({"error": "Colony not loaded"}, status=409)

    try:
        body = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    decisions = body.get("decisions") or {}
    if not isinstance(decisions, dict):
        return web.json_response(
            {"error": "decisions must be an object {trigger_id: decision}"},
            status=400,
        )

    from framework.tools.queen_lifecycle_tools import resolve_missed

    try:
        results = await resolve_missed(session, decisions)
    except Exception as exc:  # noqa: BLE001
        logger.exception("resolve_missed failed: %s", exc)
        return web.json_response(
            {"error": f"Failed to resolve missed triggers: {exc}"},
            status=500,
        )
    return web.json_response({"results": results})


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

    tdef.enabled = True
    session.active_trigger_ids.add(trigger_id)
    session_id = request.match_info["session_id"]
    await _persist_active_triggers(session, session_id)

    bus = getattr(session, "event_bus", None)
    if bus:
        from framework.host.event_bus import AgentEvent, EventType

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
        tdef.enabled = False

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


_EVENTS_HISTORY_DEFAULT_LIMIT = 500
_EVENTS_HISTORY_MAX_LIMIT = 10000

# Hard ceiling on the worker-thread file read. The paged read is normally
# sub-second even for huge logs, so a breach means the shared thread pool is
# saturated and the read never got a thread — not a slow disk. We fail fast
# with a retryable 503 instead of letting the request (and the desktop's
# session-load spinner) hang indefinitely. The client's SSE replay already
# carries the recent transcript, so a re-open simply retries.
_EVENTS_HISTORY_READ_TIMEOUT_S = 20.0

# Files at or below this size use the simple forward-scan path (cheap enough
# that the seek-backward dance isn't worth it). Above this threshold we read
# the tail directly from end-of-file so a 50 MB log doesn't have to be paged
# through entirely just to surface the last 2000 lines.
_EVENTS_HISTORY_REVERSE_TAIL_THRESHOLD_BYTES = 1 << 20  # 1 MB
_EVENTS_HISTORY_REVERSE_TAIL_CHUNK_BYTES = 64 * 1024

# Any single ``data`` field larger than this is replaced with a small marker
# before the event log is returned to the client. New sessions no longer
# persist heavy diagnostic fields (see _DISK_STRIPPED_DATA_FIELDS in
# event_bus.py), but logs written before that fix carry ~280 KB
# ``full_request`` dumps on every context-usage event — without this trim a
# session restore would ship a multi-hundred-MB response the desktop cannot
# load. Belt-and-suspenders for any future heavy field too.
_EVENTS_HISTORY_MAX_FIELD_BYTES = 64 * 1024
# Diagnostic-only fields always dropped from the response regardless of size.
_EVENTS_HISTORY_STRIPPED_FIELDS: tuple[str, ...] = ("full_request",)


def _truncate_large_event(event: dict) -> dict:
    """Drop diagnostic-only fields and replace any oversized ``data`` field
    with a ``{"_truncated": true, ...}`` marker, so one bloated event can't
    blow up the whole response. Returns the event unchanged when nothing
    needs trimming; otherwise returns a shallow copy (the input is not
    mutated)."""
    data = event.get("data")
    if not isinstance(data, dict):
        return event
    trimmed: dict | None = None
    for key, value in data.items():
        if key in _EVENTS_HISTORY_STRIPPED_FIELDS:
            if trimmed is None:
                trimmed = dict(data)
            trimmed[key] = {"_truncated": True, "_reason": "diagnostic_field"}
            continue
        # Only nested structures can be large; scalars are always small.
        if not isinstance(value, (dict, list)):
            continue
        try:
            size = len(json.dumps(value, default=str))
        except (TypeError, ValueError):
            continue
        if size > _EVENTS_HISTORY_MAX_FIELD_BYTES:
            if trimmed is None:
                trimmed = dict(data)
            trimmed[key] = {"_truncated": True, "_original_bytes": size}
    if trimmed is None:
        return event
    event = dict(event)
    event["data"] = trimmed
    return event


# Dedicated, bounded pool for latency-sensitive UI disk reads (events/history).
# Kept SEPARATE from the process-wide default ThreadPoolExecutor that
# ``asyncio.to_thread`` uses — that pool is shared with tool spillover, colony
# data polls, mkdirs, credential syncs, and the resource monitor, so under load
# (a busy LLM turn + parallel colony workers) a history read dispatched there
# can queue behind unrelated work until it trips the 20s timeout above, leaving
# the desktop's session-switch overlay stuck on a spinner. Isolating these reads
# guarantees a switch always gets a worker promptly. Mirrors the ``_TOOL_EXECUTOR``
# isolation in agent_loop/internals/tool_result_handler.py.
_HISTORY_READ_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None
_HISTORY_READ_EXECUTOR_LOCK = threading.Lock()


def _history_read_executor() -> concurrent.futures.ThreadPoolExecutor:
    """Lazily build the shared, bounded UI-read thread pool."""
    global _HISTORY_READ_EXECUTOR
    ex = _HISTORY_READ_EXECUTOR
    if ex is None:
        with _HISTORY_READ_EXECUTOR_LOCK:
            ex = _HISTORY_READ_EXECUTOR
            if ex is None:
                workers = max(4, int(os.environ.get("HIVE_HISTORY_READ_WORKERS", "8")))
                ex = concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hive-history-read")
                _HISTORY_READ_EXECUTOR = ex
    return ex


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


def _count_events_total(events_path: Path, file_size: int) -> int:
    """Total non-blank line (event) count of the whole file, counted by a
    fast newline-only byte scan — no JSON parse. Mirrors the total pass in
    ``_read_events_tail`` so the two readers agree."""
    import os as _os

    total = 0
    with open(events_path, "rb") as fb:
        while True:
            chunk = fb.read(1 << 20)
            if not chunk:
                break
            total += chunk.count(b"\n")
    # File may end without a trailing newline; if so, the last non-empty
    # line was missed by the newline count. Count it.
    if file_size > 0:
        with open(events_path, "rb") as fb:
            fb.seek(-1, _os.SEEK_END)
            if fb.read(1) != b"\n":
                total += 1
    return total


def _read_events_page(
    events_path: Path,
    limit: int,
    before_offset: int | None,
) -> tuple[list[dict], int, int]:
    """Read one backward page of an append-only JSONL events log.

    Returns ``(events, start_offset, total)``:

    * ``events`` — at most ``limit`` parsed events, oldest-first, drawn from
      the region ``[0, upper)`` where ``upper`` is ``before_offset`` (or the
      file size when ``before_offset is None``, i.e. the first/tail page).
      These are the ``limit`` events immediately preceding ``upper``.
    * ``start_offset`` — byte offset of the first returned event's line
      (the next backward cursor). ``0`` once the file start is reached or
      when nothing was returned — both mean "no older events remain".
    * ``total`` — total non-blank line (event) count of the whole file when
      ``before_offset is None``; ``-1`` on cursor pages (the client doesn't
      need it there, and skipping the full-file newline scan keeps each
      cursor page O(page) instead of O(file)).

    ``before_offset`` must fall on a line boundary — it is always a
    ``start_offset`` this function returned earlier, so the byte just before
    it is a ``\\n``. The whole scheme assumes one event per non-blank line
    (the same assumption ``_read_events_tail`` already makes), so a line's
    byte offset doubles as its event index anchor for the caller.
    """
    file_size = events_path.stat().st_size
    upper = file_size if before_offset is None else max(0, min(before_offset, file_size))
    if upper == 0:
        return [], 0, (_count_events_total(events_path, file_size) if before_offset is None else -1)

    # Read backward from ``upper`` until we have at least ``limit`` complete
    # lines (one extra newline beyond ``limit`` lets us pin the first kept
    # line's start), or we reach the file start.
    chunk_size = _EVENTS_HISTORY_REVERSE_TAIL_CHUNK_BYTES
    pieces: list[bytes] = []
    newline_count = 0
    pos = upper
    with open(events_path, "rb") as fb:
        while pos > 0 and newline_count <= limit:
            read_size = min(chunk_size, pos)
            pos -= read_size
            fb.seek(pos)
            chunk = fb.read(read_size)
            newline_count += chunk.count(b"\n")
            pieces.append(chunk)
    pieces.reverse()
    blob = b"".join(pieces)  # bytes of region [pos, upper)

    # Line starts within (pos, upper]: the byte after each newline. Plus
    # offset 0 itself when we read all the way to the file start (pos == 0).
    # When pos > 0 the bytes before the first newline are a partial line we
    # didn't fully read — it's excluded, which is correct (it belongs to an
    # older page).
    line_starts: list[int] = []
    if pos == 0:
        line_starts.append(0)
    for i, b in enumerate(blob):
        if b == 0x0A:  # '\n'
            s = pos + i + 1
            if s < upper:
                line_starts.append(s)

    # Build (start_offset, text) for each complete line: text runs to the
    # next line start, or to ``upper`` for the final line (the last file
    # line has no trailing newline only when upper == file_size).
    rows: list[tuple[int, bytes]] = []
    for idx, s in enumerate(line_starts):
        e = line_starts[idx + 1] - 1 if idx + 1 < len(line_starts) else upper
        rows.append((s, blob[s - pos : e - pos]))

    # Drop blanks, keep the last ``limit`` events (those nearest ``upper``).
    rows = [(s, t) for (s, t) in rows if t.strip()]
    if len(rows) > limit:
        rows = rows[-limit:]

    events: list[dict] = []
    for _s, raw in rows:
        try:
            events.append(json.loads(raw.decode("utf-8", errors="replace")))
        except json.JSONDecodeError:
            continue

    start_offset = rows[0][0] if rows else 0
    total = _count_events_total(events_path, file_size) if before_offset is None else -1
    return events, start_offset, total


async def handle_session_events_history(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/events/history — persisted eventbus log.

    Reads ``events.jsonl`` from the session directory on disk so it works for
    both live sessions and cold (post-server-restart) sessions.  The frontend
    replays these events through ``sseEventToChatMessage`` to fully reconstruct
    the UI state on resume.

    Query params:
        limit: maximum number of events to return (default 500, max 10000).
        before_offset / before_index: backward-paging cursor. Omit both to
            fetch the TAIL (the most recent ``limit`` events). To page older,
            pass the previous response's ``start_offset`` as ``before_offset``
            and its ``start_index`` as ``before_index``; the response then
            holds the ``limit`` events immediately preceding that cursor.

    Response shape::

        {
            "events": [...],          # up to ``limit`` events, oldest-first
            "session_id": "...",
            "total": 12345,           # total events in the file (-1 on cursor pages)
            "returned": 500,          # len(events)
            "truncated": false,       # kept for back-compat; unused by the client
            "limit": 500,             # the effective limit used
            "start_index": 11846,     # abs 1-based line-index of the first returned event
            "start_offset": 987654,   # byte offset of the first returned line — next cursor
            "has_more_older": true,   # older events remain (start_offset > 0)
        }

    ``events.jsonl`` is append-only chronological, so the read walks backward
    from the cursor (or EOF) and the client stitches pages oldest-first as the
    user scrolls up. Long-running colonies have produced files with 50k+
    events; paging keeps each page-mount and each scroll-step cheap.

    The actual file read runs in a worker thread via ``asyncio.to_thread`` so
    it doesn't block the event loop while other requests are in flight.

    On cold resume, ``_start_queen`` truncates ``events.jsonl`` before the
    new EventBus begins writing (see session_manager.py).  This keeps each
    runtime segment self-contained — the frontend never sees stale tool
    calls from prior runs, and the seq-based dedup in chat-helpers.ts
    (which assumes a single monotonically-increasing seq space per
    session) works correctly.
    """
    session_id = request.match_info["session_id"]

    def _int_param(name: str, default: int | None) -> int | None:
        raw = request.query.get(name)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    limit = _int_param("limit", _EVENTS_HISTORY_DEFAULT_LIMIT) or _EVENTS_HISTORY_DEFAULT_LIMIT
    limit = max(1, min(limit, _EVENTS_HISTORY_MAX_LIMIT))
    before_offset = _int_param("before_offset", None)
    # ``before_index`` anchors the absolute event index of the returned page
    # (and therefore the rewritten ``seq``). When omitted on a cursor read we
    # fall back to seq = start_offset-relative numbering below.
    before_index = _int_param("before_index", None)

    def _empty(extra: dict | None = None) -> web.Response:
        body = {
            "events": [],
            "session_id": session_id,
            "total": 0,
            "returned": 0,
            "truncated": False,
            "limit": limit,
            "start_index": 0,
            "start_offset": 0,
            "has_more_older": False,
        }
        if extra:
            body.update(extra)
        return web.json_response(body)

    from framework.server.session_manager import _find_queen_session_dir

    queen_dir = _find_queen_session_dir(session_id)
    events_path = queen_dir / "events.jsonl"
    if not events_path.exists():
        return _empty()

    try:
        loop = asyncio.get_running_loop()
        events, start_offset, total = await asyncio.wait_for(
            loop.run_in_executor(
                _history_read_executor(),
                _read_events_page,
                events_path,
                limit,
                before_offset,
            ),
            timeout=_EVENTS_HISTORY_READ_TIMEOUT_S,
        )
    except TimeoutError:
        # The read couldn't complete in time — almost always the shared thread
        # pool being saturated, not a slow disk. Fail fast with a retryable
        # error so the request (and the desktop's loading overlay) can't hang
        # forever; the client's SSE replay already carries the transcript.
        # NB: must precede the OSError handler — asyncio.TimeoutError is the
        # builtin TimeoutError on 3.11+, which is itself an OSError subclass.
        logger.warning(
            "events/history read timed out after %.0fs for session=%s (thread pool saturated?)",
            _EVENTS_HISTORY_READ_TIMEOUT_S,
            session_id,
        )
        return web.json_response(
            {"error": "events_history_timeout", "session_id": session_id},
            status=503,
        )
    except OSError:
        return _empty()

    # Trim oversized / diagnostic-only fields so a bloated log (e.g. one
    # written before full_request was excluded from persistence) can't
    # produce a response too large for the desktop to fetch and parse.
    events = [_truncate_large_event(e) for e in events]

    returned = len(events)

    # Absolute 1-based line-index of the first returned event. First/tail
    # page: derive from ``total``. Cursor page: derive from the client's
    # ``before_index`` (the index of the event it currently holds at the top),
    # so indices stay contiguous across page joins even though ``total`` isn't
    # recomputed on cursor reads.
    if before_offset is None:
        start_index = max(1, total - returned + 1) if returned else 1
    elif before_index is not None:
        start_index = max(1, before_index - returned)
    else:
        # No index anchor supplied on a cursor read — fall back to a
        # monotonic-but-unanchored numbering. Callers always pass
        # before_index, so this only guards malformed requests.
        start_index = 1

    # Rewrite seq to the event's absolute 1-based file line-index. This is
    # unique and stable across pages, and equals the runtime's own seq for the
    # newest (untruncated) region — so the live-SSE / restore dedup in
    # chat-helpers.ts (eventDedupeKey = "timestamp|seq") keeps working. The
    # old per-response numbering would collide across pages.
    for i, e in enumerate(events):
        e["seq"] = start_index + i

    has_more_older = start_offset > 0
    return web.json_response(
        {
            "events": events,
            "session_id": session_id,
            "total": total,
            "returned": returned,
            "truncated": total > returned if total >= 0 else False,
            "limit": limit,
            "start_index": start_index,
            "start_offset": start_offset,
            "has_more_older": has_more_older,
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

    # Off-loop: this walks every queen's sessions/ dir, JSON-parses every
    # conversation part of any summary-stale session and rewrites its
    # summary.json — hundreds of ms to seconds of disk+CPU that used to
    # stall every SSE stream on each sidebar refresh.
    disk_sessions = await asyncio.get_running_loop().run_in_executor(_history_read_executor(), SessionManager.list_cold_sessions)
    for s in disk_sessions:
        if s["session_id"] in live_sessions:
            live = live_sessions[s["session_id"]]
            s["cold"] = False
            s["live"] = True
            # Fill in agent_name from live memory if meta.json wasn't written yet
            if not s.get("agent_name") and live.colony_id:
                s["agent_name"] = live.colony_id
            if not s.get("agent_path") and live.worker_path:
                s["agent_path"] = str(live.worker_path)

    return web.json_response({"sessions": disk_sessions})


def _validate_colony_id_segment(raw: str | None) -> str | None:
    """Return the ``raw`` colony name if it's a safe single path segment.

    Rejects empty values, anything containing path separators, parent
    references (``..``), or NUL bytes so the caller can never traverse
    outside ``COLONIES_DIR`` when joining.
    """
    if not raw or not isinstance(raw, str):
        return None
    if raw in {".", ".."}:
        return None
    if "/" in raw or "\\" in raw or "\x00" in raw:
        return None
    return raw


async def handle_list_colony_sessions(request: web.Request) -> web.Response:
    """GET /api/colonies/{colony_id}/sessions — overseer history for one colony.

    Returns sessions stored under
    ``colonies/<colony_id>/queens/<q>/sessions/<sid>/``, newest first.
    Empty list when the colony has no overseer sessions yet (no 404 —
    callers treat empty as "no prior chat" and create a fresh session).
    """
    colony_id = _validate_colony_id_segment(request.match_info.get("colony_id"))
    if colony_id is None:
        return web.json_response(
            {"error": "Invalid colony_id"},
            status=400,
        )

    manager = _get_manager(request)
    live_sessions = {s.id: s for s in manager.list_sessions()}

    # Off-loop for the same reason as handle_session_history: summary
    # rebuilds parse every part file of stale sessions.
    sessions = await asyncio.get_running_loop().run_in_executor(_history_read_executor(), SessionManager.list_colony_sessions, colony_id)
    for s in sessions:
        sid = s.get("session_id")
        if sid in live_sessions:
            live = live_sessions[sid]
            s["cold"] = False
            s["live"] = True
            if not s.get("agent_name") and live.colony_id:
                s["agent_name"] = live.colony_id
            if not s.get("agent_path") and live.worker_path:
                s["agent_path"] = str(live.worker_path)

    return web.json_response({"sessions": sessions})


async def handle_get_active_colony_session(request: web.Request) -> web.Response:
    """GET /api/colonies/{colony_id}/active-session — newest overseer
    session with messages, or ``{"session": null}`` when none exists."""
    colony_id = _validate_colony_id_segment(request.match_info.get("colony_id"))
    if colony_id is None:
        return web.json_response(
            {"error": "Invalid colony_id"},
            status=400,
        )

    entry = SessionManager.get_colony_active_session(colony_id)
    return web.json_response({"session": entry})


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
    """DELETE /api/agents — remove an agent.

    Body: {"agent_path": "exports/my_agent", "purge": false}

    Stops any live sessions for this agent, then either:
    - Soft delete (default): marks the colony as deleted in metadata.json
      so it disappears from /discover while its tracked data stays on disk.
    - Purge ("purge": true): permanently removes the agent directory and
      all its tracked data from disk.
    """
    manager = _get_manager(request)
    body = await request.json()
    agent_path = body.get("agent_path")
    purge = bool(body.get("purge"))
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

    if not (resolved.exists() and resolved.is_dir()):
        return web.json_response({"deleted": str(resolved), "purged": purge})

    if purge:
        # Permanently remove the agent directory and all tracked data
        try:
            shutil.rmtree(resolved)
        except OSError as e:
            return web.json_response({"error": f"Failed to delete agent directory: {e}"}, status=500)
        return web.json_response({"deleted": str(resolved), "purged": True})

    # Soft delete: flag the colony so it disappears from /discover but its
    # tracked data remains on disk.
    metadata_path = resolved / "metadata.json"
    try:
        mdata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        if not isinstance(mdata, dict):
            mdata = {}
        mdata["deleted"] = True
        metadata_path.write_text(json.dumps(mdata, indent=2), encoding="utf-8")
    except OSError as e:
        return web.json_response({"error": f"Failed to mark agent deleted: {e}"}, status=500)

    return web.json_response({"deleted": str(resolved), "purged": False})


async def handle_reveal_session_folder(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/reveal — open session data folder in the OS file manager."""
    manager: SessionManager = request.app["manager"]
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


async def handle_report_session_bundle(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/report-bundle

    User-initiated "report a problem with this session". Writes a
    ``user_report.json`` marker (training signal: label=bad, user_reported),
    packages the session tree (full screenshots, credentials scrubbed) into a
    tar.gz under ``data/reports/``, and returns its on-disk path + metadata. The
    desktop uploads the file directly to GCS via a backend-issued signed URL and
    can also save a local copy — so we do NOT base64 the (multi-MB) bundle here.

    Body JSON: ``{"description": str, "severity": "low|medium|high|critical"}``.
    """
    from datetime import datetime

    from framework.server._session_report import (
        SEVERITIES,
        build_session_report_bundle,
        sha256_hex,
        write_user_report_marker,
    )

    session_id = request.match_info["session_id"]
    manager: SessionManager = request.app["manager"]
    session = manager.get_session(session_id)
    storage_session_id = (session.queen_resume_from or session.id) if session else session_id

    folder = session.queen_dir if session and getattr(session, "queen_dir", None) else None
    if folder is None:
        from framework.server.session_manager import _find_queen_session_dir

        folder = _find_queen_session_dir(storage_session_id)
    if not folder.exists():
        return web.json_response({"error": "session folder not found"}, status=404)

    try:
        body = await request.json()
    except Exception:
        body = {}
    description = str(body.get("description") or "")
    severity = str(body.get("severity") or "medium")
    if severity not in SEVERITIES:
        severity = "medium"

    marker = write_user_report_marker(folder, description, severity)
    bundle, stats = build_session_report_bundle(
        folder,
        session_id=storage_session_id,
        description=description,
        severity=severity,
        marker=marker,
    )

    # Write to a temp dir OUTSIDE the session tree so (a) a later report never
    # re-packs this bundle and (b) the session dir doesn't grow unbounded. The
    # desktop reads it for the signed-URL upload + optional local save, then it
    # ages out with the OS temp dir.
    import tempfile

    reports_dir = Path(tempfile.gettempdir()) / "hive-session-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{storage_session_id}.tar.gz"
    bundle_path = reports_dir / filename
    bundle_path.write_bytes(bundle)

    return web.json_response(
        {
            "ok": True,
            "filename": filename,
            "bundle_path": str(bundle_path),
            "size": len(bundle),
            "sha256": sha256_hex(bundle),
            "content_type": "application/gzip",
            "marker": marker,
            "stats": {
                "files": stats.files,
                "text_files": stats.text_files,
                "binary_files": stats.binary_files,
                "binary_omitted": stats.binary_omitted,
                "images_stripped": stats.images_stripped,
            },
        }
    )


def _colony_root_for_session_dir(session_dir: Path) -> Path | None:
    """Return the owning colony root for a session dir, or None.

    Colony overseer sessions live at
    ``.../colonies/<colony>/queens/<q>/sessions/<sid>``; the walk returns
    ``.../colonies/<colony>`` (the colony's shared working dir). Queen DM
    sessions (``.../queens/<q>/sessions/<sid>``) have no colony → None.
    """
    for parent in session_dir.parents:
        if parent.parent is not None and parent.parent.name == "colonies":
            return parent
    return None


async def handle_session_attachment(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/attachment/{filename} — serve a saved attachment."""
    session_id = request.match_info["session_id"]
    filename = request.match_info["filename"]

    # Prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        return web.Response(status=400, text="Invalid filename")

    from framework.server.session_manager import (
        _find_queen_session_dir,
        _iter_queen_session_dirs,
    )

    # Per session dir, search order for the requested basename:
    #   1. data/attachments/  — inbound uploads + files explicitly saved there.
    #   2. attachments/       — legacy pre-D1 location.
    #   3. session working-dir root — where csv_write / write_file drop
    #      queen- and worker-generated files during a run.
    #   4. owning colony root — colony-shared outputs written outside any
    #      single session.
    # Without 3 & 4, downloading a queen-generated CSV 404s even though the
    # file exists (it just isn't under data/attachments/). filename is a
    # validated basename (traversal chars rejected above), so joining it onto
    # each candidate dir cannot escape that dir.
    #
    # A session_id is NOT unique across colonies: a DM session forked into
    # more than one colony keeps its id, so several dirs can match. The chip
    # URL carries only id + basename, not the colony, so we must check every
    # matching session dir and serve whichever one actually holds the file —
    # picking just the first match (old behavior) 404s when the file lives in
    # a different colony's fork of the same session.
    def _candidate_dirs(session_dir: Path) -> list[Path]:
        dirs = [
            session_dir / "data" / "attachments",
            session_dir / "attachments",
            session_dir,
        ]
        colony_root = _colony_root_for_session_dir(session_dir)
        if colony_root is not None:
            dirs.append(colony_root)
        return dirs

    session_dirs = list(_iter_queen_session_dirs(session_id))
    if not session_dirs:
        # No real match anywhere — fall back to the default-queen guess so the
        # legacy single-dir behavior is preserved for the 404 path.
        session_dirs = [_find_queen_session_dir(session_id)]

    filepath: Path | None = None
    for session_dir in session_dirs:
        for candidate_dir in _candidate_dirs(session_dir):
            candidate = candidate_dir / filename
            if candidate.is_file():
                filepath = candidate
                break
        if filepath is not None:
            break

    if filepath is None:
        # Resumed sessions store under their resume-SOURCE directory
        # (``storage_session_id = queen_resume_from or id``), which the
        # by-id directory walk above cannot find under the CURRENT id.
        # Ask the live session for its actual storage dir — without this,
        # every attachment produced after a cold-resume 404s (invisible
        # image chips) even though the file is right there on disk.
        live = _get_manager(request).get_session(session_id)
        live_dir = getattr(live, "queen_dir", None) if live is not None else None
        if live_dir:
            for candidate_dir in _candidate_dirs(Path(live_dir)):
                candidate = candidate_dir / filename
                if candidate.is_file():
                    filepath = candidate
                    break

    if filepath is None:
        return web.Response(status=404, text="Attachment not found")

    mime_map = {
        # Inline-previewable in any modern browser.
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        # Text-shaped: browsers render these as plain text in a new tab.
        ".csv": "text/csv",
        ".tsv": "text/tab-separated-values",
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".json": "application/json",
        ".jsonl": "application/x-ndjson",
        ".yaml": "application/yaml",
        ".yml": "application/yaml",
        ".toml": "application/toml",
        ".xml": "application/xml",
        ".html": "text/html",
        ".htm": "text/html",
        ".css": "text/css",
        ".js": "text/javascript",
        ".mjs": "text/javascript",
        ".ts": "text/plain",  # browsers won't preview x-typescript natively
        ".tsx": "text/plain",
        ".jsx": "text/plain",
        ".py": "text/plain",
        ".rb": "text/plain",
        ".go": "text/plain",
        ".rs": "text/plain",
        ".java": "text/plain",
        ".c": "text/plain",
        ".cpp": "text/plain",
        ".h": "text/plain",
        ".sh": "text/plain",
        ".sql": "text/plain",
        ".ini": "text/plain",
        ".cfg": "text/plain",
        ".conf": "text/plain",
        ".log": "text/plain",
    }
    # Anything not listed above → application/octet-stream, which causes
    # the browser to trigger a download instead of trying to inline it.
    content_type = mime_map.get(filepath.suffix.lower(), "application/octet-stream")
    return web.FileResponse(filepath, headers={"Content-Type": content_type})


async def handle_upload_attachment(request: web.Request) -> web.Response:
    """POST /api/sessions/{session_id}/upload-attachment — upload a file attachment.

    Accepts multipart/form-data with a single file field named 'file'.
    Saves to the session's attachments/ directory and returns the filename.
    """
    session_id = request.match_info["session_id"]
    manager: SessionManager = request.app["manager"]

    session = manager.get_session(session_id)
    if not session:
        return web.json_response({"error": "session not found"}, status=404)

    queen_dir = session.queen_dir
    if not queen_dir:
        from framework.server.session_manager import _find_queen_session_dir

        queen_dir = _find_queen_session_dir(session.queen_resume_from or session_id)

    # Save under data/ so MCP tools can reach the file via
    # $HIVE_STORAGE_PATH/data/attachments/... Mirrors handle_chat's behavior.
    attachments_dir = queen_dir / "data" / "attachments"
    attachments_dir.mkdir(parents=True, exist_ok=True)

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"error": "expected a 'file' field"}, status=400)

    original_name = field.filename or "upload"
    ext_map = {
        "application/pdf": ".pdf",
        "text/csv": ".csv",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/gif": ".gif",
    }
    content_type = field.headers.get("Content-Type", "application/octet-stream")
    # Also check by filename extension
    import os

    file_ext = os.path.splitext(original_name)[1].lower()
    ext = ext_map.get(content_type, file_ext or ".bin")

    # Preserve the user's filename + force the content-type-derived
    # extension (defends against ".jpg" sniff-tricks) + disambiguate
    # against existing files in the attachments dir. Same helper is
    # reused by `attach_file_tool` so user-uploads and assistant-attaches
    # produce identical on-disk shapes.
    from aden_tools.utils.attachments import (
        TEXT_EXT_TO_MIME,
        disambiguate_attachment_filename,
        sanitize_attachment_basename,
    )

    base = sanitize_attachment_basename(original_name, force_ext=ext)
    filename = disambiguate_attachment_filename(attachments_dir, base)
    filepath = attachments_dir / filename

    # Stream to disk to avoid loading entire file into memory
    with open(filepath, "wb") as f:
        while True:
            chunk = await field.read_chunk(8192)
            if not chunk:
                break
            f.write(chunk)

    # Extract text from PDFs so the queen can read the content. We
    # deliberately do NOT rasterize PDF pages to PNGs any more — after
    # Layer B the chat handler emits a single native PDF `file` block
    # which LiteLLM auto-remaps to each provider's native PDF shape
    # (Anthropic `document`, Gemini `inline_data`, OpenAI native `file`).
    # Rendering every page was slow on long PDFs and triggered the
    # frontend's > pdfMaxPages rejection for documents that would
    # otherwise upload fine as a single native attachment.
    #
    # Large PDFs (> 10 MB) are also exempt from text extraction here —
    # the frontend prepends `extracted_text` to the queen's message, and
    # a 1000-page extraction is megabytes of text that itself blows the
    # context. handle_chat applies the same threshold to skip the file
    # block, leaving the agent to call pdf_read partially via the
    # [Attachments] block hint.
    _LARGE_PDF_THRESHOLD_BYTES = 10 * 1024 * 1024
    extracted_text = ""
    if ext == ".pdf" and filepath.stat().st_size <= _LARGE_PDF_THRESHOLD_BYTES:
        try:
            import pdfplumber

            with pdfplumber.open(filepath) as pdf:
                text_parts = []
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text and page_text.strip():
                        text_parts.append(f"[PDF page {page_num + 1}]\n{page_text.strip()}")
                extracted_text = "\n\n".join(text_parts)
        except ImportError:
            pass
        except Exception:
            pass

    elif ext == ".csv":
        # Bounded parse — the composer cap matches PDFs (100 MB), so
        # stream header + first 200 rows and count the rest row-by-row
        # instead of list()'ing the whole file into memory.
        try:
            import csv
            from itertools import islice

            with open(filepath, newline="", encoding="utf-8", errors="replace") as fh:
                reader = csv.reader(fh)
                header = next(reader, None)
                if header is not None:
                    data_rows = list(islice(reader, 200))
                    row_count = len(data_rows) + sum(1 for _ in reader)
                    lines = [f"[CSV file: {original_name}, {row_count} rows, {len(header)} columns]"]
                    lines.append(" | ".join(header))
                    lines.append(" | ".join("---" for _ in header))
                    for row in data_rows:
                        lines.append(" | ".join(row))
                    if row_count > 200:
                        lines.append(f"... ({row_count - 200} more rows truncated)")
                    extracted_text = "\n".join(lines)
        except Exception:
            pass

    elif ext in TEXT_EXT_TO_MIME and ext != ".svg":
        # Text-shaped file (txt/md/json/code/...) — capped preview for the
        # chip/lightbox only. handle_chat owns the queen-context prepend
        # (Layer F1) and applies its own large-file truncation there.
        # Bounded read: the cap matches PDFs (100 MB), so never read the
        # whole file just to build a preview.
        _TEXT_PREVIEW_CAP_CHARS = 64 * 1024
        try:
            with open(filepath, encoding="utf-8", errors="replace") as fh:
                raw = fh.read(_TEXT_PREVIEW_CAP_CHARS + 1)
            if len(raw) > _TEXT_PREVIEW_CAP_CHARS:
                extracted_text = raw[:_TEXT_PREVIEW_CAP_CHARS] + "\n... (preview truncated)"
            else:
                extracted_text = raw
        except Exception:
            pass

    return web.json_response(
        {
            "filename": filename,
            "path": f"data/attachments/{filename}",
            "session_id": session_id,
            "content_type": content_type,
            "original_name": original_name,
            "extracted_text": extracted_text,
            # page_images intentionally omitted — see PDF block above.
            # Older clients that read this field will see an empty list
            # and skip their > pdfMaxPages rejection.
            "page_images": [],
        }
    )


async def handle_session_live_tools(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/live_tools — what the LLM can call right now.

    Diagnostic endpoint: returns the tool list ``phase_state.get_current_tools()``
    would hand the agent loop on its next iteration, plus the framework-added
    synthetics (``ask_user`` / ``escalate``) the loop appends at dispatch time.
    Used by the DebugPanel to verify that an MCP tool actually became available
    after the user authorized its OAuth provider — the cached
    ``available_tools`` and the post-auth tool surface can diverge during a
    bootstrap-time window, and this view is the ground truth.
    """
    manager: SessionManager = request.app["manager"]
    session_id = request.match_info["session_id"]
    session = manager.get_session(session_id)
    if not session:
        return web.json_response({"error": f"session '{session_id}' not found"}, status=404)

    phase_state = getattr(session, "phase_state", None)
    phase = getattr(phase_state, "phase", None) if phase_state else None
    mcp_names: set[str] = set(getattr(phase_state, "mcp_tool_names_all", set()) or set()) if phase_state else set()

    # Build two faithful views — the panel renders them side by side:
    #   * actual_tools   — what the agent loop can LITERALLY call this turn:
    #                      ``phase_state.get_current_tools()`` (the eager set)
    #                      plus the ``ask_user`` synthetic the loop appends at
    #                      dispatch. This mirrors AgentLoop._refresh_dynamic_tools
    #                      (``tools[:] = dynamic_tools_provider() + synthetics``).
    #   * expected_tools — the configured/allowed surface, each tagged with a
    #                      ``status`` so the panel can show WHY an allowed tool
    #                      is not callable yet (searchable / unregistered).
    # When ``get_current_tools()`` is unavailable we report ``actual_tools=[]`` +
    # ``phase_state_ready=False`` rather than falling back to ``independent_tools``
    # (the registry) — that fallback used to misrepresent the allowed surface as
    # the live callable set.
    phase_state_ready = False
    eager_tools: list = []
    searchable_tools: list = []
    unregistered_names: set[str] = set()
    if phase_state is not None:
        getter = getattr(phase_state, "get_current_tools", None)
        if callable(getter):
            try:
                eager_tools = list(getter())
                phase_state_ready = True
            except Exception:
                logger.debug("phase_state.get_current_tools() raised", exc_info=True)
        s_getter = getattr(phase_state, "get_searchable_tools", None)
        if callable(s_getter):
            try:
                searchable_tools = list(s_getter())
            except Exception:
                logger.debug("phase_state.get_searchable_tools() raised", exc_info=True)
        u_getter = getattr(phase_state, "unregistered_allowlisted_names", None)
        if callable(u_getter):
            try:
                unregistered_names = set(u_getter() or set())
            except Exception:
                logger.debug("phase_state.unregistered_allowlisted_names() raised", exc_info=True)

    _SYNTHETIC = {"ask_user", "escalate", "report_to_parent", "suggest_colony"}

    def _tool_kind(name: str) -> str:
        if name in mcp_names:
            return "mcp"
        if name in _SYNTHETIC:
            return "synthetic"
        return "lifecycle"

    # actual_tools: the eager (callable-now) set.
    actual_tools: list[dict] = []
    for t in eager_tools:
        name = getattr(t, "name", "")
        if not name:
            continue
        actual_tools.append({"name": name, "description": getattr(t, "description", "") or "", "kind": _tool_kind(name)})

    # ``ask_user`` is appended by AgentLoop._build_ask_user_tool() at dispatch
    # for direct-user-io contexts (queens) and is NOT carried in phase_state,
    # so add it to the callable view if it isn't already there.
    framework_added: list[dict] = []
    if phase_state is not None and not any(e["name"] == "ask_user" for e in actual_tools):
        ask_user_entry = {"name": "ask_user", "description": "Ask the user a question.", "kind": "synthetic"}
        framework_added.append(ask_user_entry)
        actual_tools.append(ask_user_entry)
    actual_tools.sort(key=lambda e: (e["kind"], e["name"]))

    # expected_tools: the configured/allowed surface, status-tagged.
    #   callable     — eager, also in actual_tools
    #   searchable   — allowed but loaded on demand via search_tools
    #   unregistered — allowlisted but no live MCP server registered this session
    expected_tools: list[dict] = []
    for t in eager_tools:
        name = getattr(t, "name", "")
        if not name:
            continue
        expected_tools.append({"name": name, "description": getattr(t, "description", "") or "", "kind": _tool_kind(name), "status": "callable"})
    for t in searchable_tools:
        name = getattr(t, "name", "")
        if not name:
            continue
        expected_tools.append({"name": name, "description": getattr(t, "description", "") or "", "kind": _tool_kind(name), "status": "searchable"})
    for name in sorted(unregistered_names):
        expected_tools.append({"name": name, "description": "", "kind": _tool_kind(name), "status": "unregistered"})
    _status_order = {"callable": 0, "searchable": 1, "unregistered": 2}
    expected_tools.sort(key=lambda e: (_status_order.get(e["status"], 9), e["kind"], e["name"]))

    try:
        from framework.server.routes_queen_tools import _connected_providers

        connected = sorted(_connected_providers())
    except Exception:
        logger.debug("connected-providers snapshot unavailable", exc_info=True)
        connected = []

    # Diagnostic: re-run the admission-gate snapshot computation right now,
    # and walk the session's queen registry to count Google-mapped tools that
    # were dropped at registration. Lets us tell apart "admin gate didn't see
    # the credential" from "credential present but tool not in catalog" by
    # comparing what's admitted (``_mcp_server_tools``) vs what the gate
    # would admit today.
    diagnostic: dict[str, Any] = {}
    try:
        registry = getattr(session, "_queen_tool_registry", None)
        if registry is not None and hasattr(registry, "_compute_mcp_gate_cred_snapshot"):
            tpm, lp = registry._compute_mcp_gate_cred_snapshot()
            diagnostic["gate_live_providers_now"] = sorted(lp)
            diagnostic["gate_tool_provider_map_size"] = len(tpm)
            registered_mcp = set()
            for names in (getattr(registry, "_mcp_server_tools", {}) or {}).values():
                registered_mcp.update(names)
            tools_by_provider_admitted: dict[str, int] = {}
            tools_by_provider_dropped: dict[str, list[str]] = {}
            for tool_name, prov in tpm.items():
                if not prov:
                    continue
                if tool_name in registered_mcp:
                    tools_by_provider_admitted[prov] = tools_by_provider_admitted.get(prov, 0) + 1
                else:
                    tools_by_provider_dropped.setdefault(prov, []).append(tool_name)
            diagnostic["admitted_by_provider"] = tools_by_provider_admitted
            diagnostic["dropped_by_provider"] = {
                p: {"count": len(names), "sample": sorted(names)[:5]} for p, names in tools_by_provider_dropped.items()
            }
            diagnostic["registry_mcp_total"] = len(registered_mcp)
            # Per-provider count of names actually in registry._tools (post-admit)
            google_in_registry = sorted(n for n in registered_mcp if tpm.get(n) == "google")
            diagnostic["google_admitted_sample"] = google_in_registry[:8]

        # phase_state-side counts: see whether the queen lifecycle layer
        # carried the registry's google tools into independent_tools and
        # whether the allowlist filter kept them.
        if phase_state is not None:
            allowed = getattr(phase_state, "enabled_mcp_tools", None)
            mcp_names_ps = set(getattr(phase_state, "mcp_tool_names_all", set()) or set())
            indep = list(getattr(phase_state, "independent_tools", []) or [])
            filt = list(getattr(phase_state, "_filtered_independent_tools", []) or [])
            indep_names = {getattr(t, "name", "") for t in indep}
            filt_names = {getattr(t, "name", "") for t in filt}
            google_admitted_set = set(diagnostic.get("google_admitted_sample") or [])
            # If the registry diagnostic ran, recompute the FULL google set
            if registry is not None and hasattr(registry, "_compute_mcp_gate_cred_snapshot"):
                tpm2, _ = registry._compute_mcp_gate_cred_snapshot()
                google_admitted_set = {
                    n for names in (getattr(registry, "_mcp_server_tools", {}) or {}).values() for n in names if tpm2.get(n) == "google"
                }
            diagnostic["phase_state"] = {
                "allowlist_total": len(allowed) if allowed is not None else None,
                "allowlist_is_none": allowed is None,
                "mcp_tool_names_all_total": len(mcp_names_ps),
                "google_in_mcp_names_all": len(google_admitted_set & mcp_names_ps),
                "independent_tools_total": len(indep),
                "google_in_independent_tools": len(google_admitted_set & indep_names),
                "filtered_independent_total": len(filt),
                "google_in_filtered": len(google_admitted_set & filt_names),
                "google_admitted_total": len(google_admitted_set),
                "google_in_allowlist": (len(google_admitted_set & set(allowed)) if allowed is not None else None),
            }
    except Exception:
        logger.debug("admission-gate diagnostic failed", exc_info=True)

    # Worker tool-tiering view: per live worker, the eager/searchable split
    # from its ToolTierState (see ColonyRuntime._build_worker). ``enabled``
    # False means the split is dark for that worker (no keep-set configured)
    # and it carries its full spawn toolset eagerly.
    workers_view: list[dict] = []
    try:
        colony = getattr(session, "colony_runtime", None)
        for wid, worker in (getattr(colony, "_workers", {}) or {}).items():
            wctx = getattr(worker, "context", None)
            tier = getattr(wctx, "tool_tier_state", None)
            if tier is None:
                workers_view.append(
                    {
                        "worker_id": wid,
                        "tiering": {"enabled": False, "eager_total": len(getattr(wctx, "available_tools", []) or [])},
                    }
                )
                continue
            workers_view.append(
                {
                    "worker_id": wid,
                    "tiering": {
                        "enabled": True,
                        "eager_total": len(tier.get_current_tools()),
                        "searchable_total": len(tier.get_searchable_tools()),
                        "loaded_via_search": list(tier.loaded_tool_names),
                    },
                }
            )
    except Exception:
        logger.debug("worker tiering view failed", exc_info=True)

    return web.json_response(
        {
            "session_id": session_id,
            "phase": phase,
            "phase_state_ready": phase_state_ready,
            "workers": workers_view,
            # ``tools`` stays as a back-compat alias of ``actual_tools``.
            "tools": actual_tools,
            "actual_tools": actual_tools,
            "expected_tools": expected_tools,
            "framework_added": framework_added,
            "connected_providers": connected,
            "diagnostic": diagnostic,
            "mcp_tool_count_registered": len(mcp_names),
        }
    )


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
    # ``live`` and ``history`` must be registered before {session_id}.
    app.router.add_get("/api/sessions/live", handle_live_sessions_stream)
    app.router.add_get("/api/sessions/history", handle_session_history)
    app.router.add_delete("/api/sessions/history/{session_id}", handle_delete_history_session)
    app.router.add_get("/api/sessions/{session_id}/snapshot", handle_get_session_snapshot)
    app.router.add_get("/api/sessions/{session_id}", handle_get_live_session)
    app.router.add_delete("/api/sessions/{session_id}", handle_stop_session)

    # Colony lifecycle
    app.router.add_post("/api/sessions/{session_id}/colony", handle_load_colony)
    app.router.add_delete("/api/sessions/{session_id}/colony", handle_unload_colony)
    # Dismiss the "Create Colony" popup opened by a colony-phase queen's
    # task_create(new_colony=true). Distinct from DM-side suggest_colony
    # dismissal (which works via a normal chat message) because the
    # colony-pivot path blocks inside an awaited future.
    app.router.add_post(
        "/api/sessions/{session_id}/dismiss-colony-pivot",
        handle_dismiss_colony_pivot,
    )

    # Missed-trigger handshake (UI POSTs the user's per-trigger decisions
    # after a MISSED_TRIGGERS event lands on session load).
    app.router.add_post(
        "/api/sessions/{session_id}/colony/resolve_missed",
        handle_resolve_missed_triggers,
    )

    # Per-colony overseer session history. Separate from /api/sessions/history
    # (queen DM history) because clicking a colony in the sidebar should resume
    # the colony's own ongoing chat, not surface unrelated queen DMs.
    app.router.add_get("/api/colonies/{colony_id}/sessions", handle_list_colony_sessions)
    app.router.add_get(
        "/api/colonies/{colony_id}/active-session",
        handle_get_active_colony_session,
    )

    # Session info
    app.router.add_post("/api/sessions/{session_id}/reveal", handle_reveal_session_folder)
    app.router.add_post("/api/sessions/{session_id}/report-bundle", handle_report_session_bundle)
    app.router.add_get("/api/sessions/{session_id}/attachment/{filename}", handle_session_attachment)
    app.router.add_post("/api/sessions/{session_id}/upload-attachment", handle_upload_attachment)
    app.router.add_get("/api/sessions/{session_id}/stats", handle_session_stats)
    app.router.add_get("/api/sessions/{session_id}/triggers", handle_list_triggers)
    app.router.add_post("/api/sessions/{session_id}/triggers", handle_create_trigger)
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

    app.router.add_get("/api/sessions/{session_id}/events/history", handle_session_events_history)
    app.router.add_get("/api/sessions/{session_id}/live_tools", handle_session_live_tools)
