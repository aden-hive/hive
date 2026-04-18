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
- GET /api/sessions/{session_id}/colony/data/tables       — list user tables in progress.db
- GET /api/sessions/{session_id}/colony/data/tables/{table}/rows — paginated rows
- PATCH /api/sessions/{session_id}/colony/data/tables/{table}/rows — edit a row
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
    """GET /api/sessions/{session_id}/workers -- list workers in a session's colony.

    Returns two populations merged:
      1. In-memory workers from the session's unified ColonyRuntime
         (``session.colony._workers``). Includes live + just-finished
         entries since ``_workers`` isn't pruned on termination.
      2. Historical worker directories on disk under
         ``<session_dir>/workers/`` that are not in memory. Populated
         from dir name / first user message / dir mtime. These appear
         as ``status="historical"`` so the frontend can style them
         distinctly from actives.

    Falls back to the legacy ``session.colony_runtime`` for the
    in-memory half when ``session.colony`` isn't set.
    """
    session, err = resolve_session(request)
    if err:
        return err

    runtime = getattr(session, "colony", None) or getattr(session, "colony_runtime", None)

    workers: list[dict] = []
    known_ids: set[str] = set()
    storage_path: Path | None = None
    if runtime is not None:
        for info in runtime.list_workers():
            workers.append(_worker_info_to_dict(info))
            known_ids.add(info.id)
        raw_storage = getattr(runtime, "_storage_path", None)
        if raw_storage is not None:
            storage_path = Path(raw_storage)

    # Fall back to the session's directory if the runtime didn't expose one.
    if storage_path is None:
        session_dir = getattr(session, "queen_dir", None) or getattr(session, "session_dir", None)
        if session_dir is not None:
            storage_path = Path(session_dir)

    if storage_path is not None:
        workers.extend(
            await asyncio.to_thread(_walk_historical_workers, storage_path, known_ids)
        )

    return web.json_response({"workers": workers})


def _walk_historical_workers(storage_path: Path, known_ids: set[str]) -> list[dict]:
    """Scan ``<storage_path>/workers/`` for worker session dirs not already
    in memory and return minimal ``WorkerSummary``-shaped entries.

    We don't persist a standalone status file per worker, so the on-disk
    entries get ``status="historical"`` and ``result=None``. The task is
    reconstructed from the first non-boilerplate user message in the
    worker's conversation parts.
    """
    workers_dir = storage_path / "workers"
    if not workers_dir.exists() or not workers_dir.is_dir():
        return []

    out: list[dict] = []
    try:
        entries = list(workers_dir.iterdir())
    except OSError:
        return []

    # Newest dir first so recent runs surface first in the tab.
    entries.sort(key=lambda p: _safe_mtime(p), reverse=True)

    for entry in entries:
        if not entry.is_dir():
            continue
        wid = entry.name
        if wid in known_ids:
            continue
        out.append(
            {
                "worker_id": wid,
                "task": _extract_historical_task(entry),
                "status": "historical",
                "started_at": _safe_mtime(entry),
                "result": None,
            }
        )
    return out


def _safe_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _extract_historical_task(worker_dir: Path) -> str:
    """Pull the worker's initial task from its conversation parts.

    seq 0 is a boilerplate "Hello" greeting in most flows; the real
    task lands in an early user message (typically seq 1 or 2). Scan
    the first few parts and return the first ``role="user"`` content
    that isn't the greeting. Bounded at 5 parts to stay cheap on
    directory listings containing hundreds of workers.
    """
    parts_dir = worker_dir / "conversations" / "parts"
    if not parts_dir.exists():
        return ""
    try:
        for i in range(5):
            p = parts_dir / f"{i:010d}.json"
            if not p.exists():
                break
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("role") != "user":
                continue
            content = data.get("content", "")
            if not isinstance(content, str):
                continue
            text = content.strip()
            if not text or text.lower() == "hello":
                continue
            return text[:400]
    except Exception:
        return ""
    return ""


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


# ── Raw data grid (airtable-style view/edit of progress.db tables) ─────
#
# The Data tab lets the operator inspect and hand-edit SQLite rows.
# Identifier-quoting note: SQLite params can only bind values, never
# identifiers, so we have to interpolate table/column names into SQL.
# Every name is *validated against sqlite_master / PRAGMA table_info*
# before use and then wrapped with ``_q()`` which escapes embedded
# quotes. Do NOT accept raw names from the request without running them
# through ``_validate_ident`` first.


def _q(ident: str) -> str:
    """Quote a SQLite identifier (table or column) safely."""
    return '"' + ident.replace('"', '""') + '"'


def _list_user_tables(con: sqlite3.Connection) -> list[str]:
    return [
        r["name"]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]


def _table_columns(con: sqlite3.Connection, table: str) -> list[dict]:
    """Return PRAGMA table_info rows as dicts. Empty list if no such table."""
    return [
        {
            "name": r["name"],
            "type": r["type"] or "",
            "notnull": bool(r["notnull"]),
            # pk>0 means the column is part of the primary key (ordinal);
            # 0 means non-PK.
            "pk": int(r["pk"]),
            "dflt_value": r["dflt_value"],
        }
        for r in con.execute(f"PRAGMA table_info({_q(table)})")
    ]


def _read_tables_overview(db_path: Path) -> list[dict]:
    """List user tables with columns + row counts."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    try:
        con.row_factory = sqlite3.Row
        out: list[dict] = []
        for name in _list_user_tables(con):
            cols = _table_columns(con, name)
            count_row = con.execute(f"SELECT COUNT(*) AS c FROM {_q(name)}").fetchone()
            out.append(
                {
                    "name": name,
                    "columns": cols,
                    "row_count": int(count_row["c"]),
                    "primary_key": [c["name"] for c in cols if c["pk"] > 0],
                }
            )
        return out
    finally:
        con.close()


def _validate_ident(name: str, known: set[str]) -> str | None:
    """Return ``name`` if present in ``known``, else ``None``."""
    return name if name in known else None


def _read_table_rows(
    db_path: Path,
    table: str,
    limit: int,
    offset: int,
    order_by: str | None,
    order_dir: str,
) -> dict:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5.0)
    try:
        con.row_factory = sqlite3.Row
        tables = set(_list_user_tables(con))
        if _validate_ident(table, tables) is None:
            return {"error": f"unknown table: {table}"}
        cols = _table_columns(con, table)
        col_names = {c["name"] for c in cols}

        sql = f"SELECT * FROM {_q(table)}"
        if order_by and order_by in col_names:
            direction = "DESC" if order_dir.lower() == "desc" else "ASC"
            sql += f" ORDER BY {_q(order_by)} {direction}"
        sql += " LIMIT ? OFFSET ?"
        rows = con.execute(sql, (int(limit), int(offset))).fetchall()
        total = con.execute(f"SELECT COUNT(*) AS c FROM {_q(table)}").fetchone()["c"]
        return {
            "table": table,
            "columns": cols,
            "primary_key": [c["name"] for c in cols if c["pk"] > 0],
            "rows": [dict(r) for r in rows],
            "total": int(total),
            "limit": int(limit),
            "offset": int(offset),
        }
    finally:
        con.close()


def _update_table_row(
    db_path: Path,
    table: str,
    pk: dict,
    updates: dict,
) -> dict:
    """Apply ``updates`` (column->value) to the row matching ``pk``.

    Returns ``{"updated": n}`` with the number of rows affected (0 or 1),
    or ``{"error": ...}`` on validation failure.
    """
    if not updates:
        return {"error": "no updates provided"}
    con = sqlite3.connect(db_path, timeout=5.0)
    try:
        con.row_factory = sqlite3.Row
        tables = set(_list_user_tables(con))
        if _validate_ident(table, tables) is None:
            return {"error": f"unknown table: {table}"}
        cols = _table_columns(con, table)
        col_names = {c["name"] for c in cols}
        pk_cols = [c["name"] for c in cols if c["pk"] > 0]
        if not pk_cols:
            return {"error": f"table {table!r} has no primary key; cannot edit by row"}

        # Validate pk has every pk column and all values are scalars.
        missing = [p for p in pk_cols if p not in pk]
        if missing:
            return {"error": f"missing primary key columns: {missing}"}

        # Validate update columns exist and aren't part of the primary key
        # (changing a PK column would silently break joins/foreign refs).
        bad = [c for c in updates if c not in col_names]
        if bad:
            return {"error": f"unknown columns: {bad}"}
        pk_update = [c for c in updates if c in pk_cols]
        if pk_update:
            return {"error": f"cannot edit primary key columns: {pk_update}"}

        set_sql = ", ".join(f"{_q(c)} = ?" for c in updates)
        where_sql = " AND ".join(f"{_q(c)} = ?" for c in pk_cols)
        sql = f"UPDATE {_q(table)} SET {set_sql} WHERE {where_sql}"
        params = list(updates.values()) + [pk[c] for c in pk_cols]
        cur = con.execute(sql, params)
        con.commit()
        return {"updated": cur.rowcount}
    finally:
        con.close()


async def handle_list_tables(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/colony/data/tables"""
    session, err = resolve_session(request)
    if err:
        return err
    db_path = _resolve_progress_db(session)
    if db_path is None:
        return web.json_response({"tables": []})
    tables = await asyncio.to_thread(_read_tables_overview, db_path)
    return web.json_response({"tables": tables})


async def handle_table_rows(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/colony/data/tables/{table}/rows"""
    session, err = resolve_session(request)
    if err:
        return err
    db_path = _resolve_progress_db(session)
    if db_path is None:
        return web.json_response({"error": "no progress.db"}, status=404)

    table = request.match_info["table"]
    # Clamp limit: 500 is enough for the grid's virtualization window;
    # a larger cap would make accidental full-table loads cheap.
    try:
        limit = max(1, min(500, int(request.query.get("limit", "100"))))
        offset = max(0, int(request.query.get("offset", "0")))
    except ValueError:
        return web.json_response({"error": "invalid limit/offset"}, status=400)
    order_by = request.query.get("order_by") or None
    order_dir = request.query.get("order_dir", "asc")

    result = await asyncio.to_thread(
        _read_table_rows, db_path, table, limit, offset, order_by, order_dir
    )
    if "error" in result:
        return web.json_response(result, status=400)
    return web.json_response(result)


async def handle_update_row(request: web.Request) -> web.Response:
    """PATCH /api/sessions/{session_id}/colony/data/tables/{table}/rows

    Body: ``{"pk": {col: value, ...}, "updates": {col: value, ...}}``.
    """
    session, err = resolve_session(request)
    if err:
        return err
    db_path = _resolve_progress_db(session)
    if db_path is None:
        return web.json_response({"error": "no progress.db"}, status=404)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    pk = body.get("pk") or {}
    updates = body.get("updates") or {}
    if not isinstance(pk, dict) or not isinstance(updates, dict):
        return web.json_response({"error": "pk and updates must be objects"}, status=400)

    table = request.match_info["table"]
    result = await asyncio.to_thread(_update_table_row, db_path, table, pk, updates)
    if "error" in result:
        return web.json_response(result, status=400)
    return web.json_response(result)


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
    app.router.add_get(
        "/api/sessions/{session_id}/colony/data/tables", handle_list_tables
    )
    app.router.add_get(
        "/api/sessions/{session_id}/colony/data/tables/{table}/rows",
        handle_table_rows,
    )
    app.router.add_patch(
        "/api/sessions/{session_id}/colony/data/tables/{table}/rows",
        handle_update_row,
    )
