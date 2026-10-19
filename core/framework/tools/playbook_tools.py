"""The ``run_playbook`` tool — colony wiring for the playbook runner.

This module is the thin glue between the queen's tool surface and the pure
convergence runner in ``framework.host.playbook``. It does the colony-coupled
work the runner deliberately stays out of:

  - resolves the colony binding + tracker db_path,
  - scopes the worker tool set (strips queen-only tools so a worker can't
    recurse into run_playbook / run_worker),
  - builds ``dispatch_one`` (spawn one worker + await its report) and
    ``query_rows`` (a tracker SELECT) closures,
  - runs the playbook script in the background (async with completion
    callback), and injects a ``[PLAYBOOK_COMPLETE]`` notification to the
    queen when it finishes.

Execution model (design v0.4 §1.1): the tool returns immediately with a run
handle; the convergence loop runs in a background task and absorbs routine
worker outcomes; the queen is woken only on completion.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import logging
import os
import traceback
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _error_detail(exc: BaseException) -> tuple[str, str]:
    """Return ``(concise, full_traceback)`` for an exception.

    The full traceback is formatted here so it survives regardless of the host's
    log formatting — it goes into the log message, the run-log, and the tool
    result. The concise line names the ROOT cause (e.g. the TypeError in the
    playbook), not our PlaybookScriptError wrapper, and pinpoints the failing
    playbook line — so "playbook run() raised: 0" becomes
    "KeyError: 0 (playbook line 16)".
    """
    full = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip()

    root = exc
    while root.__cause__ is not None:
        root = root.__cause__

    lineno: int | None = None
    tb = root.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<playbook>":
            lineno = tb.tb_lineno
        tb = tb.tb_next

    where = f" (playbook line {lineno})" if lineno is not None else ""
    concise = f"{type(root).__name__}: {root}{where}"
    return concise, full


def _zero_dispatch_hint(out: dict[str, Any]) -> str | None:
    """A diagnostic when a playbook completed without dispatching ANY worker.

    Legitimate when the table was already converged (a resume). But it's also the
    silent-failure signature the queen hit: a pending query that returns a COUNT
    (one row) instead of the undone rows, or worker() called without converge so
    the coroutine is never awaited. We return a hint, not an error — the queen
    decides which case it is.
    """
    if out.get("dispatched", 0) != 0:
        return None
    return (
        "dispatched 0 workers. If the table is already converged this is correct. "
        "If you expected work: (1) `pending` must SELECT the undone ROWS (e.g. "
        "`SELECT id, url FROM t WHERE done_at IS NULL`), NOT `SELECT COUNT(*)` "
        "(which returns one row); (2) dispatch via `await converge(pending=..., "
        "dispatch=lambda row, i: worker(...))` — worker() is async and converge "
        "awaits it; calling worker() in a bare loop without await runs nothing; "
        "(3) tracker_query returns a list of row dicts — index a row's column "
        "(row['url']), not the list."
    )


# Keep references to in-flight playbook tasks so asyncio doesn't GC them.
_PLAYBOOK_TASKS: set[asyncio.Task] = set()

# Registry of currently-running playbooks, keyed by run_id — the handle the
# queen gets back from run_playbook. Lets get_playbook_status / stop_playbook
# peek at or kill a run (the TaskOutput / TaskStop analogs). Entry:
# {"task": <converge coroutine task>, "run": <PlaybookRun>, "colony": <colony>}.
_RUNNING_PLAYBOOKS: dict[str, dict[str, Any]] = {}


async def _stop_batch_workers(colony: Any, batch_id: str) -> int:
    """Stop every still-active worker belonging to a playbook's batch."""
    workers = list(getattr(colony, "_workers", {}).values())
    targets = [w for w in workers if getattr(w, "batch_id", "") == batch_id and getattr(w, "is_active", False)]
    for w in targets:
        try:
            await colony.stop_worker(getattr(w, "id", None))
        except Exception:
            logger.warning("stop_playbook: failed to stop worker %s", getattr(w, "id", "?"), exc_info=True)
    return len(targets)


async def stop_playbooks_for_colony(colony: Any) -> list[str]:
    """Cancel every running playbook convergence loop owned by ``colony``.

    A bare ``stop_worker`` only kills the workers that are live *right now* — it
    does not touch a playbook's convergence loop, which immediately re-dispatches
    fresh workers for any still-pending rows. So "stop all workers" is a lie
    while a playbook is running. Cancelling the convergence task injects a
    ``CancelledError`` straight into its ``wait_for_worker_reports`` await, so the
    loop unwinds and never dispatches another round — we wait briefly for that to
    happen so the caller doesn't report "stopped" mid-flight.

    The loop's in-flight workers are deliberately left running: the caller
    (``stop_worker``) snapshots and stops ALL colony workers next, giving these
    now-orphaned workers the same [STOP REQUESTED] grace window and report
    collection as any other worker. Stopping them here would rob them of that.

    Scoped by colony identity so one session's stop never reaches another's runs.
    Returns the run_ids that were cancelled.
    """
    if colony is None:
        return []
    targets = [(run_id, entry) for run_id, entry in list(_RUNNING_PLAYBOOKS.items()) if entry.get("colony") is colony]
    cancelled: list[str] = []
    for run_id, entry in targets:
        task = entry.get("task")
        if task is not None and not task.done():
            task.cancel()
        # Let the cancellation propagate / loop unwind before we move on, so a
        # mid-flight dispatch can't sneak a fresh worker past the snapshot the
        # caller is about to take. The _finish wrapper records the run as stopped
        # and clears it from the registry.
        if task is not None:
            try:
                await asyncio.wait({task}, timeout=2.0)
            except Exception:
                pass
        cancelled.append(run_id)
    return cancelled


def _sanitize_name(name: str) -> str:
    """Filesystem-safe slug from a playbook's meta name."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(name).strip().lower())
    return (safe.strip("-") or "playbook")[:64]


def _persist_script(colony_dir: Any, name: str, script: str) -> Path | None:
    """Save an inline playbook to ``colonies/<id>/playbooks/<name>.play.py``.

    This is what makes resume real: re-running is just re-invoking the SAME
    script over the current tracker (done rows are skipped). Without a saved
    copy the queen would have to re-supply the exact script every time, and it
    would be lost across sessions / context compaction. Re-running an
    inline playbook of the same name overwrites the file — that's the
    edit-and-re-run iteration loop. Best-effort; returns the path or None.
    """
    target = Path(colony_dir) / "playbooks" / f"{_sanitize_name(name)}.play.py"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(script, encoding="utf-8")
        return target
    except OSError:
        logger.warning("run_playbook: failed to persist script to %s", target, exc_info=True)
        return None


def _fast_result_grace() -> float:
    """Seconds to await a playbook before falling back to async + callback.

    Long enough that a fail-fast playbook (NameError, bad query — all pre-
    dispatch) returns its real outcome synchronously; short enough not to block
    the queen once a run is genuinely dispatching workers. Set to 0 to disable
    (pure async). Env: HIVE_PLAYBOOK_FAST_GRACE.
    """
    try:
        return max(0.0, float(os.environ.get("HIVE_PLAYBOOK_FAST_GRACE", "1.5")))
    except ValueError:
        return 1.5


_FAST_RESULT_GRACE_S = _fast_result_grace()

# Ceiling for a single pending-query fetch. High enough that realistic colony
# batches are never silently truncated; query_rows warns if a query exceeds it.
_PENDING_ROW_CAP = 100_000


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


# Concurrency is QUEEN-PROGRAMMED: the playbook declares `meta["concurrency"]`
# (how many workers run at once); the framework honors it and only REJECTS when
# it exceeds the hard ceiling. No more silent throttle by a hidden global cap.
_MAX_PLAYBOOK_CONCURRENCY = _int_env("HIVE_MAX_PLAYBOOK_CONCURRENCY", 32)
_DEFAULT_PLAYBOOK_CONCURRENCY = _int_env("HIVE_DEFAULT_PLAYBOOK_CONCURRENCY", 8)


def _resolve_concurrency(meta: dict[str, Any]) -> tuple[int, str | None]:
    """Resolve + validate the queen-declared concurrency from ``meta``.

    Returns ``(n, None)`` or ``(0, error)``. The queen owns the number; we only
    reject it when it exceeds the hard ceiling.
    """
    requested = meta.get("concurrency", _DEFAULT_PLAYBOOK_CONCURRENCY)
    try:
        n = max(1, int(requested))
    except (TypeError, ValueError):
        return 0, f"meta['concurrency'] must be an integer, got {requested!r}."
    if n > _MAX_PLAYBOOK_CONCURRENCY:
        return 0, (
            f"meta['concurrency']={n} exceeds the maximum {_MAX_PLAYBOOK_CONCURRENCY}. "
            "Lower it, split the batch, or raise HIVE_MAX_PLAYBOOK_CONCURRENCY."
        )
    return n, None


def _extract_rows_result(res: dict[str, Any]) -> dict[str, Any] | None:
    """Pull the rows-bearing result out of an execute_sql return.

    A pending query with a trailing ``;`` (or, defensively, multiple statements)
    comes back as ``kind="script"`` rather than ``kind="rows"`` — returning [] for
    that case makes converge think the table is already converged (#3). Here we
    accept a single rows result, or the last rows sub-result of a script.
    """
    kind = res.get("kind")
    if kind == "rows":
        return res
    if kind == "script":
        for sub in reversed(res.get("results", [])):
            if isinstance(sub, dict) and sub.get("kind") == "rows":
                return sub
    return None


def register_playbook_tools(registry: Any, session: Any = None) -> int:
    """Register the ``run_playbook`` tool. Returns the number registered (0/1)."""
    if session is None:
        return 0

    from framework.llm.provider import Tool

    async def run_playbook(
        *,
        playbook: str | None = None,
        playbook_path: str | None = None,
        playbook_name: str | None = None,
        args: Any = None,
    ) -> str:
        # ---- resolve colony + binding (needed to locate saved playbooks) --
        colony = getattr(session, "colony", None)
        if colony is None:
            return json.dumps({"error": "No unified ColonyRuntime on this session (session.colony is None)."})

        from framework.host.colony_binding import ColonyBinding, current_binding
        from framework.host.tracker_db import ensure_tracker_db

        binding = current_binding()
        if binding is None:
            name = getattr(session, "colony_id", None) or getattr(colony, "colony_id", None)
            if name:
                binding = ColonyBinding.for_name(str(name))
        if binding is None:
            return json.dumps(
                {
                    "error": (
                        "run_playbook: no colony binding in context. This queen "
                        "has not created a colony — playbooks reconcile a tracker "
                        "table, which needs a colony."
                    )
                }
            )
        db_path = Path(binding.tracker_db)
        log_db_path = Path(binding.dir) / "colony.db"  # run-log store (NOT the tracker)
        try:
            await asyncio.to_thread(ensure_tracker_db, binding.dir)
        except Exception as exc:
            logger.warning("run_playbook: ensure_tracker_db failed: %s", exc)

        # ---- resolve the script: inline / path / saved name ---------------
        playbooks_dir = Path(binding.dir) / "playbooks"
        script, source_path, err = _resolve_script(playbook, playbook_path, playbook_name, playbooks_dir)
        if err is not None:
            return json.dumps({"error": err})

        # ---- scope the worker tool set ------------------------------------
        tools_override = _worker_tools(colony)

        # Concurrency is declared by the queen in meta (resolved after load). The
        # colony's current global cap is only a FLOOR we never drop below — we
        # raise it for the run so the scheduler actually admits the declared
        # number, then restore it when the run finishes.
        colony_config = getattr(colony, "_config", None)
        original_colony_cap = getattr(colony_config, "max_concurrent_workers", None)

        # ---- build the injected closures ----------------------------------
        batch_id = "pb_" + uuid.uuid4().hex[:12]

        # Run-scoped monotonic dispatch counter. In the playbook model every
        # dispatch_one spawns its own size-1 batch, so spawn_batch's per-call
        # ``batch_index`` is always 1 — useless for telling parallel/serial
        # workers apart. This counter gives each worker a stable, unique seq
        # within the run; it drives the worker's display badge ("· #seq") and
        # its cloud-usage suffix. asyncio is single-threaded and next() never
        # awaits, so increments are race-free across concurrent dispatches.
        _dispatch_seq = itertools.count(1)

        def query_rows(sql: str) -> list[dict[str, Any]]:
            from framework.host.tracker_db import execute_sql

            # High cap so realistic batches aren't silently truncated; warn (never
            # drop silently) if a query still exceeds it (#2).
            res = execute_sql(db_path, sql, row_cap=_PENDING_ROW_CAP)
            rows_res = _extract_rows_result(res)  # handles trailing ';' / script kind (#3)
            if rows_res is None:
                return []
            if rows_res.get("truncated"):
                logger.warning(
                    "run_playbook %s: pending query hit the %d-row cap — rows beyond "
                    "that are NOT dispatched this round. Add LIMIT/paginate or split "
                    "the batch.",
                    batch_id,
                    _PENDING_ROW_CAP,
                )
            cols = rows_res.get("columns", [])
            return [dict(zip(cols, row, strict=False)) for row in rows_res.get("rows", [])]

        async def dispatch_one(
            task: str,
            *,
            data: dict[str, Any] | None = None,
            profile: str | None = None,
            timeout: float | None = None,
            schema: dict[str, Any] | None = None,
            goal: str | None = None,
        ) -> dict[str, Any]:
            spec_data = dict(data or {})
            spec_data["binding"] = binding.to_dict()
            spec_data.setdefault("task", task)
            # Run-scoped seq (see _dispatch_seq) carried as batch metadata, NOT
            # task input — spawn_batch lifts it onto the worker so the UI badge
            # and cloud-usage suffix can disambiguate peers that all share this
            # run's batch_id with a degenerate batch_index of 1.
            entry: dict[str, Any] = {
                "task": task,
                "data": spec_data,
                "worker_seq": next(_dispatch_seq),
            }
            if isinstance(goal, str) and goal.strip():
                entry["goal"] = goal.strip()
            if profile:
                entry["profile_name"] = profile
            # The receipt schema rides the spawn spec → specializes the worker's
            # report_to_parent tool + system prompt (enforced worker-side).
            if schema:
                entry["report_schema"] = schema
            wids = await colony.spawn_batch(
                [entry],
                tools_override=tools_override,
                batch_id=batch_id,
            )
            reports = await colony.wait_for_worker_reports(wids, timeout=timeout or 600.0)
            if not reports:
                return {"status": "failed", "error": "no report from worker", "data": {}}
            return reports[0]

        # ---- load + validate the script SYNCHRONOUSLY ---------------------
        # Catch the common failures (syntax, bad import, undefined
        # name at module scope, missing meta/run) BEFORE returning, so the queen
        # gets the real error in the tool result instead of an optimistic
        # "started" for a playbook that never actually ran.
        from framework.host.playbook import PlaybookRun, PlaybookScriptError

        run_id = batch_id
        run = PlaybookRun(
            dispatch_one=dispatch_one,
            query_rows=query_rows,
            run_id=run_id,
            concurrency_cap=None,  # set from meta after load (queen-declared)
        )
        try:
            run.load(script)
        except PlaybookScriptError as exc:
            concise, tb = _error_detail(exc)
            logger.error("run_playbook %s did NOT load: %s\n%s", run_id, concise, tb)
            return json.dumps(
                {
                    "status": "failed",
                    "run_id": run_id,
                    "error": f"playbook did not start — {concise}",
                    "traceback": tb,
                }
            )

        # ---- persist the script to colony scope (this is how resume works) --
        # Re-running is resume: re-invoke this SAME script over the current
        # tracker and done rows are skipped. An inline script is saved to the
        # colony library (playbooks/<meta-name>.play.py) so the queen can re-run
        # it BY NAME and edit it to iterate, across turns and sessions. When it
        # came from a path/name it already lives there.
        if source_path:
            saved_path: str | None = source_path
        else:
            _saved = _persist_script(binding.dir, (run._meta or {}).get("name") or run_id, script)
            saved_path = str(_saved) if _saved else None
        saved_name = (run._meta or {}).get("name")

        # ---- concurrency: queen-declared, honored, rejected only if too big ----
        concurrency, cerr = _resolve_concurrency(run._meta or {})
        if cerr is not None:
            return json.dumps({"status": "failed", "run_id": run_id, "error": cerr})
        run._concurrency_cap = concurrency  # chunk defaults to this; converge honors it

        # Honor it: raise the colony's effective cap so the scheduler admits this
        # many at once (never LOWER — that would starve other colony work). The
        # per-run chunk semaphore (= concurrency) is the actual limiter; restored
        # when the run finishes (fast path + background).
        def _restore_cap() -> None:
            if colony_config is not None and original_colony_cap is not None:
                colony_config.max_concurrent_workers = original_colony_cap

        if colony_config is not None and original_colony_cap is not None:
            colony_config.max_concurrent_workers = max(original_colony_cap, concurrency)

        # ---- run, with a fast-result grace window -------------------------
        # Faithfulness: most playbook failures (a NameError in run(), a bad
        # tracker query, a bad import) happen in milliseconds — before any
        # worker is dispatched. Await the run briefly: if it FAILS or COMPLETES
        # within the grace window, return the real outcome to the queen now. Only
        # a genuinely long run (dispatching workers, awaiting reports) falls
        # through to "started" + the [PLAYBOOK_COMPLETE] callback.
        task = asyncio.create_task(run.run_loaded(args), name=f"playbook:{run_id}")
        _PLAYBOOK_TASKS.add(task)
        done, _pending = await asyncio.wait({task}, timeout=_FAST_RESULT_GRACE_S)

        if task in done:
            _PLAYBOOK_TASKS.discard(task)
            _restore_cap()
            exc = task.exception()
            if exc is not None:
                concise, tb = _error_detail(exc)
                logger.error("run_playbook %s failed: %s\n%s", run_id, concise, tb)
                await _record_run(binding.dir, run_id, out=None, error=tb)
                return json.dumps(
                    {
                        "status": "failed",
                        "run_id": run_id,
                        "error": f"playbook failed — {concise}",
                        "traceback": tb,
                        "log_db": str(log_db_path),
                    }
                )
            out = task.result()
            await _record_run(binding.dir, run_id, out=out, error=None)
            dead = out.get("deadletter") or []
            result_payload: dict[str, Any] = {
                "status": "completed",
                "run_id": run_id,
                "concurrency": concurrency,
                "dispatched": out.get("dispatched", 0),
                "dead_lettered": len(dead),
                "result": out.get("result"),
                "log_db": str(log_db_path),
                "playbook_name": saved_name,  # re-run via run_playbook(playbook_name=…) to resume the gap
                "playbook_path": saved_path,
            }
            hint = _zero_dispatch_hint(out)
            if hint is not None:
                result_payload["hint"] = hint
            return json.dumps(result_payload)

        # Track it so the queen can check / stop it by run_id.
        _RUNNING_PLAYBOOKS[run_id] = {"task": task, "run": run, "colony": colony}

        # Still running — finish in the background and notify on completion.
        async def _finish() -> None:
            try:
                out = await task
                await _record_run(binding.dir, run_id, out=out, error=None)
                await _notify_complete(session, run_id, out=out, error=None, log_db=str(log_db_path))
            except asyncio.CancelledError:  # stopped via stop_playbook
                logger.info("run_playbook %s stopped by request", run_id)
                await _record_run(binding.dir, run_id, out=None, error="stopped by stop_playbook")
                await _notify_complete(session, run_id, out=None, error="stopped by request", log_db=str(log_db_path))
            except Exception as exc:  # surface any failure to the queen, not the void
                concise, tb = _error_detail(exc)
                logger.error("run_playbook %s failed (background): %s\n%s", run_id, concise, tb)
                await _record_run(binding.dir, run_id, out=None, error=tb)
                await _notify_complete(session, run_id, out=None, error=concise, log_db=str(log_db_path))
            finally:
                _restore_cap()
                _RUNNING_PLAYBOOKS.pop(run_id, None)
                _PLAYBOOK_TASKS.discard(task)

        finish_task = asyncio.create_task(_finish(), name=f"playbook-finish:{run_id}")
        _PLAYBOOK_TASKS.add(finish_task)
        finish_task.add_done_callback(_PLAYBOOK_TASKS.discard)

        return json.dumps(
            {
                "status": "started",
                "run_id": run_id,
                "concurrency": concurrency,
                "log_db": str(log_db_path),
                "playbook_name": saved_name,
                "playbook_path": saved_path,
                "message": (
                    f"Playbook is dispatching workers in the background, {concurrency} "
                    "at a time (your meta['concurrency']). Routine outcomes (retry, "
                    "dead-letter) are handled by the convergence loop; you'll receive a "
                    "[PLAYBOOK_COMPLETE] notification when it finishes (status=done or "
                    f"error). Check progress anytime with get_playbook_status(run_id='{run_id}') "
                    f"or kill it with stop_playbook(run_id='{run_id}'). Saved to the colony "
                    f"library as '{saved_name}' — TO RESUME (after a stop, or after editing "
                    f"{saved_path}), call run_playbook(playbook_name='{saved_name}'); done rows "
                    "are skipped."
                ),
            }
        )

    _tool = Tool(
        name="run_playbook",
        description=(
            "Run a colony playbook — a deterministic Python script that drives a "
            "tracker table to convergence: query the undone work, dispatch "
            "workers on it, re-query, repeat. Use it whenever the goal has row "
            "shape; reach for run_worker only for one-off heterogeneous tasks. "
            "ASYNC: returns a run_id immediately and notifies you via "
            "[PLAYBOOK_COMPLETE]; the convergence loop absorbs routine worker "
            "outcomes. Re-running is resume — done rows drop out of the pending "
            "query, so a second run only does the gap.\n\n"
            "SUPPLY THE SCRIPT (exactly one):\n"
            "• `playbook` — inline; saved to the colony library at "
            "playbooks/<meta-name>.play.py (returned as name+path).\n"
            "• `playbook_name` — run a saved playbook by meta name (the normal "
            "way to resume or re-run).\n"
            "• `playbook_path` — a script file on disk.\n"
            "Iterate by editing the saved file (or re-sending inline with the "
            "same meta name, which overwrites) and re-running by name.\n\n"
            "SCRIPT SHAPE: define `meta` (name, description, optional "
            f"`concurrency` = workers running at once; default "
            f"{_DEFAULT_PLAYBOOK_CONCURRENCY}, max {_MAX_PLAYBOOK_CONCURRENCY}; "
            "lanes throttle per-account within it) and `async def run(args)`. "
            "Injected in-script functions (NOT tools): converge / worker / "
            "tracker_query / tracker_count / lane / deadletter / log / phase. "
            "There is no mid-run escalation — a worker unsure about a row "
            "records that on the row (e.g. status='needs_review') for you to "
            "review after the run.\n\n"
            "Give every worker() a `goal` — one sentence in plain end-user "
            "language saying what that worker is doing; the UI shows it as "
            "the worker's title (it is not shown to the worker).\n\n"
            "THE WORK-LIST: `pending()` returns one dict per worker dispatch. "
            "For cheap-per-row work (most campaigns), each dict should be a "
            "CHUNK of 5-10 rows grouped in plain Python — every worker pays a "
            "~2-3k-token orientation tax before its first useful action, so "
            "one-row-per-worker multiplies that tax by N. Reserve one-row "
            "dispatches for rows that are individually large jobs. Chunking and "
            "convergence compose: done rows drop out of the next round's query "
            "and stragglers re-group. Give a chunked worker a `timeout` covering "
            "the whole slice, and a task string telling it to process rows as "
            "consecutive tool calls, upserting each row right after acting on "
            "it — rate pacing happens inside the tool layer, so a worker never "
            "needs a turn per row and a partial slice re-queues cleanly.\n\n"
            "CONTRACT — get these right or the playbook silently dispatches 0 "
            "workers:\n"
            "• tracker_query(sql) / tracker_count(sql) are SYNCHRONOUS — no "
            "await. tracker_query returns a LIST OF ROW DICTS; index a row's "
            "column (row['url']). A SELECT COUNT(*) is for counting — never the "
            "pending list.\n"
            "• converge(...) and worker(...) are ASYNC: `await converge("
            "pending=..., dispatch=lambda unit, i: worker(...))` — converge "
            "awaits the worker coroutines and owns parallelism. worker() in a "
            "bare loop without await dispatches NOTHING; `for u in units: await "
            "worker(...)` runs serially and defeats meta['concurrency']. "
            "Parallel dispatch happens ONLY through converge.\n\n"
            "EXAMPLE (chunked — the default for cheap-per-row work):\n"
            '  meta = {"name": "enrich", "description": "...", "concurrency": 4}\n'
            '  RECEIPT = {"type":"object","required":["processed"],'
            '"properties":{"processed":{"type":"array"}}}\n'
            "  CHUNK = 8\n"
            "  async def run(args):\n"
            "      def pending():\n"
            "          rows = tracker_query("
            '"SELECT id, url FROM leads WHERE done_at IS NULL")\n'
            "          return [{\"ids\": [r['id'] for r in rows[i:i+CHUNK]],\n"
            "                   \"urls\": [r['url'] for r in rows[i:i+CHUNK]]}\n"
            "                  for i in range(0, len(rows), CHUNK)]\n"
            "      await converge(\n"
            "          pending=pending,\n"
            "          dispatch=lambda chunk, i: worker(\n"
            '              task=f"Enrich EACH of these, upserting its row + done_at '
            "as you go: {chunk['urls']}\",\n"
            "              goal=f\"Researching {len(chunk['ids'])} leads' websites\",\n"
            '              profile="acct-1", skill="enrich", schema=RECEIPT,\n'
            "              timeout=120 * len(chunk['ids'])),\n"
            "          max_rounds=3)\n"
            '      return {"remaining": tracker_count('
            '"SELECT 1 FROM leads WHERE done_at IS NULL")}'
        ),
        parameters={
            "type": "object",
            "properties": {
                "playbook": {
                    "type": "string",
                    "description": (
                        "Inline playbook script (Python). Saved to the colony "
                        "library at playbooks/<meta-name>.play.py. Pass exactly "
                        "one of playbook / playbook_name / playbook_path."
                    ),
                },
                "playbook_name": {
                    "type": "string",
                    "description": (
                        "Re-run a SAVED playbook by its meta name (the colony "
                        "library) — the normal way to resume or re-run without "
                        "re-sending the script."
                    ),
                },
                "playbook_path": {
                    "type": "string",
                    "description": "Path to a playbook script file on disk.",
                },
                "args": {
                    "type": "object",
                    "description": "Optional JSON object passed to the script's run(args) entrypoint.",
                },
            },
        },
    )
    registry.register("run_playbook", _tool, lambda inputs: run_playbook(**inputs))

    async def get_playbook_status(*, run_id: str) -> str:
        """Status of a playbook run by run_id — live if running, else the run-log."""
        entry = _RUNNING_PLAYBOOKS.get(run_id)
        if entry is not None:
            run = entry["run"]
            return json.dumps(
                {
                    "status": "running",
                    "run_id": run_id,
                    "dispatched": getattr(run, "dispatched", 0),
                    "dead_lettered": run.deadletter.size if hasattr(run, "deadletter") else 0,
                    "phase": getattr(run, "_phase", None),
                    "recent_log": (getattr(run, "logs", []) or [])[-10:],
                }
            )
        # Not running — look it up in the run-log (finished or never-started).
        from framework.host.colony_db import list_playbook_runs

        db_path, derr = _resolve_log_db(session)
        if derr is None:
            rows = await asyncio.to_thread(list_playbook_runs, db_path, limit=200)
            match = [r for r in rows if r.get("run_id") == run_id]
            if match:
                return json.dumps({"status": "finished", **match[0]})
        return json.dumps({"status": "not_found", "run_id": run_id})

    _status_tool = Tool(
        name="get_playbook_status",
        description=(
            "Check a playbook run by its run_id (the handle run_playbook returned). "
            "If still running, returns live progress (dispatched count, dead-lettered, "
            "phase, recent log lines). If finished, returns its run-log row. You "
            "usually DON'T need this — completion fires a [PLAYBOOK_COMPLETE] "
            "notification — use it only for an interim peek. (Use get_worker_status "
            "for an individual run_worker worker, not a playbook.)"
        ),
        parameters={
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "The playbook run_id."}},
            "required": ["run_id"],
        },
    )
    registry.register("get_playbook_status", _status_tool, lambda inputs: get_playbook_status(**inputs))

    async def stop_playbook(*, run_id: str) -> str:
        """Kill a running playbook by run_id: stop dispatching + stop its workers."""
        entry = _RUNNING_PLAYBOOKS.get(run_id)
        if entry is None:
            return json.dumps({"status": "not_running", "run_id": run_id, "message": "No running playbook with that run_id (already finished?)."})
        # Cancel the convergence loop (no more dispatch), then stop in-flight workers.
        entry["task"].cancel()
        stopped = await _stop_batch_workers(entry["colony"], run_id)
        return json.dumps(
            {
                "status": "stopped",
                "run_id": run_id,
                "workers_stopped": stopped,
                "message": (
                    "Stopped. Rows already marked done are kept; to continue, re-run "
                    "with run_playbook(playbook_name=...) — done rows are skipped (the "
                    "tracker is the resume point, so no run-id is needed)."
                ),
            }
        )

    _stop_tool = Tool(
        name="stop_playbook",
        description=(
            "Kill a RUNNING playbook by its run_id: stops the convergence loop (no "
            "more rows dispatched) and stops its in-flight workers. Use it to halt a "
            "run that's going wrong (bad protocol, burning an account). Rows already "
            "marked done are kept — re-run with run_playbook(playbook_name=...) to "
            "resume from where the tracker stands (no run-id needed; the tracker is "
            "the resume point). (Use stop_worker for an individual run_worker worker.)"
        ),
        parameters={
            "type": "object",
            "properties": {"run_id": {"type": "string", "description": "The playbook run_id to stop."}},
            "required": ["run_id"],
        },
    )
    registry.register("stop_playbook", _stop_tool, lambda inputs: stop_playbook(**inputs))

    async def list_playbook_runs_tool(*, run_id: str | None = None, limit: int = 20) -> str:
        """Read the colony's playbook run-log from colony.db."""
        from framework.host.colony_db import list_playbook_runs

        db_path, err = _resolve_log_db(session)
        if err is not None:
            return json.dumps({"error": err})
        runs = await asyncio.to_thread(list_playbook_runs, db_path, limit=max(1, int(limit)))
        if run_id:
            runs = [r for r in runs if r.get("run_id") == run_id]
        return json.dumps({"runs": runs})

    _list_tool = Tool(
        name="list_playbook_runs",
        description=(
            "Read the playbook run-log for this colony (from colony.db, the "
            "colony bookkeeping store — separate from the domain tracker). "
            "Returns recent runs most-recent-first: run_id, name, status, "
            "dispatched, dead_lettered, result, and the log narration. Pass "
            "`run_id` to fetch one run (e.g. the id run_playbook returned), or "
            "`limit` for the most recent N."
        ),
        parameters={
            "type": "object",
            "properties": {
                "run_id": {"type": "string", "description": "Fetch only this run."},
                "limit": {"type": "integer", "description": "Most recent N runs (default 20)."},
            },
        },
    )
    registry.register("list_playbook_runs", _list_tool, lambda inputs: list_playbook_runs_tool(**inputs))
    return 4  # run_playbook, get_playbook_status, stop_playbook, list_playbook_runs


def _saved_playbook_names(playbooks_dir: Path) -> list[str]:
    """Names of saved playbooks in a colony's playbooks/ dir (the library)."""
    if not playbooks_dir.exists():
        return []
    return sorted(f.name[: -len(".play.py")] for f in playbooks_dir.glob("*.play.py"))


def _resolve_script(
    playbook: str | None,
    playbook_path: str | None,
    playbook_name: str | None,
    playbooks_dir: Path,
) -> tuple[str, str | None, str | None]:
    """Resolve the script from exactly one of inline / path / saved-name.

    Returns ``(script, source_path, error)``. ``source_path`` is the on-disk
    location when loaded from a path or a saved name (None for inline).
    """
    given = [bool(playbook), bool(playbook_path), bool(playbook_name)]
    if sum(given) > 1:
        return "", None, "Pass exactly ONE of `playbook` (inline), `playbook_path`, or `playbook_name`."

    if playbook:
        return playbook, None, None

    if playbook_path:
        p = Path(playbook_path).expanduser()
        if not p.is_file():
            return "", None, f"playbook_path '{playbook_path}' does not exist or is not a file."
        try:
            return p.read_text(encoding="utf-8"), str(p), None
        except OSError as exc:
            return "", None, f"failed to read playbook_path: {exc}"

    if playbook_name:
        p = playbooks_dir / f"{_sanitize_name(playbook_name)}.play.py"
        if not p.is_file():
            saved = _saved_playbook_names(playbooks_dir)
            return "", None, (f"no saved playbook named '{playbook_name}'. Saved playbooks in this colony: {saved or '(none yet)'}.")
        try:
            return p.read_text(encoding="utf-8"), str(p), None
        except OSError as exc:
            return "", None, f"failed to read saved playbook: {exc}"

    return "", None, "Provide `playbook` (inline script), `playbook_path`, or `playbook_name`."


def _resolve_log_db(session: Any) -> tuple[Path, str | None]:
    """Resolve the path to this colony's run-log DB (colony.db)."""
    colony = getattr(session, "colony", None)
    from framework.host.colony_binding import ColonyBinding, current_binding

    binding = current_binding()
    if binding is None:
        name = getattr(session, "colony_id", None) or getattr(colony, "colony_id", None)
        if name:
            binding = ColonyBinding.for_name(str(name))
    if binding is None:
        return Path(), "no colony binding in context — this queen has not created a colony."
    return Path(binding.dir) / "colony.db", None


def _worker_tools(colony: Any) -> list[Any]:
    """Colony tools minus queen-only tools — so spawned workers can't recurse
    into run_playbook / run_worker / phase switches."""
    try:
        from framework.server.routes_execution import _resolve_queen_only_tools

        queen_only = set(_resolve_queen_only_tools())
    except Exception:
        queen_only = set()
    # Belt-and-suspenders: never hand a worker the orchestration tools.
    queen_only |= {
        "run_playbook",
        "run_worker",
        "list_playbook_runs",
        "get_playbook_status",
        "stop_playbook",
    }
    colony_tools = list(getattr(colony, "_tools", []) or [])
    return [t for t in colony_tools if getattr(t, "name", None) not in queen_only]


async def _record_run(colony_dir_path: Any, run_id: str, *, out: dict[str, Any] | None, error: str | None) -> None:
    """Persist the run-log to the colony bookkeeping DB (colony.db) — separate
    from the domain tracker. Observability only; best-effort."""
    from pathlib import Path

    from framework.host.colony_db import record_playbook_run

    db_path = Path(colony_dir_path) / "colony.db"
    try:
        if error is not None:
            await asyncio.to_thread(
                record_playbook_run,
                db_path,
                run_id=run_id,
                name=None,
                status="error",
                error=error,
            )
            return
        out = out or {}
        meta = out.get("meta") or {}
        await asyncio.to_thread(
            record_playbook_run,
            db_path,
            run_id=run_id,
            name=meta.get("name"),
            status="done",
            dispatched=out.get("dispatched", 0),
            dead_lettered=len(out.get("deadletter") or []),
            result=out.get("result"),
            logs=out.get("logs") or [],
        )
    except Exception:
        logger.exception("run_playbook %s: failed to persist run-log to colony.db", run_id)


def _get_queen_loop(session: Any) -> Any:
    """The queen's AgentLoop, for completion injection (mirrors run_worker)."""
    try:
        queen_executor = getattr(session, "queen_executor", None)
        node_registry = getattr(queen_executor, "node_registry", None)
        if isinstance(node_registry, dict):
            return node_registry.get("queen")
    except Exception:
        logger.debug("run_playbook: could not resolve queen loop for notification", exc_info=True)
    return None


async def _notify_complete(
    session: Any,
    run_id: str,
    *,
    out: dict[str, Any] | None,
    error: str | None,
    log_db: str | None = None,
) -> None:
    """Inject a [PLAYBOOK_COMPLETE] turn into the queen's loop (the callback)."""
    queen_loop = _get_queen_loop(session)
    if queen_loop is None:
        logger.warning("run_playbook %s: no queen loop; completion not surfaced", run_id)
        return
    log_line = f"<log_db>{log_db}</log_db>\n" if log_db else ""
    if error is not None:
        msg = f"[PLAYBOOK_COMPLETE]\n<run_id>{run_id}</run_id>\n<status>error</status>\n{log_line}<error>{error}</error>"
    else:
        out = out or {}
        result = out.get("result")
        dead = out.get("deadletter") or []
        # A tail of the narration so the queen sees progress even if she wasn't
        # watching; the full run-log persists to colony.db.
        log_tail = (out.get("logs") or [])[-10:]
        log_block = "\n".join(log_tail)
        hint = _zero_dispatch_hint(out)
        hint_line = f"<hint>{hint}</hint>\n" if hint else ""
        msg = (
            "[PLAYBOOK_COMPLETE]\n"
            f"<run_id>{run_id}</run_id>\n"
            "<status>done</status>\n"
            f"{log_line}"
            f"<dispatched>{out.get('dispatched', 0)}</dispatched>\n"
            f"<dead_lettered>{len(dead)}</dead_lettered>\n"
            f"<result>{json.dumps(result, default=str)}</result>\n"
            f"{hint_line}"
            f"<log_tail>\n{log_block}\n</log_tail>"
        )
    try:
        await queen_loop.inject_event(msg)
    except Exception:
        logger.exception("run_playbook %s: failed to inject completion notification", run_id)
