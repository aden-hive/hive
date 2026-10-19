"""Colony worker inspection routes.

These expose per-spawned-worker data (identified by worker_id) so the
frontend can render a colony-workers sidebar analogous to the queen
profile panel. Distinct from ``routes_workers.py``, which deals with
*graph nodes* inside a worker definition rather than live worker
instances.

Session-scoped (bound to a live session's runtime):
- GET /api/sessions/{session_id}/workers            — live + completed workers
- GET /api/sessions/{session_id}/colony/skills      — colony's shared skills catalog
- GET /api/sessions/{session_id}/colony/tools       — colony's default tools

Colony-scoped (bound to the on-disk colony directory, independent of any
live session — one colony has exactly one tracker.db):
- GET /api/colonies/{colony_id}/data/tables       — list user tables in tracker.db
- GET /api/colonies/{colony_id}/data/changes      — row-level change log (since=<cursor>)
- GET /api/colonies/{colony_id}/data/tables/{table}/rows — paginated rows
- PATCH /api/colonies/{colony_id}/data/tables/{table}/rows — edit a row
"""

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

from aiohttp import web

from framework.server.app import get_request_executor, resolve_session

# Same validation used by create_colony — keep them in sync. Blocks path
# traversal (``..``) and shell-special chars; the endpoint would 400 on
# anything else anyway, but validating early avoids a disk hit.
_COLONY_NAME_RE = re.compile(r"^[a-z0-9_]+$")

# Worker ids are session-style slugs (``session_YYYYMMDD_HHMMSS_hex``).
# Validating before joining onto a filesystem path blocks traversal via
# a crafted ``worker_id`` URL segment.
_WORKER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

logger = logging.getLogger(__name__)


# Cache of parsed ``meta.json`` files for historical workers, keyed by
# worker_id. meta.json is written once at spawn and never updated, so
# entries here are valid for the process lifetime — the workers tab
# polls this list every 2s and would otherwise re-read + JSON-parse
# every historical meta on every poll. Unbounded in size; in practice
# a colony has at most a few thousand workers (sub-kB metas each).
# Failed reads are NOT cached so transient I/O errors don't poison.
_HISTORICAL_META_CACHE: dict[str, dict] = {}


def _read_historical_meta(worker_id: str, meta_path: Path) -> dict | None:
    """Read & cache ``meta.json`` for a terminated worker.

    Returns ``None`` when the file is missing, unreadable, or yields a
    non-dict payload — caller should skip the entry, matching the
    pre-cache behavior of ``_walk_colony_workers``.
    """
    cached = _HISTORICAL_META_CACHE.get(worker_id)
    if cached is not None:
        return cached
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    _HISTORICAL_META_CACHE[worker_id] = meta
    return meta


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
            # Tool-call consumption + whether the framework (possibly via
            # the colony's adaptive budget) cut the run off. getattr with
            # defaults: historical result.json tombstones and pre-upgrade
            # results lack these fields.
            "tool_calls_used": getattr(r, "tool_calls_used", 0) or 0,
            "budget_limited": bool(getattr(r, "budget_limited", False)),
        }
    return {
        "worker_id": info.id,
        "task": info.task,
        "status": str(info.status),
        "started_at": info.started_at,
        "result": result_dict,
        "profile_name": getattr(info, "profile_name", "") or "",
        "batch": {
            "batch_id": getattr(info, "batch_id", "") or "",
            "batch_index": getattr(info, "batch_index", 0) or 0,
            "batch_size": getattr(info, "batch_size", 0) or 0,
            "worker_seq": getattr(info, "worker_seq", 0) or 0,
        },
    }


async def handle_list_workers(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/workers -- list workers in a session's colony.

    Returns two populations merged:
      1. In-memory workers from the session's unified ColonyRuntime
         (``session.colony._workers``). Includes live + just-finished
         entries since ``_workers`` isn't pruned on termination.
      2. Historical worker directories on disk. Two locations are
         scanned, in order:
           a. ``<colony>/workers/`` — current layout. Multiple queen
              sessions can write here, so each entry's ``meta.json``
              is checked and only workers with
              ``queen_session_id == session.id`` are returned.
           b. ``<queen_session_dir>/workers/`` — legacy layout for
              workers spawned before the colony-root move. Naturally
              session-scoped because the path includes the session id.
         Historical entries appear as ``status="historical"`` so the
         frontend can style them distinctly from actives.
    """
    session, err = resolve_session(request)
    if err:
        return err

    runtime = _resolve_colony_runtime(session)

    workers: list[dict] = []
    known_ids: set[str] = set()
    storage_path: Path | None = None
    colony_id: str | None = None
    if runtime is not None:
        for info in runtime.list_workers():
            workers.append(_worker_info_to_dict(info))
            known_ids.add(info.id)
        raw_storage = getattr(runtime, "_storage_path", None)
        if raw_storage is not None:
            storage_path = Path(raw_storage)
        colony_id = getattr(runtime, "colony_id", None)

    # Fall back to the session's directory if the runtime didn't expose one.
    if storage_path is None:
        session_dir = getattr(session, "queen_dir", None) or getattr(session, "session_dir", None)
        if session_dir is not None:
            storage_path = Path(session_dir)

    if colony_id is None:
        colony_id = getattr(session, "colony_id", None)

    # Current layout: <colony>/workers/<worker_id>/, filtered by queen_session_id.
    # Route through the dedicated request executor so a queen tool call
    # holding the default thread pool can't stall the colony workers list.
    loop = asyncio.get_running_loop()
    executor = get_request_executor()
    if colony_id:
        from framework.config import colony_workers_dir

        workers.extend(
            await loop.run_in_executor(
                executor,
                _walk_colony_workers,
                colony_workers_dir(colony_id),
                session.id,
                known_ids,
            )
        )
        # Avoid double-counting if a worker happens to also exist under
        # the legacy path (shouldn't, but be defensive).
        known_ids.update(w["worker_id"] for w in workers)

    # Legacy layout: <queen_session_dir>/workers/<worker_id>/.
    if storage_path is not None:
        workers.extend(await loop.run_in_executor(executor, _walk_historical_workers, storage_path, known_ids))

    # Attach task progress summaries for active workers.
    from framework.tasks.store import get_task_store

    _ACTIVE_STATUSES = frozenset({"pending", "running", "queued"})
    store = get_task_store()
    for w in workers:
        # Queen-authored goal (the human title for the worker card).
        # Historical entries carry it from meta.json via the disk walk;
        # everything served from runtime memory needs the store meta read —
        # INCLUDING completed workers: _workers isn't pruned on termination,
        # so a finished worker keeps coming from the in-memory path (goal-less
        # WorkerInfo) while its id suppresses the disk walk. Gating this on
        # active statuses made a card's title regress to the raw task prompt
        # at the moment its worker completed.
        if not w.get("goal"):
            try:
                meta = await store.get_meta(w["worker_id"])
                w["goal"] = getattr(meta, "goal", None) if meta else None
            except Exception:
                w["goal"] = None
        if w["status"] not in _ACTIVE_STATUSES:
            continue
        # Workers' task lists are keyed by the BARE worker_id (the worker's
        # exec-context session_id — see colony_runtime._worker_session_id).
        # The previous composite key ("session:<id>:<id>") resolved to the
        # empty _misc/ sandbox, so task_summary was silently always empty.
        tlid = w["worker_id"]
        try:
            tasks = await store.list_tasks(tlid)
            # Exclude archived from the total so it stays consistent with the
            # per-status counts below (archived tasks are parked in History,
            # not the active plan).
            w["task_summary"] = {
                "total": sum(1 for t in tasks if t.status.value != "archived"),
                "completed": sum(1 for t in tasks if t.status.value == "completed"),
                "in_progress": sum(1 for t in tasks if t.status.value == "in_progress"),
                "pending": sum(1 for t in tasks if t.status.value == "pending"),
            }
        except Exception:
            w["task_summary"] = None

    return web.json_response({"workers": workers})


def _resolve_colony_runtime(session):
    """Return the session's unified ColonyRuntime (``session.colony``)."""
    return getattr(session, "colony", None)


def _resolve_worker_dir(session, runtime, worker_id: str) -> Path | None:
    """Locate a worker's on-disk run directory.

    Checks both layouts ``handle_list_workers`` scans, in the same order:
      1. ``<colony>/workers/<worker_id>/``        — current layout.
      2. ``<storage_path>/workers/<worker_id>/``  — legacy, session-scoped.
    Returns ``None`` when neither exists or ``worker_id`` is malformed.
    """
    if not _WORKER_ID_RE.match(worker_id):
        return None

    # Current layout.
    colony_id = getattr(runtime, "colony_id", None) or getattr(session, "colony_id", None)
    if colony_id:
        from framework.config import colony_workers_dir

        wdir = colony_workers_dir(colony_id) / worker_id
        if wdir.is_dir():
            return wdir

    # Legacy layout: the worker dir nests under the spawning session.
    storage_path: Path | None = None
    raw_storage = getattr(runtime, "_storage_path", None) if runtime is not None else None
    if raw_storage is not None:
        storage_path = Path(raw_storage)
    if storage_path is None:
        session_dir = getattr(session, "queen_dir", None) or getattr(session, "session_dir", None)
        if session_dir is not None:
            storage_path = Path(session_dir)
    if storage_path is not None:
        wdir = storage_path / "workers" / worker_id
        if wdir.is_dir():
            return wdir

    return None


async def _worker_tasks(worker_id: str) -> list[dict]:
    """Return the worker's full task list, serialized for the frontend.

    Workers own a task list keyed by the BARE worker_id (their exec-context
    session_id — same key ``handle_list_workers`` uses for its count
    summaries; the old ``session:<id>:<id>`` composite resolved to the empty
    _misc/ sandbox). Returns an empty list if the worker never created
    tasks or the store errors.
    """
    from framework.tasks.store import get_task_store

    store = get_task_store()
    tlid = worker_id
    try:
        tasks = await store.list_tasks(tlid)
    except Exception:
        return []
    return [t.model_dump(mode="json") for t in tasks]


def _read_worker_from_disk(worker_id: str, wdir: Path) -> dict:
    """Load a terminated worker's detail from its on-disk run dir ``wdir``.

    Reads ``meta.json`` (lineage written at spawn) and ``result.json``
    (terminal report); both are absent for legacy-layout workers, which
    then fall back to an mtime timestamp and a task scraped from the
    conversation. Callers resolve ``wdir`` via ``_resolve_worker_dir``.
    """
    meta: dict = {}
    meta_path = wdir / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            meta = {}

    result = None
    result_path = wdir / "result.json"
    if result_path.exists():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            result = None

    return {
        "worker_id": worker_id,
        "task": meta.get("task") or _extract_historical_task(wdir),
        "goal": meta.get("goal") or None,
        "status": "historical",
        "started_at": meta.get("spawned_at") or _safe_mtime(wdir),
        "result": result,
        "profile_name": meta.get("profile_name") or "",
        "batch": {
            "batch_id": meta.get("batch_id") or "",
            "batch_index": meta.get("batch_index") or 0,
            "batch_size": meta.get("batch_size") or 0,
            "worker_seq": meta.get("worker_seq") or 0,
        },
    }


async def handle_get_worker(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/workers/{worker_id} -- inspect one worker.

    Live workers are served from the colony runtime (full status, result,
    batch coordinates, task list). A worker that has already terminated and
    been pruned from memory is served from its on-disk run directory.
    Returns 404 when the worker is unknown to both.
    """
    session, err = resolve_session(request)
    if err:
        return err

    worker_id = request.match_info["worker_id"]
    runtime = _resolve_colony_runtime(session)

    worker = runtime.get_worker(worker_id) if runtime is not None else None
    if worker is not None:
        detail = _worker_info_to_dict(worker.info)
        detail["batch"] = {
            "batch_id": getattr(worker, "_batch_id", "") or "",
            "batch_index": getattr(worker, "_batch_index", 0) or 0,
            "batch_size": getattr(worker, "_batch_size", 0) or 0,
            "worker_seq": getattr(worker, "_worker_seq", 0) or 0,
        }
        detail["tasks"] = await _worker_tasks(worker_id)
        # Queen-authored goal — seeded into the worker's task-list meta at
        # spawn (colony_runtime.spawn); the worker card's human title.
        try:
            from framework.tasks.store import get_task_store

            _meta = await get_task_store().get_meta(worker_id)
            detail["goal"] = getattr(_meta, "goal", None) if _meta else None
        except Exception:
            detail["goal"] = None
        return web.json_response({"worker": detail})

    loop = asyncio.get_running_loop()
    executor = get_request_executor()
    wdir = await loop.run_in_executor(executor, _resolve_worker_dir, session, runtime, worker_id)
    if wdir is not None:
        detail = await loop.run_in_executor(executor, _read_worker_from_disk, worker_id, wdir)
        detail["tasks"] = await _worker_tasks(worker_id)
        return web.json_response({"worker": detail})

    return web.json_response({"error": f"unknown worker: {worker_id}"}, status=404)


# ── Worker conversation transcript ─────────────────────────────────

# Cap on conversation parts returned. Worker runs rarely exceed a few
# hundred parts; this bounds a pathological run without paginating.
_CONVERSATION_MAX_PARTS = 2000
# Per-message content cap. Tool results can be large (full HTML dumps,
# SQL result sets); the transcript view only needs a readable preview.
_CONVERSATION_CONTENT_CAP = 20000


def _read_worker_conversation(wdir: Path) -> dict:
    """Read a worker's message transcript from ``conversations/parts/``.

    Each part is a JSON file ``{seq, role, content, tool_calls?,
    tool_use_id?}``; the zero-padded filename is the seq, so sorting
    filenames yields chronological order. Oversized ``content`` is
    truncated to keep the response bounded.
    """
    parts_dir = wdir / "conversations" / "parts"
    if not parts_dir.is_dir():
        return {"messages": [], "total": 0, "truncated": False}

    try:
        files = sorted(p for p in parts_dir.iterdir() if p.suffix == ".json")
    except OSError:
        return {"messages": [], "total": 0, "truncated": False}

    total = len(files)
    truncated = total > _CONVERSATION_MAX_PARTS

    messages: list[dict] = []
    for p in files[:_CONVERSATION_MAX_PARTS]:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        content = data.get("content")
        if not isinstance(content, str):
            content = "" if content is None else json.dumps(content)
        if len(content) > _CONVERSATION_CONTENT_CAP:
            content = content[:_CONVERSATION_CONTENT_CAP] + "\n…[truncated]"

        msg: dict = {
            "seq": data.get("seq", 0),
            "role": data.get("role", ""),
            "content": content,
        }
        raw_calls = data.get("tool_calls")
        if isinstance(raw_calls, list) and raw_calls:
            msg["tool_calls"] = [
                {
                    "name": (c.get("function") or {}).get("name", ""),
                    "arguments": (c.get("function") or {}).get("arguments", ""),
                }
                for c in raw_calls
                if isinstance(c, dict)
            ]
        tool_use_id = data.get("tool_use_id")
        if tool_use_id:
            msg["tool_use_id"] = tool_use_id
        messages.append(msg)

    return {"messages": messages, "total": total, "truncated": truncated}


async def handle_get_worker_conversation(request: web.Request) -> web.Response:
    """GET /api/sessions/{session_id}/workers/{worker_id}/conversation

    Returns the worker's full message transcript, read from its on-disk
    ``conversations/parts/`` directory. Works for live and terminated
    workers alike — parts are written incrementally during the run.
    404 when the worker directory can't be located.
    """
    session, err = resolve_session(request)
    if err:
        return err

    worker_id = request.match_info["worker_id"]
    runtime = _resolve_colony_runtime(session)

    loop = asyncio.get_running_loop()
    executor = get_request_executor()
    wdir = await loop.run_in_executor(executor, _resolve_worker_dir, session, runtime, worker_id)
    if wdir is None:
        return web.json_response({"error": f"unknown worker: {worker_id}"}, status=404)

    result = await loop.run_in_executor(executor, _read_worker_conversation, wdir)
    result["worker_id"] = worker_id
    return web.json_response(result)


def _walk_colony_workers(
    workers_dir: Path,
    queen_session_id: str,
    known_ids: set[str],
) -> list[dict]:
    """Scan ``<colony>/workers/`` for worker dirs spawned by ``queen_session_id``.

    Reads each worker's ``meta.json`` (written at spawn time) and only
    returns workers whose ``queen_session_id`` matches. Workers without a
    meta.json are skipped because we can't attribute them safely — but
    that should never happen for entries written by the current code.
    """
    if not workers_dir.exists() or not workers_dir.is_dir():
        return []

    out: list[dict] = []
    try:
        entries = list(workers_dir.iterdir())
    except OSError:
        return []

    entries.sort(key=lambda p: _safe_mtime(p), reverse=True)

    for entry in entries:
        if not entry.is_dir():
            continue
        wid = entry.name
        if wid in known_ids:
            continue
        meta_path = entry / "meta.json"
        if not meta_path.exists():
            continue
        meta = _read_historical_meta(wid, meta_path)
        if meta is None:
            continue
        if meta.get("queen_session_id") != queen_session_id:
            continue
        out.append(
            {
                "worker_id": wid,
                "task": meta.get("task") or _extract_historical_task(entry),
                "goal": meta.get("goal") or None,
                "status": "historical",
                "started_at": meta.get("spawned_at") or _safe_mtime(entry),
                "result": None,
                "profile_name": meta.get("profile_name") or "",
                "batch": {
                    "batch_id": meta.get("batch_id") or "",
                    "batch_index": meta.get("batch_index") or 0,
                    "batch_size": meta.get("batch_size") or 0,
                    "worker_seq": meta.get("worker_seq") or 0,
                },
            }
        )
    return out


def _walk_historical_workers(storage_path: Path, known_ids: set[str]) -> list[dict]:
    """Scan ``<storage_path>/workers/`` for legacy-layout worker dirs.

    Pre-dates the move to ``<colony>/workers/``. The path itself was the
    session scope, so no metadata filter is needed.
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

    runtime = session.colony
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

    runtime = session.colony
    if runtime is None:
        return web.json_response({"tools": []})

    provider_map = getattr(runtime, "_tool_provider_map", None)
    tools = [_tool_to_dict(t, provider_map) for t in (runtime._tools or [])]
    tools.sort(key=lambda t: t["name"])
    return web.json_response({"tools": tools})


# ── Tracker DB progress snapshot (protected task tables) ───────────


def _resolve_tracker_db_by_name(colony_id: str) -> Path | None:
    """Resolve a colony's tracker.db path by directory name.

    Fast path: the DB file already exists — return its path without
    doing any SQLite work. This is the vast majority of read requests.

    Slow path: the DB doesn't exist yet (first read on a brand-new
    colony, or post-corrupt-recovery) — fall back to ``ensure_tracker_db``
    which will open the DB in write mode to set the WAL journal_mode
    pragma and run any pending migrations. This path is single-threaded
    per colony_id (whoever wins the race creates the file; subsequent
    readers hit the fast path).

    Why the split matters: ``ensure_tracker_db`` opens a WRITE-mode
    connection and runs ``PRAGMA journal_mode = WAL`` which needs an
    exclusive lock (verified against a v71 sandbox 2026-07-03: 20
    concurrent /data/tables reads all hit
    ``sqlite3.OperationalError: database is locked`` after burning the
    5 s busy_timeout — cf. traceback in commit message). The read
    path DOES NOT NEED any writer setup: readers open a snapshot with
    ``?mode=ro&immutable=1`` which skips journal / lock / WAL machinery
    entirely. Calling ``ensure_tracker_db`` from the read path was
    pure lock-contention on the writer side.
    """
    if not _COLONY_NAME_RE.match(colony_id):
        return None
    from framework.config import COLONIES_DIR

    colony_dir = COLONIES_DIR / colony_id
    if not colony_dir.is_dir():
        return None
    # Fast path: DB already exists → return the path directly, no SQLite work.
    db_path = colony_dir / "tracker" / "tracker.db"
    if db_path.is_file():
        return db_path
    # Slow path: DB missing → ensure_tracker_db creates it. Rare.
    from framework.host.tracker_db import ensure_tracker_db

    return ensure_tracker_db(colony_dir)


# Hard ceiling on a single colony-data read. Reads route through
# `get_request_executor()` so they don't queue behind queen tool calls;
# even so, the SQL work itself may still be slow when the tracker.db
# lives on the NFS-backed /root/.hive volume and the queen is actively
# writing to it. Fail fast with a retryable 503 rather than hanging the
# colony UI forever. Mirrors routes_sessions._EVENTS_HISTORY_READ_TIMEOUT_S.
_COLONY_DATA_READ_TIMEOUT_S = 15.0


# Local (rootfs) snapshot dir for tracker.db reads. In the sandbox VM
# `/root/.hive/colonies/<id>/tracker/tracker.db` sits on an NFS-backed
# per-team volume. Snapshotting to /var/tmp before each read gives us a
# locally-consistent copy that we can query at in-memory speed — no NFS
# in the SQL loop.
_TRACKER_SNAPSHOT_DIR = Path("/var/tmp") / "hive-tracker-snapshots"


# Per-source snapshot cache. Concurrent readers on the same tracker.db
# (the desktop's colony data grid polls tables + rows every ~2 s from
# 6-8 in-flight fetches at once) would otherwise each pay the full
# NFS-copy cost — verified 2026-07-03 on a v72 probe with 40-concurrent
# GETs where every request completed successfully but each individual
# snapshot took 5-11 s because 40 threads competed for e2b's NFS
# bandwidth. Sharing a snapshot across all readers within a short
# window collapses N reads back to 1 copy.
#
# TTL 2 s balances freshness against copy amortization: colony
# browsing tolerates a couple seconds of staleness, and it's long
# enough that a burst of poll-driven reads all hit the same cached
# snapshot. Beyond TTL the next reader triggers a fresh copy;
# concurrent readers during that copy block on the per-source lock so
# only one copy is ever in flight per source path.
_SNAPSHOT_TTL_S = 2.0
_SNAPSHOT_CACHE: dict[str, tuple[float, Path]] = {}
_SNAPSHOT_CACHE_META_LOCK = threading.Lock()
_SNAPSHOT_PER_SRC_LOCKS: dict[str, threading.Lock] = {}


def _get_per_src_lock(src_key: str) -> threading.Lock:
    """Get-or-create the per-source lock used to single-flight snapshots."""
    with _SNAPSHOT_CACHE_META_LOCK:
        lock = _SNAPSHOT_PER_SRC_LOCKS.get(src_key)
        if lock is None:
            lock = threading.Lock()
            _SNAPSHOT_PER_SRC_LOCKS[src_key] = lock
        return lock


def _do_fresh_snapshot(src_path: Path) -> Path:
    """Perform the actual byte-copy + probe. No caching, no locking.

    We deliberately do NOT use ``sqlite3.Connection.backup()`` here.
    On an NFS-backed WAL source the backup API must open the -shm/-wal
    sidecars to coordinate reader marks, and NFS cannot provide the
    memory-mapped shared-memory region SQLite needs (sqlite.org/wal.html:
    "WAL mode does not work over a network filesystem"). Under
    concurrent readers .backup() raises SQLITE_IOERR_SHMOPEN /
    READONLY_CANTINIT / spins on BUSY_SNAPSHOT — verified live on
    v69 and researched thoroughly in workflow w0n7zto36.

    Instead we plain-``shutil.copyfile`` — only read()+write() syscalls,
    no fcntl/mmap/shm. The caller opens the copy with
    ``?mode=ro&immutable=1`` which disables all WAL/journal/lock
    machinery. The main .db file is quiescent between WAL checkpoints,
    so byte-copies are almost always page-consistent; on the rare
    checkpoint overlap the ``sqlite_master`` probe below trips
    SQLITE_CORRUPT / NOTADB (Python: sqlite3.DatabaseError) and we
    retry.

    Tradeoff: reflects state as of the last WAL checkpoint (typically
    seconds stale — SQLite's default ``wal_autocheckpoint=1000`` pages).
    Acceptable for browsing.
    """
    _TRACKER_SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    fd, dst_str = tempfile.mkstemp(prefix="tracker-", suffix=".db", dir=str(_TRACKER_SNAPSHOT_DIR))
    os.close(fd)
    dst = Path(dst_str)

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            shutil.copyfile(str(src_path), str(dst))
            probe = sqlite3.connect(f"file:{dst}?mode=ro&immutable=1", uri=True)
            try:
                probe.execute("SELECT count(*) FROM sqlite_master").fetchone()
            finally:
                probe.close()
            return dst
        except (OSError, sqlite3.DatabaseError) as exc:
            last_err = exc
            logger.warning(
                "tracker snapshot attempt %d failed for %s: %s: %s",
                attempt + 1,
                src_path,
                type(exc).__name__,
                exc,
            )

    try:
        dst.unlink()
    except OSError:
        pass
    assert last_err is not None
    raise last_err


def _snapshot_tracker_to_local(src_path: Path) -> Path:
    """Return a local /var/tmp snapshot of ``src_path``, sharing it
    across concurrent readers within a ``_SNAPSHOT_TTL_S`` window.

    Concurrency shape:
      - Fast path: the cache has a snapshot for ``src_path`` that is
        younger than TTL and still on disk → return its path. All
        threads on the fast path proceed without touching NFS at all.
      - Slow path: no fresh snapshot exists. Acquire the per-source
        lock (single-flight so only ONE copy runs even if N readers
        arrive simultaneously). Re-check the cache under the lock in
        case another thread already produced one while we were waiting
        (double-checked-locking pattern). If still stale, do the copy,
        publish it to the cache, and unlink the previous cached entry.

    Callers MUST NOT unlink the returned path — the cache owns its
    lifetime. Stale entries are unlinked when replaced.
    """
    src_key = str(src_path)
    now = time.monotonic()

    # Fast path: no lock needed for a read of a monotonically-updated
    # dict; the worst case is a torn read that either sees no cache
    # (falls through to slow path) or a slightly-stale one (which the
    # TTL check filters).
    cached = _SNAPSHOT_CACHE.get(src_key)
    if cached is not None:
        ts, path = cached
        if now - ts < _SNAPSHOT_TTL_S and path.is_file():
            return path

    lock = _get_per_src_lock(src_key)
    with lock:
        # Double-checked locking: another thread may have just refreshed
        # the cache while we blocked on the lock.
        now = time.monotonic()
        cached = _SNAPSHOT_CACHE.get(src_key)
        if cached is not None:
            ts, path = cached
            if now - ts < _SNAPSHOT_TTL_S and path.is_file():
                return path

        fresh = _do_fresh_snapshot(src_path)
        # Publish and evict the previous entry. Publish under the
        # per-source lock so no reader sees a torn (ts, path) pair.
        prev = _SNAPSHOT_CACHE.get(src_key)
        _SNAPSHOT_CACHE[src_key] = (time.monotonic(), fresh)
        if prev is not None and prev[1] != fresh:
            try:
                prev[1].unlink()
            except OSError:
                pass
        return fresh


def _colony_data_timeout(colony_id: str, what: str) -> web.Response:
    logger.warning(
        "colony data read timed out after %.0fs for colony=%s (%s)",
        _COLONY_DATA_READ_TIMEOUT_S,
        colony_id,
        what,
    )
    return web.json_response({"error": "colony_data_timeout", "colony_id": colony_id}, status=503)


def _q(ident: str) -> str:
    """Quote a SQLite identifier (table or column) safely."""
    return '"' + ident.replace('"', '""') + '"'


def _list_user_tables(con: sqlite3.Connection) -> list[str]:
    return [
        r["name"]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '\\_%' ESCAPE '\\' ORDER BY name"
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
    """List user tables with columns + row counts.

    Snapshots ``db_path`` to /var/tmp first (see ``_snapshot_tracker_to_local``)
    so the SQL work runs against a local copy with no NFS in the loop.
    The overview does N × COUNT(*) — one per table — which dominates the
    query time and is exactly the pattern that hung the 13:33 storm.
    """
    snapshot = _snapshot_tracker_to_local(db_path)
    # immutable=1 is essential: the copied file still has WAL flags in
    # its header, and without it SQLite would try to open the missing
    # -shm/-wal sidecars (which we intentionally didn't copy).
    # Do NOT unlink `snapshot` — the cache in _snapshot_tracker_to_local
    # owns its lifetime and shares it across concurrent readers within
    # the TTL window.
    con = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True, timeout=5.0)
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
    # Snapshot to /var/tmp first — see _read_tables_overview and
    # _snapshot_tracker_to_local. The COUNT(*) at line-end is the slow
    # part for a large table; local-disk removes NFS lock contention
    # from the equation entirely.
    snapshot = _snapshot_tracker_to_local(db_path)
    # See _read_tables_overview: immutable=1 skips WAL/journal machinery
    # so the reader never touches -shm/-wal. Do NOT unlink `snapshot` —
    # the cache in _snapshot_tracker_to_local owns its lifetime.
    con = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True, timeout=5.0)
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


# Cap on change-log entries returned per /data/changes read. The UI only
# needs "what changed since the last 5s poll"; a burst beyond this just
# sets truncated=true and the client falls back to a generic refresh.
_CHANGES_ROWS_CAP = 2000

_CHANGE_TRIGGER_PREFIX = "_tracker_chg_"


def _read_changes(db_path: Path, since: int) -> dict:
    """Read row-level change-log entries with id > ``since``.

    ``since < 0`` is the client's init call: return only the current
    cursor + trigger coverage so the first poll doesn't badge history.
    Entries are deduped by (table, pk); the first op wins so a row that
    was inserted then updated in the window still reads as "insert".
    """
    snapshot = _snapshot_tracker_to_local(db_path)
    con = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True, timeout=5.0)
    try:
        con.row_factory = sqlite3.Row
        cursor = int(con.execute("SELECT COALESCE(MAX(id), 0) AS c FROM _tracker_changes").fetchone()["c"])
        # Tables with our triggers installed — the client uses this to
        # fall back to row-count diffing for uncovered (unregistered)
        # tables instead of showing no signal at all.
        covered = [
            r["t"]
            for r in con.execute(
                "SELECT DISTINCT tbl_name AS t FROM sqlite_master WHERE type='trigger' AND name LIKE ? ESCAPE '\\'",
                (_CHANGE_TRIGGER_PREFIX.replace("_", "\\_") + "%",),
            )
        ]
        tables: dict[str, dict[str, dict]] = {}
        truncated = False
        if 0 <= since < cursor:
            rows = con.execute(
                "SELECT table_name, pk, op FROM _tracker_changes WHERE id > ? ORDER BY id LIMIT ?",
                (since, _CHANGES_ROWS_CAP + 1),
            ).fetchall()
            if len(rows) > _CHANGES_ROWS_CAP:
                truncated = True
                rows = rows[:_CHANGES_ROWS_CAP]
            for r in rows:
                try:
                    pk = json.loads(r["pk"])
                except (json.JSONDecodeError, TypeError):
                    continue
                per_table = tables.setdefault(r["table_name"], {})
                key = json.dumps(pk, sort_keys=True)
                if key not in per_table:
                    per_table[key] = {"pk": pk, "op": r["op"]}
        return {
            "cursor": cursor,
            "covered": covered,
            "truncated": truncated,
            "tables": {name: {"count": len(m), "rows": list(m.values())} for name, m in tables.items()},
        }
    finally:
        con.close()


async def handle_table_changes(request: web.Request) -> web.Response:
    """GET /api/colonies/{colony_id}/data/changes?since=<id>"""
    colony_id = request.match_info["colony_id"]
    try:
        since = int(request.query.get("since", "-1"))
    except ValueError:
        return web.json_response({"error": "invalid since"}, status=400)

    def _work() -> dict | None:
        db_path = _resolve_tracker_db_by_name(colony_id)
        if db_path is None:
            return None
        try:
            return _read_changes(db_path, since)
        except sqlite3.Error:
            # Pre-migration DB (no _tracker_changes yet): report "no
            # change log" rather than failing the poll.
            return {"cursor": 0, "covered": [], "truncated": False, "tables": {}}

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(get_request_executor(), _work),
            timeout=_COLONY_DATA_READ_TIMEOUT_S,
        )
    except TimeoutError:
        return _colony_data_timeout(colony_id, "changes")
    if result is None:
        return web.json_response({"cursor": 0, "covered": [], "truncated": False, "tables": {}})
    return web.json_response(result)


async def handle_list_tables(request: web.Request) -> web.Response:
    """GET /api/colonies/{colony_id}/data/tables"""
    colony_id = request.match_info["colony_id"]

    def _work() -> dict:
        db_path = _resolve_tracker_db_by_name(colony_id)
        if db_path is None:
            return {"tables": []}
        return {"tables": _read_tables_overview(db_path)}

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(get_request_executor(), _work),
            timeout=_COLONY_DATA_READ_TIMEOUT_S,
        )
    except TimeoutError:
        return _colony_data_timeout(colony_id, "tables")
    return web.json_response(result)


async def handle_table_rows(request: web.Request) -> web.Response:
    """GET /api/colonies/{colony_id}/data/tables/{table}/rows"""
    colony_id = request.match_info["colony_id"]
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

    def _work() -> dict | None:
        db_path = _resolve_tracker_db_by_name(colony_id)
        if db_path is None:
            return None
        return _read_table_rows(db_path, table, limit, offset, order_by, order_dir)

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(get_request_executor(), _work),
            timeout=_COLONY_DATA_READ_TIMEOUT_S,
        )
    except TimeoutError:
        return _colony_data_timeout(colony_id, "rows")
    if result is None:
        return web.json_response({"error": "no tracker.db"}, status=404)
    if "error" in result:
        return web.json_response(result, status=400)
    return web.json_response(result)


async def handle_update_row(request: web.Request) -> web.Response:
    """PATCH /api/colonies/{colony_id}/data/tables/{table}/rows

    Body: ``{"pk": {col: value, ...}, "updates": {col: value, ...}}``.
    """
    colony_id = request.match_info["colony_id"]
    table = request.match_info["table"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    pk = body.get("pk") or {}
    updates = body.get("updates") or {}
    if not isinstance(pk, dict) or not isinstance(updates, dict):
        return web.json_response({"error": "pk and updates must be objects"}, status=400)

    def _work() -> dict | None:
        db_path = _resolve_tracker_db_by_name(colony_id)
        if db_path is None:
            return None
        return _update_table_row(db_path, table, pk, updates)

    try:
        loop = asyncio.get_running_loop()
        result = await asyncio.wait_for(
            loop.run_in_executor(get_request_executor(), _work),
            timeout=_COLONY_DATA_READ_TIMEOUT_S,
        )
    except TimeoutError:
        return _colony_data_timeout(colony_id, "update")
    if result is None:
        return web.json_response({"error": "no tracker.db"}, status=404)
    if "error" in result:
        return web.json_response(result, status=400)
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Global (cross-colony) team DB — proxied to hive-backend /v1/global-db/*.
#
# The shared global DB lives in the cloud (Postgres, schema-per-team), not on
# local disk. The runtime forwards these read/edit calls (adding the cloud
# JWT via the global_db client) so the desktop Leads view can reuse the same
# data-grid contract as the per-colony tracker. Requires a signed-in session.
# ---------------------------------------------------------------------------


def _global_db_error_response(exc: Exception) -> web.Response:
    from framework.global_db.client import GlobalDbError, NotSignedInError

    if isinstance(exc, NotSignedInError):
        return web.json_response({"error": str(exc), "signed_out": True}, status=401)
    if isinstance(exc, GlobalDbError):
        return web.json_response({"error": str(exc)}, status=exc.status or 400)
    logger.warning("global-db proxy error", exc_info=True)
    return web.json_response({"error": "global_db_proxy_error"}, status=502)


async def handle_global_crm_status(request: web.Request) -> web.Response:
    """GET /api/global/crm/status → backend /v1/crm/status

    The desktop's /crm gate: has this team ever been shown their CRM. Proxied
    like the other global reads because the renderer holds no cloud JWT of its
    own — the runtime owns the session and forwards it.

    Signed out is NOT "unconfigured": `_global_db_error_response` maps it to 401
    and the gate treats that as "let the CRM page show its own sign-in state",
    rather than dropping a signed-out user into the setup flow.
    """
    # The CRM package is optional (desktop-only); without it this build
    # simply has no CRM rather than a 500. 501 — NOT 404, which this
    # handler already maps to "team has no CRM yet" and would drop the
    # user into a setup flow this build cannot run.
    try:
        from framework.crm import client as crm_client, errors as crm_errors
    except ImportError:
        return web.json_response(
            {"error": "CRM is not available in this build", "code": "crm_unavailable"},
            status=501,
        )

    try:
        result = await asyncio.to_thread(crm_client.setup_status)
    except crm_errors.CrmError as e:
        # NOT _global_db_error_response: that maps global_db's own exception
        # types, and CrmError is neither of them — everything would fall through
        # to a blanket 502. Signed-out has to arrive at the desktop as 401,
        # because the gate reads that as "let the CRM page show its sign-in
        # state" and anything else as "this team has no CRM yet", which would
        # drop a signed-out user into the setup flow for a CRM they may already
        # own. A 502 would also trip the global connectivity banner.
        signed_out = e.exit_code == crm_errors.EXIT_NOT_SIGNED_IN
        status = {
            crm_errors.EXIT_NOT_SIGNED_IN: 401,
            crm_errors.EXIT_PERMISSION: 403,
            crm_errors.EXIT_NOT_FOUND: 404,
        }.get(e.exit_code, 400)
        return web.json_response(
            {"error": e.message, "code": e.code, "signed_out": signed_out},
            status=status,
        )
    except Exception as e:
        return _global_db_error_response(e)
    return web.json_response(result)


async def handle_global_list_tables(request: web.Request) -> web.Response:
    """GET /api/global/data/tables → backend /v1/global-db/tables"""
    from framework.global_db import client as gdb

    try:
        result = await gdb.list_tables()
    except Exception as e:
        return _global_db_error_response(e)
    # Opening the CRM view doubles as a free cache refresh for the
    # system-reminder — we already have fresh counts in hand.
    try:
        from framework.global_db.count_cache import record_global_tables

        if isinstance(result, dict):
            record_global_tables(result.get("tables") or [])
    except Exception:
        logger.debug("global-db: count cache record failed", exc_info=True)
    return web.json_response(result)


async def handle_global_table_rows(request: web.Request) -> web.Response:
    """GET /api/global/data/tables/{table}/rows"""
    from framework.global_db import client as gdb

    table = request.match_info["table"]
    params = {k: request.query[k] for k in ("limit", "offset", "order_by", "order_dir") if k in request.query}
    try:
        result = await gdb.list_rows(table, params=params or None)
    except Exception as e:
        return _global_db_error_response(e)
    return web.json_response(result)


async def handle_global_changes(request: web.Request) -> web.Response:
    """GET /api/global/data/changes?since=<cursor>

    Proxy for the backend's row-level change feed (cursor = max updated_at,
    stamped by the touch triggers). No ``since`` initializes: cursor +
    covered tables, no rows. Mirrors the per-colony tracker's
    /data/changes contract so the desktop shares one client shape.
    """
    from framework.global_db import client as gdb

    since = request.query.get("since") or None
    try:
        result = await gdb.list_changes(since)
    except Exception as e:
        return _global_db_error_response(e)
    return web.json_response(result)


async def handle_global_update_row(request: web.Request) -> web.Response:
    """PATCH /api/global/data/tables/{table}/rows  body: {pk, updates}"""
    from framework.global_db import client as gdb

    table = request.match_info["table"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    pk = body.get("pk") or {}
    updates = body.get("updates") or {}
    if not isinstance(pk, dict) or not isinstance(updates, dict):
        return web.json_response({"error": "pk and updates must be objects"}, status=400)
    try:
        result = await gdb.update_row(table, pk, updates)
    except Exception as e:
        return _global_db_error_response(e)
    return web.json_response(result)


# ---------------------------------------------------------------------------
# Global DB — grid "power" features (filter / search / insert / delete / FKs).
#
# The structured backend endpoints only do list + update. These compose the
# raw-SQL escape hatch (gdb.query / gdb.sql / gdb.upsert) to add the rest,
# while reusing the same {table, columns, primary_key, rows, total, ...} grid
# contract. All identifier/literal interpolation goes through
# ``framework.global_db.grid_query`` — see its module docstring.
# ---------------------------------------------------------------------------


async def _global_introspect(table: str) -> tuple[list[dict], list[str]]:
    """Fetch a table's column metadata + primary key via a 1-row list call.

    The backend returns columns/primary_key regardless of row count, so this
    is a cheap, schema-accurate source for validating filter/column names.
    """
    from framework.global_db import client as gdb

    meta = await gdb.list_rows(table, params={"limit": 1, "offset": 0})
    cols = meta.get("columns") or [] if isinstance(meta, dict) else []
    pk = meta.get("primary_key") or [] if isinstance(meta, dict) else []
    return cols, pk


async def handle_global_table_query(request: web.Request) -> web.Response:
    """POST /api/global/data/tables/{table}/query

    Body: ``{filter?: [{column, op, value}], search?, order_by?, order_dir?,
    limit?, offset?}``. Returns the same shape as the rows endpoint.
    """
    from framework.global_db import client as gdb, grid_query

    table = request.match_info["table"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    filters = body.get("filter") or []
    if not isinstance(filters, list):
        return web.json_response({"error": "filter must be a list"}, status=400)
    search = body.get("search")
    order_by = body.get("order_by") or None
    order_dir = body.get("order_dir", "asc")
    try:
        limit = max(1, min(500, int(body.get("limit", 100))))
        offset = max(0, int(body.get("offset", 0)))
    except (TypeError, ValueError):
        return web.json_response({"error": "invalid limit/offset"}, status=400)

    try:
        cols, pk = await _global_introspect(table)
    except Exception as e:
        return _global_db_error_response(e)
    allowed = {c["name"] for c in cols}
    if order_by and order_by not in allowed:
        order_by = None

    try:
        select_sql = grid_query.build_select(
            table,
            allowed,
            filters=filters,
            search=search,
            order_by=order_by,
            order_dir=order_dir,
            limit=limit,
            offset=offset,
        )
        count_sql = grid_query.build_count(table, allowed, filters=filters, search=search)
    except grid_query.SqlBuildError as e:
        return web.json_response({"error": str(e)}, status=400)

    try:
        rows_res = await gdb.query(select_sql, row_cap=limit)
        count_res = await gdb.query(count_sql)
    except Exception as e:
        return _global_db_error_response(e)

    rows = rows_res.get("rows") or [] if isinstance(rows_res, dict) else []
    total = 0
    crows = count_res.get("rows") or [] if isinstance(count_res, dict) else []
    if crows and isinstance(crows[0], dict) and crows[0]:
        try:
            total = int(next(iter(crows[0].values())))
        except (TypeError, ValueError):
            total = len(rows)
    return web.json_response(
        {
            "table": table,
            "columns": cols,
            "primary_key": pk,
            "rows": rows,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    )


# Cap on distinct groups returned, so a high-cardinality group column can't
# return an unbounded result set. Highest-count groups come first.
_GROUP_COUNTS_CAP = 200


async def handle_global_table_group_counts(request: web.Request) -> web.Response:
    """POST /api/global/data/tables/{table}/group-counts

    Body: ``{group_by, filter?, search?}``. Returns ``{table, group_by,
    groups: [{value, count}]}`` — one entry per distinct ``group_by`` value
    with its total count under the active filters, highest-count first. Lets a
    board/grouped view size + order its columns (and show accurate per-column
    totals) with a single query instead of loading every row.
    """
    from framework.global_db import client as gdb, grid_query

    table = request.match_info["table"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    group_by = body.get("group_by") or None
    if not group_by:
        return web.json_response({"error": "group_by is required"}, status=400)
    filters = body.get("filter") or []
    if not isinstance(filters, list):
        return web.json_response({"error": "filter must be a list"}, status=400)
    search = body.get("search")

    try:
        cols, _pk = await _global_introspect(table)
    except Exception as e:
        return _global_db_error_response(e)
    allowed = {c["name"] for c in cols}

    try:
        sql = grid_query.build_group_counts(
            table,
            allowed,
            group_by=group_by,
            filters=filters,
            search=search,
            limit=_GROUP_COUNTS_CAP,
        )
    except grid_query.SqlBuildError as e:
        return web.json_response({"error": str(e)}, status=400)

    try:
        res = await gdb.query(sql, row_cap=_GROUP_COUNTS_CAP)
    except Exception as e:
        return _global_db_error_response(e)

    rows = res.get("rows") or [] if isinstance(res, dict) else []
    groups = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            count = int(r.get("count"))
        except (TypeError, ValueError):
            count = 0
        groups.append({"value": r.get("value"), "count": count})
    return web.json_response({"table": table, "group_by": group_by, "groups": groups})


def _normalize_linkedin(url: str) -> str:
    """Normalize a LinkedIn URL to a stable slug: drop scheme/www, query/hash,
    trailing slash, lowercased. THE canonical form for lead identity — agents
    and the UI dedup against the same person only if this lives in one place."""
    u = url.strip().lower()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = re.sub(r"[?#].*$", "", u)
    return u.rstrip("/")


def _derive_lead_id(row: dict) -> str | None:
    """Canonical lead_id: normalized LinkedIn URL if present, else normalized
    email. None when neither identifier is supplied."""
    li = row.get("linkedin_url")
    if isinstance(li, str):
        slug = _normalize_linkedin(li)
        if slug:
            return slug
    email = row.get("email")
    if isinstance(email, str) and email.strip():
        return email.strip().lower()
    return None


async def handle_global_insert_row(request: web.Request) -> web.Response:
    """POST /api/global/data/tables/{table}/rows  body: {row: {...}}

    True INSERT semantics (mode='insert'): a conflict returns 409 with the
    attempted pk instead of silently overwriting a teammate's row — the UI
    turns that into "already exists — open it". For leads, the canonical
    lead_id is derived HERE (server-side) so the dedup key can't drift
    between the UI and agents.
    """
    from framework.global_db import client as gdb

    table = request.match_info["table"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    row = body.get("row")
    if not isinstance(row, dict):
        return web.json_response({"error": "row must be an object"}, status=400)

    try:
        cols, pk = await _global_introspect(table)
    except Exception as e:
        return _global_db_error_response(e)
    allowed = {c["name"] for c in cols}
    bad = [k for k in row if k not in allowed]
    if bad:
        return web.json_response({"error": f"unknown columns: {bad}"}, status=400)

    row = dict(row)
    # Insert keys on the primary key, so a single text PK must be present.
    if len(pk) == 1 and not row.get(pk[0]):
        if table == "leads" and pk[0] == "lead_id":
            derived = _derive_lead_id(row)
            if not derived:
                return web.json_response(
                    {"error": "Add an email or LinkedIn URL to identify the lead."},
                    status=400,
                )
            row[pk[0]] = derived
        else:
            # Mint a UUID for records the client didn't id.
            col_type = next((c["type"] for c in cols if c["name"] == pk[0]), "") or ""
            if "int" not in col_type.lower():
                row[pk[0]] = uuid.uuid4().hex

    attempted_pk = {c: row.get(c) for c in pk}
    try:
        result = await gdb.upsert(table, row, mode="insert")
    except gdb.GlobalDbError as e:
        if e.status == 409:
            return web.json_response(
                {"error": "conflict", "message": str(e), "pk": attempted_pk},
                status=409,
            )
        return _global_db_error_response(e)
    except Exception as e:
        return _global_db_error_response(e)
    inserted = result.get("inserted", 0) if isinstance(result, dict) else 0
    return web.json_response({"inserted": inserted, "pk": attempted_pk})


async def handle_global_delete_row(request: web.Request) -> web.Response:
    """DELETE /api/global/data/tables/{table}/rows  body: {pk: {...}}"""
    from framework.global_db import client as gdb, grid_query

    table = request.match_info["table"]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    pk_vals = body.get("pk")
    if not isinstance(pk_vals, dict) or not pk_vals:
        return web.json_response({"error": "pk must be a non-empty object"}, status=400)

    try:
        _cols, pk = await _global_introspect(table)
    except Exception as e:
        return _global_db_error_response(e)
    if not pk:
        return web.json_response({"error": f"table {table!r} has no primary key"}, status=400)
    missing = [c for c in pk if c not in pk_vals]
    if missing:
        return web.json_response({"error": f"missing primary key columns: {missing}"}, status=400)

    try:
        delete_sql = grid_query.build_delete(table, pk_vals, pk)
    except grid_query.SqlBuildError as e:
        return web.json_response({"error": str(e)}, status=400)
    try:
        result = await gdb.sql(delete_sql)
    except Exception as e:
        return _global_db_error_response(e)
    deleted = result.get("rowCount", 0) if isinstance(result, dict) else 0
    return web.json_response({"deleted": deleted})


# ---- CRM grid read layer (hive-backend /v1/crm/*) --------------------------
# Thin pass-throughs: ALL projection, FK-resolution, custom-field flattening and
# visibility live server-side in the backend CRM service. The desktop CRM views
# call these instead of the generic /api/global/data/* grid, so they never see a
# raw UUID or a raw metadata JSONB. Nothing is composed here (unlike the leads
# grid, whose SQL the runtime builds) — the backend owns the whole contract.


async def _crm_proxy(request: web.Request, method: str, path: str) -> web.Response:
    from framework.global_db import client as gdb

    body = None
    # POST/PATCH/DELETE carry a JSON body (DELETE's is optional — an absent body
    # is fine and forwarded as null).
    if method in ("POST", "PATCH", "PUT", "DELETE"):
        if request.can_read_body:
            try:
                body = await request.json()
            except Exception:
                if method != "DELETE":
                    return web.json_response({"error": "invalid JSON body"}, status=400)
    try:
        res = await gdb.request(method, path, json=body)
    except Exception as e:
        return _global_db_error_response(e)
    return web.json_response(res)


async def handle_crm_schema(request: web.Request) -> web.Response:
    """GET /api/crm/grid/schema"""
    return await _crm_proxy(request, "GET", "/v1/crm/grid/schema")


async def handle_crm_entity_query(request: web.Request) -> web.Response:
    """POST /api/crm/grid/{entity}/query"""
    entity = quote(request.match_info["entity"], safe="")
    return await _crm_proxy(request, "POST", f"/v1/crm/grid/{entity}/query")


async def handle_crm_entity_group_counts(request: web.Request) -> web.Response:
    """POST /api/crm/grid/{entity}/group-counts"""
    entity = quote(request.match_info["entity"], safe="")
    return await _crm_proxy(request, "POST", f"/v1/crm/grid/{entity}/group-counts")


async def handle_crm_entity_detail(request: web.Request) -> web.Response:
    """GET /api/crm/grid/{entity}/{id}"""
    entity = quote(request.match_info["entity"], safe="")
    rid = quote(request.match_info["id"], safe="")
    return await _crm_proxy(request, "GET", f"/v1/crm/grid/{entity}/{rid}")


async def handle_crm_entity_create(request: web.Request) -> web.Response:
    """POST /api/crm/grid/{entity}  body: {fields, identities?, because?}"""
    entity = quote(request.match_info["entity"], safe="")
    return await _crm_proxy(request, "POST", f"/v1/crm/grid/{entity}")


async def handle_crm_entity_update(request: web.Request) -> web.Response:
    """PATCH /api/crm/grid/{entity}/{id}  body: {fields?, identities?, because?}"""
    entity = quote(request.match_info["entity"], safe="")
    rid = quote(request.match_info["id"], safe="")
    return await _crm_proxy(request, "PATCH", f"/v1/crm/grid/{entity}/{rid}")


async def handle_crm_entity_delete(request: web.Request) -> web.Response:
    """DELETE /api/crm/grid/{entity}/{id}  — soft-delete (archive) the record."""
    entity = quote(request.match_info["entity"], safe="")
    rid = quote(request.match_info["id"], safe="")
    return await _crm_proxy(request, "DELETE", f"/v1/crm/grid/{entity}/{rid}")


async def handle_crm_entity_set_stage(request: web.Request) -> web.Response:
    """POST /api/crm/grid/{entity}/{id}/stage  body: {value, because?}

    The one write the read-only grid allows: a kanban stage move. The backend
    validates entity + stage and pairs it with a 'stage_changed' interaction.
    """
    entity = quote(request.match_info["entity"], safe="")
    rid = quote(request.match_info["id"], safe="")
    return await _crm_proxy(request, "POST", f"/v1/crm/grid/{entity}/{rid}/stage")


async def handle_crm_claim(request: web.Request) -> web.Response:
    """POST /api/crm/claim  body: {ids: [...], because?}"""
    return await _crm_proxy(request, "POST", "/v1/crm/claim")


async def handle_crm_release(request: web.Request) -> web.Response:
    """POST /api/crm/release  body: {ids: [...], because?}"""
    return await _crm_proxy(request, "POST", "/v1/crm/release")


# Discover foreign keys in the team schema so the UI can follow relationships
# (e.g. a lead's interactions) generically, without hardcoding the model.
# The query runs under the per-team NOSUPERUSER role, whose information_schema
# views only expose objects it has rights on — i.e. its own schema. Excluding
# the two system schemas therefore yields exactly the team's FKs, without
# depending on search_path / current_schema() resolution.
_FK_INTROSPECT_SQL = (
    "SELECT tc.table_name AS table_name, kcu.column_name AS column_name, "
    "ccu.table_name AS ref_table, ccu.column_name AS ref_column "
    "FROM information_schema.table_constraints tc "
    "JOIN information_schema.key_column_usage kcu "
    "ON tc.constraint_name = kcu.constraint_name "
    "AND tc.constraint_schema = kcu.constraint_schema "
    "JOIN information_schema.constraint_column_usage ccu "
    "ON tc.constraint_name = ccu.constraint_name "
    "AND tc.constraint_schema = ccu.constraint_schema "
    "WHERE tc.constraint_type = 'FOREIGN KEY' "
    "AND tc.table_schema NOT IN ('pg_catalog', 'information_schema') "
    "ORDER BY tc.table_name, kcu.column_name"
)


async def handle_global_foreign_keys(request: web.Request) -> web.Response:
    """GET /api/global/data/foreign-keys → [{table, column, ref_table, ref_column}]"""
    from framework.global_db import client as gdb

    try:
        result = await gdb.query(_FK_INTROSPECT_SQL)
    except Exception as e:
        return _global_db_error_response(e)
    rows = result.get("rows") or [] if isinstance(result, dict) else []
    fks = [
        {
            "table": r.get("table_name"),
            "column": r.get("column_name"),
            "ref_table": r.get("ref_table"),
            "ref_column": r.get("ref_column"),
        }
        for r in rows
        if isinstance(r, dict)
    ]
    return web.json_response({"foreign_keys": fks})


def register_routes(app: web.Application) -> None:
    """Register colony worker routes."""
    # Session-scoped — these read live runtime state from a session.
    app.router.add_get("/api/sessions/{session_id}/workers", handle_list_workers)
    # Per-worker inspect detail. Stop / stop-all already live in
    # routes_workers.py (handle_stop_live_worker / handle_stop_all_live_workers);
    # this only adds the missing read-side detail endpoint.
    app.router.add_get("/api/sessions/{session_id}/workers/{worker_id}", handle_get_worker)
    # Worker message transcript, read from conversations/parts on disk.
    app.router.add_get(
        "/api/sessions/{session_id}/workers/{worker_id}/conversation",
        handle_get_worker_conversation,
    )
    app.router.add_get("/api/sessions/{session_id}/colony/skills", handle_list_colony_skills)
    app.router.add_get("/api/sessions/{session_id}/colony/tools", handle_list_colony_tools)
    # Colony-scoped — one tracker.db per colony, no session indirection.
    app.router.add_get("/api/colonies/{colony_id}/data/tables", handle_list_tables)
    app.router.add_get("/api/colonies/{colony_id}/data/changes", handle_table_changes)
    app.router.add_get(
        "/api/colonies/{colony_id}/data/tables/{table}/rows",
        handle_table_rows,
    )
    app.router.add_patch(
        "/api/colonies/{colony_id}/data/tables/{table}/rows",
        handle_update_row,
    )
    # Global (cross-colony) team DB — proxied to the cloud backend, no colony
    # or session indirection. Powers the desktop Leads view.
    app.router.add_get("/api/global/crm/status", handle_global_crm_status)
    app.router.add_get("/api/global/data/tables", handle_global_list_tables)
    app.router.add_get("/api/global/data/changes", handle_global_changes)
    app.router.add_get("/api/global/data/foreign-keys", handle_global_foreign_keys)
    app.router.add_get("/api/global/data/tables/{table}/rows", handle_global_table_rows)
    app.router.add_post("/api/global/data/tables/{table}/query", handle_global_table_query)
    app.router.add_post(
        "/api/global/data/tables/{table}/group-counts",
        handle_global_table_group_counts,
    )
    app.router.add_post("/api/global/data/tables/{table}/rows", handle_global_insert_row)
    app.router.add_patch("/api/global/data/tables/{table}/rows", handle_global_update_row)
    app.router.add_delete("/api/global/data/tables/{table}/rows", handle_global_delete_row)
    # CRM grid read layer — projected/display-ready views (People/Orgs/Deals/
    # Activity), proxied to the backend CRM service. Replaces the generic grid
    # for CRM entities. Plus the assignment-layer writes (claim/release).
    app.router.add_get("/api/crm/grid/schema", handle_crm_schema)
    app.router.add_post("/api/crm/grid/{entity}/query", handle_crm_entity_query)
    app.router.add_post("/api/crm/grid/{entity}/group-counts", handle_crm_entity_group_counts)
    app.router.add_get("/api/crm/grid/{entity}/{id}", handle_crm_entity_detail)
    app.router.add_post("/api/crm/grid/{entity}", handle_crm_entity_create)
    app.router.add_patch("/api/crm/grid/{entity}/{id}", handle_crm_entity_update)
    app.router.add_delete("/api/crm/grid/{entity}/{id}", handle_crm_entity_delete)
    app.router.add_post("/api/crm/grid/{entity}/{id}/stage", handle_crm_entity_set_stage)
    app.router.add_post("/api/crm/claim", handle_crm_claim)
    app.router.add_post("/api/crm/release", handle_crm_release)
