"""Deterministic playbook runner — the convergence spine (design v0.4 §3, §9).

The runner executes a playbook script and exposes the orchestration hooks the
script calls. It owns no durable state: the tracker is the source of truth, so
"what's done / what's left" is always a fresh query, and re-running a playbook
is resume by construction.

Decoupling: the runner depends only on two injected async callables —

  - ``dispatch_one(task, *, data, profile, timeout) -> report_dict``
        spawn ONE worker and await its terminal report. ``report_dict`` is the
        colony's worker report shape (``status`` / ``summary`` / ``data`` /
        ``error`` / ...); ``data`` is the worker's structured receipt.
  - ``query_rows(sql) -> list[dict]``
        run a tracker SELECT and return rows as dicts.

Everything else (converge loop, retry/backoff, lanes, dead-letter, schema
validation, the exec namespace) is pure and lives here.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Injected colony callables. Tracker reads are synchronous (a local SQLite
# SELECT is sub-millisecond), so playbooks call tracker_query/tracker_count
# without ``await``; only worker dispatch is async.
DispatchOne = Callable[..., Awaitable[dict[str, Any]]]
QueryRows = Callable[[str], list[dict[str, Any]]]


class PlaybookError(Exception):
    """Base error for playbook execution."""


class PlaybookScriptError(PlaybookError):
    """The playbook script is malformed (bad ``meta``, missing ``run``, raised)."""


async def _maybe_await(value: Any) -> Any:
    """Await ``value`` if it is awaitable, else return it unchanged.

    Lets a playbook write ``pending=lambda: tracker_query(...)`` (async) or a
    plain ``pending=lambda: [...]`` (sync) and have both work in ``converge``.
    """
    if inspect.isawaitable(value):
        return await value
    return value


class DeadLetter:
    """Terminal-failure store for the queen to review. No silent drops."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def add(self, item: dict[str, Any]) -> None:
        self._items.append(item)

    def list(self) -> list[dict[str, Any]]:
        return list(self._items)

    @property
    def size(self) -> int:
        return len(self._items)

    def __len__(self) -> int:  # convenience
        return len(self._items)


class _RateGate:
    """Per-lane min-interval throttle. Spaces dispatches ``>= min_interval``
    seconds apart even when ``concurrency`` workers share the lane.

    ``rate_per_min`` is the start-rate ceiling (e.g. LinkedIn invites/DMs that
    must be paced under a weekly cap). ``acquire`` RESERVES the next slot under
    a lock — just the arithmetic — then sleeps OUTSIDE the lock. Holding the
    lock across the sleep would serialize a ``concurrency>1`` lane to
    one-at-a-time; reserving-then-sleeping lets N workers each grab a distinct,
    monotonically increasing slot and then run in parallel up to the lane
    semaphore. So this gate bounds the START rate; the semaphore bounds
    simultaneity, and the two compose.

    Uses the event loop's monotonic clock (``loop.time()``) — no wall-clock
    dependency, so it is immune to clock skew and to sandboxes that block
    ``time.time``/``Date.now``.
    """

    def __init__(self, rate_per_min: float) -> None:
        self.min_interval = 60.0 / rate_per_min
        self._next_at: float | None = None
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        loop = asyncio.get_event_loop()
        async with self._lock:
            now = loop.time()
            start = now if self._next_at is None else max(now, self._next_at)
            self._next_at = start + self.min_interval
            wait = start - now
        if wait > 0:
            await asyncio.sleep(wait)


class PlaybookRun:
    """One execution of a playbook. Holds the injected colony callables and the
    per-run state (lanes, dead-letter, logs, phase) and exposes the hooks the
    script calls."""

    def __init__(
        self,
        *,
        dispatch_one: DispatchOne,
        query_rows: QueryRows,
        run_id: str,
        default_timeout: float = 600.0,
        concurrency_cap: int | None = None,
    ) -> None:
        self._dispatch_one = dispatch_one
        self._query_rows = query_rows
        self.run_id = run_id
        self._default_timeout = default_timeout
        # The colony's max_concurrent_workers — the REAL ceiling. chunk/lanes are
        # playbook-side semaphores that cannot exceed it; we default chunk to it
        # and warn when settings imply more parallelism than it allows.
        self._concurrency_cap = concurrency_cap

        self.deadletter = DeadLetter()
        self.logs: list[str] = []
        self._lanes: dict[str, asyncio.Semaphore] = {}
        self._lane_specs: dict[str, dict[str, Any]] = {}
        # Per-lane start-rate throttle. Only populated for lanes declared with
        # rate_per_min; absent => unthrottled (back-compat with every lane that
        # passes no rate_per_min).
        self._lane_gates: dict[str, _RateGate] = {}
        self._phase: str | None = None
        # Coarse counters for the run-log / reduce.
        self.dispatched = 0
        # Set by load().
        self._meta: dict[str, Any] | None = None
        self._run_fn: Any = None

    # ---- hooks injected into the script namespace --------------------------

    def log(self, message: str) -> None:
        """Progress narration. Observational only — does NOT wake the queen."""
        text = str(message)
        self.logs.append(text)
        logger.info("[playbook %s] %s", self.run_id, text)

    def phase(self, title: str) -> None:
        """Group subsequent work under a phase label (for the run-log)."""
        self._phase = str(title)
        self.log(f"phase: {title}")

    def lane(self, name: str, *, concurrency: int = 1, rate_per_min: int | None = None) -> None:
        """Declare a per-account rate lane. ``concurrency`` bounds simultaneity
        (a semaphore); ``rate_per_min`` bounds the start-rate (a min-interval
        gate, see :class:`_RateGate`). The two compose — e.g. ``lane("acct-1",
        concurrency=1, rate_per_min=2)`` runs one worker at a time, ``>=30s``
        apart, which is what paces LinkedIn invites/DMs under their weekly cap."""
        if concurrency < 1:
            concurrency = 1
        self._lanes[name] = asyncio.Semaphore(concurrency)
        self._lane_specs[name] = {"concurrency": concurrency, "rate_per_min": rate_per_min}
        if rate_per_min is not None and rate_per_min > 0:
            self._lane_gates[name] = _RateGate(float(rate_per_min))
            self.log(f"lane '{name}': concurrency={concurrency}, rate_per_min={rate_per_min} (>= {60.0 / rate_per_min:.1f}s between dispatches)")
        cap = self._concurrency_cap
        if cap is not None and concurrency > cap:
            self.log(
                f"note: lane '{name}' concurrency={concurrency} exceeds the colony cap "
                f"({cap}) — at most {cap} of this account's workers run at once. Raise "
                f"max_concurrent_workers to go higher."
            )

    def tracker_query(self, sql: str) -> list[dict[str, Any]]:
        """Run a tracker SELECT and return rows as dicts. Synchronous — no await."""
        return self._query_rows(sql)

    def tracker_count(self, sql: str) -> int:
        """Number of rows the SELECT returns (the size of the gap). No await."""
        return len(self._query_rows(sql))

    async def worker(
        self,
        task: str,
        *,
        profile: str | None = None,
        lane: str | None = None,
        skill: str | None = None,
        retries: int = 0,
        backoff: str | None = None,
        timeout: float | None = None,
        schema: dict[str, Any] | None = None,
        phase: str | None = None,
        data: dict[str, Any] | None = None,
        goal: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch one monolithic worker job and await its receipt.

        ``goal`` — one plain-language sentence describing what this worker
        is doing, for the UI's worker title (e.g. "Checking Instagram
        profiles 13-18 for who accepts DMs"). Not shown to the worker.

        ``schema`` (if given) is the receipt contract: it rides the spawn spec to
        the worker, where it specializes ``report_to_parent``'s ``data`` parameter
        and the worker's system prompt — so the worker is TOLD the shape and the
        provider guides it there. Enforcement is worker-side; this method does NOT
        re-validate the receipt or retry on shape (a tracker-blind retry of an
        already-done, non-idempotent action is what caused duplicate work).

        Retries up to ``retries`` times on transient LIFECYCLE failure only.
        Returns ``{"status": "done"|"failed", "receipt": {...}, "attempts": n,
        "error": str|None}``. Dead-lettering is NOT done here — ``converge``
        owns it, dead-lettering whatever rows are still unresolved when it stops
        (so a permanently-failing row is recorded once, not once per round).
        """
        task_text = str(task)
        if skill:
            # The worker auto-sees colony skills in its catalog; a by-name
            # reference in the task is what activates it.
            if skill not in task_text:
                task_text = f"{task_text}\n\nFollow the '{skill}' skill."
        timeout = timeout if timeout is not None else self._default_timeout
        attempts = max(1, retries + 1)
        last_error: str | None = None
        receipt: dict[str, Any] = {}

        for attempt in range(1, attempts + 1):
            report = await self._dispatch_guarded(
                task_text,
                data=data,
                profile=profile,  # a profile IS the account binding; rotate accounts by rotating profile
                timeout=timeout,
                lane=lane,
                schema=schema,
                goal=goal,
            )
            self.dispatched += 1
            status = str(report.get("status", "unknown"))
            receipt = report.get("data") or {}
            if status == "success":
                # The receipt shape is enforced WORKER-SIDE: `schema` rides the
                # spawn spec and specializes the worker's report_to_parent tool +
                # system prompt, so a successful report already conforms. We do NOT
                # re-validate queen-side or retry on shape — a tracker-blind retry
                # on an already-completed (non-idempotent) action is exactly what
                # caused duplicate sends. Retries below are for lifecycle failures.
                return {"status": "done", "receipt": receipt, "attempts": attempt, "error": None}
            last_error = report.get("error") or f"worker status={status}"
            if attempt < attempts:
                await self._backoff_sleep(backoff, attempt)

        # Exhausted retries. Return failed — converge dead-letters the row if it
        # is still unresolved after the final round.
        return {"status": "failed", "receipt": receipt, "attempts": attempts, "error": last_error}

    async def _dispatch_guarded(
        self,
        task_text: str,
        *,
        data: dict[str, Any] | None,
        profile: str | None,
        timeout: float,
        lane: str | None,
        schema: dict[str, Any] | None = None,
        goal: str | None = None,
    ) -> dict[str, Any]:
        """Dispatch through the lane's rate gate (start-rate) then its semaphore
        (simultaneity), if declared. The gate is the OUTER throttle so spacing is
        applied before a worker occupies a concurrency slot."""
        kwargs: dict[str, Any] = {"data": data, "profile": profile, "timeout": timeout, "schema": schema}
        # Forwarded only when set — keeps older dispatch_one implementations
        # (and test fakes) with the pre-goal signature working unchanged.
        if goal is not None:
            kwargs["goal"] = goal
        gate = self._lane_gates.get(lane) if lane else None
        if gate is not None:
            await gate.acquire()  # space dispatches >= min_interval apart
        sem = self._lanes.get(lane) if lane else None
        if sem is not None:
            async with sem:  # then bound simultaneity
                return await self._dispatch_one(task_text, **kwargs)
        if lane and sem is None:
            self.log(f"warning: lane '{lane}' not declared via lane(); dispatching unthrottled")
        return await self._dispatch_one(task_text, **kwargs)

    @staticmethod
    async def _backoff_sleep(backoff: str | None, attempt: int) -> None:
        if not backoff:
            return
        if backoff == "exp":
            await asyncio.sleep(min(30.0, 2.0**attempt))
        elif backoff == "linear":
            await asyncio.sleep(min(30.0, 2.0 * attempt))
        # unknown backoff spec -> no sleep

    async def converge(
        self,
        *,
        pending: Callable[[], Any],
        dispatch: Callable[[dict[str, Any], int], Any],
        max_rounds: int = 1,
        circuit_breaker: float | None = None,
        chunk: int | None = None,
    ) -> dict[str, Any]:
        """Drive the table to convergence.

        Each round: query ``pending()`` for undone rows, dispatch one worker per
        row (``chunk`` in flight at a time), re-query. Repeat up to ``max_rounds``
        or until empty, unless ``circuit_breaker`` (failure fraction in a round)
        trips first. The runner owns no memory of which rows it did — it
        re-derives the work-list from ``pending()`` every round, which is exactly
        why re-running the whole playbook resumes for free.
        """
        cap = self._concurrency_cap
        # Fix #2: default chunk to the colony cap so a big round doesn't construct
        # a worker (AgentLoop) per row up front — only ``cap`` are ever running.
        if chunk is None and cap is not None:
            chunk = cap
        # Fix #1: tell the queen when her settings imply more parallelism than the
        # colony cap allows (silently capped otherwise).
        if cap is not None:
            lane_total = sum(s["concurrency"] for s in self._lane_specs.values())
            if (chunk is not None and chunk > cap) or lane_total > cap:
                self.log(
                    f"note: colony max_concurrent_workers={cap} bounds this run; "
                    f"chunk={chunk} / total lane concurrency={lane_total} above it "
                    f"won't increase actual parallelism — raise the colony cap to go higher."
                )

        rounds_run = 0
        for _round in range(max(1, max_rounds)):
            rows = await _maybe_await(pending())
            if not rows:
                break
            rounds_run += 1
            results = await self._dispatch_round(rows, dispatch, chunk)
            failed = sum(1 for r in results if _is_failure(r))
            self.log(f"round {rounds_run}: {len(rows)} dispatched, {len(rows) - failed} ok, {failed} failed")
            if circuit_breaker is not None and rows and (failed / len(rows)) > circuit_breaker:
                self.log(f"circuit breaker tripped: {failed}/{len(rows)} failed > {circuit_breaker:.0%}; stopping")
                break

        # Whatever is still pending when we stop is the unresolved gap —
        # dead-letter each remaining row once (the tracker is the truth; these
        # rows never reached done).
        remaining_rows = await _maybe_await(pending())
        for row in remaining_rows:
            self.deadletter.add({"row": row, "reason": f"unresolved after {rounds_run} round(s)"})
        return {
            "rounds": rounds_run,
            "converged": len(remaining_rows) == 0,
            "remaining": len(remaining_rows),
            "dead_lettered": len(remaining_rows),
        }

    async def _dispatch_round(
        self,
        rows: list[dict[str, Any]],
        dispatch: Callable[[dict[str, Any], int], Any],
        chunk: int | None,
    ) -> list[Any]:
        sem = asyncio.Semaphore(chunk) if chunk and chunk > 0 else None

        async def run_one(row: dict[str, Any], idx: int) -> Any:
            # Create + await the dispatch coroutine inside the chunk gate so we
            # never have more than ``chunk`` workers in flight.
            if sem is not None:
                async with sem:
                    return await _maybe_await(dispatch(row, idx))
            return await _maybe_await(dispatch(row, idx))

        return await asyncio.gather(
            *(run_one(row, i) for i, row in enumerate(rows)),
            return_exceptions=True,
        )

    # ---- script execution --------------------------------------------------

    def _namespace(self) -> dict[str, Any]:
        """Build the namespace the script runs in.

        The script runs in-process via ``exec`` in the colony's uv environment —
        it gets the FULL standard library and every installed package (``import
        json`` / ``re`` / ``datetime`` just work). We do NOT restrict builtins:
        ``exec`` in-process is not a security boundary (it's trivially escapable),
        so stripping builtins bought no isolation and only broke legitimate
        playbook code. The queen is a trusted author in her own process. A real
        sandbox (subprocess / RestrictedPython) would only be needed for
        UNTRUSTED playbooks — not the case here.

        Not setting ``__builtins__`` makes ``exec`` inject the real builtins.
        """
        return {
            # hooks injected on top of the full environment
            "converge": self.converge,
            "worker": self.worker,
            "tracker_query": self.tracker_query,
            "tracker_count": self.tracker_count,
            "lane": self.lane,
            "deadletter": self.deadletter,
            "log": self.log,
            "phase": self.phase,
        }

    def load(self, script: str) -> Any:
        """Compile + exec the script body and validate it. SYNCHRONOUS.

        This is the deterministic, fast part — it catches the common failure
        modes (syntax error, a bad import, an undefined name at
        module scope, missing/invalid ``meta``, missing ``run``) BEFORE any
        background work, so the tool can return a faithful error instead of an
        optimistic "started". Stores ``meta``/``run`` for ``run_loaded`` and
        returns the run callable. Raises :class:`PlaybookScriptError`.
        """
        namespace = self._namespace()
        try:
            code = compile(script, "<playbook>", "exec")
            exec(code, namespace)  # noqa: S102 - intentional script execution (see _namespace docstring)
        except Exception as exc:  # compile/exec error in the script body
            raise PlaybookScriptError(f"playbook body failed to load: {exc}") from exc

        meta = namespace.get("meta")
        if not isinstance(meta, dict) or not meta.get("name"):
            raise PlaybookScriptError("playbook must define a `meta` dict with at least a 'name'")
        run_fn = namespace.get("run")
        if not callable(run_fn):
            raise PlaybookScriptError("playbook must define `async def run(args)`")

        self._meta = meta
        self._run_fn = run_fn
        return run_fn

    async def run_loaded(self, args: Any = None) -> dict[str, Any]:
        """Execute the already-``load``ed ``run(args)``. Raises on run() failure."""
        try:
            result = self._run_fn(args)
            result = await _maybe_await(result)
        except PlaybookScriptError:
            raise
        except Exception as exc:
            raise PlaybookScriptError(f"playbook run() raised: {exc}") from exc

        return {
            "meta": self._meta,
            "result": result,
            "logs": self.logs,
            "deadletter": self.deadletter.list(),
            "dispatched": self.dispatched,
        }

    async def execute(self, script: str, args: Any = None) -> dict[str, Any]:
        """Compile + exec the script, then await its ``run(args)`` entrypoint."""
        self.load(script)
        return await self.run_loaded(args)


def _is_failure(result: Any) -> bool:
    """A round result counts as a failure if it raised, or the worker did not
    complete (status not 'done')."""
    if isinstance(result, BaseException):
        return True
    if isinstance(result, dict):
        return result.get("status") not in ("done", None)
    return False


async def run_playbook_script(
    script: str,
    *,
    args: Any = None,
    dispatch_one: DispatchOne,
    query_rows: QueryRows,
    run_id: str,
    default_timeout: float = 600.0,
    concurrency_cap: int | None = None,
) -> dict[str, Any]:
    """Convenience entrypoint: build a ``PlaybookRun`` and execute ``script``."""
    run = PlaybookRun(
        dispatch_one=dispatch_one,
        query_rows=query_rows,
        run_id=run_id,
        default_timeout=default_timeout,
        concurrency_cap=concurrency_cap,
    )
    return await run.execute(script, args)
