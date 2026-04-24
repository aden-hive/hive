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


class WorkerStatus(StrEnum):
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


@dataclass
class WorkerInfo:
    id: str
    task: str
    status: WorkerStatus
    started_at: float = 0.0
    result: WorkerResult | None = None


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
        colony_id: str = "",
        persistent: bool = False,
        storage_path: Path | None = None,
    ):
        self.id = worker_id
        self.task = task
        self.status = WorkerStatus.PENDING
        self._agent_loop = agent_loop
        self._context = context
        self._event_bus = event_bus
        self._colony_id = colony_id
        self._persistent = persistent
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

    @property
    def info(self) -> WorkerInfo:
        return WorkerInfo(
            id=self.id,
            task=self.task,
            status=self.status,
            started_at=self._started_at,
            result=self._result,
        )

    @property
    def is_active(self) -> bool:
        return self.status in (WorkerStatus.PENDING, WorkerStatus.RUNNING)

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
            from framework.loader.tool_registry import ToolRegistry

            ToolRegistry.set_execution_context(profile=self.id)
        except Exception:
            logger.debug(
                "Worker %s: failed to scope browser profile",
                self.id,
                exc_info=True,
            )

        try:
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
                )
                await self._emit_terminal_events(None, force_status=explicit["status"])
            else:
                self._result = WorkerResult(
                    error="Worker stopped by queen",
                    duration_seconds=duration,
                    status="stopped",
                    summary="Worker was cancelled before completion.",
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
        """Construct a WorkerResult from AgentResult + optional explicit report."""
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
            )
        # Synthesise a minimal report from AgentResult
        if agent_result.success:
            summary = f"Completed task '{self.task[:80]}' with {len(agent_result.output or {})} outputs."
            data = dict(agent_result.output or {})
        else:
            summary = f"Task '{self.task[:80]}' failed: {agent_result.error or 'unknown'}"
            data = {}
        return WorkerResult(
            output=dict(agent_result.output or {}),
            error=agent_result.error,
            tokens_used=getattr(agent_result, "tokens_used", 0),
            duration_seconds=duration,
            status=default_status,
            summary=summary,
            data=data,
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
                        "colony_id": self._colony_id,
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
                    "colony_id": self._colony_id,
                    "task": self.task,
                    "status": force_status or result.status,
                    "summary": result.summary,
                    "data": result.data,
                    "error": result.error,
                    "duration_seconds": result.duration_seconds,
                    "tokens_used": result.tokens_used,
                },
            )
        )

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
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Worker '%s' background task crashed: %s",
                self.id,
                exc,
                exc_info=exc,
            )

    async def stop(self) -> None:
        """Cancel the worker's background task, if any."""
        if self._persistent:
            # Signal the input loop to exit cleanly first
            await self._input_queue.put(None)
        if self._task_handle and not self._task_handle.done():
            self._task_handle.cancel()
            try:
                await self._task_handle
            except asyncio.CancelledError:
                pass

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
            raise RuntimeError(
                f"seed_conversation must be called before start_background (worker {self.id} is {self.status})"
            )

        # Write parts directly to the worker's on-disk conversation store
        # so that the AgentLoop's FileConversationStore picks them up when
        # NodeConversation loads from disk. We require an explicit
        # storage_path — falling back to CWD previously caused part files
        # to leak into the process working directory.
        if self._storage_path is None:
            raise RuntimeError(
                f"seed_conversation requires storage_path to be set on "
                f"Worker {self.id}; construct Worker with storage_path=..."
            )

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
