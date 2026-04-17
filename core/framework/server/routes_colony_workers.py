"""Colony worker inspection routes.

These expose per-spawned-worker data (identified by worker_id) so the
frontend can render a colony-workers sidebar analogous to the queen
profile panel. Distinct from ``routes_workers.py``, which deals with
*graph nodes* inside a worker definition rather than live worker
instances.

- GET /api/sessions/{session_id}/workers            — live + completed workers
- GET /api/sessions/{session_id}/colony/skills      — colony's shared skills catalog
- GET /api/sessions/{session_id}/colony/tools       — colony's default tools
- GET /api/sessions/{session_id}/colony/progress/snapshot — progress.db tasks/steps snapshot
- GET /api/sessions/{session_id}/colony/progress/stream   — SSE feed of upserts (polled)
"""

import asyncio
import json
import logging
import sqlite3
from pathlib import Path

from aiohttp import web

from framework.server.app import resolve_session

logger = logging.getLogger(__name__)

# Poll interval for the progress SSE stream. Progress rows flip on the
# order of seconds as workers finish LLM turns, so 1s feels live without
# hammering the DB.
_PROGRESS_POLL_INTERVAL = 1.0


def _worker_info_to_dict(info) -> dict:
    """Serialize a WorkerInfo dataclass to a JSON-friendly dict."""
    result_dict = None
    if info.result is not None:
        r = info.result
        result_dict = {
            "status": r.status,
            "summary": r.summary,
            "error": r.error,
            "tokens_used": r.tokens_used,
            "duration_seconds": r.duration_seconds,
        }
    return {
        "worker_id": info.id,
        "task": info.task,
        "status": str(info.status),
        "started_at": info.started_at,
        "result": result_dict,
    }


async def handle_list_workers(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/workers -- list workers in a session's colony."""
    session, err = resolve_session(request)
    if err:
        return err

    runtime = session.colony_runtime
    if runtime is None:
        return web.json_response({"workers": []})

    workers = [_worker_info_to_dict(info) for info in runtime.list_workers()]
    return web.json_response({"workers": workers})


# ── Skills & tools ─────────────────────────────────────────────────

def _parsed_skill_to_dict(skill) -> dict:
    """Serialize a ParsedSkill for the frontend."""
    return {
        "name": skill.name,
        "description": skill.description,
        "location": skill.location,
        "base_dir": skill.base_dir,
        "source_scope": skill.source_scope,
    }


async def handle_list_colony_skills(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/colony/skills -- list skills the colony sees."""
    session, err = resolve_session(request)
    if err:
        return err

    runtime = session.colony_runtime
    if runtime is None:
        return web.json_response({"skills": []})

    # Reach into the skills manager's catalog. There is no public
    # iterator yet; we touch the private dict directly and defensively
    # tolerate either shape (bare SkillsManager, or the
    # from_precomputed variant which has no catalog).
    catalog = getattr(runtime._skills_manager, "_catalog", None)
    skills_dict = getattr(catalog, "_skills", None) if catalog is not None else None
    if not isinstance(skills_dict, dict):
        return web.json_response({"skills": []})

    skills = [_parsed_skill_to_dict(s) for s in skills_dict.values()]
    skills.sort(key=lambda s: s["name"])
    return web.json_response({"skills": skills})


# Tools that ship with the framework and have no credential provider,
# but still deserve their own logical group. Surfaced to the frontend
# as ``provider="system"`` so the UI treats them exactly like a
# credential-backed group.
_SYSTEM_TOOLS: frozenset[str] = frozenset(
    {
        "get_account_info",
        "get_current_time",
        "bash_kill",
        "bash_output",
        "execute_command_tool",
        "example_tool",
    }
)


def _tool_to_dict(tool, provider_map: dict[str, str] | None) -> dict:
    """Serialize a Tool dataclass for the frontend.

    ``provider_map`` is the colony runtime's tool_name → credential
    provider map (built by the CredentialResolver pipeline stage from
    ``CredentialStoreAdapter.get_tool_provider_map()``). Credential-
    backed tools get a canonical provider key (e.g. ``"hubspot"``,
    ``"gmail"``); framework / core tools return ``None``, except for
    the hand-picked entries in ``_SYSTEM_TOOLS`` which are tagged
    ``"system"``.
    """
    name = getattr(tool, "name", "")
    provider = (provider_map or {}).get(name)
    if provider is None and name in _SYSTEM_TOOLS:
        provider = "system"
    return {
        "name": name,
        "description": getattr(tool, "description", ""),
        "provider": provider,
    }


async def handle_list_colony_tools(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/colony/tools -- list the colony's default tools."""
    session, err = resolve_session(request)
    if err:
        return err

    runtime = session.colony_runtime
    if runtime is None:
        return web.json_response({"tools": []})

    provider_map = getattr(runtime, "_tool_provider_map", None)
    tools = [_tool_to_dict(t, provider_map) for t in (runtime._tools or [])]
    tools.sort(key=lambda t: t["name"])
    return web.json_response({"tools": tools})


# ── Progress DB (tasks/steps) ──────────────────────────────────────

def _resolve_progress_db(session) -> Path | None:
    """Resolve the colony's progress.db path for ``session``.

    Returns ``None`` if the session is not bound to a colony yet or if
    the DB file doesn't exist.
    """
    colony_name = getattr(session, "colony_name", None)
    if not colony_name:
        return None
    db_path = Path.home() / ".hive" / "colonies" / colony_name / "data" / "progress.db"
    return db_path if db_path.exists() else None


def _read_progress_snapshot(db_path: Path, worker_id: str | None) -> dict:
    """Read tasks + steps from progress.db, optionally filtered by worker_id.

    The worker_id filter applies to tasks (claimed by that worker) and
    to steps (executed by that worker). If omitted, returns all rows.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    try:
        con.row_factory = sqlite3.Row
        if worker_id:
            task_rows = con.execute(
                "SELECT * FROM tasks WHERE worker_id = ? ORDER BY updated_at DESC",
                (worker_id,),
            ).fetchall()
            step_rows = con.execute(
                "SELECT * FROM steps WHERE worker_id = ? ORDER BY task_id, seq",
                (worker_id,),
            ).fetchall()
        else:
            task_rows = con.execute(
                "SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 500"
            ).fetchall()
            step_rows = con.execute(
                "SELECT * FROM steps ORDER BY task_id, seq LIMIT 2000"
            ).fetchall()
        return {
            "tasks": [dict(r) for r in task_rows],
            "steps": [dict(r) for r in step_rows],
        }
    finally:
        con.close()


async def handle_progress_snapshot(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/colony/progress/snapshot

    Optional ?worker_id=... to filter to rows touched by a specific worker.
    """
    session, err = resolve_session(request)
    if err:
        return err

    db_path = _resolve_progress_db(session)
    if db_path is None:
        return web.json_response({"tasks": [], "steps": []})

    worker_id = request.query.get("worker_id") or None
    snapshot = await asyncio.to_thread(_read_progress_snapshot, db_path, worker_id)
    return web.json_response(snapshot)


def _read_progress_upserts(
    db_path: Path,
    worker_id: str | None,
    since: str | None,
) -> tuple[list[dict], list[dict], str | None]:
    """Return task/step rows with ``updated_at`` (tasks) or a derived
    timestamp (steps) newer than ``since``, plus the new high-water mark.

    Steps don't carry an ``updated_at`` column — we use
    ``COALESCE(completed_at, started_at)`` as the change witness. A step
    without either timestamp hasn't changed since the last poll and is
    skipped.

    ``since`` is an ISO8601 string (as produced by progress_db._now_iso).
    ``None`` means "give me everything" — used for the SSE priming frame.
    """
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    try:
        con.row_factory = sqlite3.Row
        task_sql = "SELECT * FROM tasks"
        step_sql = (
            "SELECT *, COALESCE(completed_at, started_at) AS _ts "
            "FROM steps WHERE COALESCE(completed_at, started_at) IS NOT NULL"
        )
        task_args: list = []
        step_args: list = []
        if since is not None:
            task_sql += " WHERE updated_at > ?"
            step_sql += " AND COALESCE(completed_at, started_at) > ?"
            task_args.append(since)
            step_args.append(since)
        if worker_id:
            joiner_t = " AND " if since is not None else " WHERE "
            task_sql += joiner_t + "worker_id = ?"
            step_sql += " AND worker_id = ?"
            task_args.append(worker_id)
            step_args.append(worker_id)
        task_sql += " ORDER BY updated_at"
        step_sql += " ORDER BY _ts"

        task_rows = con.execute(task_sql, task_args).fetchall()
        step_rows = con.execute(step_sql, step_args).fetchall()

        tasks = [dict(r) for r in task_rows]
        steps = [dict(r) for r in step_rows]
        # High-water mark = max timestamp across both sets. Fall back to
        # the previous ``since`` when nothing changed.
        ts_values = [t["updated_at"] for t in tasks]
        ts_values.extend(s["_ts"] for s in steps if s.get("_ts"))
        new_since = max(ts_values) if ts_values else since
        return tasks, steps, new_since
    finally:
        con.close()


async def handle_progress_stream(request: web.Request) -> web.StreamResponse:
    """GET /api/sessions/{session_id}/colony/progress/stream

    SSE feed that emits ``snapshot`` once (current state) followed by
    ``upsert`` events whenever a task/step row changes. Polls the DB
    every ``_PROGRESS_POLL_INTERVAL`` seconds — the sqlite3 CLI path
    workers use for writes doesn't fire SQLite's update hook on our
    connection, so polling is the robust option.
    """
    session, err = resolve_session(request)
    if err:
        return err

    worker_id = request.query.get("worker_id") or None

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    async def _send(event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        await resp.write(payload.encode("utf-8"))

    db_path = _resolve_progress_db(session)
    if db_path is None:
        await _send("snapshot", {"tasks": [], "steps": []})
        await _send("end", {"reason": "no_progress_db"})
        return resp

    try:
        snapshot = await asyncio.to_thread(_read_progress_snapshot, db_path, worker_id)
        await _send("snapshot", snapshot)

        since: str | None = None
        # Initialize the high-water mark from the snapshot so we don't
        # re-emit every row as "new" on the first poll.
        ts_values: list[str] = [t.get("updated_at") for t in snapshot["tasks"] if t.get("updated_at")]
        ts_values.extend(
            s.get("completed_at") or s.get("started_at")
            for s in snapshot["steps"]
            if s.get("completed_at") or s.get("started_at")
        )
        if ts_values:
            since = max(v for v in ts_values if v)

        # The loop relies on client disconnect surfacing as
        # ConnectionResetError from ``_send`` — no explicit alive check
        # required.
        while True:
            await asyncio.sleep(_PROGRESS_POLL_INTERVAL)
            tasks, steps, new_since = await asyncio.to_thread(
                _read_progress_upserts, db_path, worker_id, since
            )
            if tasks or steps:
                await _send("upsert", {"tasks": tasks, "steps": steps})
                since = new_since
    except (asyncio.CancelledError, ConnectionResetError):
        # Client disconnected; clean exit.
        raise
    except Exception as exc:
        logger.warning("progress stream error: %s", exc, exc_info=True)
        try:
            await _send("error", {"message": str(exc)})
        except Exception:
            pass
    return resp


def register_routes(app: web.Application) -> None:
    """Register colony worker routes."""
    app.router.add_get("/api/sessions/{session_id}/workers", handle_list_workers)
    app.router.add_get(
        "/api/sessions/{session_id}/colony/skills", handle_list_colony_skills
    )
    app.router.add_get(
        "/api/sessions/{session_id}/colony/tools", handle_list_colony_tools
    )
    app.router.add_get(
        "/api/sessions/{session_id}/colony/progress/snapshot",
        handle_progress_snapshot,
    )
    app.router.add_get(
        "/api/sessions/{session_id}/colony/progress/stream",
        handle_progress_stream,
    )
