"""Worker — a single autonomous AgentLoop clone in a colony.

Two modes:

**Ephemeral (default)**: runs a single AgentLoop execution with a task,
emits a `SUBAGENT_REPORT` event on termination (success, partial, or
failed), and terminates. Used for parallel fan-out from the overseer.

**Persistent (``persistent=True``)**: runs an initial AgentLoop execution
(usually idle, no task) and then loops forever, receiving user chat via
``inject(message)`` and pumping each message into the already-running
agent loop via ``inject_event``. Used for the colony's long-running
client-facing overseer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


async def _connected_browser_labels() -> set[str] | None:
    """Return the set of Chrome browser-profile labels whose Hive extension is
    currently connected to the bridge, or ``None`` if the bridge can't be
    probed.

    ``None`` means "unknown" — callers must NOT treat it as "nothing connected"
    (that would false-fail a worker over a transient probe miss). Mirrors the
    /profiles probe in framework.server.app and the list_browser_profiles tool;
    kept tiny and dependency-free so it can run inline at worker start.
    """
    import json
    import os

    bridge_port = int(os.environ.get("HIVE_BRIDGE_PORT", "14829"))
    for status_port in (bridge_port + 1, 9230):  # primary, then legacy
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", status_port), timeout=0.5)
            writer.write(b"GET /profiles HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
            await writer.drain()
            raw = await asyncio.wait_for(reader.read(65536), timeout=0.5)
            writer.close()
        except Exception:
            continue
        if b"\r\n\r\n" not in raw:
            continue
        try:
            data = json.loads(raw.split(b"\r\n\r\n", 1)[1])
        except Exception:
            continue
        return {p.get("label") for p in (data.get("profiles") or []) if p.get("label")}
    return None


# How long a single worker gets to unwind after its task is cancelled before we
# stop waiting and force it terminal. Bounded on purpose: one worker wedged in a
# shielded cleanup (or swallowing CancelledError) must never be able to hang the
# colony-wide stop sweep.
STOP_TIMEOUT_SEC = 10.0


class WorkerStatus(StrEnum):
    # QUEUED: task spec is registered but no AgentLoop has started yet —
    # the colony's max_concurrent_workers cap is currently saturated and
    # this worker is waiting in ColonyRuntime._pending_queue for capacity.
    # Promotes to PENDING when a running peer terminates.
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class WorkerResult:
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    tokens_used: int = 0
    duration_seconds: float = 0.0
    # New: structured report fields. Populated by report_to_parent tool or
    # synthesised from AgentResult on termination.
    status: str = "success"  # "success" | "partial" | "failed" | "timeout" | "stopped"
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    # Cumulative tool calls the worker actually dispatched. Feeds colony
    # budget adaptation (successful workers' consumption sets the norm)
    # and the queen-facing "tool_calls: M/N" rendering.
    tool_calls_used: int = 0
    # True when the framework cut this worker off via the lifetime
    # tool-call budget (budget-triggered grace). Such results are censored
    # observations — the adaptation sampler must exclude them so cut-off
    # workers exert zero downward force on the colony norm.
    budget_limited: bool = False


@dataclass
class WorkerInfo:
    id: str
    task: str
    status: WorkerStatus
    started_at: float = 0.0
    result: WorkerResult | None = None
    # Name of the colony's worker profile this worker was spawned from.
    # Empty for legacy / single-template colonies. Surfaced in the UI so
    # the user can see "Worker w_42 in colony X is using profile slack-work"
    # and reason about which authorized account this run is touching.
    profile_name: str = ""
    # Batch coordinates copied off the underlying ``Worker``. Empty/zero
    # for solo spawns. Exposed on ``WorkerInfo`` (not just looked up off
    # the Worker via getattr) so the list endpoint can render batch
    # labels without a second lookup per row.
    batch_id: str = ""
    batch_index: int = 0
    batch_size: int = 0
    # Run-scoped dispatch sequence for playbook workers. Playbook dispatches
    # are size-1 batches that all share one batch_id, so batch_index is always
    # 1 and can't tell peers apart; this monotonic seq (minted by the playbook
    # runner) is the stable per-worker ordinal the UI badge renders. 0 for
    # non-playbook spawns, which keep using batch_index.
    worker_seq: int = 0


class Worker:
    """A single autonomous clone in a colony.

    Ephemeral mode (default):
    - PENDING → RUNNING → COMPLETED/FAILED/STOPPED, one shot, terminates.

    Persistent mode (``persistent=True``, used by the overseer):
    - PENDING → RUNNING (never transitions out by itself).
    - Receives user chat via ``inject(message)``.
    - Each injected message is pumped into the running AgentLoop via
      ``inject_event``, triggering another turn.
    """

    def __init__(
        self,
        worker_id: str,
        task: str,
        agent_loop: Any,
        context: Any,
        event_bus: Any = None,
        stream_id: str = "",
        persistent: bool = False,
        storage_path: Path | None = None,
        profile_name: str = "",
        integrations: dict[str, str] | None = None,
        browser_profile: str = "",
        batch_id: str = "",
        batch_index: int = 0,
        batch_size: int = 0,
        worker_seq: int = 0,
    ):
        self.id = worker_id
        self.task = task
        self.status = WorkerStatus.PENDING
        self._agent_loop = agent_loop
        self._context = context
        self._event_bus = event_bus
        self._stream_id = stream_id
        self._persistent = persistent
        # Worker profile binding. ``integrations`` is a {provider_id: alias}
        # map applied as default account overrides for every MCP tool call
        # this worker makes (see CredentialStoreAdapter.account_overrides).
        # An explicit ``account="..."`` arg on a tool call still wins.
        self._profile_name = profile_name
        self._integrations: dict[str, str] = dict(integrations or {})
        # Chrome browser-profile label this worker's browser tools target
        # (from the worker profile). Empty → the logical "default" profile,
        # preserving single-browser behaviour. Injected into browser tool calls
        # as the ``browser_profile`` CONTEXT_PARAM and used to route this
        # worker's tab-group reap to the right extension connection.
        self._browser_profile = browser_profile or "default"
        # Batch coordinates. When this worker was spawned as part of a
        # parallel fan-out (run_worker / spawn_batch), these
        # let the queen-side report formatter render index/count and
        # compute remaining-in-batch. Defaults are empty/0 for solo
        # spawns (run_agent_with_input, the persistent overseer, etc.).
        self._batch_id = batch_id
        self._batch_index = batch_index
        self._batch_size = batch_size
        # Run-scoped dispatch ordinal for playbook workers (0 otherwise).
        self._worker_seq = worker_seq
        # Colony budget adaptation exemption. Pinned workers are never
        # clamped by the colony's adaptive nominal budget and never enter
        # its sample pool. Persistent workers (the overseer) are pinned by
        # construction; ColonyRuntime pins at spawn (explicit queen
        # tool_call_lifetime_budget override, playbook dispatches) and
        # unconditionally on resume (a clamp below a resumed worker's
        # cursor-restored counter would instantly re-grace it, breaking
        # the documented resume-raise contract).
        self.budget_pinned: bool = persistent
        # Canonical on-disk home for this worker (conversations, events,
        # result.json, data). Required when seed_conversation() is used —
        # we deliberately do NOT fall back to CWD, which previously caused
        # conversation parts to leak into the process working directory.
        self._storage_path: Path | None = Path(storage_path) if storage_path is not None else None
        self._task_handle: asyncio.Task | None = None
        self._started_at: float = 0.0
        self._result: WorkerResult | None = None
        self._input_queue: asyncio.Queue[str | None] = asyncio.Queue()
        # Set by AgentLoop when the worker's LLM calls ``report_to_parent``.
        # Takes precedence over the synthesised report from AgentResult.
        self._explicit_report: dict[str, Any] | None = None
        # Back-reference so AgentLoop's report_to_parent handler can call
        # record_explicit_report on the owning Worker. The agent_loop's
        # _owner_worker attribute is set here during construction.
        if agent_loop is not None:
            agent_loop._owner_worker = self

        # Reap-timeline timestamps (time.monotonic()) used by the
        # /reap-timeline introspection endpoint to verify the SUBAGENT_REPORT
        # → done-callback → browser-reap ordering end-to-end. None until the
        # corresponding hook fires; see _emit_terminal_events,
        # _on_task_done, _schedule_browser_reap.
        self._report_published_at: float | None = None
        self._done_callback_at: float | None = None
        self._reap_scheduled_at: float | None = None
        self._reap_completed_at: float | None = None
        self._reap_result: dict[str, Any] | None = None

    @property
    def info(self) -> WorkerInfo:
        return WorkerInfo(
            id=self.id,
            task=self.task,
            status=self.status,
            started_at=self._started_at,
            result=self._result,
            profile_name=self._profile_name,
            batch_id=self._batch_id,
            batch_index=self._batch_index,
            batch_size=self._batch_size,
            worker_seq=self._worker_seq,
        )

    @property
    def is_active(self) -> bool:
        # QUEUED workers are "active" in the batch-tracking sense: their
        # eventual report is still pending, so the queen-side
        # batch_remaining counter must include them.
        return self.status in (
            WorkerStatus.QUEUED,
            WorkerStatus.PENDING,
            WorkerStatus.RUNNING,
        )

    @property
    def is_queued(self) -> bool:
        return self.status == WorkerStatus.QUEUED

    @property
    def batch_id(self) -> str:
        """Batch identifier (set by spawn_batch). Empty for solo spawns."""
        return self._batch_id

    @property
    def batch_index(self) -> int:
        """1-based position of this worker in its batch. 0 for solo spawns."""
        return self._batch_index

    @property
    def batch_size(self) -> int:
        """Total tasks in this worker's batch. 0 for solo spawns."""
        return self._batch_size

    @property
    def worker_seq(self) -> int:
        """Run-scoped dispatch ordinal for playbook workers. 0 otherwise."""
        return self._worker_seq

    @property
    def output_file(self) -> str:
        """Filesystem path to this worker's conversation transcript dir.

        Returns the empty string if the worker has no on-disk storage
        (legacy or in-memory-only spawns). When set, points at
        ``{storage}/conversations/parts/`` — the dir holding the
        per-message JSON parts. The queen can list this dir or read
        the latest part to inspect what the worker actually did.
        """
        if self._storage_path is None:
            return ""
        return str(self._storage_path / "conversations" / "parts")

    @property
    def is_persistent(self) -> bool:
        return self._persistent

    @property
    def agent_loop(self) -> Any:
        """The wrapped AgentLoop. Used by the SessionManager chat path."""
        return self._agent_loop

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> WorkerResult:
        """Entry point for the worker's background task.

        Ephemeral workers run ``AgentLoop.execute`` once and terminate,
        emitting a ``SUBAGENT_REPORT`` event.

        Persistent workers run the initial execute then loop forever
        processing injected user messages.
        """
        self.status = WorkerStatus.RUNNING
        self._started_at = time.monotonic()

        # Scope browser profile (and any other CONTEXT_PARAMS) to this
        # worker. asyncio.create_task() copies the parent's contextvars,
        # so without this override every spawned worker inherits the
        # queen's `profile=<queen_session_id>` and its browser_* tool
        # calls end up driving the queen's Chrome tab group. Setting
        # it here (inside the new Task's context) shadows the parent
        # value without affecting the queen's ongoing calls.
        try:
            from framework.host.colony_binding import ColonyBinding
            from framework.loader.tool_registry import ToolRegistry

            ctx = self._context
            agent_id = getattr(ctx, "agent_id", None) or self.id
            session_id = getattr(ctx, "session_id", None) or self.id
            # input_data carries the queen-resolved colony binding (built
            # by ``fork_session_into_colony`` and re-stamped per spawn by
            # ``run_worker``). It is the authoritative source
            # for "which colony does this worker belong to" — distinct
            # from AgentContext.colony_id (the event-bus scope, = queen
            # session.id for DM sessions). Without binding propagation,
            # tracker_query / tracker_upsert have no DB to target and
            # workers couldn't see tables the queen registered.
            input_data = getattr(ctx, "input_data", None) or {}
            binding = ColonyBinding.from_dict(input_data.get("binding")) if isinstance(input_data, dict) else None
            # See queen_orchestrator._queen_loop for the rationale on
            # usage_agent_id. Workers must live in a colony, so the cloud
            # identity is "worker_{colony_id}_{suffix}" — the suffix
            # disambiguates parallel peers in the same batch so each
            # worker shows up as its own row in cloud usage logs.
            # Playbook dispatches are size-1 batches, so batch_index is always 1
            # and can't disambiguate peers. The playbook runner instead stamps a
            # run-scoped monotonic ``worker_seq`` (framework.tools.playbook_tools)
            # — prefer it for both the usage suffix and the display badge.
            worker_seq = self._worker_seq or None
            if binding:
                if worker_seq is not None:
                    suffix = str(worker_seq)
                elif self._batch_index:
                    suffix = str(self._batch_index)
                else:
                    suffix = agent_id.rsplit("_", 1)[-1][:6]
                usage_agent_id = f"worker_{binding.name}_{suffix}"
            else:
                usage_agent_id = agent_id
            # Human-readable label for browser tab groups / the bridge side
            # panel. A worker belongs to a colony, so the colony name (plus a
            # batch index to disambiguate parallel peers) is the meaningful
            # label; profile stays the session id. Best-effort, cosmetic only.
            profile_display_name: str | None = None
            if binding is not None:
                from framework.utils.text import humanize_slug

                colony_label = humanize_slug(binding.name)
                profile_display_name = colony_label
                if worker_seq is not None:
                    profile_display_name = f"{colony_label} · #{worker_seq}"
                elif self._batch_index:
                    profile_display_name = f"{colony_label} · worker {self._batch_index}"
            elif self._profile_name:
                profile_display_name = self._profile_name
            exec_ctx_fields: dict[str, Any] = {
                "profile": self.id,
                "agent_id": agent_id,
                "session_id": session_id,
                "usage_agent_id": usage_agent_id,
            }
            # NB: browser_profile is intentionally NOT injected here. It is now a
            # VISIBLE browser-tool parameter the agent passes explicitly (the
            # task tells it which profile). Injecting it as a hidden CONTEXT_PARAM
            # both hid it from the schema and overrode any agent-supplied value —
            # which is exactly why workers always ran on the default profile. The
            # worker's bound profile (self._browser_profile) is still used for the
            # pre-flight availability check and the tab-group reap below.
            # Loose-optimistic default cwd for terminal tools (the worker's
            # session dir). Omitted when this worker has no filesystem storage.
            if self._storage_path is not None:
                exec_ctx_fields["session_cwd"] = str(self._storage_path)
            if profile_display_name:
                exec_ctx_fields["profile_display_name"] = profile_display_name
            if binding is not None:
                exec_ctx_fields["binding"] = binding
                # Flat colony_id so it can cross into MCP tools as a CONTEXT_PARAM
                # (the ColonyBinding object itself isn't JSON-serializable).
                exec_ctx_fields["colony_id"] = binding.name
            # Acting identity for the CRM, derived from the two fields above and
            # stamped here so it reaches the `hive-crm` CLI subprocess (which has
            # no execution context of its own) as a CONTEXT_PARAM. The CRM package
            # is optional — its absence or failure must NOT abort execution-context
            # stamping, which the tracker binding depends on (without the binding
            # on the contextvar, worker tracker tools can't resolve the colony DB).
            try:
                from framework.crm.principal import for_agent as _principal_for

                principal = _principal_for(agent_id, binding.name if binding is not None else None)
                if principal:
                    exec_ctx_fields["principal"] = principal
            except Exception:
                logger.debug("Worker %s: CRM principal lookup unavailable", self.id, exc_info=True)
            ToolRegistry.set_execution_context(**exec_ctx_fields)
        except Exception:
            logger.debug(
                "Worker %s: failed to scope execution context",
                self.id,
                exc_info=True,
            )

        # Pre-flight: "should not even be attempted." A worker bound to a
        # SPECIFIC Chrome browser profile fails fast when that profile's
        # extension isn't connected — otherwise its browser tools error on
        # every call and the agent burns the whole timeout retrying (the
        # 600s-hang symptom). Best-effort: an unreachable bridge probe returns
        # None ("unknown") → we proceed and let the tool layer's instant
        # fail-fast handle it. "default"/unbound workers are untouched.
        _bp = (self._browser_profile or "").strip()
        if _bp and _bp != "default":
            try:
                _connected = await _connected_browser_labels()
            except Exception:
                _connected = None
            if _connected is not None and _bp not in _connected:
                self.status = WorkerStatus.FAILED
                duration = time.monotonic() - self._started_at
                _avail = ", ".join(sorted(_connected)) or "none"
                self._result = WorkerResult(
                    error=f"browser profile '{_bp}' not connected",
                    duration_seconds=duration,
                    status="failed",
                    summary=(
                        f"Not attempted: the Chrome profile '{_bp}' this worker is bound to has "
                        f"no connected Hive extension. Open that Chrome profile, enable the Hive "
                        f"Browser Bridge extension, and label it '{_bp}' in the side panel, then "
                        f"re-dispatch. Connected browser profiles right now: {_avail}."
                    ),
                )
                await self._emit_terminal_events(None, force_status="failed")
                return self._result

        # Pin MCP tool calls to this worker's profile-bound aliases. Empty
        # mapping is a no-op so ephemeral workers and legacy single-profile
        # colonies are unaffected. The contextvar is propagated to all
        # awaited child coroutines, so every tool invocation downstream of
        # ``execute`` sees the binding without further plumbing.
        from aden_tools.credentials.store_adapter import account_overrides

        try:
            with account_overrides(self._integrations):
                result = await self._agent_loop.execute(self._context)
            duration = time.monotonic() - self._started_at

            if result.success:
                self.status = WorkerStatus.COMPLETED
                self._result = self._build_result(result, duration, default_status="success")
            else:
                self.status = WorkerStatus.FAILED
                self._result = self._build_result(result, duration, default_status="failed")

            await self._emit_terminal_events(result)

            if self._persistent:
                # Persistent worker: keep the loop alive, pump injected
                # messages forever. Status stays RUNNING; info reflects
                # current progress.
                self.status = WorkerStatus.RUNNING
                await self._persistent_input_loop()

            return self._result  # type: ignore[return-value]

        except asyncio.CancelledError:
            self.status = WorkerStatus.STOPPED
            duration = time.monotonic() - self._started_at
            # Preserve any explicit report the worker's LLM already filed
            # via ``report_to_parent`` before being cancelled — the caller
            # cares about that payload even on a hard stop. Only fall back
            # to the canned "stopped" message when no explicit report exists.
            explicit = self._explicit_report
            if explicit is not None:
                self._result = WorkerResult(
                    error="Worker stopped by queen after reporting",
                    duration_seconds=duration,
                    status=explicit["status"],
                    summary=explicit["summary"],
                    data=explicit["data"],
                    tool_calls_used=self._loop_tool_calls_used(),
                    budget_limited=self._loop_budget_limited(),
                )
                await self._emit_terminal_events(None, force_status=explicit["status"])
            else:
                self._result = WorkerResult(
                    error="Worker stopped by queen",
                    duration_seconds=duration,
                    status="stopped",
                    summary="Worker was cancelled before completion.",
                    tool_calls_used=self._loop_tool_calls_used(),
                    budget_limited=self._loop_budget_limited(),
                )
                await self._emit_terminal_events(None, force_status="stopped")
            return self._result

        except Exception as exc:
            self.status = WorkerStatus.FAILED
            duration = time.monotonic() - self._started_at
            self._result = WorkerResult(
                error=str(exc),
                duration_seconds=duration,
                status="failed",
                summary=f"Worker crashed: {exc}",
                tool_calls_used=self._loop_tool_calls_used(),
                budget_limited=self._loop_budget_limited(),
            )
            logger.error("Worker %s failed: %s", self.id, exc, exc_info=True)
            await self._emit_terminal_events(None, force_status="failed")
            return self._result

    async def _persistent_input_loop(self) -> None:
        """Pump injected messages into the running AgentLoop forever.

        Each ``inject(msg)`` call puts a string on ``_input_queue``. This
        loop awaits it and calls ``agent_loop.inject_event(msg)`` which
        wakes the loop's pending user-input gate.
        """
        while True:
            msg = await self._input_queue.get()
            if msg is None:
                # Sentinel: shutdown
                return
            try:
                await self._agent_loop.inject_event(msg, is_client_input=True)
            except Exception:
                logger.exception(
                    "Overseer %s: inject_event failed for injected message",
                    self.id,
                )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _loop_tool_calls_used(self) -> int:
        """Read the loop's cumulative tool-call counter, tolerating loops
        that predate the public property (and None loops in tests).

        Load-bearing for the cancelled/stopped/crashed result paths, which
        build a WorkerResult without an AgentResult — without this, killed
        workers would report zero consumption.
        """
        return int(getattr(self._agent_loop, "tool_calls_used", 0) or 0)

    def _loop_budget_limited(self) -> bool:
        """Live-counter mirror of _build_result's budget_limited derivation,
        for result paths that have no AgentResult (cancelled/crashed).

        Without this, a worker that hit its (possibly colony-clamped)
        budget, reported during grace, and was then hard-stopped before
        the loop's own exit would emit budget_limited=False — admitting a
        censored sample into the colony norm and losing the queen's
        resume hint.
        """
        stats_fn = getattr(self._agent_loop, "stats", None)
        if not callable(stats_fn):
            return False
        try:
            counters = stats_fn() or {}
        except Exception:
            return False
        return int(counters.get("tool_lifetime_budget_grace", 0) or 0) > 0

    def record_explicit_report(
        self,
        status: str,
        summary: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Called by AgentLoop when the worker's LLM invokes ``report_to_parent``.

        Stores the report so that when ``run()`` reaches the termination
        block, the explicit report wins over a synthesised one.
        """
        self._explicit_report = {
            "status": status,
            "summary": summary,
            "data": data or {},
        }

    def _build_result(
        self,
        agent_result: Any,
        duration: float,
        default_status: str,
    ) -> WorkerResult:
        """Construct a WorkerResult from AgentResult + optional explicit report.

        Three outcomes:
          1. Explicit report present → use it verbatim (worker called
             ``report_to_parent``, the framework-blessed terminal channel).
          2. No explicit report, agent_result.success=True → backstop:
             the worker ran the loop to completion (likely exhausting
             max_iterations + grace_iterations) but never reported.
             Synthesise a ``partial`` report so the queen always sees
             a SUBAGENT_REPORT, and tag ``data.no_explicit_report=True``
             so queen-side logic can branch on "synthesised vs explicit".
          3. No explicit report, agent_result.success=False → keep the
             failure path's framing (worker errored out before reporting).
        """
        # Telemetry shared by all three outcomes. budget_limited comes from
        # the loop's reliability counter bumped on budget-triggered grace
        # (tool_lifetime_budget_grace) — the signal that the framework, not
        # the task, ended this worker's run.
        tool_calls_used = getattr(agent_result, "tool_calls_used", 0)
        reliability = getattr(agent_result, "reliability_stats", None) or {}
        budget_limited = reliability.get("tool_lifetime_budget_grace", 0) > 0
        explicit = self._explicit_report
        if explicit is not None:
            return WorkerResult(
                output=dict(agent_result.output or {}),
                error=agent_result.error,
                tokens_used=getattr(agent_result, "tokens_used", 0),
                duration_seconds=duration,
                status=explicit["status"],
                summary=explicit["summary"],
                data=explicit["data"],
                tool_calls_used=tool_calls_used,
                budget_limited=budget_limited,
            )
        # Synthesise a minimal report from AgentResult
        if agent_result.success:
            # Backstop: the worker exited cleanly (loop completed or
            # implicit judge ACCEPTed) but never called report_to_parent.
            # Without this synthesis the queen would see an empty result
            # for what looks like a successful worker.
            summary = (
                f"Worker terminated without calling report_to_parent. "
                f"Task: '{self.task[:80]}'. Iteration / grace budget exhausted, "
                f"or the agent yielded an empty turn."
            )
            data = dict(agent_result.output or {})
            data["no_explicit_report"] = True
            synthesised_status = "partial"
        else:
            summary = f"Task '{self.task[:80]}' failed: {agent_result.error or 'unknown'}"
            data = {"no_explicit_report": True}
            synthesised_status = default_status
        return WorkerResult(
            output=dict(agent_result.output or {}),
            error=agent_result.error,
            tokens_used=getattr(agent_result, "tokens_used", 0),
            duration_seconds=duration,
            status=synthesised_status,
            summary=summary,
            data=data,
            tool_calls_used=tool_calls_used,
            budget_limited=budget_limited,
        )

    async def _emit_terminal_events(
        self,
        agent_result: Any,
        force_status: str | None = None,
    ) -> None:
        """Emit EXECUTION_COMPLETED/FAILED AND SUBAGENT_REPORT on termination.

        Both events are published so that consumers that listen for
        either shape keep working. The SUBAGENT_REPORT carries the
        structured summary the overseer actually cares about.
        """
        if self._event_bus is None:
            return

        from framework.host.event_bus import AgentEvent, EventType

        # EXECUTION_COMPLETED / EXECUTION_FAILED (backwards-compat)
        if agent_result is not None:
            lifecycle_type = EventType.EXECUTION_COMPLETED if agent_result.success else EventType.EXECUTION_FAILED
            await self._event_bus.publish(
                AgentEvent(
                    type=lifecycle_type,
                    stream_id=self._context.stream_id or self.id,
                    node_id=self.id,
                    execution_id=self._context.execution_id or self.id,
                    data={
                        "worker_id": self.id,
                        "colony_id": self._stream_id,
                        "task": self.task,
                        "success": agent_result.success,
                        "error": agent_result.error,
                        "output_keys": (list(agent_result.output.keys()) if agent_result.output else []),
                    },
                )
            )

        # SUBAGENT_REPORT — the structured channel the overseer awaits
        result = self._result
        if result is None:
            return
        await self._event_bus.publish(
            AgentEvent(
                type=EventType.SUBAGENT_REPORT,
                stream_id=self._context.stream_id or self.id,
                node_id=self.id,
                execution_id=self._context.execution_id or self.id,
                data={
                    "worker_id": self.id,
                    "colony_id": self._stream_id,
                    "task": self.task,
                    "status": force_status or result.status,
                    "summary": result.summary,
                    "data": result.data,
                    "error": result.error,
                    "duration_seconds": result.duration_seconds,
                    "tokens_used": result.tokens_used,
                    # Tool-call consumption vs the effective lifetime budget
                    # (possibly shrunk mid-run by colony adaptation). The
                    # queen-side formatter renders "tool_calls: M/N";
                    # budget_limited flags a framework cutoff — the queen's
                    # cue that resume-with-raised-budget may be warranted.
                    "tool_calls_used": result.tool_calls_used,
                    "budget_limited": result.budget_limited,
                    "tool_call_lifetime_budget": getattr(
                        getattr(self._agent_loop, "_config", None),
                        "tool_call_lifetime_budget",
                        0,
                    ),
                    # Carried in the payload (not looked up off the worker
                    # registry) so the colony's adaptation sampler can
                    # filter pinned workers even after registry eviction.
                    "budget_pinned": self.budget_pinned,
                    # Batch coordinates so the queen-side formatter can
                    # render task_index/task_count and compute the
                    # remaining-in-batch counter from the colony's
                    # active worker registry. Empty/0 for solo spawns.
                    "batch_id": self._batch_id,
                    "batch_index": self._batch_index,
                    "batch_size": self._batch_size,
                    # On-disk path the queen can read to inspect the
                    # full worker conversation when the user asks for
                    # specifics. Empty when the worker has no storage.
                    "output_file": self.output_file,
                },
            )
        )
        # Record after the publish awaits its subscribers. EventBus.publish
        # runs handlers under asyncio.gather (with a per-handler timeout) so
        # this point is "all SUBAGENT_REPORT subscribers have completed or
        # timed out" — i.e. the queen has fully consumed the report. The
        # /reap-timeline endpoint asserts this happens before the browser
        # reap is scheduled.
        self._report_published_at = time.monotonic()

    # ------------------------------------------------------------------
    # External control
    # ------------------------------------------------------------------

    async def start_background(self) -> None:
        """Spawn the worker's run() as an asyncio background task."""
        self._task_handle = asyncio.create_task(self.run(), name=f"worker:{self.id}")
        # Surface any exception that escapes run(); without this callback
        # a crash here only becomes visible when stop() eventually awaits
        # the handle (and is silently lost if stop() is never called).
        self._task_handle.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task) -> None:
        # Stamp the moment the done-callback fires — i.e. Worker.run has
        # returned. The /reap-timeline endpoint compares this against
        # _report_published_at to confirm the report was emitted first.
        self._done_callback_at = time.monotonic()
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                logger.error(
                    "Worker '%s' background task crashed: %s",
                    self.id,
                    exc,
                    exc_info=exc,
                )
        # Reap the worker's browser tab group on every termination path
        # (completed, cancelled, crashed). Workers are 1:1 with browser
        # profiles — Worker.run sets profile=self.id — so without this
        # the Chrome tab group is orphaned when the worker dies.
        self._schedule_browser_reap()

    def _schedule_browser_reap(self) -> None:
        """Fire-and-forget close of this worker's bound browser tab group.

        Called from the sync done-callback, so the actual close (which
        awaits a bridge round-trip) has to be scheduled as a task. The
        colony also awaits a fallback sweep in ``stop_all_workers`` to
        cover the case where the loop is being shut down and these
        background tasks wouldn't get a chance to complete.
        """
        try:
            from gcu.browser.tools.lifecycle import close_profile_context
        except ImportError:
            return  # gcu browser tools not loaded in this build
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return  # event loop already gone (process shutdown)

        async def _tracked_reap() -> None:
            # Wrapper so the /reap-timeline endpoint can see when the
            # bridge round-trip actually finished. close_profile_context
            # is idempotent so the colony backstop overlapping with this
            # is harmless.
            try:
                result = await close_profile_context(self.id, reason="worker_shutdown", browser_profile=self._browser_profile or "default")
                self._reap_result = result
            except Exception as exc:
                logger.warning("Browser reap raised for worker %s: %s", self.id, exc)
                self._reap_result = {"ok": False, "error": str(exc)}
            finally:
                self._reap_completed_at = time.monotonic()

        loop.create_task(_tracked_reap(), name=f"reap-browser:{self.id}")
        self._reap_scheduled_at = time.monotonic()

    async def stop(self, *, timeout: float = STOP_TIMEOUT_SEC) -> bool:
        """Force this worker to terminate. Idempotent and time-bounded.

        Returns True if the worker exited on its own after the cancel, False if
        it had to be force-marked terminal (it swallowed the cancellation or
        overran ``timeout``) — the caller surfaces that as a wedged worker.

        Every path must converge on a TERMINAL status. Anything left
        non-terminal is an orphan: the scheduler can still promote it, and the
        UI still counts it as working.

        Three cases:

        * **QUEUED / never started** — there is no task to cancel. Previously
          this method was a silent no-op here, so the worker stayed QUEUED in
          ``_pending_queue`` and ``_drain_pending_queue`` happily *started* it
          after the user had stopped it. Mark it STOPPED instead; the colony
          dequeues it and synthesises its terminal report
          (``_cancel_queued_workers``), and the drain's ``status != QUEUED``
          guard then correctly skips it.
        * **RUNNING / PENDING** — cancel the task and await it, but BOUNDED. A
          task that swallows ``CancelledError`` (or blocks in a shielded
          cleanup) would otherwise hang this coroutine forever — and with it
          the whole stop sweep.
        * **already terminal** — no-op, so a per-worker stop and a stop-all can
          safely overlap.
        """
        if not self.is_active:
            return True

        if self._persistent:
            # Signal the input loop to exit cleanly first
            await self._input_queue.put(None)

        if self._task_handle is None:
            # Never started (queued behind the concurrency cap, or spawned but
            # not yet admitted). Nothing to cancel — just make it terminal.
            self.status = WorkerStatus.STOPPED
            return True

        if not self._task_handle.done():
            self._task_handle.cancel()

        # gather(return_exceptions=True) so the child's CancelledError comes
        # back as a value instead of propagating — we must not mistake the
        # worker's cancellation for our own.
        clean = True
        try:
            await asyncio.wait_for(
                asyncio.gather(self._task_handle, return_exceptions=True),
                timeout,
            )
        except TimeoutError:
            clean = False
            logger.warning(
                "Worker %s did not exit within %.1fs of cancel — force-stopping",
                self.id,
                timeout,
            )

        if self.is_active:
            # The task swallowed the cancel, or timed out, and never set a
            # terminal status itself. Force one so the registry converges.
            self.status = WorkerStatus.STOPPED
            clean = False
        return clean

    async def inject(self, message: str) -> None:
        """Pump a user message into the worker.

        For ephemeral workers this is rarely used (they don't take
        follow-up input). For persistent overseers this is the chat
        injection path.
        """
        await self._input_queue.put(message)

    async def seed_conversation(self, messages: list[dict[str, Any]]) -> None:
        """Pre-populate the worker's ConversationStore before starting.

        Used when forking a queen DM into a colony: the DM's prior
        conversation becomes the colony overseer's starting point so the
        overseer resumes mid-thought instead of greeting the user fresh.

        ``messages`` is a list of dicts matching the ConversationStore's
        part format: ``{seq, role, content, tool_calls, tool_use_id,
        created_at, phase}``. The caller is responsible for rewriting
        ``agent_id`` to match the new worker, and for numbering ``seq``
        monotonically from 0.

        Must be called BEFORE ``start_background``.
        """
        if self.status != WorkerStatus.PENDING:
            raise RuntimeError(f"seed_conversation must be called before start_background (worker {self.id} is {self.status})")

        # Write parts directly to the worker's on-disk conversation store
        # so that the AgentLoop's FileConversationStore picks them up when
        # NodeConversation loads from disk. We require an explicit
        # storage_path — falling back to CWD previously caused part files
        # to leak into the process working directory.
        if self._storage_path is None:
            raise RuntimeError(f"seed_conversation requires storage_path to be set on Worker {self.id}; construct Worker with storage_path=...")

        parts_dir = self._storage_path / "conversations" / "parts"
        parts_dir.mkdir(parents=True, exist_ok=True)

        import json

        for i, msg in enumerate(messages):
            msg = dict(msg)  # copy
            msg.setdefault("seq", i)
            msg.setdefault("agent_id", self.id)
            part_file = parts_dir / f"{msg['seq']:010d}.json"
            part_file.write_text(json.dumps(msg), encoding="utf-8")

        logger.info(
            "Worker %s: seeded %d messages into %s",
            self.id,
            len(messages),
            parts_dir,
        )
