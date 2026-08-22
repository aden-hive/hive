"""
Event Bus - Pub/sub event system for inter-stream communication.

Allows streams to:
- Publish events about their execution
- Subscribe to events from other streams
- Coordinate based on shared state changes
"""

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import IO, Any

from framework.host.event_log import EventLogFile
from framework.host.events_policy import is_worker_local, is_worker_stream

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HIVE_DEBUG_EVENTS — write every published event to a JSONL file.
#
# Set the env var to any truthy value to enable:
#   HIVE_DEBUG_EVENTS=1          → writes to ~/.hive/event_logs/<ts>.jsonl
#   HIVE_DEBUG_EVENTS=/tmp/ev    → writes to that exact directory
#
# Each line is a full JSON serialisation of the AgentEvent.
# The file is opened lazily on first publish and flushed after every write.
# ---------------------------------------------------------------------------
_DEBUG_EVENTS_RAW = os.environ.get("HIVE_DEBUG_EVENTS", "").strip()
_DEBUG_EVENTS_ENABLED = _DEBUG_EVENTS_RAW.lower() in ("1", "true", "full") or (
    bool(_DEBUG_EVENTS_RAW) and _DEBUG_EVENTS_RAW.lower() not in ("0", "false", "")
)


def _open_event_log() -> IO[str] | None:
    """Open a JSONL event log file.  Returns None if disabled."""
    if not _DEBUG_EVENTS_ENABLED:
        return None
    raw = _DEBUG_EVENTS_RAW
    if raw.lower() in ("1", "true", "full"):
        from framework.config import HIVE_HOME

        log_dir = HIVE_HOME / "event_logs"
    else:
        log_dir = Path(raw)
    log_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = log_dir / f"{ts}.jsonl"
    logger.info("Event debug log → %s", path)
    return open(path, "a", encoding="utf-8")  # noqa: SIM115


_event_log_file: IO[str] | None = None
_event_log_ready = False  # lazy init guard


# Module-level singleton bus used for app-wide events that aren't
# scoped to a particular session — credential connect/disconnect,
# tool-catalog refreshes, tools-config changes. Anything that needs
# to fan out to every UI surface (Tool Library, integrations page,
# etc.) publishes here. Sessions still use their own per-session
# EventBus for per-session telemetry; the global bus is purely for
# cross-cutting state changes.
_global_event_bus: "EventBus | None" = None


def get_global_event_bus() -> "EventBus":
    """Return the process-wide global event bus, creating it on first use.

    Lazily-initialised so importing the module never spawns asyncio
    primitives in the wrong loop. Callers in async contexts should be
    fine — ``EventBus.__init__`` only constructs ``asyncio.Lock`` /
    ``Semaphore``, both of which bind to the current loop on first use.
    """
    global _global_event_bus
    if _global_event_bus is None:
        _global_event_bus = EventBus(max_history=200)
    return _global_event_bus


async def publish_global(event: "AgentEvent") -> None:
    """Publish ``event`` on the global bus, swallowing failures.

    The global bus is purely informational — UI surfaces refetch on
    receipt, but no business logic depends on it. Wrapping in a
    swallow-all keeps us from breaking the originating handler when
    a stray subscriber raises.
    """
    try:
        await get_global_event_bus().publish(event)
    except Exception:  # pragma: no cover — best-effort telemetry
        logger.exception("Global event publish failed for type=%s", getattr(event, "type", "?"))


class EventType(StrEnum):
    """Types of events that can be published."""

    # Execution lifecycle
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_PAUSED = "execution_paused"
    EXECUTION_RESUMED = "execution_resumed"

    # Billing / entitlement signal from the Hive LLM proxy. Emitted once
    # the moment a 402 (or equivalent) is detected, *in addition to* the
    # usual EXECUTION_FAILED that follows. The desktop client listens for
    # this and reopens the upgrade popup so the user can refresh their
    # plan without parsing free-form error strings.
    PAYMENT_REQUIRED = "payment_required"

    # State changes
    STATE_CHANGED = "state_changed"
    STATE_CONFLICT = "state_conflict"

    # Goal tracking
    GOAL_PROGRESS = "goal_progress"
    GOAL_ACHIEVED = "goal_achieved"
    CONSTRAINT_VIOLATION = "constraint_violation"

    # Stream lifecycle
    STREAM_STARTED = "stream_started"
    STREAM_STOPPED = "stream_stopped"

    # Node event-loop lifecycle
    NODE_LOOP_STARTED = "node_loop_started"
    NODE_LOOP_ITERATION = "node_loop_iteration"
    NODE_LOOP_COMPLETED = "node_loop_completed"

    # LLM streaming observability
    LLM_TEXT_DELTA = "llm_text_delta"
    LLM_REASONING_DELTA = "llm_reasoning_delta"
    LLM_TURN_COMPLETE = "llm_turn_complete"

    # Tool lifecycle
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_COMPLETED = "tool_call_completed"

    # Queen/user interaction events
    CLIENT_OUTPUT_DELTA = "client_output_delta"
    # The agent's hidden <think> reasoning for this turn. It is stripped from the
    # visible output (client_output_delta), so it is surfaced separately here for
    # monitors/UIs that want to show the grounding the agent did before speaking.
    CLIENT_REASONING = "client_reasoning"
    CLIENT_INPUT_REQUESTED = "client_input_requested"
    CLIENT_INPUT_RECEIVED = "client_input_received"
    # Emitted when a received user message is actually woven into the
    # conversation (drained), as opposed to merely received. CLIENT_INPUT_RECEIVED
    # fires at receive time — before the in-flight turn finishes — so its
    # timestamp predates the streaming deltas the message should sort after.
    # This event's timestamp is the true injection moment (the drain), letting
    # the UI position the user bubble at its real conversation seq. Correlated
    # to the received event via ``correlation_id``.
    CLIENT_INPUT_COMMITTED = "client_input_committed"

    # The agent called credentials(action="collect"): the frontend should
    # render a SECURE credential form with the carried field specs. The user's
    # secret values are POSTed straight to the store via
    # /api/sessions/{id}/credential-form — they never flow back through this
    # event or the conversation. Carries {credential_id, account, title,
    # instructions, fields, correlation_id}.
    CLIENT_CREDENTIAL_FORM_REQUESTED = "client_credential_form_requested"

    # Queen suggested forking this session into a colony. Carries the
    # proposed colony_id (auto-populated in the frontend "Create Colony"
    # popup) and an optional rationale. The frontend opens the popup with
    # the current queen pre-selected; on confirm it POSTs /api/sessions
    # with colony_id + source_session_id to drive the fork.
    COLONY_SUGGESTION_REQUESTED = "colony_suggestion_requested"

    # Internal node observability
    NODE_INTERNAL_OUTPUT = "node_internal_output"
    NODE_INPUT_BLOCKED = "node_input_blocked"
    NODE_STALLED = "node_stalled"
    NODE_TOOL_DOOM_LOOP = "node_tool_doom_loop"

    # Judge decisions (implicit judge in event loop nodes)
    JUDGE_VERDICT = "judge_verdict"

    # Retry tracking
    NODE_RETRY = "node_retry"

    # Stream-health observability. Split from NODE_RETRY so the UI can
    # distinguish "slow TTFT on a huge context" (healthy, just slow) from
    # "stream went silent mid-generation" (probable stall) from "we nudged
    # the model to continue" (recovery), which NODE_RETRY used to conflate.
    STREAM_TTFT_EXCEEDED = "stream_ttft_exceeded"
    STREAM_INACTIVE = "stream_inactive"
    STREAM_NUDGE_SENT = "stream_nudge_sent"
    # The agent loop's authoritative top-level state changed (executing /
    # awaiting_user / interrupted). Emitted by the loop itself; the session
    # snapshot reads the latest one rather than re-deriving activity.
    LOOP_STATE_CHANGED = "loop_state_changed"
    # A reminder/nudge was injected into the conversation by the
    # ReminderHub — covers idle nudges, the tool-budget advisory, the
    # stream-stall continue-nudge, and lifecycle reminders.
    REMINDER_INJECTED = "reminder_injected"
    TOOL_CALL_REPLAY_DETECTED = "tool_call_replay_detected"

    # Worker agent lifecycle
    WORKER_COMPLETED = "worker_completed"
    WORKER_FAILED = "worker_failed"

    # Context management
    CONTEXT_COMPACTION_STARTED = "context_compaction_started"
    CONTEXT_COMPACTED = "context_compacted"
    CONTEXT_USAGE_UPDATED = "context_usage_updated"

    # External triggers
    WEBHOOK_RECEIVED = "webhook_received"

    # Custom events
    CUSTOM = "custom"

    # Escalation (agent requests handoff to queen)
    ESCALATION_REQUESTED = "escalation_requested"

    # Execution resurrection (auto-restart on non-fatal failure)
    EXECUTION_RESURRECTED = "execution_resurrected"

    # Colony lifecycle (session manager → frontend)
    WORKER_COLONY_LOADED = "worker_colony_loaded"
    # The "Create Colony" popup confirmed a fork (POST /api/sessions
    # with colony_id + source_session_id); carries colony_id + path
    # so the frontend can render a system message linking to the new
    # colony page at /colony/{colony_id}.
    COLONY_CREATED = "colony_created"
    CREDENTIALS_REQUIRED = "credentials_required"

    # Queen-initiated silent session split on detected work shift.
    # Published on the OLD session bus; frontend listens and swaps to
    # the new session via URL replace (no banner, no flicker).
    # Data: {new_session_id, queen_id, from_session_id, reason}.
    SESSION_FORKED = "session_forked"

    # Queen phase changes (working <-> reviewing)
    QUEEN_PHASE_CHANGED = "queen_phase_changed"

    # Queen identity — which queen profile was selected for this session
    QUEEN_IDENTITY_SELECTED = "queen_identity_selected"

    # Subagent reports (one-way progress updates from sub-agents)
    SUBAGENT_REPORT = "subagent_report"

    # Trigger lifecycle (queen-level triggers / heartbeats)
    TRIGGER_AVAILABLE = "trigger_available"
    TRIGGER_ACTIVATED = "trigger_activated"
    TRIGGER_DEACTIVATED = "trigger_deactivated"
    TRIGGER_FIRED = "trigger_fired"
    TRIGGER_REMOVED = "trigger_removed"
    TRIGGER_UPDATED = "trigger_updated"

    # Emitted on session load when a previously-running trigger's
    # ``last_fired_at`` is older than the schedule expects — i.e. the
    # session was closed during one or more scheduled fires. The UI
    # surfaces a per-trigger handshake (fire one catch-up / skip /
    # reschedule) and POSTs the user's decisions back to
    # ``/api/sessions/{id}/colony/resolve_missed``.
    MISSED_TRIGGERS = "missed_triggers"

    # Task system lifecycle (per-list diffs streamed to the UI)
    TASK_CREATED = "task_created"
    TASK_UPDATED = "task_updated"
    TASK_DELETED = "task_deleted"
    TASK_LIST_RESET = "task_list_reset"
    TASK_LIST_REATTACH_MISMATCH = "task_list_reattach_mismatch"

    # Synthesised event sent FIRST on every fresh SSE subscribe so the
    # renderer can rehydrate "is this queen still busy?" instantly,
    # without waiting for the next live event. Built from the ring
    # buffer; never persisted. See compute_session_snapshot() and the
    # SSE replay loop for the producer.
    SESSION_SNAPSHOT = "session_snapshot"

    # Cross-cutting "app-wide" events used by the global SSE channel
    # (`/api/events/global`). They have no session scope — every
    # interested UI surface (Tool Library, integrations page, ...)
    # subscribes once at app boot and refreshes its local state on
    # receipt. Published by:
    #   - routes_credentials on save/delete
    #   - routes_queen_tools / routes_colony_tools on PATCH/DELETE
    #   - tool_registry after resync_mcp_servers_if_needed completes
    #   - routes_events, when the `hive-crm` CLI reports a write it just
    #     landed (framework.crm.notify), so a CRM board the user is
    #     watching refreshes while their queen configures it
    CREDENTIAL_PROVIDER_CONNECTED = "credential_provider_connected"
    CREDENTIAL_PROVIDER_DISCONNECTED = "credential_provider_disconnected"
    TOOL_CATALOG_REFRESHED = "tool_catalog_refreshed"
    TOOLS_CONFIG_CHANGED = "tools_config_changed"
    CRM_CHANGED = "crm_changed"


@dataclass
class AgentEvent:
    """An event in the agent system."""

    type: EventType
    stream_id: str
    node_id: str | None = None  # Which node emitted this event
    execution_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None  # For tracking related events
    colony_id: str | None = None  # Which colony emitted this event
    run_id: str | None = None  # Unique ID per trigger() invocation — used for run dividers
    # Monotonic publish counter assigned by EventBus.publish(). Lets the
    # renderer dedupe duplicate events that arrive via both the disk
    # eventsHistory and the live SSE replay paths.
    seq: int = 0

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = {
            "type": self.type.value,
            "stream_id": self.stream_id,
            "node_id": self.node_id,
            "execution_id": self.execution_id,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "colony_id": self.colony_id,
            "seq": self.seq,
        }
        if self.run_id is not None:
            d["run_id"] = self.run_id
        return d


# Type for event handlers
EventHandler = Callable[[AgentEvent], Awaitable[None]]


# event.data keys that are diagnostic-only and must NOT be persisted to the
# per-session events.jsonl. `full_request` is the entire LLM prompt (system
# text + every message + tool defs) re-serialised on every context-usage
# tick — ~280 KB each, hundreds per session. Persisting it bloated logs to
# tens of MB and made the desktop's session restore fetch + parse a payload
# far too large to load. The live SSE broadcast still carries the full
# event for any live debug consumer — only the on-disk copy is trimmed.
_DISK_STRIPPED_DATA_FIELDS: tuple[str, ...] = ("full_request",)


def _event_to_disk_dict(event: AgentEvent) -> dict:
    """``event.to_dict()`` with diagnostic-only heavy fields removed.

    Returns a copy safe to ``json.dumps`` into events.jsonl; the original
    event (and its ``data`` dict) is left untouched so the live broadcast
    is unaffected.
    """
    d = event.to_dict()
    data = d.get("data")
    if isinstance(data, dict) and any(f in data for f in _DISK_STRIPPED_DATA_FIELDS):
        d["data"] = {k: v for k, v in data.items() if k not in _DISK_STRIPPED_DATA_FIELDS}
    return d


@dataclass
class Subscription:
    """A subscription to events."""

    id: str
    event_types: set[EventType]
    handler: EventHandler
    filter_stream: str | None = None  # Only receive events from this stream
    filter_node: str | None = None  # Only receive events from this node
    filter_execution: str | None = None  # Only receive events from this execution
    filter_colony: str | None = None  # Only receive events from this colony


class EventBus:
    """
    Pub/sub event bus for inter-stream communication.

    Features:
    - Async event handling
    - Type-based subscriptions
    - Stream/execution filtering
    - Event history for debugging

    Example:
        bus = EventBus()

        # Subscribe to execution events
        async def on_execution_complete(event: AgentEvent):
            print(f"Execution {event.execution_id} completed")

        bus.subscribe(
            event_types=[EventType.EXECUTION_COMPLETED],
            handler=on_execution_complete,
        )

        # Publish an event
        await bus.publish(AgentEvent(
            type=EventType.EXECUTION_COMPLETED,
            stream_id="webhook",
            execution_id="exec_123",
            data={"result": "success"},
        ))
    """

    def __init__(
        self,
        max_history: int = 1000,
        max_concurrent_handlers: int = 10,
    ):
        """
        Initialize event bus.

        Args:
            max_history: Maximum events to keep in history
            max_concurrent_handlers: Maximum concurrent handler executions
        """
        self._subscriptions: dict[str, Subscription] = {}
        self._event_history: list[AgentEvent] = []
        self._max_history = max_history
        self._semaphore = asyncio.Semaphore(max_concurrent_handlers)
        self._subscription_counter = 0
        self._lock = asyncio.Lock()
        # Monotonic counter stamped onto every published event. Used
        # by the renderer for dedupe across the disk-history and
        # live-SSE replay paths.
        self._seq_counter: int = 0
        # Per-session persistent event log (always-on, survives restarts).
        # EventLogFile owns the handle, the path, and the reopen-on-failed-write
        # recovery that keeps one bad write from silently dropping every
        # subsequent event (the 2026-07-02 01:04:30 case).
        self._queen_log: EventLogFile | None = None
        # Per-worker logs, opened lazily on a worker's first event and closed
        # when it reports. Empty unless a resolver is installed (see
        # ``set_worker_log_resolver``); without one, every event goes to the
        # queen's log exactly as it always has.
        self._worker_logs: dict[str, EventLogFile] = {}
        self._worker_log_resolver: Callable[[str], Path | None] | None = None
        self._session_log_iteration_offset: int = 0
        # Rate-limits the WARN for a session-log write that raised *outside* the
        # file layer (e.g. a json.dumps failure), which EventLogFile can't see.
        self._session_log_write_broken: bool = False
        # Accumulator for client_output_delta snapshots — flushed on llm_turn_complete.
        # Key: (stream_id, node_id, execution_id, iteration, inner_turn) → latest AgentEvent
        self._pending_output_snapshots: dict[tuple, AgentEvent] = {}
        # Per-execution tool index counter used to stamp tool_index on
        # TOOL_CALL_STARTED events so the frontend can assign deterministic
        # pill IDs across replay paths (disk history vs SSE ring buffer).
        # Key: execution_id → next index (1-based).
        self._tool_index_by_execution: dict[str, int] = {}
        # tool_use_id → stored tool_index so TOOL_CALL_COMPLETED can
        # stamp the same index that STARTED assigned.
        self._tool_index_by_use_id: dict[str, int] = {}
        # Sticky LoopActivity cell — written by ``publish`` whenever a
        # LOOP_STATE_CHANGED for a non-worker stream lands. Read by
        # ``compute_session_snapshot`` so the snapshot reflects the loop's
        # own announced state directly, never re-derived from event
        # history (which can age out of the bounded ring buffer). Stays
        # ``None`` until the first LOOP_STATE_CHANGED — meaning "loop has
        # not announced yet." Cleared on session reload — a fresh
        # ``EventBus`` instance starts with no cell.
        self._latest_loop_state: dict[str, Any] | None = None

    def set_session_log(self, path: Path, *, iteration_offset: int = 0) -> None:
        """Enable per-session event persistence to a JSONL file.

        Called once when the queen starts so that all events survive server
        restarts and can be replayed to reconstruct the frontend state.

        ``iteration_offset`` is added to the ``iteration`` field in logged
        events so that cold-resumed sessions produce monotonically increasing
        iteration values — preventing frontend message ID collisions between
        the original run and resumed runs.
        """
        # Close the prior log first, and NULL the attribute before opening the
        # new one, so that an open() failure can't leave a closed handle in
        # place (which would raise ValueError on every future write).
        if self._queen_log is not None:
            self._queen_log.close()
            self._queen_log = None
        self._queen_log = EventLogFile(path)
        self._session_log_iteration_offset = iteration_offset
        self._session_log_write_broken = False
        logger.info("Session event log → %s (iteration_offset=%d)", path, iteration_offset)

    def set_worker_log_resolver(self, resolver: Callable[[str], Path | None] | None) -> None:
        """Route worker-local events to per-worker logs instead of the queen's.

        ``resolver`` maps a worker ``stream_id`` (``"worker:<uuid>"``) to the
        path of that worker's ``events.jsonl``, or ``None`` if it can't be
        placed (in which case the event falls back to the queen's log rather
        than being dropped).

        Installed by :class:`ColonyRuntime`, which is the only thing that knows
        where a worker's directory lives. Until it is installed the bus behaves
        exactly as before — every event lands in the queen's log.
        """
        self._worker_log_resolver = resolver

    def _worker_log_for(self, stream_id: str) -> EventLogFile | None:
        """Lazily open (and cache) the log for ``stream_id``."""
        existing = self._worker_logs.get(stream_id)
        if existing is not None:
            return existing
        if self._worker_log_resolver is None:
            return None
        try:
            path = self._worker_log_resolver(stream_id)
        except Exception:
            logger.debug("worker log resolver raised for %s", stream_id, exc_info=True)
            return None
        if path is None:
            return None
        try:
            log = EventLogFile(path)
        except OSError as err:
            logger.warning("could not open worker event log %s: %s", path, err)
            return None
        self._worker_logs[stream_id] = log
        return log

    def _sinks_for(self, event: "AgentEvent") -> list[EventLogFile]:
        """Which logs this event is written to.

        * queen event      → queen log
        * worker META      → queen log **and** the worker's own log
        * worker chatter   → the worker's log only

        Worker META stays in the queen's log because that is what her replay
        needs to rebuild worker bubbles; it is also kept in the worker's log so
        that log is a complete, self-contained record for forensics.
        """
        queen = [self._queen_log] if self._queen_log is not None else []
        if self._worker_log_resolver is None:
            return queen  # routing disabled — legacy behaviour
        if not is_worker_stream(event.stream_id):
            return queen

        worker = self._worker_log_for(event.stream_id or "")
        if worker is None:
            return queen  # can't place it — never drop, fall back to the queen
        if is_worker_local(event.stream_id, event.type):
            return [worker]
        return [worker, *queen]

    def _close_worker_log(self, stream_id: str) -> None:
        """Close a worker's log once it has reported.

        SUBAGENT_REPORT fires exactly once per worker (synthesized if the
        worker never reported, and still emitted on crash/cancel), so this is
        the one place a worker is guaranteed to pass through — which is what
        keeps the handle map from leaking.
        """
        log = self._worker_logs.pop(stream_id, None)
        if log is not None:
            log.close()

    def close_session_log(self) -> None:
        """Close the per-session event log file and any open worker logs."""
        # Flush any pending output snapshots before closing
        self._flush_pending_snapshots()
        if self._queen_log is not None:
            self._queen_log.close()
            self._queen_log = None
        for log in self._worker_logs.values():
            log.close()
        self._worker_logs.clear()
        self._session_log_write_broken = False

    # Event types that are high-frequency streaming deltas — accumulated rather
    # than written individually to the session log.
    _STREAMING_DELTA_TYPES = frozenset(
        {
            EventType.CLIENT_OUTPUT_DELTA,
            EventType.LLM_TEXT_DELTA,
            EventType.LLM_REASONING_DELTA,
        }
    )

    def _write_session_log_event(self, event: AgentEvent) -> None:
        """Write an event to the per-session log with streaming coalescing.

        Streaming deltas (client_output_delta, llm_text_delta) are accumulated
        in memory.  When llm_turn_complete fires, any pending snapshots for that
        (stream_id, node_id, execution_id) are flushed as single consolidated
        events before the turn-complete event itself is written.

        Note: iteration offset is already applied in publish() before this is
        called, so events here already have correct iteration values.
        """
        if self._queen_log is None:
            return

        if event.type in self._STREAMING_DELTA_TYPES:
            # Accumulate — keep the latest event (which carries the full
            # snapshot of the prose), but PRESERVE the timestamp of the
            # FIRST event in the series. The frontend sorts the message
            # list by createdAt; if the coalesced snapshot inherited the
            # last delta's timestamp, mid-stream tool calls (e.g.
            # chart_render) would have an earlier timestamp than the
            # prose they were emitted inside, and after refresh the tool
            # pill would visually attach to the prior message instead of
            # the queen's response. Stamping the first timestamp keeps
            # cold-replay ordering consistent with the live stream.
            # event.type is part of the key: reasoning deltas and text deltas
            # share iteration/inner_turn but must coalesce into SEPARATE
            # slots — merged, the prose snapshot inherits the reasoning
            # stream's start timestamp (breaking cold-replay ordering) or is
            # outright overwritten by a late reasoning delta.
            key = (
                event.stream_id,
                event.node_id,
                event.execution_id,
                event.data.get("iteration"),
                event.data.get("inner_turn", 0),
                event.type,
            )
            existing = self._pending_output_snapshots.get(key)
            if existing is not None:
                event = replace(event, timestamp=existing.timestamp)
            self._pending_output_snapshots[key] = event
            return

        # The consolidated reasoning block supersedes the tail-capped rolling
        # snapshot for the same turn: drop the pending delta slot so a
        # tool-only turn doesn't flush a stale subset AFTER the full block
        # (disk replay applies events in order — last write would win).
        if event.type == EventType.CLIENT_REASONING:
            self._pending_output_snapshots.pop(
                (
                    event.stream_id,
                    event.node_id,
                    event.execution_id,
                    event.data.get("iteration"),
                    event.data.get("inner_turn", 0),
                    EventType.LLM_REASONING_DELTA,
                ),
                None,
            )

        # On turn-complete, flush accumulated snapshots for this stream first
        if event.type == EventType.LLM_TURN_COMPLETE:
            self._flush_pending_snapshots(
                stream_id=event.stream_id,
                node_id=event.node_id,
                execution_id=event.execution_id,
            )

        line = json.dumps(_event_to_disk_dict(event), default=str)
        for sink in self._sinks_for(event):
            sink.write(line)

        # A worker's log is closed on its terminal report — the one event every
        # worker is guaranteed to emit exactly once.
        if event.type == EventType.SUBAGENT_REPORT and is_worker_stream(event.stream_id):
            self._close_worker_log(event.stream_id or "")

    def _flush_pending_snapshots(
        self,
        stream_id: str | None = None,
        node_id: str | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Flush accumulated streaming snapshots to the session log.

        When called with filters, only matching entries are flushed.
        When called without filters (e.g. on close), everything is flushed.
        """
        if self._queen_log is None or not self._pending_output_snapshots:
            return

        to_flush: list[tuple] = []
        for key, _evt in self._pending_output_snapshots.items():
            if stream_id is not None:
                k_stream, k_node, k_exec, _, _, _ = key
                if k_stream != stream_id or k_node != node_id or k_exec != execution_id:
                    continue
            to_flush.append(key)

        flushed: list[EventLogFile] = []
        for key in to_flush:
            evt = self._pending_output_snapshots.pop(key)
            try:
                line = json.dumps(_event_to_disk_dict(evt), default=str)
                # Coalesced deltas are per-stream, so they route per-stream too —
                # a worker's prose snapshot belongs in the worker's log.
                for sink in self._sinks_for(evt):
                    sink.write(line)
                    flushed.append(sink)
            except Exception:
                pass

        for sink in flushed:
            try:
                sink.flush()
            except Exception:
                pass

    def subscribe(
        self,
        event_types: list[EventType],
        handler: EventHandler,
        filter_stream: str | None = None,
        filter_node: str | None = None,
        filter_execution: str | None = None,
        filter_colony: str | None = None,
    ) -> str:
        """
        Subscribe to events.

        Args:
            event_types: Types of events to receive
            handler: Async function to call when event occurs
            filter_stream: Only receive events from this stream
            filter_node: Only receive events from this node
            filter_execution: Only receive events from this execution
            filter_colony: Only receive events from this colony

        Returns:
            Subscription ID (use to unsubscribe)
        """
        self._subscription_counter += 1
        sub_id = f"sub_{self._subscription_counter}"

        subscription = Subscription(
            id=sub_id,
            event_types=set(event_types),
            handler=handler,
            filter_stream=filter_stream,
            filter_node=filter_node,
            filter_execution=filter_execution,
            filter_colony=filter_colony,
        )

        self._subscriptions[sub_id] = subscription
        logger.debug(f"Subscription {sub_id} registered for {event_types}")

        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Unsubscribe from events.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if subscription was found and removed
        """
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            logger.debug(f"Subscription {subscription_id} removed")
            return True
        return False

    async def publish(self, event: AgentEvent) -> None:
        """
        Publish an event to all matching subscribers.

        Args:
            event: Event to publish
        """
        # Apply iteration offset at the source so ALL consumers (SSE subscribers,
        # event history, session log) see the same monotonically increasing
        # iteration values.  Without this, live SSE would use raw iterations
        # while events.jsonl would use offset iterations, causing ID collisions
        # on the frontend when replaying after cold resume.
        if self._session_log_iteration_offset and isinstance(event.data, dict) and "iteration" in event.data:
            offset = self._session_log_iteration_offset
            event.data = {**event.data, "iteration": event.data["iteration"] + offset}

        # Add to history (lock-protected so seq assignment is atomic
        # under concurrent publishers).
        async with self._lock:
            self._seq_counter += 1
            event.seq = self._seq_counter
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history = self._event_history[-self._max_history :]

        # Sticky LoopActivity cell — keep the loop's last announcement
        # reachable even after the LOOP_STATE_CHANGED event has aged out
        # of the bounded ring buffer. Worker streams have their own loops
        # and must NOT overwrite the queen's state (the snapshot filters
        # them out anyway). This is the single writer of the cell.
        if event.type == EventType.LOOP_STATE_CHANGED and isinstance(event.data, dict):
            stream = event.stream_id or "queen"
            if not stream.startswith("worker"):
                self._latest_loop_state = {
                    "activity": event.data.get("activity"),
                    "park_reason": event.data.get("park_reason"),
                    "interrupt_cause": event.data.get("interrupt_cause"),
                    "questions": event.data.get("questions"),
                    "stream_id": event.stream_id,
                    "node_id": event.node_id,
                    "execution_id": event.execution_id,
                    "at": event.timestamp,
                    "seq": event.seq,
                }

        # Stamp tool_index so the frontend's pill IDs are deterministic
        # across replay paths. Without this, ReplayState.turnCounters
        # racing between the disk-history and SSE-ring-buffer paths
        # produced different pill IDs for the same tool call → duplicates.
        if isinstance(event.data, dict):
            if event.type == EventType.TOOL_CALL_STARTED and event.execution_id:
                idx = self._tool_index_by_execution.get(event.execution_id, 0) + 1
                self._tool_index_by_execution[event.execution_id] = idx
                event.data["tool_index"] = idx
                tool_use_id = event.data.get("tool_use_id")
                if isinstance(tool_use_id, str) and tool_use_id:
                    self._tool_index_by_use_id[tool_use_id] = idx
            elif event.type == EventType.TOOL_CALL_COMPLETED:
                tool_use_id = event.data.get("tool_use_id")
                if isinstance(tool_use_id, str) and tool_use_id:
                    idx = self._tool_index_by_use_id.get(tool_use_id)
                    if idx is not None:
                        event.data["tool_index"] = idx

        # Write event to JSONL file (gated by HIVE_DEBUG_EVENTS env var)
        if _DEBUG_EVENTS_ENABLED:
            global _event_log_file, _event_log_ready  # noqa: PLW0603
            if not _event_log_ready:
                _event_log_file = _open_event_log()
                _event_log_ready = True
            if _event_log_file is not None:
                try:
                    line = json.dumps(event.to_dict(), default=str)
                    _event_log_file.write(line + "\n")
                    _event_log_file.flush()
                except Exception:
                    pass  # never break event delivery

        # Per-session persistent log (always-on when set_session_log was called).
        # Streaming deltas are coalesced: client_output_delta and llm_text_delta
        # are accumulated and flushed as a single snapshot event on llm_turn_complete.
        if self._queen_log is not None:
            try:
                self._write_session_log_event(event)
            except Exception as _log_err:  # noqa: BLE001
                # The old comment here was "never break event delivery",
                # which is still the intent — a broken session log must
                # not take out live SSE subscribers. But swallowing the
                # exception WITHOUT any log meant a session-log failure
                # was invisible until manual forensics. Rate-limited WARN
                # via the shared flag on the first drop; the recovery path
                # inside _write_line_with_recovery flips it back on
                # successful reopen.
                if not self._session_log_write_broken:
                    self._session_log_write_broken = True
                    logger.warning(
                        "Session event log write raised (subsequent drops silent): %s",
                        _log_err,
                    )

        # Find matching subscriptions
        matching_handlers: list[EventHandler] = []

        for subscription in self._subscriptions.values():
            if self._matches(subscription, event):
                matching_handlers.append(subscription.handler)

        # Execute handlers concurrently
        if matching_handlers:
            await self._execute_handlers(event, matching_handlers)

    def _matches(self, subscription: Subscription, event: AgentEvent) -> bool:
        """Check if a subscription matches an event."""
        # Check event type
        if event.type not in subscription.event_types:
            return False

        # Check stream filter
        if subscription.filter_stream and subscription.filter_stream != event.stream_id:
            return False

        # Check node filter
        if subscription.filter_node and subscription.filter_node != event.node_id:
            return False

        # Check execution filter
        if subscription.filter_execution and subscription.filter_execution != event.execution_id:
            return False

        # Check colony filter
        if subscription.filter_colony and subscription.filter_colony != event.colony_id:
            return False

        return True

    # Per-handler wall-clock timeout. A subscriber that deadlocks or
    # blocks on slow I/O would otherwise freeze the publisher (and via
    # ``await publish(...)`` any coroutine that emits events) indefinitely.
    # 15 s is generous for legitimate handlers and cheap to tune later.
    _HANDLER_TIMEOUT_SECONDS: float = 15.0

    async def _execute_handlers(
        self,
        event: AgentEvent,
        handlers: list[EventHandler],
    ) -> None:
        """Execute handlers concurrently with rate limiting + hard timeout."""

        async def run_handler(handler: EventHandler) -> None:
            async with self._semaphore:
                try:
                    await asyncio.wait_for(
                        handler(event),
                        timeout=self._HANDLER_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    handler_name = getattr(handler, "__qualname__", repr(handler))
                    logger.error(
                        "EventBus handler %s exceeded %.0fs on event %s — dropping; fix the handler or the publisher will stall",
                        handler_name,
                        self._HANDLER_TIMEOUT_SECONDS,
                        getattr(event.type, "name", event.type),
                    )
                except Exception:
                    logger.exception(f"Handler error for {event.type}")

        # Run all handlers concurrently
        await asyncio.gather(*[run_handler(h) for h in handlers], return_exceptions=True)

    # === CONVENIENCE PUBLISHERS ===

    async def emit_execution_started(
        self,
        stream_id: str,
        execution_id: str,
        input_data: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit execution started event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_STARTED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={"input": input_data or {}},
                correlation_id=correlation_id,
                run_id=run_id,
            )
        )

    async def emit_execution_completed(
        self,
        stream_id: str,
        execution_id: str,
        output: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit execution completed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_COMPLETED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={"output": output or {}},
                correlation_id=correlation_id,
                run_id=run_id,
            )
        )

    async def emit_execution_failed(
        self,
        stream_id: str,
        execution_id: str,
        error: str,
        correlation_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit execution failed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_FAILED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={"error": error},
                correlation_id=correlation_id,
                run_id=run_id,
            )
        )

    async def emit_payment_required(
        self,
        stream_id: str,
        execution_id: str | None = None,
        message: str | None = None,
        upstream_status: int | None = 402,
        correlation_id: str | None = None,
        run_id: str | None = None,
    ) -> None:
        """Emit a billing-gate signal (typically a 402 from the Hive LLM proxy).

        Fires alongside the EXECUTION_FAILED that follows. The desktop client
        listens for this dedicated event and reopens the upgrade popup so
        the user can refresh their plan without parsing the failure string.
        """
        await self.publish(
            AgentEvent(
                type=EventType.PAYMENT_REQUIRED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={
                    "message": message or "LLM provider returned payment required.",
                    "upstream_status": upstream_status,
                },
                correlation_id=correlation_id,
                run_id=run_id,
            )
        )

    async def emit_goal_progress(
        self,
        stream_id: str,
        progress: float,
        criteria_status: dict[str, Any],
    ) -> None:
        """Emit goal progress event."""
        await self.publish(
            AgentEvent(
                type=EventType.GOAL_PROGRESS,
                stream_id=stream_id,
                data={
                    "progress": progress,
                    "criteria_status": criteria_status,
                },
            )
        )

    async def emit_constraint_violation(
        self,
        stream_id: str,
        execution_id: str,
        constraint_id: str,
        description: str,
    ) -> None:
        """Emit constraint violation event."""
        await self.publish(
            AgentEvent(
                type=EventType.CONSTRAINT_VIOLATION,
                stream_id=stream_id,
                execution_id=execution_id,
                data={
                    "constraint_id": constraint_id,
                    "description": description,
                },
            )
        )

    async def emit_state_changed(
        self,
        stream_id: str,
        execution_id: str,
        key: str,
        old_value: Any,
        new_value: Any,
        scope: str,
    ) -> None:
        """Emit state changed event."""
        await self.publish(
            AgentEvent(
                type=EventType.STATE_CHANGED,
                stream_id=stream_id,
                execution_id=execution_id,
                data={
                    "key": key,
                    "old_value": old_value,
                    "new_value": new_value,
                    "scope": scope,
                },
            )
        )

    # === NODE EVENT-LOOP PUBLISHERS ===

    async def emit_node_loop_started(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
        max_iterations: int | None = None,
    ) -> None:
        """Emit node loop started event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_LOOP_STARTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"max_iterations": max_iterations},
            )
        )

    async def emit_node_loop_iteration(
        self,
        stream_id: str,
        node_id: str,
        iteration: int,
        execution_id: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> None:
        """Emit node loop iteration event."""
        data: dict[str, Any] = {"iteration": iteration}
        if extra_data:
            data.update(extra_data)
        await self.publish(
            AgentEvent(
                type=EventType.NODE_LOOP_ITERATION,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_node_loop_completed(
        self,
        stream_id: str,
        node_id: str,
        iterations: int,
        execution_id: str | None = None,
    ) -> None:
        """Emit node loop completed event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_LOOP_COMPLETED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"iterations": iterations},
            )
        )

    # === LLM STREAMING PUBLISHERS ===

    async def emit_llm_text_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        execution_id: str | None = None,
        inner_turn: int = 0,
    ) -> None:
        """Emit LLM text delta event."""
        await self.publish(
            AgentEvent(
                type=EventType.LLM_TEXT_DELTA,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"content": content, "snapshot": snapshot, "inner_turn": inner_turn},
            )
        )

    async def emit_llm_reasoning_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        execution_id: str | None = None,
        iteration: int | None = None,
        inner_turn: int = 0,
        snapshot: str | None = None,
    ) -> None:
        """Emit LLM reasoning delta event.

        ``snapshot`` mirrors the client_output_delta contract: accumulated
        reasoning so far (possibly tail-capped by the emitter), so consumers
        render by replacement instead of concatenating deltas.
        """
        data: dict = {"content": content, "inner_turn": inner_turn}
        if iteration is not None:
            data["iteration"] = iteration
        if snapshot is not None:
            data["snapshot"] = snapshot
        await self.publish(
            AgentEvent(
                type=EventType.LLM_REASONING_DELTA,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_llm_turn_complete(
        self,
        stream_id: str,
        node_id: str,
        stop_reason: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cached_tokens: int = 0,
        cache_creation_tokens: int = 0,
        cost_usd: float = 0.0,
        credits: float | None = None,
        execution_id: str | None = None,
        iteration: int | None = None,
        system_prefix_sha: str | None = None,
        system_suffix_sha: str | None = None,
        history_anchor_idx: int | None = None,
        message_count: int | None = None,
    ) -> None:
        """Emit LLM turn completion with stop reason and model metadata.

        ``cached_tokens`` and ``cache_creation_tokens`` are subsets of
        ``input_tokens`` (already inside provider ``prompt_tokens``).
        Subscribers should display them, not add them to a total.

        ``cost_usd`` is the USD cost for this turn when known (Anthropic,
        OpenAI, OpenRouter). 0.0 means unreported (not free).

        ``credits`` is the per-turn Hive credit cost summed across requests
        in the turn. ``None`` means no Hive-aliased call carried a credits
        field; the data dict omits the key entirely in that case so
        subscribers can distinguish "no estimate" from zero.

        ``system_prefix_sha`` / ``system_suffix_sha`` / ``history_anchor_idx``
        / ``message_count`` are diagnostic fingerprints written by the
        AgentLoop right before each LLM call. They make cache-hit
        anomalies post-mortem-debuggable from events.jsonl alone:

        * ``system_prefix_sha`` (12-char hex) — sha256 of the static
          system block that carries ``cache_control: ephemeral``. Two
          adjacent turns with the same hash but cache_read=0 on the
          second mean the cache TTL expired (or the proxy rotated
          backends). Two turns with DIFFERENT hashes means the static
          prefix mutated and there's a stability bug upstream.
        * ``system_suffix_sha`` (12-char hex) — sha256 of the dynamic
          suffix block (timestamp + recall + focus). Expected to
          change frequently; included for completeness.
        * ``history_anchor_idx`` — index in the outgoing ``messages``
          list where the rolling cache_control breakpoint was placed,
          or ``-1`` when no breakpoint was placed (first turn, or
          provider doesn't support cache_control).
        * ``message_count`` — number of messages sent on this turn,
          including system. Lets you correlate cache misses with
          message-history growth or compaction shrinkage.

        All four are omitted from the data dict when None, so existing
        consumers see no change.
        """
        data: dict = {
            "stop_reason": stop_reason,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_tokens": cached_tokens,
            "cache_creation_tokens": cache_creation_tokens,
            "cost_usd": cost_usd,
        }
        if credits is not None:
            data["credits"] = credits
        logger.info(
            "[credits] emit_llm_turn_complete: credits=%r model=%s data_has_credits_key=%s",
            credits,
            model,
            "credits" in data,
        )
        if iteration is not None:
            data["iteration"] = iteration
        if system_prefix_sha is not None:
            data["system_prefix_sha"] = system_prefix_sha
        if system_suffix_sha is not None:
            data["system_suffix_sha"] = system_suffix_sha
        if history_anchor_idx is not None:
            data["history_anchor_idx"] = history_anchor_idx
        if message_count is not None:
            data["message_count"] = message_count
        await self.publish(
            AgentEvent(
                type=EventType.LLM_TURN_COMPLETE,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    # === TOOL LIFECYCLE PUBLISHERS ===

    async def emit_tool_call_started(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Emit tool call started event."""
        await self.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_STARTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "tool_input": tool_input or {},
                },
            )
        )

    async def emit_tool_call_completed(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        result: str = "",
        is_error: bool = False,
        execution_id: str | None = None,
    ) -> None:
        """Emit tool call completed event."""
        await self.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_COMPLETED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "tool_use_id": tool_use_id,
                    "tool_name": tool_name,
                    "result": result,
                    "is_error": is_error,
                },
            )
        )

    # === CLIENT I/O PUBLISHERS ===

    async def emit_client_output_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        execution_id: str | None = None,
        iteration: int | None = None,
        inner_turn: int = 0,
    ) -> None:
        """Emit user-facing output delta for interactive queen turns."""
        data: dict = {"content": content, "snapshot": snapshot, "inner_turn": inner_turn}
        if iteration is not None:
            data["iteration"] = iteration
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_OUTPUT_DELTA,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_client_reasoning(
        self,
        stream_id: str,
        node_id: str,
        reasoning: str,
        execution_id: str | None = None,
        iteration: int | None = None,
        inner_turn: int = 0,
    ) -> None:
        """Emit the agent's hidden <think> reasoning for an interactive turn.

        The reasoning block is stripped from the visible output; this event
        carries it so a monitor/UI can display the grounding the agent did
        before speaking. Not part of the conversation the user sees.
        """
        data: dict = {"reasoning": reasoning, "inner_turn": inner_turn}
        if iteration is not None:
            data["iteration"] = iteration
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_REASONING,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_client_input_requested(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
        questions: list[dict] | None = None,
        park_reason: str | None = None,
    ) -> None:
        """Emit a user-input request for interactive queen turns.

        Args:
            questions: Optional list of question dicts from ``ask_user``.
                Each dict has ``id``, ``prompt``, and optional ``options``
                (2-3 predefined choices). The frontend renders the
                QuestionWidget for a single-entry list and the
                MultiQuestionWidget for 2+ entries. Free-text asks (no
                options) stream the prompt separately as a chat message;
                auto-block turns have no questions at all and fall back
                to the normal text input.
            park_reason: Optional :class:`ParkReason` value naming why the
                loop parked — carried into the snapshot so the debug panel
                can tell a legitimate question-park from a broken one.
        """
        data: dict[str, Any] = {}
        if questions:
            data["questions"] = questions
        if park_reason:
            data["park_reason"] = park_reason
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_INPUT_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_credential_form_requested(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
        form: dict | None = None,
    ) -> None:
        """Emit a secure-credential-form request for the frontend to render.

        Args:
            form: The no-secret form spec built by ``credential_tool``:
                ``{credential_id, account, title, instructions, fields,
                correlation_id}``. ``fields`` are field *specs* only — the
                user's entered values are POSTed straight to the encrypted
                store and never travel back through this event or the LLM
                conversation.
        """
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_CREDENTIAL_FORM_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=dict(form or {}),
            )
        )

    async def emit_client_input_committed(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
        *,
        seq: int,
        correlation_id: str | None = None,
    ) -> None:
        """Emit when a received user message is actually drained into the
        conversation. Its timestamp is the true injection moment — after the
        in-flight turn that was streaming when the message arrived — so the UI
        can place the user bubble at its real conversation position (``seq``)
        instead of at receive time. ``correlation_id`` ties it back to the
        earlier :data:`EventType.CLIENT_INPUT_RECEIVED`. See
        ``routes_execution.handle_chat`` (emits the received event + id) and the
        two drain sites in ``agent_loop`` (priority drain) and
        ``cursor_persistence.drain_injection_queue`` (boundary drain)."""
        await self.publish(
            AgentEvent(
                type=EventType.CLIENT_INPUT_COMMITTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                correlation_id=correlation_id,
                data={"seq": seq},
            )
        )

    async def emit_colony_suggestion_requested(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
        *,
        colony_id: str,
        reason: str | None = None,
        source_session_id: str | None = None,
        source_phase: str | None = None,
        goal: str | None = None,
        handoff: str | None = None,
        task_count: int | None = None,
    ) -> None:
        """Emit a colony-creation suggestion from the queen.

        Two variants, distinguished by ``source_phase``:

        - **DM source** (``source_phase`` unset or "independent"): the
          legacy ``suggest_colony`` flow. Frontend opens a "Create
          Colony" popup pre-filled with ``colony_id`` and the current
          queen auto-selected. On accept the frontend POSTs
          ``/api/sessions`` with ``colony_id`` + ``source_session_id``
          so the backend forks this session into the new colony
          (compaction included). On dismiss the frontend injects a user
          message back into this session to unblock the queen.

        - **Colony source** (``source_phase`` == "colony"): the colony
          pivot flow driven by ``task_create(new_colony=true)``. The
          popup opens with the slug field BLANK for the user to fill
          in, and shows ``goal`` as the colony description plus
          ``handoff`` read-only so the user can review what's being
          handed over. On accept the frontend POSTs ``/api/sessions``
          and the backend takes the lean-handoff path. On dismiss the
          frontend POSTs ``/api/sessions/{id}/dismiss-colony-pivot``,
          which injects a synthetic message into the source.
        """
        data: dict[str, Any] = {"colony_id": colony_id}
        if reason:
            data["reason"] = reason
        if source_session_id:
            data["source_session_id"] = source_session_id
        if source_phase:
            data["source_phase"] = source_phase
        if goal:
            data["goal"] = goal
        if handoff:
            data["handoff"] = handoff
        if task_count is not None:
            data["task_count"] = task_count
        await self.publish(
            AgentEvent(
                type=EventType.COLONY_SUGGESTION_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    # === INTERNAL NODE PUBLISHERS ===

    async def emit_node_internal_output(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit node internal output for non-user-facing execution."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_INTERNAL_OUTPUT,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"content": content},
            )
        )

    async def emit_node_stalled(
        self,
        stream_id: str,
        node_id: str,
        reason: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit node stalled event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_STALLED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"reason": reason},
            )
        )

    async def emit_tool_doom_loop(
        self,
        stream_id: str,
        node_id: str,
        description: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit tool doom loop detection event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_TOOL_DOOM_LOOP,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"description": description},
            )
        )

    async def emit_node_input_blocked(
        self,
        stream_id: str,
        node_id: str,
        prompt: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit node input blocked event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_INPUT_BLOCKED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"prompt": prompt},
            )
        )

    # === JUDGE / OUTPUT / RETRY / EDGE PUBLISHERS ===

    async def emit_judge_verdict(
        self,
        stream_id: str,
        node_id: str,
        action: str,
        feedback: str = "",
        judge_type: str = "implicit",
        iteration: int = 0,
        execution_id: str | None = None,
    ) -> None:
        """Emit judge verdict event."""
        await self.publish(
            AgentEvent(
                type=EventType.JUDGE_VERDICT,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "action": action,
                    "feedback": feedback,
                    "judge_type": judge_type,
                    "iteration": iteration,
                },
            )
        )

    async def emit_node_retry(
        self,
        stream_id: str,
        node_id: str,
        retry_count: int,
        max_retries: int,
        error: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit node retry event."""
        await self.publish(
            AgentEvent(
                type=EventType.NODE_RETRY,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "retry_count": retry_count,
                    "max_retries": max_retries,
                    "error": error,
                },
            )
        )

    async def emit_stream_ttft_exceeded(
        self,
        stream_id: str,
        node_id: str,
        ttft_seconds: float,
        limit_seconds: float,
        execution_id: str | None = None,
    ) -> None:
        """Emit when a stream stayed silent past the TTFT budget (no first event)."""
        await self.publish(
            AgentEvent(
                type=EventType.STREAM_TTFT_EXCEEDED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "ttft_seconds": ttft_seconds,
                    "limit_seconds": limit_seconds,
                },
            )
        )

    async def emit_stream_inactive(
        self,
        stream_id: str,
        node_id: str,
        idle_seconds: float,
        limit_seconds: float,
        execution_id: str | None = None,
    ) -> None:
        """Emit when a stream that had produced events went silent past budget."""
        await self.publish(
            AgentEvent(
                type=EventType.STREAM_INACTIVE,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "idle_seconds": idle_seconds,
                    "limit_seconds": limit_seconds,
                },
            )
        )

    async def emit_loop_state_changed(
        self,
        stream_id: str,
        node_id: str,
        activity: str,
        execution_id: str | None = None,
        park_reason: str | None = None,
        interrupt_cause: str | None = None,
        questions: list[dict] | None = None,
    ) -> None:
        """Emit the agent loop's authoritative top-level state.

        ``activity`` is a :class:`~framework.agent_loop.reminders.LoopActivity`
        value. ``park_reason`` / ``interrupt_cause`` carry the granular
        sub-cause. The session snapshot reads the latest of these for the
        queen stream rather than re-deriving activity from many event types.
        """
        await self.publish(
            AgentEvent(
                type=EventType.LOOP_STATE_CHANGED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "activity": activity,
                    "park_reason": park_reason,
                    "interrupt_cause": interrupt_cause,
                    "questions": questions or None,
                },
            )
        )

    async def emit_stream_nudge_sent(
        self,
        stream_id: str,
        node_id: str,
        reason: str,
        nudge_count: int,
        execution_id: str | None = None,
    ) -> None:
        """Emit when the continue-nudge was injected (recovery, not retry)."""
        await self.publish(
            AgentEvent(
                type=EventType.STREAM_NUDGE_SENT,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "reason": reason,
                    "nudge_count": nudge_count,
                },
            )
        )

    async def emit_reminder_injected(
        self,
        stream_id: str,
        node_id: str,
        source: str,
        detail: str = "",
        meta: dict | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Emit when the ReminderHub injected a system reminder.

        ``source`` names the producer (``idle_nudge``, ``tool_budget``,
        ``stream_stall``, or ``point:<lifecycle point>``). ``detail`` is a
        short human tag (idle substate, stall reason, …); ``meta`` carries
        the source's structured payload (counts, caps, elapsed).
        """
        await self.publish(
            AgentEvent(
                type=EventType.REMINDER_INJECTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "source": source,
                    "detail": detail,
                    "meta": meta or {},
                },
            )
        )

    async def emit_tool_call_replay_detected(
        self,
        stream_id: str,
        node_id: str,
        tool_name: str,
        prior_seq: int,
        execution_id: str | None = None,
    ) -> None:
        """Emit when the model is about to re-execute a prior successful call."""
        await self.publish(
            AgentEvent(
                type=EventType.TOOL_CALL_REPLAY_DETECTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "tool_name": tool_name,
                    "prior_seq": prior_seq,
                },
            )
        )

    async def emit_worker_completed(
        self,
        stream_id: str,
        node_id: str,
        worker_id: str,
        success: bool,
        output: dict[str, Any],
        activations: list[dict[str, Any]] | None = None,
        execution_id: str | None = None,
        **extra_data: Any,
    ) -> None:
        """Emit worker completed event with outgoing activations."""
        data: dict[str, Any] = {
            "worker_id": worker_id,
            "success": success,
            "output": output,
            "activations": activations or [],
            **extra_data,
        }
        await self.publish(
            AgentEvent(
                type=EventType.WORKER_COMPLETED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data=data,
            )
        )

    async def emit_worker_failed(
        self,
        stream_id: str,
        node_id: str,
        worker_id: str,
        error: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit worker failed event."""
        await self.publish(
            AgentEvent(
                type=EventType.WORKER_FAILED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"worker_id": worker_id, "error": error},
            )
        )

    async def emit_execution_paused(
        self,
        stream_id: str,
        node_id: str,
        reason: str = "",
        execution_id: str | None = None,
    ) -> None:
        """Emit execution paused event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_PAUSED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={"reason": reason},
            )
        )

    async def emit_execution_resumed(
        self,
        stream_id: str,
        node_id: str,
        execution_id: str | None = None,
    ) -> None:
        """Emit execution resumed event."""
        await self.publish(
            AgentEvent(
                type=EventType.EXECUTION_RESUMED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={},
            )
        )

    async def emit_webhook_received(
        self,
        source_id: str,
        path: str,
        method: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        query_params: dict[str, str] | None = None,
    ) -> None:
        """Emit webhook received event."""
        await self.publish(
            AgentEvent(
                type=EventType.WEBHOOK_RECEIVED,
                stream_id=source_id,
                data={
                    "path": path,
                    "method": method,
                    "headers": headers,
                    "payload": payload,
                    "query_params": query_params or {},
                },
            )
        )

    async def emit_escalation_requested(
        self,
        stream_id: str,
        node_id: str,
        reason: str = "",
        context: str = "",
        execution_id: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Emit escalation requested event (agent wants queen).

        ``request_id`` is a caller-supplied handle used by the queen to
        address its reply back to the specific escalation. When omitted the
        event still fires but the queen cannot route a targeted reply.
        """
        await self.publish(
            AgentEvent(
                type=EventType.ESCALATION_REQUESTED,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "request_id": request_id,
                    "reason": reason,
                    "context": context,
                },
            )
        )

    async def emit_subagent_report(
        self,
        stream_id: str,
        node_id: str,
        subagent_id: str,
        message: str,
        data: dict[str, Any] | None = None,
        execution_id: str | None = None,
    ) -> None:
        """Emit a one-way progress report from a sub-agent."""
        await self.publish(
            AgentEvent(
                type=EventType.SUBAGENT_REPORT,
                stream_id=stream_id,
                node_id=node_id,
                execution_id=execution_id,
                data={
                    "subagent_id": subagent_id,
                    "message": message,
                    "data": data,
                },
            )
        )

    # === QUERY OPERATIONS ===

    def get_history(
        self,
        event_type: EventType | None = None,
        stream_id: str | None = None,
        execution_id: str | None = None,
        limit: int = 100,
    ) -> list[AgentEvent]:
        """
        Get event history with optional filtering.

        Args:
            event_type: Filter by event type
            stream_id: Filter by stream
            execution_id: Filter by execution
            limit: Maximum events to return

        Returns:
            List of matching events (most recent first)
        """
        events = self._event_history[::-1]  # Reverse for most recent first

        # Apply filters
        if event_type:
            events = [e for e in events if e.type == event_type]
        if stream_id:
            events = [e for e in events if e.stream_id == stream_id]
        if execution_id:
            events = [e for e in events if e.execution_id == execution_id]

        return events[:limit]

    def get_stats(self) -> dict:
        """Get event bus statistics."""
        type_counts = {}
        for event in self._event_history:
            type_counts[event.type.value] = type_counts.get(event.type.value, 0) + 1

        return {
            "total_events": len(self._event_history),
            "subscriptions": len(self._subscriptions),
            "events_by_type": type_counts,
        }

    # === WAITING OPERATIONS ===

    async def wait_for(
        self,
        event_type: EventType,
        stream_id: str | None = None,
        node_id: str | None = None,
        execution_id: str | None = None,
        colony_id: str | None = None,
        timeout: float | None = None,
    ) -> AgentEvent | None:
        """
        Wait for a specific event to occur.

        Args:
            event_type: Type of event to wait for
            stream_id: Filter by stream
            node_id: Filter by node
            execution_id: Filter by execution
            colony_id: Filter by colony
            timeout: Maximum time to wait (seconds)

        Returns:
            The event if received, None if timeout
        """
        result: AgentEvent | None = None
        event_received = asyncio.Event()

        async def handler(event: AgentEvent) -> None:
            nonlocal result
            result = event
            event_received.set()

        # Subscribe
        sub_id = self.subscribe(
            event_types=[event_type],
            handler=handler,
            filter_stream=stream_id,
            filter_node=node_id,
            filter_execution=execution_id,
            filter_colony=colony_id,
        )

        try:
            # Wait with timeout
            if timeout:
                try:
                    await asyncio.wait_for(event_received.wait(), timeout=timeout)
                except TimeoutError:
                    return None
            else:
                await event_received.wait()

            return result
        finally:
            self.unsubscribe(sub_id)


# ---------------------------------------------------------------------------
# Snapshot helpers (consumed by the SSE handler)
# ---------------------------------------------------------------------------


def compute_session_snapshot(event_bus: "EventBus") -> dict:
    """Project the queen's current state from the event bus.

    Read-only; nothing here mutates state. Used to build the
    ``session_snapshot`` event the SSE handler injects first on every
    fresh subscribe so the renderer can rehydrate "queen busy / current
    tool / awaiting input" instantly on revisit.

    Discipline: the loop's authoritative activity (``LoopActivity`` plus
    ``ParkReason`` / ``InterruptCause``) is read **only** from the
    sticky ``_latest_loop_state`` cell, never re-derived from event
    history. The cell is the loop's announcement; re-deriving from
    EXECUTION_STARTED / CLIENT_INPUT_REQUESTED / etc. would let the
    snapshot disagree with the loop. The remaining event walk is for
    side-effect data the loop's state cell does not carry: open tools,
    timestamps, and the unresolved-question-seq for replay dedup.

    The single override is the staleness backstop: a loop that
    announced EXECUTING but emitted nothing for the staleness window
    is treated as crashed — a hard crash cannot self-announce.
    """
    history = event_bus._event_history
    seq = event_bus._seq_counter

    # ── Side-effect walk: tools and timestamps only ───────────────────────
    # Activity does NOT come from this walk — see the cell read below.
    open_tools: dict[str, dict] = {}
    current_execution_id: str | None = None
    last_event_ts: datetime | None = None
    last_queen_event_ts: datetime | None = None
    last_unresolved_req_seq: int | None = None
    pending_questions: list[dict] | None = None

    for ev in history:
        last_event_ts = ev.timestamp
        # Skip worker streams — they share the queen's event_bus but
        # their lifecycle is invisible to the queen DM. Counting them
        # here would make the queen appear "Working" while only a
        # subagent is running.
        stream = ev.stream_id or "queen"
        if stream.startswith("worker"):
            continue
        last_queen_event_ts = ev.timestamp
        if ev.type == EventType.EXECUTION_STARTED:
            current_execution_id = ev.execution_id
        elif ev.type in (EventType.EXECUTION_COMPLETED, EventType.EXECUTION_FAILED):
            current_execution_id = None
            open_tools.clear()
        elif ev.type == EventType.TOOL_CALL_STARTED:
            tool_use_id = (ev.data or {}).get("tool_use_id")
            if tool_use_id:
                open_tools[tool_use_id] = {
                    "id": tool_use_id,
                    "name": (ev.data or {}).get("tool_name"),
                    "started_at": ev.timestamp.isoformat(),
                    "execution_id": ev.execution_id,
                    "seq": ev.seq,
                }
        elif ev.type == EventType.TOOL_CALL_COMPLETED:
            tool_use_id = (ev.data or {}).get("tool_use_id")
            if tool_use_id:
                open_tools.pop(tool_use_id, None)
        elif ev.type == EventType.CLIENT_INPUT_REQUESTED:
            last_unresolved_req_seq = ev.seq
            qs = (ev.data or {}).get("questions")
            pending_questions = qs if isinstance(qs, list) else None
        elif ev.type == EventType.CLIENT_INPUT_RECEIVED:
            last_unresolved_req_seq = None
            pending_questions = None

    # ── Authoritative activity: read from the loop's announcement cell ──
    # The cell is written by ``publish`` on every LOOP_STATE_CHANGED for a
    # non-worker stream. It survives ring-buffer eviction. If it's None,
    # the loop hasn't announced yet — we report nothing rather than guess.
    cell = event_bus._latest_loop_state
    activity: str | None = None
    park_reason: str | None = None
    interrupt_cause: str | None = None
    if cell is not None:
        activity = cell.get("activity")
        park_reason = cell.get("park_reason")
        interrupt_cause = cell.get("interrupt_cause")
        _qs_from_cell = cell.get("questions")
        if isinstance(_qs_from_cell, list):
            pending_questions = _qs_from_cell

    is_executing = activity == "executing"
    awaiting_input = activity == "awaiting_user"
    interrupted = activity == "interrupted"
    # The 3-state model is mutually exclusive by construction — exactly one
    # of the booleans is true when activity is set, all false when it isn't.
    if not is_executing:
        # A parked / interrupted / not-yet-announced loop owns no live tools.
        open_tools.clear()

    # Staleness backstop: a loop that announced
    # EXECUTING but emitted nothing for the window is crashed / hung — a
    # hard crash cannot self-announce. Reclassify as INTERRUPTED rather
    # than silently reporting it idle. A stale AWAITING_USER is left alone
    # (a user simply hasn't replied yet), so this keys off is_executing.
    _STALENESS_S = 300.0
    if is_executing and last_queen_event_ts is not None:
        try:
            now = datetime.now(last_queen_event_ts.tzinfo) if last_queen_event_ts.tzinfo else datetime.now()
            age = (now - last_queen_event_ts).total_seconds()
        except Exception:
            age = 0.0
        if age > _STALENESS_S:
            is_executing = False
            interrupted = True
            activity = "interrupted"
            interrupt_cause = "stale"
            current_execution_id = None
            open_tools.clear()

    queen_busy_reason: str | None = None
    if interrupted:
        queen_busy_reason = "interrupted"
    elif awaiting_input:
        queen_busy_reason = "awaiting_input"
    elif is_executing:
        queen_busy_reason = "tool" if open_tools else "llm"

    return {
        "snapshot_seq": seq,
        "activity": activity,
        "is_executing": is_executing,
        "awaiting_input": awaiting_input,
        "interrupted": interrupted,
        "interrupt_cause": interrupt_cause if interrupted else None,
        "current_execution_id": current_execution_id,
        "current_tool_calls": list(open_tools.values()),
        "queen_busy_reason": queen_busy_reason,
        "park_reason": park_reason if (awaiting_input or interrupted) else None,
        "pending_questions": pending_questions if awaiting_input else None,
        "last_event_seq": last_unresolved_req_seq,
        "last_event_at": last_event_ts.isoformat() if last_event_ts else None,
        "last_queen_event_at": last_queen_event_ts.isoformat() if last_queen_event_ts else None,
    }


def collect_resolved_request_seqs(event_bus: "EventBus") -> set[int]:
    """Indices of CLIENT_INPUT_REQUESTED events already answered by a
    later CLIENT_INPUT_RECEIVED in the buffer. Used by the SSE replay
    path to suppress already-resolved questions so the renderer
    doesn't re-pop a modal the user already dismissed.

    A single CLIENT_INPUT_RECEIVED resolves *every* preceding
    unresolved request, not just the most recent one. ``ask_user``
    blocks the agent loop, so only one logically-distinct question is
    ever open at a time — consecutive CLIENT_INPUT_REQUESTED events
    with no answer between them are re-emits of the same question
    (each resume re-publishes it, and a spurious wait wakeup re-waits
    and re-publishes again). Pairing only the latest request to the
    answer would orphan the earlier duplicates, leaving them un-
    suppressed so the SSE replay re-pops a question already answered.
    """
    history = event_bus._event_history
    resolved: set[int] = set()
    unresolved: set[int] = set()
    for ev in history:
        if ev.type == EventType.CLIENT_INPUT_REQUESTED:
            unresolved.add(ev.seq)
        elif ev.type == EventType.CLIENT_INPUT_RECEIVED:
            resolved |= unresolved
            unresolved.clear()
    return resolved
