"""ColonyRuntime — Orchestrates a colony of parallel worker clones.

Each worker is an exact copy of the queen's AgentLoop — same tools,
same prompt, same LLM. Workers run independently and report results
back to the queen via the event bus.

The ColonyRuntime replaces both AgentHost and ExecutionManager.
There are no graphs, no edges, no nodes, no data buffers.
Just: spawn N independent clones, let them run, collect results.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.agent_loop.types import AgentContext, AgentSpec
from framework.host.colony_binding import ColonyBinding
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.triggers import TriggerDefinition
from framework.host.worker import (
    STOP_TIMEOUT_SEC as WORKER_STOP_TIMEOUT_SEC,
    Worker,
    WorkerInfo,
    WorkerResult,
)
from framework.schemas.goal import Goal
from framework.storage.concurrent import ConcurrentStorage
from framework.storage.session_store import SessionStore

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider, Tool
    from framework.skills.manager import SkillsManagerConfig
    from framework.tracker.runtime_log_store import RuntimeLogStore

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """Read a positive int from env; fall back to default on missing/invalid."""
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %d", name, raw, default)
        return default
    return value if value > 0 else default


# Field whitelist for queen-driven LoopConfig overrides. Limited to the
# fields a queen has any business tuning per-worker: how long the worker
# may run (max_iterations + grace_iterations), the worker's tool-call
# budget (tool_call_budget), and how much context to carry before
# compaction kicks in (max_context_tokens). Everything else on LoopConfig
# (judge cadence, stall detection, compaction buffer math, the worker's
# tool_call_hard_multiple) stays framework-controlled.
_ALLOWED_WORKER_LOOP_OVERRIDES = frozenset(
    {"max_iterations", "grace_iterations", "tool_call_budget", "tool_call_lifetime_budget", "max_context_tokens"}
)

# Sanity bounds. Reject pathological values up front rather than letting
# them blow up mid-run. tool_call_budget=0 is permitted (means "no
# soft/hard tool-call limit", per LoopConfig default). grace_iterations=0
# disables grace entirely; >3 is almost certainly a config mistake (the
# grace turn is for wrap-up, not extra work). tool_call_lifetime_budget=0
# is permitted (disables the cumulative cap); the 2000 ceiling is a
# generous backstop — a worker emitting 2000 tool calls is pathological.
_LOOP_OVERRIDE_BOUNDS = {
    "max_iterations": (1, 1000),
    "grace_iterations": (0, 3),
    "tool_call_budget": (0, 200),
    "tool_call_lifetime_budget": (0, 2000),
    "max_context_tokens": (1_000, 1_000_000),
}


def _build_worker_loop_config(overrides: dict[str, Any]) -> Any:
    """Construct a LoopConfig with queen-supplied overrides applied.

    Imported lazily inside the helper because LoopConfig lives under the
    agent_loop package and pulling it at module-import time would create
    a cycle through the colony runtime's own AgentLoop import.

    Unknown keys are silently dropped (we don't want a typo to kill the
    spawn) but bounds violations raise — those are programmer errors,
    not data errors.
    """
    from framework.agent_loop.agent_loop import LoopConfig
    from framework.agents.queen.worker_definition import DEFAULT_LOOP_CONFIG

    # Start from the worker profile. ALL the worker knobs come straight
    # from ``worker_definition.DEFAULT_LOOP_CONFIG`` — the single source
    # of truth — so this live spawn path cannot drift from it:
    #   - max_iterations=3, grace_iterations=1: 3 work turns + 1 wrap-up
    #     turn (dispatch restricted to {report_to_parent, tracker_upsert,
    #     task_update}) so a worker that runs out of budget reports back
    #     instead of dying silently.
    #   - tool_call_budget=30, tool_call_hard_multiple=3: soft checkpoints
    #     at 30/60, hard stop at 90 (tighter than the queen's 30×5=150;
    #     sized for a 5-10 unit batch task processed in-turn).
    #   - tool_call_lifetime_budget=150: cumulative cap across ALL turns;
    #     once hit, the worker is forced into grace wind-down (report +
    #     stop) so a high-max_iterations worker can't run unbounded.
    # The queen may raise max_iterations / grace_iterations / tool_call_budget
    # / tool_call_lifetime_budget per-batch via the override whitelist;
    # tool_call_hard_multiple stays framework-locked (absent from the whitelist).
    cfg = LoopConfig(
        max_iterations=DEFAULT_LOOP_CONFIG["max_iterations"],
        grace_iterations=DEFAULT_LOOP_CONFIG["grace_iterations"],
        tool_call_budget=DEFAULT_LOOP_CONFIG["tool_call_budget"],
        tool_call_hard_multiple=DEFAULT_LOOP_CONFIG["tool_call_hard_multiple"],
        tool_call_lifetime_budget=DEFAULT_LOOP_CONFIG["tool_call_lifetime_budget"],
    )
    for key, value in (overrides or {}).items():
        if key not in _ALLOWED_WORKER_LOOP_OVERRIDES:
            logger.debug("spawn loop_config_overrides: ignoring unsupported key %r", key)
            continue
        if not isinstance(value, int):
            raise ValueError(f"loop_config override {key!r} must be int, got {type(value).__name__}")
        lo, hi = _LOOP_OVERRIDE_BOUNDS[key]
        if not (lo <= value <= hi):
            raise ValueError(f"loop_config override {key!r}={value} out of range [{lo}, {hi}]")
        setattr(cfg, key, value)
    return cfg


# Laptop-safe default. Each worker is a full AgentLoop (Claude SDK session +
# tool catalog), so ~4 concurrent is the realistic ceiling on a dev machine.
# Override via HIVE_MAX_CONCURRENT_WORKERS for servers.
_DEFAULT_MAX_CONCURRENT_WORKERS = _env_int("HIVE_MAX_CONCURRENT_WORKERS", 4)


def _env_flag(name: str, default: bool) -> bool:
    """Read a boolean from env ("0"/"false"/"no"/"off" → False)."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


# ── Adaptive worker operating budget ────────────────────────────────
# Within a colony, successful workers define the norm: the colony's
# nominal tool_call_lifetime_budget shrinks toward what successful
# workers actually consume, so likely-failing workers are wound down
# early (via the loop's existing budget-grace machinery) instead of
# burning the full fixed ceiling. In-memory, colony-wide. Shrinks on the
# statistical estimate; raises ONLY on the max-guard (an uncensored,
# observed success cost) so the norm can recover when the colony's work
# gets more expensive. See _maybe_adapt_colony_budget.
# Kill switch: HIVE_ADAPTIVE_TOOL_BUDGET=0 (or per-colony metadata.json
# ``adaptive_tool_budget: false``, resolved by the session layer into
# ColonyConfig like max_concurrent_workers).
_DEFAULT_ADAPTIVE_TOOL_BUDGET = _env_flag("HIVE_ADAPTIVE_TOOL_BUDGET", True)
# Successes required before the colony trusts its norm at all.
_ADAPTIVE_BUDGET_MIN_SAMPLES = _env_int("HIVE_ADAPTIVE_BUDGET_MIN_SAMPLES", 3)
# Never clamp below this many tool calls — slow-but-legit workers must
# keep enough room to land a real result.
_ADAPTIVE_BUDGET_FLOOR = _env_int("HIVE_ADAPTIVE_BUDGET_FLOOR", 30)
# Headroom over the typical success: a would-be success must cost more
# than MULTIPLIER × median(successes) before it is wound down.
_ADAPTIVE_BUDGET_MULTIPLIER = 2.0
# Max-guard: the nominal never drops below MAX_GUARD × the most
# expensive success observed, pinning the estimate to uncensored
# evidence already gathered (anti-death-spiral).
_ADAPTIVE_BUDGET_MAX_GUARD = 1.25
# Dispersion guard: when p90 > LIMIT × median the colony is running
# visibly heterogeneous work and has no single norm — skip shrinking.
_ADAPTIVE_BUDGET_DISPERSION_LIMIT = 4.0
# Rolling sample window (bounded-deque precedent: runtime_resources.py).
_ADAPTIVE_BUDGET_SAMPLE_WINDOW = 50


# Token budget for the conversation-tail fallback used when a worker times
# out without ever calling ``report_to_parent``. One assistant turn, capped
# so a runaway message can't blow up the queen's stop_worker tool result.
_STOP_TAIL_MAX_CHARS = 500


async def _tail_last_assistant_message(worker: Any) -> str | None:
    """Best-effort: read the worker's most recent non-empty assistant turn.

    Returned excerpt is truncated to ``_STOP_TAIL_MAX_CHARS`` characters
    (with an ellipsis suffix when truncated). Returns ``None`` when the
    worker has no conversation store, no assistant turns, or the read
    raises — the caller is the stop path and must never fail because of
    a best-effort enrichment.

    Reaches across ``worker._agent_loop._conversation_store`` deliberately:
    the queen-stop path is the only caller and a defensive getattr is
    cheaper than threading the store through Worker's public API for
    one consumer.
    """
    try:
        agent_loop = getattr(worker, "_agent_loop", None)
        store = getattr(agent_loop, "_conversation_store", None)
        if store is None:
            return None
        parts = await store.read_parts()
        for part in reversed(parts):
            if part.get("role") != "assistant":
                continue
            content = (part.get("content") or "").strip()
            if not content:
                continue
            if len(content) > _STOP_TAIL_MAX_CHARS:
                return content[:_STOP_TAIL_MAX_CHARS] + "…"
            return content
        return None
    except Exception:
        logger.debug(
            "tail_last_assistant_message failed for %s",
            getattr(worker, "id", "?"),
            exc_info=True,
        )
        return None


@dataclass
class ColonyConfig:
    max_concurrent_workers: int = _DEFAULT_MAX_CONCURRENT_WORKERS
    # Colony-adaptive worker operating budget (see module constants above).
    # Overridable per colony via metadata.json ``adaptive_tool_budget``.
    adaptive_tool_budget: bool = _DEFAULT_ADAPTIVE_TOOL_BUDGET
    cache_ttl: float = 60.0
    batch_interval: float = 0.1
    max_history: int = 1000
    result_retention_max: int = 1000
    result_retention_ttl_seconds: float | None = None
    idempotency_ttl_seconds: float = 300.0
    idempotency_max_keys: int = 10000
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8080
    webhook_routes: list[dict] = field(default_factory=list)
    max_resurrections: int = 3


@dataclass
class TriggerSpec:
    """Specification for a trigger that auto-spawns workers."""

    id: str
    name: str
    trigger_type: str  # "webhook", "api", "timer", "event", "manual"
    trigger_config: dict[str, Any] = field(default_factory=dict)
    isolation_level: str = "shared"
    priority: int = 0
    max_concurrent: int = 10
    max_resurrections: int = 3


class StreamEventBus(EventBus):
    """Proxy that stamps ``colony_id`` on every published event.

    ``colony_id`` here is the event-bus broadcast scope — equal to the
    queen session id for DM sessions and to the colony name for colony
    sessions. It is *not* an on-disk identity: see
    :class:`ColonyBinding` for that.
    """

    def __init__(self, bus: EventBus, stream_id: str) -> None:
        self._real_bus = bus
        self._stream_id = stream_id
        self.last_activity_time: float = time.monotonic()

    async def publish(self, event: AgentEvent) -> None:
        event.colony_id = self._stream_id
        self.last_activity_time = time.monotonic()
        await self._real_bus.publish(event)

    def subscribe(self, *args: Any, **kwargs: Any) -> str:
        return self._real_bus.subscribe(*args, **kwargs)

    def unsubscribe(self, subscription_id: str) -> bool:
        return self._real_bus.unsubscribe(subscription_id)

    def get_history(self, *args: Any, **kwargs: Any) -> list:
        return self._real_bus.get_history(*args, **kwargs)

    def get_stats(self) -> dict:
        return self._real_bus.get_stats()

    async def wait_for(self, *args: Any, **kwargs: Any) -> Any:
        return await self._real_bus.wait_for(*args, **kwargs)


class ColonyRuntime:
    """Orchestrates a colony of parallel worker clones.

    Each worker is an exact copy of the queen's AgentLoop. Workers run
    independently, report results via the event bus, and terminate.

    Supports:
    - Spawning/stopping workers
    - Timer and webhook triggers that auto-spawn workers
    - Pipeline middleware (credentials, tools, skills)
    - Event pub/sub for queen-worker communication
    """

    def __init__(
        self,
        agent_spec: AgentSpec,
        goal: Goal,
        storage_path: str | Path,
        llm: LLMProvider | None = None,
        tools: list[Tool] | None = None,
        tool_executor: Callable | None = None,
        config: ColonyConfig | None = None,
        runtime_log_store: RuntimeLogStore | None = None,
        stream_id: str = "primary",
        binding: ColonyBinding | None = None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
        event_bus: EventBus | None = None,
        skills_manager_config: SkillsManagerConfig | None = None,
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
        skill_dirs: list[str] | None = None,
        pipeline_stages: list | None = None,
        queen_id: str | None = None,
    ):
        """
        Args:
            stream_id: Event-bus broadcast scope. Always equal to the
                owning session.id — what filters and subscribers use to
                isolate one session's events from another's. NOT an
                on-disk path component.
            binding: Optional on-disk colony identity (name + dir +
                tracker.db). ``None`` means this runtime is hosting a
                DM/queen session that has not yet created a colony.
                ``fork_session_into_colony`` produces a binding and
                installs it via ``set_binding`` (and on the queen's
                execution context).
        """
        from framework.pipeline.runner import PipelineRunner
        from framework.skills.manager import SkillsManager

        self._agent_spec = agent_spec
        self._goal = goal
        self._config = config or ColonyConfig()
        self._runtime_log_store = runtime_log_store
        self._queen_id: str | None = queen_id
        self._binding: ColonyBinding | None = binding
        self._stream_id: str = stream_id

        if pipeline_stages:
            self._pipeline = PipelineRunner(pipeline_stages)
        else:
            self._pipeline = self._load_pipeline_from_config()

        # Resolve per-colony override paths so UI toggles can reach this
        # runtime. Callers that build their own SkillsManagerConfig stay
        # in charge; bare construction auto-wires the standard paths.
        colony_id = binding.name if binding is not None else None
        _effective_cfg = skills_manager_config
        if _effective_cfg is None and not (skills_catalog_prompt or protocols_prompt):
            _effective_cfg = self._build_default_skills_config(colony_id, queen_id)

        if _effective_cfg is not None:
            self._skills_manager = SkillsManager(_effective_cfg)
            self._skills_manager.load()
        elif skills_catalog_prompt or protocols_prompt:
            import warnings

            warnings.warn(
                "Passing pre-rendered skills_catalog_prompt/protocols_prompt is deprecated. Pass skills_manager_config instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._skills_manager = SkillsManager.from_precomputed(skills_catalog_prompt, protocols_prompt)
        else:
            self._skills_manager = SkillsManager()
            self._skills_manager.load()

        self.skill_dirs: list[str] = self._skills_manager.allowlisted_dirs

        self._accounts_prompt = accounts_prompt
        self._accounts_data = accounts_data
        self._tool_provider_map = tool_provider_map
        self._dynamic_memory_provider_factory: Callable[[str], Callable[[], str] | None] | None = None

        storage_path_obj = Path(storage_path) if isinstance(storage_path, str) else storage_path
        self._storage_path: Path = storage_path_obj
        self._storage = ConcurrentStorage(
            base_path=storage_path_obj,
            cache_ttl=self._config.cache_ttl,
            batch_interval=self._config.batch_interval,
        )
        self._session_store = SessionStore(storage_path_obj)

        self._event_bus = event_bus or EventBus(max_history=self._config.max_history)
        self._scoped_event_bus = StreamEventBus(self._event_bus, self._stream_id)

        # Make the event bus visible to the task-system event emitters so
        # task lifecycle events fan out to the same bus the rest of the
        # system uses. Idempotent — last writer wins.
        try:
            from framework.tasks.events import set_default_event_bus

            set_default_event_bus(self._event_bus)
        except Exception:
            logger.debug("Failed to register default task event bus", exc_info=True)

        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor

        # Per-colony MCP tool allowlist — applied when spawning workers. A
        # value of ``None`` means "allow every MCP tool" (default), an empty
        # list disables every MCP tool, and a list of names only enables
        # those. Lifecycle / synthetic tools always pass through the filter
        # because their names are absent from ``_mcp_tool_names_all``. The
        # allowlist is re-read on every ``spawn`` so a PATCH that mutates
        # this attribute via ``set_tool_allowlist`` takes effect on the
        # NEXT worker spawn without a runtime restart. In-flight workers
        # keep the tool list they booted with — workers have no dynamic
        # tools provider today.
        self._enabled_mcp_tools: list[str] | None = None
        self._mcp_tool_names_all: set[str] = set()

        # Worker management
        self._workers: dict[str, Worker] = {}
        # Pending fan-out queue. When spawn_batch is called with more
        # tasks than colony.max_concurrent_workers can run at once, the
        # excess tasks land here in FIFO order. Each entry is a fully
        # realized Worker (status=QUEUED, no AgentLoop spawned yet)
        # plus enough state to call ``_start_queued_worker`` later.
        # Workers terminate via ``_publish_terminal_events``; the
        # ``_drain_pending_queue`` callback runs after each terminal
        # event and promotes queued workers to RUNNING up to the cap.
        from collections import deque as _deque

        self._pending_queue: _deque[Worker] = _deque()
        # Lock guarding _pending_queue + _workers transitions when the
        # scheduler is mid-promotion. Coarse-grained because we promote
        # at most a handful at a time and the promotion path is short.
        self._scheduler_lock = asyncio.Lock()
        # Dispatch gate. Set by a user-initiated stop; every admission goes
        # through _enqueue_or_admit_worker, which refuses while this is on.
        # Without it a queen turn that is still unwinding can spawn fresh
        # workers *into the middle of the stop sweep*, so "stop everything"
        # silently doesn't stick. Cleared by resume_dispatch() when the user
        # sends their next message.
        self._dispatch_blocked = False
        # Adaptive operating budget state (colony-wide, in-memory —
        # restart = cold start, intentionally). ``_budget_samples`` holds
        # tool_calls_used of qualifying successes; ``_budget_applied`` is
        # the current colony nominal (None until the first shrink). Both
        # are only touched from the event-loop thread (terminal-event
        # subscriber + admission paths), no extra locking needed.
        self._budget_samples: _deque[int] = _deque(maxlen=_ADAPTIVE_BUDGET_SAMPLE_WINDOW)
        self._budget_applied: int | None = None
        # Colony-lifetime max of admitted samples. The 1.25x max-guard
        # reads THIS, not the windowed max: with a windowed max, 50 cheap
        # samples could evict the one expensive success and let the norm
        # ratchet below evidence already gathered (death-spiral re-opened).
        # Same lifetime as the monotone _budget_applied.
        self._budget_max_success: int = 0
        # The persistent client-facing overseer (optional). Set by
        # ``start_overseer()`` at session start. In a DM session the
        # overseer is the queen chatting with the user with 0 parallel
        # workers. In a colony session she's the queen orchestrating N
        # parallel workers.
        self._overseer: Worker | None = None
        self._triggers: dict[str, TriggerSpec] = {}
        self._trigger_definitions: dict[str, TriggerDefinition] = {}

        # Timer/webhook infrastructure
        self._event_subscriptions: list[str] = []
        self._timer_tasks: list[asyncio.Task] = []
        self._timer_next_fire: dict[str, float] = {}
        self._webhook_server: Any = None
        # Background tasks owned by the runtime that aren't timers —
        # e.g. the per-spawn soft/hard timeout watchers kicked off by
        # run_worker. We hold strong references so asyncio
        # does not garbage-collect them mid-sleep (Python's asyncio
        # docs explicitly warn that create_task() needs a referenced
        # handle).
        self._background_tasks: set[asyncio.Task] = set()

        # Idempotency
        self._idempotency_keys: OrderedDict[str, str] = OrderedDict()
        self._idempotency_times: dict[str, float] = {}

        # User presence
        self._last_user_input_time: float = 0.0

        # Result retention
        self._execution_results: OrderedDict[str, WorkerResult] = OrderedDict()
        self._execution_result_times: dict[str, float] = {}

        self._running = False
        self._timers_paused = False
        self._lock = asyncio.Lock()

        self.intro_message: str = ""

    @property
    def skills_catalog_prompt(self) -> str:
        # Phase-filter once this runtime is bound to a real colony, so a worker
        # sees the same catalog its overseer does — `visibility: [colony]` skills
        # in, `[independent]` ones (the CRM setup skill) out. The queen gets this
        # filtering from QueenPhaseState; workers read the catalog from here and
        # were the one path it never reached. Unbound (a DM session) keeps the
        # unfiltered catalog: there is no colony phase to filter to.
        if self._binding is not None:
            return self._skills_manager.skills_catalog_prompt_for_phase("colony")
        return self._skills_manager.skills_catalog_prompt

    @property
    def protocols_prompt(self) -> str:
        return self._skills_manager.protocols_prompt

    @property
    def stream_id(self) -> str:
        """Event-bus broadcast scope (= owning session.id)."""
        return self._stream_id

    @property
    def agent_id(self) -> str:
        return self._stream_id

    @property
    def goal(self) -> Goal:
        """The colony's overall goal.

        Exposed as a public property for queen lifecycle tools that
        introspect the runtime (e.g. ``get_worker_status``,
        ``get_goal_progress``). Previously only available as the private
        ``_goal`` attribute.
        """
        return self._goal

    @property
    def overseer(self) -> Worker | None:
        """The colony's long-running client-facing overseer worker.

        ``None`` until ``start_overseer()`` has been called. The overseer
        is a persistent ``Worker`` that wraps the queen's ``AgentLoop``
        and routes user chat via ``inject(message)``.
        """
        return self._overseer

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def timers_paused(self) -> bool:
        return self._timers_paused

    @property
    def user_idle_seconds(self) -> float:
        if self._last_user_input_time == 0.0:
            return float("inf")
        return time.monotonic() - self._last_user_input_time

    @property
    def agent_idle_seconds(self) -> float:
        if not self._workers:
            return float("inf")
        min_idle = float("inf")
        now = time.monotonic()
        for w in self._workers.values():
            if w.is_active and w._started_at > 0:
                idle = now - w._started_at
                if idle < min_idle:
                    min_idle = idle
        bus_idle = now - self._scoped_event_bus.last_activity_time
        return min(min_idle, bus_idle)

    @property
    def active_worker_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.is_active)

    @property
    def total_worker_count(self) -> int:
        """All workers registered in this runtime — active + finished + queued.

        Strictly in-memory: covers the lifetime of this ``ColonyRuntime``
        instance, not the on-disk colony's full history. Finished workers
        stay in ``_workers`` until the runtime is torn down, so this is a
        cumulative session count rather than a live gauge.
        """
        return len(self._workers)

    def _apply_pipeline_results(self) -> None:
        for stage in self._pipeline.stages:
            if stage.tool_registry is not None:
                # Register task tools on the same registry every worker
                # pulls from. Done here (not at worker spawn) so the
                # colony's `_tools` snapshot includes them.
                try:
                    from framework.tasks.tools import register_task_tools

                    register_task_tools(stage.tool_registry)
                except Exception:
                    logger.warning(
                        "Failed to register task tools on pipeline registry",
                        exc_info=True,
                    )

                # Tracker tools: workers get tracker_upsert only. The
                # queen-only pair (tracker_sql, tracker_register_writable)
                # is registered on the queen's separate registry. Even
                # though worker.json's ``tools`` list is filtered at fork
                # time, restricting registration here is defense-in-depth
                # so a non-LLM caller can't invoke them through this
                # registry's executor.
                try:
                    from framework.tools.tracker_tools import register_tracker_tools

                    register_tracker_tools(stage.tool_registry, role="worker")
                except Exception:
                    logger.warning(
                        "Failed to register tracker tools on pipeline registry",
                        exc_info=True,
                    )

                # CRM tools: crm_summary (read-only) so a worker that touches the
                # CRM can load the current global state before it writes. The
                # executor must live on the worker registry too — the fork
                # snapshot carries the name, this makes it callable.
                try:
                    from framework.tools.crm_tools import register_crm_tools

                    register_crm_tools(stage.tool_registry, role="worker")
                except Exception:
                    logger.warning(
                        "Failed to register CRM tools on pipeline registry",
                        exc_info=True,
                    )

                # Browser discovery tool (read-only) so a worker driving the
                # browser via the hive-browser CLI keeps the capability visible
                # and the browser-automation skill pre-activated.
                try:
                    from framework.tools.browser_tools import register_browser_tools

                    register_browser_tools(stage.tool_registry, role="worker")
                except Exception:
                    logger.warning(
                        "Failed to register browser tools on pipeline registry",
                        exc_info=True,
                    )

                tools = list(stage.tool_registry.get_tools().values())
                if tools:
                    self._tools = tools
                    self._tool_executor = stage.tool_registry.get_executor()
            if stage.llm is not None and self._llm is None:
                self._llm = stage.llm
            if stage.accounts_prompt:
                self._accounts_prompt = stage.accounts_prompt
                self._accounts_data = stage.accounts_data
                self._tool_provider_map = stage.tool_provider_map
            if stage.skills_manager is not None:
                self._skills_manager = stage.skills_manager

    @staticmethod
    def _load_pipeline_from_config():
        from framework.config import get_hive_config
        from framework.pipeline.registry import build_pipeline_from_config
        from framework.pipeline.runner import PipelineRunner

        config = get_hive_config()
        stages_config = config.get("pipeline", {}).get("stages", [])
        if not stages_config:
            return PipelineRunner([])
        return build_pipeline_from_config(stages_config)

    @staticmethod
    def _build_default_skills_config(
        colony_id: str | None,
        queen_id: str | None,
    ) -> SkillsManagerConfig:
        """Assemble a ``SkillsManagerConfig`` that wires in the per-queen
        override file and the ``queen_ui`` / ``colony_ui`` scope dirs based
        on the standard ``~/.hive`` layout.

        ``colony_id`` must be an actual on-disk colony name
        (``~/.hive/colonies/{name}/``). DM sessions where the ``colony_id``
        is a session UUID should pass ``None`` so we don't scan stray
        directories under a session identifier.
        """
        from framework.agents.queen.queen_profiles import default_skills_for
        from framework.config import COLONIES_DIR, QUEENS_DIR
        from framework.skills.discovery import ExtraScope
        from framework.skills.manager import SkillsManagerConfig

        extras: list[ExtraScope] = []
        queen_overrides_path: Path | None = None
        if queen_id:
            queen_home = QUEENS_DIR / queen_id
            queen_overrides_path = queen_home / "skills_overrides.json"
            extras.append(ExtraScope(directory=queen_home / "skills", label="queen_ui", priority=2))

        # Role-default preset skills (e.g. LinkedIn campaign for marketing
        # queens), applied in-memory just like role-default tools. Sourced
        # from the queen profile — the single place defaults are defined. The
        # colony runtime carries its originating queen_id, so colonies inherit.
        default_preset_skills = default_skills_for(queen_id) if queen_id else frozenset()

        if colony_id:
            colony_home = COLONIES_DIR / colony_id
            # Surface both the new flat ``skills/`` (where new skills are
            # written) and the legacy nested ``.hive/skills/`` (left intact
            # for pre-flatten colonies) as tagged ``colony_ui`` scopes, so
            # UI-created entries resolve with correct provenance regardless
            # of which on-disk layout the colony has.
            extras.append(
                ExtraScope(
                    directory=colony_home / "skills",
                    label="colony_ui",
                    priority=3,
                )
            )
            extras.append(
                ExtraScope(
                    directory=colony_home / ".hive" / "skills",
                    label="colony_ui",
                    priority=3,
                )
            )

        return SkillsManagerConfig(
            queen_id=queen_id,
            queen_overrides_path=queen_overrides_path,
            extra_scope_dirs=extras,
            default_preset_skills=default_preset_skills,
            interactive=False,  # HTTP-driven runtimes never prompt for consent
        )

    @property
    def queen_id(self) -> str | None:
        """The queen that owns this runtime, if known."""
        return self._queen_id

    @property
    def colony_id(self) -> str | None:
        """The on-disk colony name, or ``None`` for a DM session.

        Reads from :attr:`binding`; distinct from :attr:`stream_id`, the
        event-bus broadcast scope.
        """
        return self._binding.name if self._binding is not None else None

    @property
    def binding(self) -> ColonyBinding | None:
        """The on-disk :class:`ColonyBinding`, or ``None`` for DM sessions."""
        return self._binding

    def set_binding(self, binding: ColonyBinding) -> None:
        """Attach an on-disk binding after construction.

        Called by ``fork_session_into_colony`` once the queen has named
        the colony and ``ensure_tracker_db`` has materialized the DB.
        """
        self._binding = binding

    @property
    def skills_manager(self):
        """Access the live :class:`SkillsManager` (for HTTP handlers)."""
        return self._skills_manager

    async def reload_skills(self) -> dict[str, Any]:
        """Rebuild the catalog after an override change; in-flight workers
        pick up the new catalog on their next iteration via
        ``dynamic_skills_catalog_provider``.

        Returns a small stats dict that HTTP handlers can echo back to
        the UI ("applied — N skills now in catalog").
        """
        async with self._skills_manager.mutation_lock:
            self._skills_manager.reload()
            self.skill_dirs = self._skills_manager.allowlisted_dirs
            catalog_prompt = self._skills_manager.skills_catalog_prompt
            return {
                "catalog_chars": len(catalog_prompt),
                "skill_dirs": list(self.skill_dirs),
            }

    # ── Per-colony tool allowlist ───────────────────────────────

    def set_tool_allowlist(
        self,
        enabled_mcp_tools: list[str] | None,
        mcp_tool_names_all: set[str] | None = None,
    ) -> None:
        """Configure the per-colony MCP tool allowlist.

        Called at construction time (from SessionManager) and again from
        the ``/api/colony/{name}/tools`` PATCH handler when a user edits
        the allowlist. The change applies to the NEXT worker spawn — we
        never mutate the tool pool of a worker that is already running
        (a tiered worker's dynamic tools provider only ever GROWS its
        eager set via search_tools; the underlying pool stays the spawn
        snapshot, so hot-reloading it would diverge from what the LLM
        already saw).
        """
        self._enabled_mcp_tools = list(enabled_mcp_tools) if enabled_mcp_tools is not None else None
        if mcp_tool_names_all is not None:
            self._mcp_tool_names_all = set(mcp_tool_names_all)

    def _apply_tool_allowlist(self, tools: list) -> list:
        """Filter ``tools`` against the colony's MCP allowlist.

        Lifecycle / synthetic tools (those whose names are NOT in
        ``_mcp_tool_names_all``) are never gated. MCP tools are kept only
        when ``_enabled_mcp_tools`` is None (default allow) or contains
        their name. Input list order is preserved so downstream cache
        keys and logs stay stable.
        """
        if self._enabled_mcp_tools is None:
            return tools
        allowed = set(self._enabled_mcp_tools)
        return [t for t in tools if getattr(t, "name", None) not in self._mcp_tool_names_all or getattr(t, "name", None) in allowed]

    # ── Scheduler (parallel-worker concurrency cap + queueing) ──

    def _running_worker_count(self, *, exclude_id: str | None = None) -> int:
        """Count workers actively running (PENDING or RUNNING).

        Excludes QUEUED workers (waiting to be promoted) and terminal
        statuses. This is what we compare against
        ``max_concurrent_workers`` to decide whether new work admits
        immediately or queues.

        ``exclude_id`` skips that worker from the count — used by the
        admission decision so a freshly-registered worker (status
        defaults to PENDING in __init__, before admission flips it)
        doesn't count itself toward the cap.
        """
        from framework.host.worker import WorkerStatus

        return sum(1 for wid, w in self._workers.items() if wid != exclude_id and w.status in (WorkerStatus.PENDING, WorkerStatus.RUNNING))

    async def _drain_pending_queue(self) -> int:
        """Promote queued workers to running, up to the colony cap.

        Returns the number of workers promoted on this drain. Callers:
        - ``spawn`` after a fresh admission decision (in case the cap
          shifted between the queue-decision and the drain).
        - The SUBAGENT_REPORT subscriber after every worker terminal
          event — that's the typical promotion trigger.

        Idempotent and safe to over-call. The scheduler lock is held
        for the dequeue + start_background sequence so two concurrent
        drains can't both promote the same worker.
        """
        promoted = 0
        async with self._scheduler_lock:
            cap = self._config.max_concurrent_workers
            while self._pending_queue and self._running_worker_count() < cap:
                worker = self._pending_queue.popleft()
                # Worker may have been cancelled between queue and drain
                # (colony.stop on a queued worker synthesises a terminal
                # report and dequeues separately). Defensive check.
                from framework.host.worker import WorkerStatus

                if worker.status != WorkerStatus.QUEUED:
                    continue
                # Promote: QUEUED → PENDING. start_background flips
                # PENDING → RUNNING inside the run() coroutine.
                worker.status = WorkerStatus.PENDING
                # The colony norm may have shrunk while this worker sat
                # queued — clamp with the freshest nominal before start.
                self._apply_adaptive_budget(worker)
                try:
                    await worker.start_background()
                    promoted += 1
                    logger.info(
                        "Scheduler: promoted queued worker %s (batch=%s, idx=%d/%d) — now running %d/%d",
                        worker.id,
                        worker.batch_id or "-",
                        worker.batch_index,
                        worker.batch_size,
                        self._running_worker_count(),
                        cap,
                    )
                except Exception:
                    logger.exception(
                        "Scheduler: failed to promote queued worker %s",
                        worker.id,
                    )
                    worker.status = WorkerStatus.FAILED
        return promoted

    async def _on_worker_terminal_event(self, event: AgentEvent) -> None:
        """Bus subscriber that drains the pending queue on each terminal.

        Subscribed to SUBAGENT_REPORT during ``start()``. Every parallel
        worker fires exactly one SUBAGENT_REPORT when it terminates
        (success / failed / stopped / timeout / auto-failed); each one
        is an opportunity to start a queued sibling.
        """
        # Filter: only drain when a worker we own just terminated.
        # Reports from other colonies (cross-colony bus reach) shouldn't
        # trigger our scheduler.
        try:
            data = event.data or {}
            colony_id = data.get("colony_id")
            if colony_id and colony_id != self._stream_id:
                return
            # Adapt BEFORE draining so a worker promoted by this very
            # event starts with the freshest nominal budget.
            self._maybe_adapt_colony_budget(data)
            await self._drain_pending_queue()
        except Exception:
            logger.exception("Scheduler: drain on SUBAGENT_REPORT failed (non-fatal)")

    def _maybe_adapt_colony_budget(self, data: dict[str, Any]) -> None:
        """Feed one terminal report into the colony's adaptive budget.

        Successful workers define the norm: on each qualifying success we
        recompute the colony nominal and — when it shrank — clamp every
        unpinned in-flight worker via ``AgentLoop.apply_lifetime_budget_cap``
        (honored at the worker's next iteration boundary, riding the
        existing budget-grace wind-down). Queued workers pick the nominal
        up at promotion; see ``_apply_adaptive_budget``.

        The nominal moves asymmetrically: it shrinks on the composite
        statistical estimate, but raises only on the max-guard — see the
        evidence-driven raise below.

        Sample admission is strict — censored observations must exert
        zero force on the norm:
        - status must be "success" (worker-reported; partial/failed/
          stopped/timeout excluded),
        - budget_limited reports are excluded (the framework cut that
          worker off; its consumption is a censored data point),
        - pinned workers are excluded (explicit queen budget override,
          playbook dispatches, resumed workers, the persistent overseer),
        - zero-call successes are degenerate and excluded.

        Never raises: caller wraps in the subscriber's try/except, and a
        budget-adaptation bug must never break scheduling.
        """
        if not self._config.adaptive_tool_budget:
            return
        if data.get("status") != "success" or data.get("budget_limited") or data.get("budget_pinned"):
            return
        used = data.get("tool_calls_used")
        if not isinstance(used, int) or used <= 0:
            return
        self._budget_samples.append(used)
        self._budget_max_success = max(self._budget_max_success, used)
        if len(self._budget_samples) < _ADAPTIVE_BUDGET_MIN_SAMPLES:
            return

        import math
        import statistics

        samples = sorted(self._budget_samples)
        median = statistics.median(samples)
        p90 = samples[min(len(samples) - 1, math.ceil(0.9 * len(samples)) - 1)]
        if p90 > _ADAPTIVE_BUDGET_DISPERSION_LIMIT * median:
            # Dispersion guard: visibly heterogeneous work → no single norm.
            return
        # Base = the worker profile's configured ceiling. Workers spawned
        # with an explicit queen override are pinned and never clamped, so
        # the profile default is the right cap for everyone adaptable.
        from framework.agents.queen.worker_definition import DEFAULT_LOOP_CONFIG

        base = int(DEFAULT_LOOP_CONFIG["tool_call_lifetime_budget"])
        if base <= 0:
            return  # budget disabled at the profile level — nothing to adapt
        # Median/p90 read the recency window; the max-guard reads the
        # colony-lifetime max so window eviction can't erode it.
        nominal = max(
            math.ceil(_ADAPTIVE_BUDGET_MULTIPLIER * median),
            math.ceil(_ADAPTIVE_BUDGET_MAX_GUARD * self._budget_max_success),
        )
        nominal = max(_ADAPTIVE_BUDGET_FLOOR, min(nominal, base))
        current = self._budget_applied if self._budget_applied is not None else base
        if nominal < current:
            self._budget_applied = nominal
            logger.info(
                "Colony %s: adaptive tool budget %d -> %d (samples=%d, median=%.1f, max=%d)",
                self._stream_id,
                current,
                nominal,
                len(samples),
                median,
                self._budget_max_success,
            )
            from framework.host.worker import WorkerStatus

            for w in self._workers.values():
                if w.budget_pinned or w.is_persistent:
                    continue
                if w.status not in (WorkerStatus.PENDING, WorkerStatus.RUNNING):
                    continue
                try:
                    w.agent_loop.apply_lifetime_budget_cap(nominal)
                except Exception:
                    logger.debug("adaptive budget clamp failed for %s", w.id, exc_info=True)
            return

        # Evidence-driven raise. Shrinking is statistical (the median may be
        # depressed by survivorship once a clamp is censoring the expensive
        # tail), so raising must NOT be: only the max-guard — a cost a worker
        # has actually been observed to succeed at, never a censored one —
        # may push the nominal back up. Without this the nominal is a one-way
        # ratchet: a colony whose workload gets more expensive clamps every
        # worker at the stale norm, and each cutoff is excluded from the
        # samples, so it can never learn it was wrong.
        #
        # Self-healing without any extra tool-call spend: successes still land
        # under the current cap, so a worker finishing just below it lifts
        # max_success, and the floor climbs ~MAX_GUARD x per near-cap success
        # until it re-saturates ``base``. Monotone (max_success only grows,
        # capped at base) so raises cannot oscillate with shrinks, and the
        # worst case is simply the pre-adaptive fixed ceiling.
        #
        # In-flight workers are deliberately NOT re-broadcast: the setter is
        # shrink-only and refuses raises. Already-clamped workers finish under
        # the old, lower cap; newly spawned/promoted ones pick the raised
        # nominal up via _apply_adaptive_budget.
        evidence_floor = min(
            base,
            max(_ADAPTIVE_BUDGET_FLOOR, math.ceil(_ADAPTIVE_BUDGET_MAX_GUARD * self._budget_max_success)),
        )
        if evidence_floor <= current:
            return
        self._budget_applied = evidence_floor
        logger.info(
            "Colony %s: adaptive tool budget raised %d -> %d (max success=%d, samples=%d)",
            self._stream_id,
            current,
            evidence_floor,
            self._budget_max_success,
            len(samples),
        )

    def _apply_adaptive_budget(self, worker: Worker) -> None:
        """Clamp one worker to the current colony nominal (idempotent).

        Called right before ``start_background()`` on both admission
        paths so queued workers promoted after a shrink — and workers
        spawned into a colony that already has a norm — start clamped.
        Shrink-only by construction (the setter refuses raises), so
        double application is harmless.
        """
        nominal = self._budget_applied
        if nominal is None or worker.budget_pinned or worker.is_persistent:
            return
        if not self._config.adaptive_tool_budget:
            return
        try:
            worker.agent_loop.apply_lifetime_budget_cap(nominal)
        except Exception:
            logger.debug("adaptive budget clamp failed for %s", worker.id, exc_info=True)

    def block_dispatch(self) -> None:
        """Refuse new workers until the user speaks again. See ``_dispatch_blocked``."""
        self._dispatch_blocked = True

    def resume_dispatch(self) -> None:
        """Re-open dispatch. Called when the user sends their next message —
        the same moment the queen's ``_user_stopped`` flag is cleared."""
        if self._dispatch_blocked:
            logger.info("ColonyRuntime: dispatch re-opened (colony=%s)", self._stream_id)
        self._dispatch_blocked = False

    async def _enqueue_or_admit_worker(self, worker: Worker) -> bool:
        """Decide whether to start a worker now or queue it.

        Caller has already constructed the Worker (all heavy I/O —
        storage dir, AgentLoop — is done) and added
        it to ``self._workers``. We just decide whether to call
        ``start_background()`` immediately (cap has slack) or stash in
        ``_pending_queue`` (cap saturated).

        Returns True when admitted (started), False when queued OR refused.

        This is the single admission chokepoint every spawn path funnels
        through, which is why the stop gate lives here: nothing can route
        around it.
        """
        from framework.host.worker import WorkerStatus

        if self._dispatch_blocked:
            # The user stopped this colony. A queen turn that is still
            # unwinding must not be able to spawn workers into the middle of
            # the sweep. Mark terminal + report so the queen's batch counter
            # still resolves instead of waiting on a worker that never runs.
            worker.status = WorkerStatus.STOPPED
            logger.info(
                "Scheduler: refused worker %s — colony is stopped (dispatch blocked)",
                worker.id,
            )
            await self._publish_stopped_report(worker, "Colony was stopped — this task was never started.")
            return False

        async with self._scheduler_lock:
            cap = self._config.max_concurrent_workers
            # Exclude the worker being admitted: it's already in
            # self._workers (added before this call) with the default
            # PENDING status, but PENDING is what we count. Skipping
            # it avoids self-counting that would push every batch's
            # first worker straight into the queue.
            running = self._running_worker_count(exclude_id=worker.id)
            if running < cap:
                # Slack available — go. start_background() will
                # transition PENDING → RUNNING via worker.run().
                # A colony that already learned a norm applies it to
                # fresh spawns too (late spawns into a running fan-out).
                self._apply_adaptive_budget(worker)
                await worker.start_background()
                return True
            # At cap. Queue.
            worker.status = WorkerStatus.QUEUED
            self._pending_queue.append(worker)
            logger.info(
                "Scheduler: queued worker %s (batch=%s, idx=%d/%d) — running %d/%d, queue depth %d",
                worker.id,
                worker.batch_id or "-",
                worker.batch_index,
                worker.batch_size,
                running,
                cap,
                len(self._pending_queue),
            )
            return False

    async def _publish_stopped_report(self, worker: Worker, summary: str) -> None:
        """Synthesize a terminal ``SUBAGENT_REPORT`` for a worker that never ran.

        We can't go through ``Worker._emit_terminal_events`` because the worker
        never started (no result, no AgentLoop run state), so mirror the same
        shape here. This is not cosmetic: the queen's batch counter only
        resolves when every worker in the batch reports, so a worker that is
        stopped without a report leaves the queen waiting on it forever.

        ``subagent_report`` is in ``events_policy.WORKER_META_TYPES``, so this
        reaches the queen's log and SSE even with per-worker event logs enabled.
        """
        if self._scoped_event_bus is None:
            return
        from framework.host.event_bus import AgentEvent, EventType

        try:
            await self._scoped_event_bus.publish(
                AgentEvent(
                    type=EventType.SUBAGENT_REPORT,
                    stream_id=worker._context.stream_id or worker.id,
                    node_id=worker.id,
                    execution_id=worker._context.execution_id or worker.id,
                    data={
                        "worker_id": worker.id,
                        "colony_id": self._stream_id,
                        "task": worker.task,
                        "status": "stopped",
                        "summary": summary,
                        "data": {},
                        "error": None,
                        "duration_seconds": 0.0,
                        "tokens_used": 0,
                        "batch_id": worker.batch_id,
                        "batch_index": worker.batch_index,
                        "batch_size": worker.batch_size,
                        "output_file": worker.output_file,
                    },
                )
            )
        except Exception:
            logger.exception(
                "Scheduler: failed to synthesise stopped report for worker %s",
                worker.id,
            )

    async def _cancel_queued_workers(self) -> int:
        """Stop every QUEUED worker and synthesize its terminal report.

        Queued workers never started, so there is no task to cancel — they are
        invisible to ``stop_all_workers()``. Without this they'd both (a) vanish
        silently from the queen's batch, and (b) be *promoted and started* by
        ``_drain_pending_queue`` after the user already stopped everything.

        Returns the count of cancelled workers.
        """
        from framework.host.worker import WorkerStatus

        cancelled = 0
        async with self._scheduler_lock:
            queued = list(self._pending_queue)
            self._pending_queue.clear()
        for worker in queued:
            if worker.status != WorkerStatus.QUEUED:
                continue
            worker.status = WorkerStatus.STOPPED
            await self._publish_stopped_report(
                worker,
                "Worker was queued behind the concurrency cap and never started — stopped before its slot opened.",
            )
            cancelled += 1
        if cancelled:
            logger.info("Scheduler: cancelled %d queued worker(s)", cancelled)
        return cancelled

    # ── Lifecycle ───────────────────────────────────────────────

    def _worker_storage_dir(self, worker_id: str) -> Path:
        """Where a spawned worker's run state lives."""
        from framework.config import colony_workers_dir

        if self._binding is not None:
            return colony_workers_dir(self._binding.name) / worker_id
        return self._storage_path / "workers" / worker_id

    def _install_worker_log_resolver(self) -> None:
        """Route worker chatter to per-worker event logs instead of the queen's.

        Off by default. The queen's log keeps every worker's META events either
        way (start / progress / finish), so her bubbles survive; what this
        moves out is the per-turn chatter, which nothing reads back from her
        log and which is shipped over the network on every history fetch when
        the runtime is remote.

        Gated because the desktop must first render worker bubbles from META
        alone — until it ships, a worker's bubble content on reload still comes
        from the chatter sitting in the queen's log.
        """
        if os.environ.get("HIVE_SPLIT_WORKER_EVENTS", "").lower() not in (
            "1",
            "true",
            "yes",
        ):
            return

        def _resolve(stream_id: str) -> Path | None:
            # Only parallel workers ("worker:<uuid>") have a directory of their
            # own. The bare "worker" tag used by single spawns does not, so it
            # falls back to the queen's log.
            if not stream_id.startswith("worker:"):
                return None
            worker_id = stream_id.split(":", 1)[1].strip()
            if not worker_id:
                return None
            return self._worker_storage_dir(worker_id) / "events.jsonl"

        self._event_bus.set_worker_log_resolver(_resolve)
        logger.info("ColonyRuntime: per-worker event logs enabled (colony=%s)", self._binding.name if self._binding else "-")

    async def start(self) -> None:
        if self._running:
            return

        async with self._lock:
            await self._storage.start()
            await self._pipeline.initialize_all()
            self._apply_pipeline_results()

            self._install_worker_log_resolver()

            # Subscribe the scheduler to SUBAGENT_REPORT so the pending
            # queue drains automatically as workers terminate. Stored
            # in _event_subscriptions so it gets cleaned up in stop().
            try:
                _sched_sub = self._scoped_event_bus.subscribe(
                    event_types=[EventType.SUBAGENT_REPORT],
                    handler=self._on_worker_terminal_event,
                )
                self._event_subscriptions.append(_sched_sub)
            except Exception:
                logger.warning(
                    "ColonyRuntime: failed to subscribe scheduler drain handler",
                    exc_info=True,
                )

            if self._config.webhook_routes:
                from framework.host.webhook_server import (
                    WebhookRoute,
                    WebhookServer,
                    WebhookServerConfig,
                )

                wh_config = WebhookServerConfig(
                    host=self._config.webhook_host,
                    port=self._config.webhook_port,
                )
                self._webhook_server = WebhookServer(self._event_bus, wh_config)
                for rc in self._config.webhook_routes:
                    route = WebhookRoute(
                        source_id=rc["source_id"],
                        path=rc["path"],
                        methods=rc.get("methods", ["POST"]),
                        secret=rc.get("secret"),
                    )
                    self._webhook_server.add_route(route)
                await self._webhook_server.start()

            await self._start_timers()
            await self._skills_manager.start_watching()

            self._running = True
            self._timers_paused = False
            logger.info(
                "ColonyRuntime started: colony_id=%s, triggers=%d",
                self._stream_id,
                len(self._triggers),
            )

    async def stop(self) -> None:
        if not self._running:
            return

        async with self._lock:
            # Full cascade: queued workers are cancelled (they never started, so
            # the running registry can't reach them) and the live ones — the
            # overseer included — are stopped concurrently on a timeout. See
            # stop_workers().
            await self.stop_all_workers()

            # Cancel timer tasks and *wait* for them to finish. Without
            # the wait the tasks are merely scheduled for cancellation —
            # if the runtime (or its event loop) shuts down before they
            # run their cleanup code, trigger state leaks.
            pending_timers = [t for t in self._timer_tasks if not t.done()]
            for task in pending_timers:
                task.cancel()
            if pending_timers:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*pending_timers, return_exceptions=True),
                        timeout=5.0,
                    )
                except TimeoutError:
                    logger.warning(
                        "ColonyRuntime.stop: %d timer task(s) did not finish within 5s",
                        sum(1 for t in pending_timers if not t.done()),
                    )
            self._timer_tasks.clear()

            for sub_id in self._event_subscriptions:
                self._event_bus.unsubscribe(sub_id)
            self._event_subscriptions.clear()

            if self._webhook_server:
                await self._webhook_server.stop()
                self._webhook_server = None

            await self._skills_manager.stop_watching()
            await self._storage.stop()

            self._running = False
            logger.info("ColonyRuntime stopped: colony_id=%s", self._stream_id)

    def _on_timer_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Timer task '%s' crashed: %s",
                task.get_name(),
                exc,
                exc_info=exc,
            )

    def pause_timers(self) -> None:
        self._timers_paused = True

    def resume_timers(self) -> None:
        self._timers_paused = False

    # ── Worker Spawning ─────────────────────────────────────────

    def _build_worker(
        self,
        *,
        worker_id: str,
        worker_storage: Path,
        task: str,
        input_data: dict[str, Any] | None,
        spawn_spec: AgentSpec,
        spawn_tools: list[Any],
        spawn_executor: Callable | None,
        spawn_catalog: str,
        spawn_skill_dirs: list[Any],
        profile_name_resolved: str,
        profile_integrations: dict[str, str],
        profile_browser: str,
        explicit_stream_id: str | None,
        loop_config_overrides: dict[str, Any] | None,
        batch_id: str = "",
        batch_index: int = 0,
        batch_size: int = 0,
        worker_seq: int = 0,
        preload_tools: list[str] | None = None,
    ) -> Worker:
        """Construct (but do not register/admit) a single Worker + its
        AgentLoop and AgentContext, pointed at ``worker_storage``.

        The SINGLE construction path shared by ``spawn`` (fresh worker,
        empty store) and ``resume_worker`` (existing worker, populated
        store). Keeping both on this one method is what guarantees a
        resumed worker is built byte-for-byte like the original — same
        AgentContext (agent_id / stream_id / session_id / colony_id /
        binding), same loop config, same Worker wiring — so AgentLoop's
        ``_restore`` reloads the saved conversation transparently. When
        ``worker_storage`` already contains conversation parts + a cursor
        (resume), AgentLoop continues from where it stopped; when it is
        empty (spawn), AgentLoop renders the fresh initial message.
        """
        from framework.agent_loop.agent_loop import AgentLoop
        from framework.storage.conversation_store import FileConversationStore

        worker_conv_store = FileConversationStore(worker_storage / "conversations")

        # AgentLoop takes bus/judge/config/executor at construction;
        # LLM, tools, stream_id, execution_id all come from the
        # AgentContext passed to execute().
        #
        # Every worker — overrides or not — routes through the SINGLE
        # worker config path, ``_build_worker_loop_config``. It builds
        # the worker profile (tool_call_budget=30, hard_multiple=3 ->
        # inner-loop hard stop at 90) and applies any queen-supplied
        # ``loop_config_overrides`` on top. Passing ``{}`` when there
        # are none is a no-op for the override loop, so a worker spawned
        # without overrides still gets the worker profile rather than
        # the neutral ``LoopConfig()`` default (budget 0 = unbounded
        # inner loop) — there is no second, divergent config path.
        #
        # The queen can dial per-worker budgets via the override
        # whitelist (e.g. cheap workers get max_iterations=10, research
        # workers get 80); tool_call_hard_multiple stays framework-locked.
        #
        # Post-spawn, the config is immutable with ONE sanctioned
        # exception: colony budget adaptation may SHRINK
        # tool_call_lifetime_budget on a live loop via
        # AgentLoop.apply_lifetime_budget_cap (boundary-safe: the grace
        # flip re-reads the config every iteration). No other field may
        # be mutated after spawn.
        #
        # spillover_dir / max_tool_result_chars are stamped below: the
        # spill dir is per-worker (path known only here) and worker tool
        # results get the same large 30k budget the queen uses. Without
        # the spillover_dir, worker tool results >8 KB were silently
        # truncated in place with no on-disk copy — large browser HTML /
        # web_search / tracker payloads lost their tails.
        from framework.config import (
            get_max_tool_result_chars as _get_max_trc,
            get_worker_max_context_tokens as _get_worker_max_ctx,
        )

        _spawn_loop_config = _build_worker_loop_config(loop_config_overrides or {})
        _spawn_loop_config.spillover_dir = str(worker_storage / "data")
        _spawn_loop_config.max_tool_result_chars = _get_max_trc()
        # Same config-first resolution the queen gets: worker_llm/llm config
        # key, then the worker model's catalog window, then the legacy
        # default. Skipped entirely when the spawner passed an explicit
        # per-worker budget (whitelisted override) — runtime intent wins.
        if "max_context_tokens" not in (loop_config_overrides or {}):
            _spawn_loop_config.max_context_tokens = _get_worker_max_ctx(
                fallback=_spawn_loop_config.max_context_tokens
            )
        agent_loop = AgentLoop(
            event_bus=self._scoped_event_bus,
            tool_executor=spawn_executor,
            conversation_store=worker_conv_store,
            config=_spawn_loop_config,
        )

        # Workers pick up UI-driven override changes via this provider,
        # which reads the live catalog on each iteration.
        # Default-bind the runtime into the closure so each loop iteration
        # captures the same instance — pyflakes B023 would flag a free-variable
        # capture here. Binds the RUNTIME, not its SkillsManager: the manager's
        # property is phase-agnostic, so reading it directly handed a worker the
        # unfiltered catalog from its second iteration onward — re-introducing
        # the setup-only CRM skill that its spawn catalog had correctly dropped.
        def _provider(runtime=self):
            return runtime.skills_catalog_prompt

        # Each worker owns its own session task list, keyed by its
        # session_id (which equals worker_id for workers).
        _worker_session_id = worker_id

        # ── Worker-side tool tiering (eager/searchable split) ─────────
        # Wired ONLY when a worker keep-set is configured (categories or
        # the ``worker_tools.always_enabled_categories`` config override).
        # With no keep-set the tier is skipped entirely: no dynamic tools
        # provider, no manifest reminder, no synthetic search_tools — the
        # worker path is byte-identical to the pre-tiering runtime.
        _tier = None
        try:
            from framework.agents.queen.queen_tools_defaults import (
                worker_always_enabled_tool_names,
            )

            _keep_set = worker_always_enabled_tool_names()
        except Exception:  # noqa: BLE001 — keep-set resolution is best-effort
            logger.debug("worker keep-set resolution failed", exc_info=True)
            _keep_set = set()
        if _keep_set:
            from framework.config import get_vision_fallback_model
            from framework.llm.capabilities import (
                filter_tools_for_model,
                supports_image_tool_results,
            )
            from framework.tools.tool_tiers import ToolTierState

            # Mirror agent_loop's boot-time image-tool filter: the tier pool
            # becomes the authoritative wire list via dynamic refresh, which
            # bypasses the loop's own filter_tools_for_model pass.
            _tier_pool = list(spawn_tools)
            _tier_model = getattr(self._llm, "model", "") or ""
            _text_only = bool(_tier_model) and not supports_image_tool_results(_tier_model)
            if _tier_model and not (_text_only and get_vision_fallback_model() is not None):
                _tier_pool, _ = filter_tools_for_model(_tier_pool, _tier_model)
            _tier = ToolTierState(
                pool=_tier_pool,
                always_enabled_names=set(_keep_set),
                gateable_names=set(self._mcp_tool_names_all),
                persist_path=worker_storage / "tool_tiers.json",
            )
            _tier.restore_loaded_tools(_tier.load_persisted_tools(), {t.name for t in _tier_pool})
            _tier.rebuild()
            if preload_tools:
                _pool_names = {t.name for t in _tier_pool}
                _valid = [n for n in preload_tools if isinstance(n, str) and n in _pool_names]
                if _valid:
                    _tier.promote_searched_tools(_valid)
            logger.info(
                "Worker %s tool tiering: pool=%d, eager=%d, searchable=%d",
                worker_id,
                len(_tier_pool),
                len(_tier.get_current_tools()),
                len(_tier.get_searchable_tools()),
            )

        # Resolve the colony binding for this worker's reminder
        # sources. Workers carry the binding through input_data
        # (queen_lifecycle_tools.run_worker stamps it on
        # every spawn). Bind the value at spawn time so the closure
        # doesn't reach back into a possibly-mutating dict per render.
        _ctx_binding = None
        _binding_raw = (input_data or {}).get("binding") if isinstance(input_data, dict) else None
        if _binding_raw is not None:
            from framework.host.colony_binding import ColonyBinding

            _ctx_binding = (
                ColonyBinding.from_dict(_binding_raw)
                if isinstance(_binding_raw, dict)
                else (_binding_raw if isinstance(_binding_raw, ColonyBinding) else None)
            )

        agent_context = AgentContext(
            runtime=self._make_runtime_adapter(worker_id),
            agent_id=worker_id,
            agent_spec=spawn_spec,
            input_data=input_data or {"task": task},
            goal_context=self._goal.to_prompt_context(),
            goal=self._goal,
            llm=self._llm,
            available_tools=list(spawn_tools),
            accounts_prompt=self._accounts_prompt,
            skills_catalog_prompt=spawn_catalog,
            protocols_prompt=self.protocols_prompt,
            skill_dirs=spawn_skill_dirs,
            dynamic_skills_catalog_provider=_provider,
            execution_id=worker_id,
            stream_id=explicit_stream_id or f"worker:{worker_id}",
            session_id=_worker_session_id,
            colony_id=self._stream_id,
            # Tracker snapshot source reads through this. Returns the
            # binding bound at spawn (immutable for the worker's
            # lifetime); ``None`` if the spawn didn't carry one — the
            # source self-skips on None.
            colony_binding_provider=lambda b=_ctx_binding: b,
            # Workers intentionally do NOT get colony_stats_provider:
            # fleet visibility is a queen-only concern.
            # Tiered workers (keep-set configured) get the same provider trio
            # the queen wires from QueenPhaseState, backed by this worker's
            # own ToolTierState; None otherwise (split disabled).
            dynamic_tools_provider=(_tier.get_current_tools if _tier is not None else None),
            searchable_tools_provider=(_tier.get_searchable_tools if _tier is not None else None),
            loaded_tool_names_provider=((lambda t=_tier: list(t.loaded_tool_names)) if _tier is not None else None),
            tool_tier_state=_tier,
        )

        return Worker(
            worker_id=worker_id,
            task=task,
            agent_loop=agent_loop,
            context=agent_context,
            event_bus=self._scoped_event_bus,
            stream_id=self._stream_id,
            storage_path=worker_storage,
            profile_name=profile_name_resolved,
            integrations=profile_integrations,
            browser_profile=profile_browser,
            batch_id=batch_id,
            batch_index=batch_index,
            batch_size=batch_size,
            worker_seq=worker_seq,
        )

    async def spawn(
        self,
        task: str,
        count: int = 1,
        input_data: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
        agent_spec: AgentSpec | None = None,
        tools: list[Any] | None = None,
        tool_executor: Callable | None = None,
        stream_id: str | None = None,
        profile_name: str | None = None,
        loop_config_overrides: dict[str, Any] | None = None,
        batch_id: str = "",
        batch_index: int = 0,
        batch_size: int = 0,
        worker_seq: int = 0,
        report_schema: dict[str, Any] | None = None,
        goal: str | None = None,
        preload_tools: list[str] | None = None,
    ) -> list[str]:
        """Spawn worker clones and start them in the background.

        ``preload_tools`` — tool names to promote into a tiered worker's
        eager set at spawn (skips the search_tools discovery round-trip for
        tools the caller KNOWS the task needs). Ignored when worker tiering
        is disabled; unknown names are dropped silently.

        ``goal`` — optional queen-authored one-sentence description of what
        this worker is doing, in end-user language. Seeded as the worker
        session's task-list ``meta.goal`` (and recorded in meta.json) so the
        UI can title the worker card before the worker's first turn; the
        worker's own task_create keeps it unless it explicitly passes a
        replacement (the executor's "existing goal is kept" contract).

        By default each spawn uses the colony's own ``agent_spec``,
        ``tools``, and ``tool_executor`` (set at construction). Pass
        the per-spawn override args to spawn a worker that runs
        DIFFERENT code from the colony default — used by the queen's
        ``run_agent_with_input`` tool to spawn the loaded honeycomb /
        custom worker through the unified runtime, instead of going
        through the deprecated ``AgentHost.trigger`` → ``Orchestrator``
        path that silently dropped ``user_request`` via the buffer
        filter.

        ``stream_id`` controls the SSE stream tag the worker's events
        publish under. Default is ``f"worker:{worker_id}"`` (the
        per-spawn unique tag used by parallel fan-out, which the SSE
        filter at routes_events.py drops to keep the queen DM clean
        of worker noise). Pass an explicit value when you want the
        worker's events to bypass that filter and stream to the queen
        DM. ``run_agent_with_input`` passes ``"worker"`` (singular,
        no colon) so the loaded primary worker's tool calls and LLM
        deltas reach the user's chat tab.

        Returns list of worker IDs.
        """
        if not self._running:
            raise RuntimeError("ColonyRuntime is not running")

        from framework.host.worker_profiles import get_worker_profile

        # Resolve the profile binding for this spawn. ``profile_name=None``
        # means "use the default profile"; an unknown name silently falls
        # back to default (the legacy single-template behavior). The
        # resolved integrations map is threaded into Worker(...) so
        # account_overrides() can pin its MCP tool calls.
        _resolved_profile = get_worker_profile(self._stream_id, profile_name) if profile_name else None
        _profile_name_resolved = _resolved_profile.name if _resolved_profile else (profile_name or "")
        _profile_integrations = dict(_resolved_profile.integrations) if _resolved_profile else {}
        # Chrome browser profile this worker drives (empty → "default"). Threaded
        # into Worker(...) so its browser tools and tab-group reap target the
        # right extension connection / Chrome profile.
        _profile_browser = (_resolved_profile.browser_profile if _resolved_profile else "") or "default"

        # Resolve per-spawn vs colony-default code identity
        spawn_spec = agent_spec or self._agent_spec
        # Per-spawn receipt contract: bind report_schema onto a copy of the spec
        # (workers are clones of the colony spec, so never mutate the shared one).
        # The schema rides the spec → specializes report_to_parent + the worker's
        # system prompt (see build_report_to_parent_tool / prompting).
        if report_schema:
            spawn_spec = spawn_spec.model_copy(update={"report_schema": report_schema})
        spawn_tools = tools if tools is not None else self._tools
        spawn_executor = tool_executor or self._tool_executor

        # Apply the per-colony MCP tool allowlist (if any). Done HERE —
        # after spawn_tools is resolved but before it's frozen into the
        # worker's AgentContext — so the next spawn reflects any PATCH
        # that happened since the last spawn. A value of ``None`` on
        # ``_enabled_mcp_tools`` is a no-op so the default path is
        # unchanged.
        spawn_tools = self._apply_tool_allowlist(spawn_tools)

        # Per-spawn MCP credential filter. The Tool Library always
        # surfaces every credentialed MCP tool so users can pre-enable
        # them, but a worker that can't actually call a tool because
        # the provider has no live OAuth account shouldn't see it in
        # the prompt at all. Drop those names here — the filter is
        # spawn-time, so the moment the user authorises a provider
        # the very next worker spawn picks up the new tools.
        try:
            from framework.credentials.validation import compute_unavailable_mcp_tools

            candidate_names = {getattr(t, "name", None) for t in spawn_tools if getattr(t, "name", None)}
            mcp_drop, mcp_messages = compute_unavailable_mcp_tools(candidate_names)
            if mcp_drop:
                spawn_tools = [t for t in spawn_tools if getattr(t, "name", None) not in mcp_drop]
                logger.info(
                    "Spawn-time MCP filter: dropped %d tool(s) without live credentials [%s]",
                    len(mcp_drop),
                    "; ".join(mcp_messages),
                )
        except Exception:
            logger.debug("Spawn-time MCP credential filter failed", exc_info=True)

        # Workers use the colony's standard skill catalog. Any skill the
        # queen wrote via ``write_skill`` lands in a discovery scope the
        # worker's SkillsManager scans on load, so it appears in the
        # catalog automatically. Activation is model-driven — see the
        # mandatory pre-reply checklist in the catalog header.
        _spawn_catalog = self.skills_catalog_prompt
        _spawn_skill_dirs = self.skill_dirs

        # Resolve the SSE stream_id once. When the caller didn't supply
        # one we use the per-worker fan-out tag (filtered out by the
        # SSE handler). When the caller passed an explicit value we
        # honor it across the whole batch — typically count=1 for the
        # primary loaded worker that needs to stream to the queen DM.
        explicit_stream_id = stream_id

        worker_ids = []
        for i in range(count):
            worker_id = self._session_store.generate_session_id()

            # Per-worker storage is colony-scoped (NOT nested inside the
            # spawning queen's overseer-session subtree). Layout:
            #     <colony>/workers/<worker_id>/
            # Lineage (which queen session spawned this worker) is recorded
            # in meta.json below, since it's no longer encoded by the path.
            # Pure-DM sessions (no binding) keep the legacy queen-session
            # nesting — run_worker requires a binding in practice
            # (see queen_lifecycle_tools.run_worker), so this
            # fallback path is only hit by tests / edge cases.
            if self._binding is not None:
                from framework.config import colony_workers_dir

                worker_storage = colony_workers_dir(self._binding.name) / worker_id
            else:
                worker_storage = self._storage_path / "workers" / worker_id
            worker_storage.mkdir(parents=True, exist_ok=True)

            # Lineage breadcrumb so the UI can answer "which queen session
            # spawned this worker?" without relying on directory nesting.
            # Written once at spawn time; never updated.
            try:
                _meta = {
                    "worker_id": worker_id,
                    "queen_session_id": self._stream_id,
                    "queen_name": self._queen_id,
                    "colony_id": self._binding.name if self._binding else None,
                    "spawned_at": time.time(),
                    "task": (task or "")[:500],
                    "profile_name": _profile_name_resolved,
                    "batch_id": batch_id or None,
                    "batch_index": batch_index,
                    "batch_size": batch_size,
                    "worker_seq": worker_seq,
                    "goal": goal or None,
                }
                (worker_storage / "meta.json").write_text(json.dumps(_meta, indent=2), encoding="utf-8")
            except OSError:
                logger.debug("Failed to write worker meta.json for %s", worker_id, exc_info=True)

            # Seed the queen-authored goal as the worker session's task-list
            # meta.goal BEFORE the loop starts, so the UI has a human title
            # from t=0 (workers' task lists are keyed by worker_id — see
            # _worker_session_id below). Best-effort: a failed seed degrades
            # the display, never the spawn.
            if goal:
                try:
                    from framework.tasks.store import get_task_store

                    await get_task_store().set_goal(worker_id, goal)
                except Exception:
                    logger.debug("Failed to seed worker goal for %s", worker_id, exc_info=True)

            worker = self._build_worker(
                worker_id=worker_id,
                worker_storage=worker_storage,
                task=task,
                input_data=input_data,
                spawn_spec=spawn_spec,
                spawn_tools=spawn_tools,
                spawn_executor=spawn_executor,
                spawn_catalog=_spawn_catalog,
                spawn_skill_dirs=_spawn_skill_dirs,
                profile_name_resolved=_profile_name_resolved,
                profile_integrations=_profile_integrations,
                profile_browser=_profile_browser,
                explicit_stream_id=explicit_stream_id,
                loop_config_overrides=loop_config_overrides,
                batch_id=batch_id,
                batch_index=batch_index,
                batch_size=batch_size,
                worker_seq=worker_seq,
                preload_tools=preload_tools,
            )

            # Budget-adaptation pinning: an explicit queen
            # tool_call_lifetime_budget override means "this exact
            # budget, hands off" — the colony norm neither clamps this
            # worker nor learns from it. Playbook dispatches
            # (worker_seq != 0) are sequential heterogeneous runs, not
            # fan-out siblings, so they are pinned too.
            worker.budget_pinned = worker.budget_pinned or worker_seq != 0 or "tool_call_lifetime_budget" in (loop_config_overrides or {})

            self._workers[worker_id] = worker
            # Scheduler decides: start now (cap has slack) or queue.
            # Queued workers stay registered in self._workers but with
            # status=QUEUED and no AgentLoop background task. The
            # SUBAGENT_REPORT subscriber drains the queue automatically
            # as running peers terminate.
            admitted = await self._enqueue_or_admit_worker(worker)
            worker_ids.append(worker_id)

            logger.info(
                "Spawned worker %s (%d/%d) using %s — %s — task: %s",
                worker_id,
                i + 1,
                count,
                "override spec" if agent_spec else "colony default spec",
                "running" if admitted else "queued",
                task[:80],
            )

        return worker_ids

    async def resume_worker(
        self,
        worker_id: str,
        *,
        tools_override: list[Any] | None = None,
        guidance: str | None = None,
        max_iterations: int | None = None,
        tool_call_lifetime_budget: int | None = None,
        batch_id: str = "",
        batch_index: int = 0,
        batch_size: int = 0,
    ) -> str:
        """Resume a worker that stopped before reporting (a "historical"
        worker), continuing its saved AgentLoop instead of spawning fresh.

        Reuses the worker's on-disk session (conversation parts + cursor)
        left behind by its prior run — nothing deletes a worker's storage,
        so a stopped/timed-out worker can be reloaded. A new Worker +
        AgentLoop are built over the EXISTING store via ``_build_worker``;
        ``AgentLoop._restore`` then reloads the transcript and continues
        from the saved iteration. The cumulative tool-call count is also
        restored from the cursor, so the lifetime tool-call budget remains
        a true cap across resumes.

        Returns the resumed ``worker_id``. Raises ``ValueError`` if the
        worker can't be resumed (unknown id, still active, no saved
        conversation, or it belongs to a different colony) so a batch
        caller can record a per-id failure without aborting the rest.
        """
        if not self._running:
            raise RuntimeError("ColonyRuntime is not running")
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string")
        worker_id = worker_id.strip()

        # Refuse to resume a worker that is still live — two AgentLoops on
        # one store would corrupt its cursor/parts.
        existing = self._workers.get(worker_id)
        if existing is not None and existing.is_active:
            raise ValueError(f"worker {worker_id} is still active ({existing.status}); cannot resume a running worker")

        # Resolve the worker's on-disk home (identical layout to spawn()).
        if self._binding is not None:
            from framework.config import colony_workers_dir

            worker_storage = colony_workers_dir(self._binding.name) / worker_id
        else:
            worker_storage = self._storage_path / "workers" / worker_id
        if not worker_storage.exists():
            raise ValueError(f"worker {worker_id} has no saved state at {worker_storage}")
        # The retention janitor tombstones a worker (result.json._janitor)
        # BEFORE deleting its transcript — refuse here so a resume can't
        # race the deletion and run on a half-removed store.
        result_path = worker_storage / "result.json"
        if result_path.exists():
            try:
                _result = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _result = {}
            if isinstance(_result, dict) and "_janitor" in _result:
                raise ValueError(f"worker {worker_id} was pruned by the retention janitor; its transcript is archived and cannot be resumed")
        parts_dir = worker_storage / "conversations" / "parts"
        if not parts_dir.exists() or not any(parts_dir.glob("*.json")):
            raise ValueError(f"worker {worker_id} has no saved conversation to resume")

        # Recover lineage/profile/task from the spawn-time meta breadcrumb.
        meta: dict[str, Any] = {}
        meta_path = worker_storage / "meta.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                logger.debug("resume_worker: failed to read meta.json for %s", worker_id, exc_info=True)

        # Cross-colony guard: only resume a worker that belongs to THIS colony.
        _meta_colony = meta.get("colony_id")
        _this_colony = self._binding.name if self._binding is not None else None
        if _meta_colony and _this_colony and _meta_colony != _this_colony:
            raise ValueError(f"worker {worker_id} belongs to colony {_meta_colony!r}, not {_this_colony!r}")

        task = str(meta.get("task") or "")
        profile_name = str(meta.get("profile_name") or "") or None

        # Resolve identity the same way spawn() does (profile + tool scope).
        # tools_override carries the queen's CURRENT scope (credential
        # preflight already applied by run_worker); apply the colony
        # allowlist for parity with the spawn path.
        from framework.host.worker_profiles import get_worker_profile

        _resolved_profile = get_worker_profile(self._stream_id, profile_name) if profile_name else None
        _profile_name_resolved = _resolved_profile.name if _resolved_profile else (profile_name or "")
        _profile_integrations = dict(_resolved_profile.integrations) if _resolved_profile else {}
        _profile_browser = (_resolved_profile.browser_profile if _resolved_profile else "") or "default"
        spawn_tools = tools_override if tools_override is not None else list(self._tools)
        spawn_tools = self._apply_tool_allowlist(spawn_tools)

        # Reconstruct input_data with the colony binding so the worker's
        # tracker reminders resolve. The full task already lives in the
        # restored conversation, so the (possibly truncated) meta task is
        # only a fallback for the fresh-message path, which resume never hits.
        input_data: dict[str, Any] = {"task": task}
        if self._binding is not None:
            input_data["binding"] = self._binding.to_dict()

        # Per-resume budget override: the queen can extend the iteration
        # ceiling so a worker that stopped near its limit has room to
        # finish. The lifetime tool-call budget is restored from the cursor
        # (AgentLoop._restore), so it stays a true cap across resumes.
        resume_overrides: dict[str, Any] = {}
        if isinstance(max_iterations, int):
            resume_overrides["max_iterations"] = max_iterations
        if isinstance(tool_call_lifetime_budget, int):
            resume_overrides["tool_call_lifetime_budget"] = tool_call_lifetime_budget

        worker = self._build_worker(
            worker_id=worker_id,
            worker_storage=worker_storage,
            task=task,
            input_data=input_data,
            spawn_spec=self._agent_spec,
            spawn_tools=spawn_tools,
            spawn_executor=self._tool_executor,
            spawn_catalog=self.skills_catalog_prompt,
            spawn_skill_dirs=self.skill_dirs,
            profile_name_resolved=_profile_name_resolved,
            profile_integrations=_profile_integrations,
            profile_browser=_profile_browser,
            explicit_stream_id=None,
            loop_config_overrides=resume_overrides or None,
            batch_id=batch_id,
            batch_index=batch_index,
            batch_size=batch_size,
            worker_seq=0,
        )

        # Optional steering turn from the queen, injected before the loop
        # re-enters. The injection queue is drained at the first resumed
        # iteration boundary (before the LLM streams), so the worker reads
        # it as its latest user turn. is_client_input=True keeps the framing
        # clean; workers don't emit client-io events so nothing else fires.
        if guidance and guidance.strip():
            await worker.agent_loop.inject_event(
                f"[Resume guidance from the queen]: {guidance.strip()}",
                is_client_input=True,
            )

        # Resumed workers are unconditionally exempt from adaptive budget
        # clamping: the cursor restores their cumulative tool-call count,
        # so a colony-norm clamp below it would flip them straight into
        # grace and silently defeat the queen's deliberate resume (often
        # a resume-with-RAISED-budget). They don't feed the sample either.
        worker.budget_pinned = True

        self._workers[worker_id] = worker
        admitted = await self._enqueue_or_admit_worker(worker)
        logger.info(
            "Resumed worker %s (%s) from saved state — task: %s",
            worker_id,
            "running" if admitted else "queued",
            task[:80],
        )
        return worker_id

    async def spawn_batch(
        self,
        tasks: list[dict[str, Any]],
        *,
        tools_override: list[Any] | None = None,
        profile_name: str | None = None,
        loop_config_overrides: dict[str, Any] | None = None,
        batch_id: str | None = None,
        preload_tools: list[str] | None = None,
    ) -> list[str]:
        """Spawn a batch of parallel workers, one per task spec.

        Each task spec is a dict ``{"task": str, "data": dict | None}``.
        Workers start as independent asyncio background tasks and run
        concurrently; this method returns their IDs immediately without
        waiting for completion.

        The overseer's ``run_worker`` tool is the usual
        caller: fire-and-forget, with each worker emitting a
        ``SUBAGENT_REPORT`` event on termination that the queen
        orchestrator turns into a ``[WORKER_REPORT]`` inject. Soft +
        hard timeouts are enforced separately by ``watch_batch_timeouts``.
        ``wait_for_worker_reports`` is only used by ``stop_worker`` now,
        which blocks briefly to harvest reports before returning to the
        queen.

        When ``tools_override`` is supplied, every spawned worker
        receives that tool list instead of the colony's default.  Used
        by ``run_worker`` to drop tools whose credentials
        failed the pre-flight check (so the spawned workers don't
        waste a startup trying to use them).

        Workers see the colony's standard skill catalog. Skills the
        queen authored via ``write_skill`` land in a scope the worker's
        discovery scan picks up, so they show up in ``<available_skills>``
        automatically — the worker activates whichever skill applies on
        demand (progressive disclosure).
        """
        # Stamp every worker in this call with the same batch_id so the
        # queen-side report formatter can correlate reports back to the
        # spawn that produced them (and compute remaining-in-batch as
        # workers complete). When the caller supplies an explicit
        # batch_id we honor it (lets run_worker control the
        # value it surfaces in its own return); otherwise we mint a
        # short timestamped id here.
        if not batch_id:
            import uuid as _uuid
            from datetime import UTC, datetime as _dt

            batch_id = _dt.now(UTC).strftime("rpw_%Y%m%dT%H%M%SZ_") + _uuid.uuid4().hex[:8]
        batch_size = len(tasks)
        worker_ids: list[str] = []
        for batch_index, spec in enumerate(tasks, start=1):
            task_text = str(spec.get("task", ""))
            task_data = spec.get("data")
            if task_data is not None and not isinstance(task_data, dict):
                task_data = {"value": task_data}

            # Per-task budget overrides (max_iterations, tool_call_budget,
            # max_context_tokens). Missing key → batch default; explicit
            # empty {} → "no overrides".
            _per_task_loop = spec.get("loop_config_overrides")
            if _per_task_loop is None:
                _loop_override = dict(loop_config_overrides or {})
            else:
                _loop_override = dict(_per_task_loop)

            # Per-task profile_name override beats the batch-level default,
            # so a fan-out can mix profiles (e.g. half tasks routed to
            # Slack:work and half to Slack:personal).
            # Optional run-scoped dispatch ordinal (playbook dispatches set
            # this so their size-1 batches stay individually identifiable;
            # ordinary fan-out leaves it 0 and relies on batch_index).
            _worker_seq = spec.get("worker_seq")
            _goal = spec.get("goal")
            ids = await self.spawn(
                task=task_text,
                count=1,
                input_data=task_data or {"task": task_text},
                tools=tools_override,
                profile_name=spec.get("profile_name") or profile_name,
                loop_config_overrides=_loop_override or None,
                batch_id=batch_id,
                batch_index=batch_index,
                batch_size=batch_size,
                worker_seq=int(_worker_seq) if _worker_seq else 0,
                report_schema=spec.get("report_schema") or None,
                goal=str(_goal).strip() if isinstance(_goal, str) and _goal.strip() else None,
                # Per-task preload beats the batch-level default (same
                # precedence as profile_name above).
                preload_tools=spec.get("preload_tools") or preload_tools,
            )
            worker_ids.extend(ids)
        return worker_ids

    async def wait_for_worker_reports(
        self,
        worker_ids: list[str],
        timeout: float = 600.0,
    ) -> list[dict[str, Any]]:
        """Block until every worker in ``worker_ids`` has reported.

        Subscribes to ``SUBAGENT_REPORT`` events on the colony event bus
        and collects one report per worker. If a worker has already
        reported (fast completion) the existing ``WorkerResult`` is used
        directly. On timeout, still-running workers are force-stopped
        via ``stop_worker`` and their reports are synthesised as
        ``status="timeout"``.

        Returns a list of report dicts in the same order as
        ``worker_ids``::

            [
                {
                    "worker_id": "...",
                    "status": "success" | "partial" | "failed" | "timeout" | "stopped",
                    "summary": "...",
                    "data": {...},
                    "error": "..." | None,
                    "duration_seconds": 12.3,
                    "tokens_used": 4567,
                },
                ...
            ]
        """
        if not worker_ids:
            return []

        # Reports already in hand (workers that finished before we got here)
        collected: dict[str, dict[str, Any]] = {}
        pending_ids: set[str] = set()

        for wid in worker_ids:
            worker = self._workers.get(wid)
            if worker is None:
                collected[wid] = {
                    "worker_id": wid,
                    "status": "failed",
                    "summary": "Worker not found in registry.",
                    "data": {},
                    "error": "no_such_worker",
                    "duration_seconds": 0.0,
                    "tokens_used": 0,
                }
                continue
            if not worker.is_active and worker._result is not None:
                # Already finished — synthesize from the stored result
                r = worker._result
                collected[wid] = {
                    "worker_id": wid,
                    "status": r.status,
                    "summary": r.summary,
                    "data": r.data,
                    "error": r.error,
                    "duration_seconds": r.duration_seconds,
                    "tokens_used": r.tokens_used,
                }
                continue
            pending_ids.add(wid)

        if not pending_ids:
            return [collected[wid] for wid in worker_ids]

        # Subscribe to SUBAGENT_REPORT events for the remaining workers
        report_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def on_report(event: AgentEvent) -> None:
            data = dict(event.data or {})
            wid = data.get("worker_id")
            if wid and wid in pending_ids:
                await report_queue.put(data)

        sub_id = self._scoped_event_bus.subscribe(
            event_types=[EventType.SUBAGENT_REPORT],
            handler=on_report,
        )

        deadline = time.monotonic() + timeout
        try:
            while pending_ids:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    report = await asyncio.wait_for(report_queue.get(), timeout=remaining)
                except TimeoutError:
                    break
                wid = report.get("worker_id")
                if wid in pending_ids:
                    collected[wid] = report
                    pending_ids.discard(wid)
        finally:
            self._scoped_event_bus.unsubscribe(sub_id)

        # Any still-pending workers are timed out. Force-stop them, then
        # prefer ``worker._result`` over a content-free timeout marker —
        # ``Worker.run``'s CancelledError branch always populates ``_result``
        # before returning, either with an explicit ``report_to_parent``
        # payload that landed just before the cancel OR with the canned
        # "Worker was cancelled before completion." fallback. Surfacing
        # either is strictly more informative than a hardcoded
        # "did not report within Ns" entry, which is what the caller
        # actually needs to summarise what happened.
        for wid in list(pending_ids):
            try:
                await self.stop_worker(wid)
            except Exception:
                logger.exception("Failed to force-stop worker %s on timeout", wid)
            worker = self._workers.get(wid)
            result = worker._result if worker is not None else None
            if result is not None:
                data = dict(result.data) if result.data else {}
                # When the worker was cancelled without ever calling
                # ``report_to_parent`` (canned ``status="stopped"`` from
                # the fallback branch), surface the tail of its on-disk
                # conversation so the queen has SOMETHING to relay about
                # where the worker was. Best-effort; never break the
                # stop path on read failures.
                if result.status == "stopped" and worker is not None:
                    excerpt = await _tail_last_assistant_message(worker)
                    if excerpt:
                        data["last_assistant_excerpt"] = excerpt
                collected[wid] = {
                    "worker_id": wid,
                    # Preserve the worker's own status: an explicit
                    # ``report_to_parent(status='success'|'partial'|'failed')``
                    # that raced in beats "timeout", and the canned
                    # cancel path's ``status='stopped'`` is more honest
                    # than "timeout" since the work did happen — it just
                    # wasn't summarised in time.
                    "status": result.status or "timeout",
                    "summary": result.summary or f"Worker did not report within {timeout:.0f}s.",
                    "data": data,
                    "error": result.error or "timeout",
                    "duration_seconds": result.duration_seconds,
                    "tokens_used": result.tokens_used,
                }
            else:
                # Worker handle is gone (e.g. stop_worker raised) — fall
                # back to the synthetic entry so the caller still sees
                # an item for every requested id.
                duration = 0.0
                if worker is not None and worker._started_at > 0:
                    duration = time.monotonic() - worker._started_at
                collected[wid] = {
                    "worker_id": wid,
                    "status": "timeout",
                    "summary": f"Worker did not report within {timeout:.0f}s.",
                    "data": {},
                    "error": "timeout",
                    "duration_seconds": duration,
                    "tokens_used": 0,
                }
            pending_ids.discard(wid)

        return [collected[wid] for wid in worker_ids]

    async def start_overseer(
        self,
        queen_spec: AgentSpec,
        seed_conversation: list[dict[str, Any]] | None = None,
        queen_tools: list[Any] | None = None,
        initial_prompt: str | None = None,
    ) -> Worker:
        """Start the colony's long-running client-facing overseer.

        The overseer is a persistent ``Worker`` that wraps the queen's
        ``AgentLoop`` and:

        - Never terminates on its own (``persistent=True`` on the Worker).
        - Has the queen's full tool set, streamed with ``stream_id="overseer"``.
        - Receives user chat via ``session.colony_runtime.overseer.inject(msg)``.

        In a queen DM session the overseer runs with 0 parallel workers.
        In a colony session she can spawn parallel workers via the
        ``run_worker`` tool which calls ``spawn_batch`` and
        returns immediately; each spawned worker emits a
        ``SUBAGENT_REPORT`` on termination that the queen orchestrator
        injects back as a ``[WORKER_REPORT]`` turn.

        Pass ``seed_conversation`` to pre-populate the overseer's
        conversation history — used when forking a DM to a colony so
        the overseer starts with the DM's prior context loaded.

        Must be called after ``start()``. Idempotent: calling a second
        time returns the already-started overseer.
        """
        if self._overseer is not None:
            return self._overseer

        if not self._running:
            raise RuntimeError("start_overseer requires the ColonyRuntime to be running (call start() first)")

        from framework.agent_loop.agent_loop import AgentLoop
        from framework.storage.conversation_store import FileConversationStore

        overseer_id = f"overseer:{self._stream_id}"

        # The overseer's conversation lives at the colony session root:
        # {colony_session}/conversations/. Workers get their own sub-dirs
        # under workers/{worker_id}/; the overseer is the root occupant.
        self._storage_path.mkdir(parents=True, exist_ok=True)
        overseer_conv_store = FileConversationStore(self._storage_path / "conversations")
        agent_loop = AgentLoop(
            event_bus=self._scoped_event_bus,
            tool_executor=self._tool_executor,
            conversation_store=overseer_conv_store,
        )

        _overseer_skills_mgr = self._skills_manager
        overseer_ctx = AgentContext(
            runtime=self._make_runtime_adapter(overseer_id),
            agent_id=overseer_id,
            agent_spec=queen_spec,
            input_data={},
            goal_context="",
            goal=self._goal,
            llm=self._llm,
            available_tools=list(queen_tools or self._tools),
            accounts_prompt=self._accounts_prompt,
            skills_catalog_prompt=self.skills_catalog_prompt,
            protocols_prompt=self.protocols_prompt,
            skill_dirs=self.skill_dirs,
            dynamic_skills_catalog_provider=lambda: _overseer_skills_mgr.skills_catalog_prompt,
            execution_id=overseer_id,
            stream_id="overseer",
        )

        overseer = Worker(
            worker_id=overseer_id,
            task="",  # no finite task — persistent conversation
            agent_loop=agent_loop,
            context=overseer_ctx,
            event_bus=self._scoped_event_bus,
            stream_id=self._stream_id,
            persistent=True,
            storage_path=self._storage_path,
        )

        if seed_conversation:
            await overseer.seed_conversation(seed_conversation)

        self._overseer = overseer
        await overseer.start_background()

        if initial_prompt:
            await overseer.inject(initial_prompt)

        logger.info(
            "Started overseer %s for colony %s (seeded=%d messages, initial_prompt=%s)",
            overseer_id,
            self._stream_id,
            len(seed_conversation or []),
            "yes" if initial_prompt else "no",
        )
        return overseer

    async def trigger(
        self,
        trigger_id: str,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
        session_state: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Trigger a worker spawn from a trigger definition.

        Non-blocking — returns worker ID immediately.
        """
        if not self._running:
            raise RuntimeError("ColonyRuntime is not running")

        if idempotency_key is not None:
            self._prune_idempotency_keys()
            cached = self._idempotency_keys.get(idempotency_key)
            if cached is not None:
                return cached

        if self._pipeline.stages:
            from framework.pipeline.stage import PipelineContext

            pipeline_ctx = PipelineContext(
                entry_point_id=trigger_id,
                input_data=input_data,
                correlation_id=correlation_id,
                session_state=session_state,
            )
            pipeline_ctx = await self._pipeline.run(pipeline_ctx)
            input_data = pipeline_ctx.input_data

        task = input_data.get("task", json.dumps(input_data))
        worker_ids = await self.spawn(
            task=task,
            count=1,
            input_data=input_data,
            session_state=session_state,
        )

        worker_id = worker_ids[0] if worker_ids else ""

        if idempotency_key is not None and worker_id:
            self._idempotency_keys[idempotency_key] = worker_id
            self._idempotency_times[idempotency_key] = time.time()

        return worker_id

    async def trigger_and_wait(
        self,
        trigger_id: str,
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> WorkerResult | None:
        worker_id = await self.trigger(trigger_id, input_data, session_state=session_state)
        if not worker_id:
            return None
        return await self.wait_for_worker(worker_id, timeout)

    # ── Worker Control ──────────────────────────────────────────

    async def stop_workers(
        self,
        *,
        worker_ids: list[str] | None = None,
        include_persistent: bool = False,
        block_dispatch: bool = False,
        per_worker_timeout: float = WORKER_STOP_TIMEOUT_SEC,
    ) -> dict[str, Any]:
        """THE cascade. Every stop path funnels through here so they can't drift.

        Callers: the chat Stop button (via ``cancel-queen``), ``POST
        .../workers/stop-all``, ``POST .../workers/{id}/stop``, the queen's
        ``stop_worker`` tool, and colony shutdown.

        Order matters:

        1. **Block new dispatch** (when asked). Without this a queen turn that
           is still running spawns fresh workers *into the middle of the sweep*
           and the stop silently doesn't stick.
        2. **Cancel QUEUED workers.** They never started, so there is no task to
           cancel and they are invisible to a "cancel the running tasks" sweep.
           Left alone, ``_drain_pending_queue`` promotes and *starts* them right
           after the user stopped everything.
        3. **Stop live workers concurrently, each on its own timeout.** One
           worker wedged in a shielded cleanup must not be able to hang the
           sweep (the old code awaited them one at a time, unbounded).
        4. **Reap browsers**, so tab groups don't leak.

        ``worker_ids=None`` means "all of them". Returns a summary the HTTP
        routes hand straight back to the client.

        Dispatch is ALWAYS blocked for the duration of the sweep — otherwise a
        queen turn running concurrently can spawn a worker in between steps 2
        and 3 and it survives the stop. ``block_dispatch=True`` additionally
        *keeps* it blocked afterwards, which is what a user Stop wants (the
        queen is done; nothing more should start until the user speaks again).
        A plain "stop these workers" leaves the queen free to keep working, so
        it restores the previous state on the way out.
        """

        was_blocked = self._dispatch_blocked
        self._dispatch_blocked = True

        try:
            return await self._stop_workers_inner(
                worker_ids=worker_ids,
                include_persistent=include_persistent,
                per_worker_timeout=per_worker_timeout,
            )
        finally:
            if not block_dispatch:
                self._dispatch_blocked = was_blocked

    async def _stop_workers_inner(
        self,
        *,
        worker_ids: list[str] | None,
        include_persistent: bool,
        per_worker_timeout: float,
    ) -> dict[str, Any]:
        """The sweep itself. Callers go through ``stop_workers`` (which owns the
        dispatch gate); split out only to keep that gate exception-safe."""
        from framework.host.worker import WorkerStatus

        targeted = worker_ids is not None
        wanted = set(worker_ids or ())

        def _selected(w: Worker) -> bool:
            if not w.is_active:
                return False
            if not include_persistent and getattr(w, "_persistent", False):
                # The persistent overseer IS the queen — stopping it would end
                # the session. Only colony shutdown passes include_persistent.
                return False
            return not targeted or w.id in wanted

        # --- 2. queued workers (never started) ---------------------------------
        queued_cancelled = 0
        if not targeted:
            # Whole-colony sweep — reuse the existing dequeue+report path.
            queued_cancelled = await self._cancel_queued_workers()
        else:
            for w in [w for w in list(self._workers.values()) if _selected(w)]:
                if w.status != WorkerStatus.QUEUED:
                    continue
                w.status = WorkerStatus.STOPPED
                await self._publish_stopped_report(w, "Worker was stopped before it started running.")
                queued_cancelled += 1
            if queued_cancelled:
                # Drop the now-terminal entries so the queue doesn't carry them.
                # (Filter in place — the drain would skip them anyway thanks to
                # its `status != QUEUED` guard, but leaving corpses in the queue
                # makes depth logging lie.)
                async with self._scheduler_lock:
                    keep = [w for w in self._pending_queue if w.status == WorkerStatus.QUEUED]
                    self._pending_queue.clear()
                    self._pending_queue.extend(keep)

        # --- 3. live workers: concurrent + individually bounded ----------------
        live = [w for w in list(self._workers.values()) if _selected(w)]
        stopped: list[str] = []
        timed_out: list[str] = []
        errors: list[dict[str, str]] = []
        if live:
            results = await asyncio.gather(
                *(w.stop(timeout=per_worker_timeout) for w in live),
                return_exceptions=True,
            )
            for w, res in zip(live, results, strict=False):
                if isinstance(res, BaseException):
                    logger.warning("stop_workers: %s raised: %s", w.id, res)
                    errors.append({"worker_id": w.id, "error": str(res)})
                elif res is False:
                    # Force-marked terminal after the timeout — it may still be
                    # burning CPU, so say so loudly rather than reporting success.
                    timed_out.append(w.id)
                    stopped.append(w.id)
                else:
                    stopped.append(w.id)

        # --- 4. browsers -------------------------------------------------------
        # Each worker's done-callback schedules its own reap, but those are
        # fire-and-forget and may not run before the loop closes. Awaiting here
        # guarantees the tab groups are released. close_profile_context is
        # idempotent, so overlapping with the done-callback is harmless.
        await self._reap_worker_browsers([w.id for w in live])

        summary = {
            "stopped": stopped,
            "stopped_count": len(stopped),
            "queued_cancelled": queued_cancelled,
            "timed_out": timed_out,
            "errors": errors or None,
        }
        if stopped or queued_cancelled:
            logger.info(
                "stop_workers: stopped=%d queued_cancelled=%d timed_out=%d errors=%d",
                len(stopped),
                queued_cancelled,
                len(timed_out),
                len(errors),
            )
        return summary

    async def stop_worker(self, worker_id: str) -> dict[str, Any]:
        """Stop one worker. Queued-aware (see ``stop_workers``)."""
        return await self.stop_workers(worker_ids=[worker_id])

    async def stop_all_workers(self) -> dict[str, Any]:
        """Colony shutdown: stop everything — overseer included — and drop the registry."""
        summary = await self.stop_workers(include_persistent=True)
        self._workers.clear()
        return summary

    async def _reap_worker_browsers(self, worker_ids: list[str]) -> None:
        if not worker_ids:
            return
        try:
            from gcu.browser.tools.lifecycle import close_profile_context
        except ImportError:
            return

        def _bp(wid: str) -> str:
            w = self._workers.get(wid)
            return (getattr(w, "_browser_profile", "") or "default") if w else "default"

        await asyncio.gather(
            *(close_profile_context(wid, reason="colony_shutdown", browser_profile=_bp(wid)) for wid in worker_ids),
            return_exceptions=True,
        )

    async def send_to_worker(self, worker_id: str, message: str) -> bool:
        worker = self._workers.get(worker_id)
        if worker and worker.is_active:
            await worker.inject(message)
            return True
        return False

    def watch_batch_timeouts(
        self,
        worker_ids: list[str],
        *,
        soft_timeout: float,
        hard_timeout: float,
        warning_message: str | None = None,
    ) -> asyncio.Task:
        """Schedule a background task that enforces soft + hard timeouts.

        Semantics:
          * At ``t = soft_timeout`` every worker in ``worker_ids`` that is
            still active AND hasn't already filed an ``_explicit_report``
            receives ``warning_message`` via ``send_to_worker`` — the inject
            appears as a user turn at the next agent-loop boundary, so the
            worker's LLM can see it and call ``report_to_parent`` with
            partial results.
          * At ``t = hard_timeout`` any worker still active is force-stopped
            via ``stop_worker``. ``Worker.run`` still emits its
            ``SUBAGENT_REPORT`` on cancel (the explicit report survives,
            if the worker reported just before the stop) so the queen
            always sees a terminal inject for every spawned worker.

        Returns the scheduled task so callers can await or cancel it.
        Non-blocking for the caller — the watcher runs on the event loop
        independently.
        """
        if warning_message is None:
            grace = max(0.0, hard_timeout - soft_timeout)
            warning_message = (
                f"[SOFT TIMEOUT] You've been running for {soft_timeout:.0f}s. "
                "Wrap up now: call report_to_parent with whatever partial "
                "results you have. You have "
                f"~{grace:.0f}s more before a hard stop — anything not "
                "reported by then will be lost."
            )

        async def _watch() -> None:
            try:
                await asyncio.sleep(soft_timeout)
                for wid in worker_ids:
                    worker = self._workers.get(wid)
                    if worker is None or not worker.is_active:
                        continue
                    if getattr(worker, "_explicit_report", None) is not None:
                        continue
                    try:
                        await self.send_to_worker(wid, warning_message)
                    except Exception:
                        logger.warning(
                            "watch_batch_timeouts: soft-timeout inject failed for %s",
                            wid,
                            exc_info=True,
                        )

                remaining = hard_timeout - soft_timeout
                if remaining <= 0:
                    return
                await asyncio.sleep(remaining)
                for wid in worker_ids:
                    worker = self._workers.get(wid)
                    if worker is None or not worker.is_active:
                        continue
                    try:
                        await self.stop_worker(wid)
                        logger.info(
                            "watch_batch_timeouts: hard-stopped %s after %ss (no report)",
                            wid,
                            hard_timeout,
                        )
                    except Exception:
                        logger.warning(
                            "watch_batch_timeouts: hard-stop failed for %s",
                            wid,
                            exc_info=True,
                        )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("watch_batch_timeouts: watcher crashed")

        task = asyncio.create_task(_watch(), name=f"batch-timeout:{worker_ids[0] if worker_ids else '?'}")
        # Hold a strong reference until completion. Without this the
        # task can be garbage-collected during `await asyncio.sleep`,
        # silently swallowing the soft-timeout inject (the exact bug
        # surfaced by workers never seeing [SOFT TIMEOUT]).
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task

    # ── Status & Query ──────────────────────────────────────────

    def list_workers(self) -> list[WorkerInfo]:
        return [w.info for w in self._workers.values()]

    def get_worker(self, worker_id: str) -> Worker | None:
        return self._workers.get(worker_id)

    def list_triggers(self) -> list[TriggerSpec]:
        return list(self._triggers.values())

    def get_entry_points(self) -> list[TriggerSpec]:
        return list(self._triggers.values())

    def get_timer_next_fire_in(self, trigger_id: str) -> float | None:
        mono = self._timer_next_fire.get(trigger_id)
        if mono is not None:
            return max(0.0, mono - time.monotonic())
        return None

    def get_worker_result(self, worker_id: str) -> WorkerResult | None:
        return self._execution_results.get(worker_id)

    async def wait_for_worker(self, worker_id: str, timeout: float | None = None) -> WorkerResult | None:
        worker = self._workers.get(worker_id)
        if worker is None:
            return self._execution_results.get(worker_id)
        if worker._task_handle is None:
            return worker.info.result
        try:
            await asyncio.wait_for(asyncio.shield(worker._task_handle), timeout=timeout)
        except TimeoutError:
            return None
        return worker.info.result

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "colony_id": self._stream_id,
            "active_workers": self.active_worker_count,
            "total_workers": len(self._workers),
            "triggers": len(self._triggers),
            "event_bus": self._event_bus.get_stats(),
            "adaptive_tool_budget": {
                "enabled": self._config.adaptive_tool_budget,
                "nominal": self._budget_applied,
                "samples": len(self._budget_samples),
            },
        }

    def get_active_streams(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        result = []
        for wid, worker in self._workers.items():
            if worker.is_active:
                # _started_at is monotonic; resolve to elapsed seconds here
                # (a monotonic timestamp is meaningless to any other process).
                elapsed = now - worker._started_at if worker._started_at > 0 else 0.0
                result.append(
                    {
                        "colony_id": self._stream_id,
                        "worker_id": wid,
                        "status": worker.status.value,
                        "task": worker.task[:100],
                        "elapsed_seconds": elapsed,
                    }
                )
        return result

    async def inject_input(
        self,
        worker_id: str,
        content: str,
        *,
        is_client_input: bool = False,
        image_content: list[dict[str, Any]] | None = None,
    ) -> bool:
        self._last_user_input_time = time.monotonic()
        worker = self._workers.get(worker_id)
        if worker and worker.is_active:
            loop = worker._agent_loop
            if hasattr(loop, "inject_event"):
                await loop.inject_event(content, is_client_input=is_client_input, image_content=image_content)
                return True
        return False

    # ── Event Subscriptions ─────────────────────────────────────

    def subscribe_to_events(
        self,
        event_types: list,
        handler: Callable,
        filter_stream: str | None = None,
        filter_colony: str | None = None,
    ) -> str:
        return self._event_bus.subscribe(
            event_types=event_types,
            handler=handler,
            filter_stream=filter_stream,
            filter_colony=filter_colony,
        )

    def unsubscribe_from_events(self, subscription_id: str) -> bool:
        return self._event_bus.unsubscribe(subscription_id)

    # ── Trigger Registration ────────────────────────────────────

    def register_trigger(self, spec: TriggerSpec) -> None:
        if self._running:
            raise RuntimeError("Cannot register triggers while runtime is running")
        if spec.id in self._triggers:
            raise ValueError(f"Trigger '{spec.id}' already registered")
        self._triggers[spec.id] = spec
        logger.info("Registered trigger: %s (%s)", spec.id, spec.trigger_type)

    def unregister_trigger(self, trigger_id: str) -> bool:
        if self._running:
            raise RuntimeError("Cannot unregister triggers while runtime is running")
        return self._triggers.pop(trigger_id, None) is not None

    # ── Internal Helpers ────────────────────────────────────────

    def _make_runtime_adapter(self, worker_id: str):
        from framework.host.stream_runtime import StreamDecisionTracker

        return StreamDecisionTracker(
            stream_id=f"worker:{worker_id}",
            storage=self._storage,
        )

    def _prune_idempotency_keys(self) -> None:
        ttl = self._config.idempotency_ttl_seconds
        if ttl > 0:
            cutoff = time.time() - ttl
            for key, recorded_at in list(self._idempotency_times.items()):
                if recorded_at < cutoff:
                    self._idempotency_times.pop(key, None)
                    self._idempotency_keys.pop(key, None)
        max_keys = self._config.idempotency_max_keys
        if max_keys > 0:
            while len(self._idempotency_keys) > max_keys:
                old_key, _ = self._idempotency_keys.popitem(last=False)
                self._idempotency_times.pop(old_key, None)

    async def _start_timers(self) -> None:
        for trig_id, spec in self._triggers.items():
            if spec.trigger_type != "timer":
                continue
            tc = spec.trigger_config
            _raw_interval = tc.get("interval_minutes")
            interval = float(_raw_interval) if _raw_interval is not None else None
            run_immediately = tc.get("run_immediately", False)

            if interval and interval > 0 and self._running:
                task = asyncio.create_task(
                    self._timer_loop(trig_id, interval, run_immediately),
                    name=f"timer:{trig_id}",
                )
                task.add_done_callback(self._on_timer_task_done)
                self._timer_tasks.append(task)

    async def _timer_loop(
        self,
        trigger_id: str,
        interval_minutes: float,
        immediate: bool,
        idle_timeout: float = 300,
    ) -> None:
        interval_secs = interval_minutes * 60
        if not immediate:
            self._timer_next_fire[trigger_id] = time.monotonic() + interval_secs
            await asyncio.sleep(interval_secs)

        while self._running:
            if self._timers_paused:
                self._timer_next_fire[trigger_id] = time.monotonic() + interval_secs
                await asyncio.sleep(interval_secs)
                continue

            idle = self.agent_idle_seconds
            if idle < idle_timeout:
                logger.debug("Timer '%s': agent active, skipping", trigger_id)
                self._timer_next_fire[trigger_id] = time.monotonic() + interval_secs
                await asyncio.sleep(interval_secs)
                continue

            self._timer_next_fire.pop(trigger_id, None)
            try:
                await self.trigger(
                    trigger_id,
                    {"event": {"source": "timer", "reason": "scheduled"}},
                )
            except Exception:
                logger.error("Timer trigger failed for '%s'", trigger_id, exc_info=True)

            self._timer_next_fire[trigger_id] = time.monotonic() + interval_secs
            await asyncio.sleep(interval_secs)

    async def cancel_all_tasks_async(self) -> bool:
        cancelled = False
        for worker in self._workers.values():
            if worker._task_handle and not worker._task_handle.done():
                worker._task_handle.cancel()
                cancelled = True
        return cancelled

    def cancel_all_tasks(self, loop: asyncio.AbstractEventLoop) -> bool:
        future = asyncio.run_coroutine_threadsafe(self.cancel_all_tasks_async(), loop)
        try:
            return future.result(timeout=5)
        except Exception:
            logger.warning("cancel_all_tasks: timed out or failed")
            return False

    async def cancel_execution(self, trigger_id: str, worker_id: str) -> bool:
        worker = self._workers.get(worker_id)
        if worker and worker.is_active:
            await worker.stop()
            return True
        return False
