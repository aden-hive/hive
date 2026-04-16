"""
Agent Runtime - Top-level orchestrator for multi-entry-point agents.

Manages agent lifecycle and coordinates multiple execution streams
while preserving the goal-driven approach.
"""

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.host.event_bus import EventBus
from framework.host.execution_manager import EntryPointSpec, ExecutionManager
from framework.host.outcome_aggregator import OutcomeAggregator
from framework.host.shared_state import SharedBufferManager
from framework.orchestrator.checkpoint_config import CheckpointConfig
from framework.orchestrator.orchestrator import ExecutionResult
from framework.storage.concurrent import ConcurrentStorage
from framework.storage.session_store import SessionStore
from framework.tracker.runtime_log_store import RuntimeLogStore

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider, Tool
    from framework.orchestrator.edge import GraphSpec
    from framework.orchestrator.goal import Goal
    from framework.pipeline.stage import PipelineStage
    from framework.skills.manager import SkillsManagerConfig

logger = logging.getLogger(__name__)


@dataclass
class AgentRuntimeConfig:
    """Configuration for AgentHost."""

    max_concurrent_executions: int = 100
    cache_ttl: float = 60.0
    batch_interval: float = 0.1
    max_history: int = 1000
    execution_result_max: int = 1000
    execution_result_ttl_seconds: float | None = None
    # Idempotency cache for trigger() deduplication
    idempotency_ttl_seconds: float = 300.0
    idempotency_max_keys: int = 10000
    # Webhook server config (only starts if webhook_routes is non-empty)
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8080
    webhook_routes: list[dict] = field(default_factory=list)
    # Each dict: {"source_id": str, "path": str, "methods": ["POST"], "secret": str|None}


@dataclass
class _GraphRegistration:
    """Tracks a loaded graph and its runtime resources."""

    graph: "GraphSpec"
    goal: "Goal"
    entry_points: dict[str, EntryPointSpec]
    streams: dict[str, ExecutionManager]  # ep_id -> stream (NOT namespaced)
    storage_subpath: str  # relative to session root, e.g. "graphs/email_agent"
    event_subscriptions: list[str] = field(default_factory=list)
    timer_tasks: list[asyncio.Task] = field(default_factory=list)
    timer_next_fire: dict[str, float] = field(default_factory=dict)


class AgentHost:
    """
    Top-level runtime that manages agent lifecycle and concurrent executions.

    Responsibilities:
    - Register and manage multiple entry points
    - Coordinate execution streams
    - Manage shared state across streams
    - Aggregate decisions/outcomes for goal evaluation
    - Handle lifecycle events (start, pause, shutdown)

    Example:
        # Create runtime
        runtime = AgentRuntime(
            graph=support_agent_graph,
            goal=support_agent_goal,
            storage_path=Path("./storage"),
            llm=llm_provider,
        )

        # Register entry points
        runtime.register_entry_point(EntryPointSpec(
            id="webhook",
            name="Zendesk Webhook",
            entry_node="process-webhook",
            trigger_type="webhook",
            isolation_level="shared",
        ))

        runtime.register_entry_point(EntryPointSpec(
            id="api",
            name="API Handler",
            entry_node="process-request",
            trigger_type="api",
            isolation_level="shared",
        ))

        # Start runtime
        await runtime.start()

        # Trigger executions (non-blocking)
        exec_1 = await runtime.trigger("webhook", {"ticket_id": "123"})
        exec_2 = await runtime.trigger("api", {"query": "help"})

        # Check goal progress
        progress = await runtime.get_goal_progress()
        print(f"Progress: {progress['overall_progress']:.1%}")

        # Stop runtime
        await runtime.stop()
    """

    def __init__(
        self,
        graph: "GraphSpec",
        goal: "Goal",
        storage_path: str | Path,
        llm: "LLMProvider | None" = None,
        tools: list["Tool"] | None = None,
        tool_executor: Callable | None = None,
        config: AgentRuntimeConfig | None = None,
        runtime_log_store: Any = None,
        checkpoint_config: CheckpointConfig | None = None,
        graph_id: str | None = None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
        event_bus: "EventBus | None" = None,
        skills_manager_config: "SkillsManagerConfig | None" = None,
        # Deprecated — pass skills_manager_config instead.
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
        skill_dirs: list[str] | None = None,
        pipeline_stages: "list[PipelineStage] | None" = None,
    ):
        """
        Initialize agent runtime.

        Args:
            graph: Graph specification for this agent
            goal: Goal driving execution
            storage_path: Path for persistent storage
            llm: LLM provider for nodes
            tools: Available tools
            tool_executor: Function to execute tools
            config: Optional runtime configuration
            runtime_log_store: Optional RuntimeLogStore for per-execution logging
            checkpoint_config: Optional checkpoint configuration for resumable sessions
            graph_id: Optional identifier for the primary graph (defaults to "primary")
            accounts_prompt: Connected accounts block for system prompt injection
            accounts_data: Raw account data for per-node prompt generation
            tool_provider_map: Tool name to provider name mapping for account routing
            event_bus: Optional external EventBus. If provided, the runtime shares
                this bus instead of creating its own. Used by SessionManager to
                share a single bus between queen, worker, and judge.
            skills_catalog_prompt: Available skills catalog for system prompt
            protocols_prompt: Default skill operational protocols for system prompt
            skill_dirs: Skill base directories for Tier 3 resource access
            skills_manager_config: Skill configuration — the runtime owns
                discovery, loading, and prompt renderation internally.
            skills_catalog_prompt: Deprecated. Pre-rendered skills catalog.
            protocols_prompt: Deprecated. Pre-rendered operational protocols.
        """
        from framework.pipeline.runner import PipelineRunner
        from framework.skills.manager import SkillsManager

        self.graph = graph
        self.goal = goal
        self._config = config or AgentRuntimeConfig()
        self._runtime_log_store = runtime_log_store
        self._checkpoint_config = checkpoint_config
        self.accounts_prompt = accounts_prompt

        # Pipeline middleware: runs before every trigger() dispatch.
        # Accepts either pre-built stage objects or loads from config.
        if pipeline_stages:
            self._pipeline = PipelineRunner(pipeline_stages)
        else:
            self._pipeline = self._load_pipeline_from_config()

        # --- Skill lifecycle: runtime owns the SkillsManager ---
        if skills_manager_config is not None:
            # New path: config-driven, runtime handles loading
            self._skills_manager = SkillsManager(skills_manager_config)
            self._skills_manager.load()
        elif skills_catalog_prompt or protocols_prompt:
            # Legacy path: caller passed pre-rendered strings
            import warnings

            warnings.warn(
                "Passing pre-rendered skills_catalog_prompt/protocols_prompt "
                "is deprecated. Pass skills_manager_config instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._skills_manager = SkillsManager.from_precomputed(skills_catalog_prompt, protocols_prompt)
        else:
            # Bare constructor: auto-load defaults
            self._skills_manager = SkillsManager()
            self._skills_manager.load()

        self.skill_dirs: list[str] = self._skills_manager.allowlisted_dirs
        self.context_warn_ratio: float | None = self._skills_manager.context_warn_ratio
        self.batch_init_nudge: str | None = self._skills_manager.batch_init_nudge

        # Primary graph identity
        self._graph_id: str = graph_id or "primary"

        # Multi-graph state
        self._graphs: dict[str, _GraphRegistration] = {}
        self._active_graph_id: str = self._graph_id

        # User presence tracking (monotonic timestamp of last inject_input)
        self._last_user_input_time: float = 0.0

        # Initialize storage
        storage_path_obj = Path(storage_path) if isinstance(storage_path, str) else storage_path
        self._storage = ConcurrentStorage(
            base_path=storage_path_obj,
            cache_ttl=self._config.cache_ttl,
            batch_interval=self._config.batch_interval,
        )

        # Initialize SessionStore for unified sessions (always enabled)
        self._session_store = SessionStore(storage_path_obj)

        # Initialize shared components
        self._state_manager = SharedBufferManager()
        self._event_bus = event_bus or EventBus(max_history=self._config.max_history)
        self._outcome_aggregator = OutcomeAggregator(goal, self._event_bus)

        # LLM and tools
        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor
        self._accounts_prompt = accounts_prompt
        self._dynamic_memory_provider_factory: Callable[[str], Callable[[], str] | None] | None = None
        self._accounts_data = accounts_data
        self._tool_provider_map = tool_provider_map

        # Entry points and streams (primary graph)
        self._entry_points: dict[str, EntryPointSpec] = {}
        self._streams: dict[str, ExecutionManager] = {}

        # Webhook server (created on start if webhook_routes configured)
        self._webhook_server: Any = None
        # Event-driven entry point subscriptions (primary graph)
        self._event_subscriptions: list[str] = []
        # Timer tasks for scheduled entry points (primary graph)
        self._timer_tasks: list[asyncio.Task] = []
        # Next fire time for each timer entry point (ep_id -> datetime)
        self._timer_next_fire: dict[str, float] = {}

        # Idempotency cache for trigger() deduplication
        self._idempotency_keys: OrderedDict[str, str] = OrderedDict()
        self._idempotency_times: dict[str, float] = {}

        # State
        self._running = False
        self._timers_paused = False
        self._lock = asyncio.Lock()

        # Optional greeting shown to user on TUI load (set by AgentRunner)
        self.intro_message: str = ""

    # ------------------------------------------------------------------
    # Skill prompt accessors (read by ExecutionManager constructors)
    # ------------------------------------------------------------------

    @property
    def skills_catalog_prompt(self) -> str:
        return self._skills_manager.skills_catalog_prompt

    @property
    def protocols_prompt(self) -> str:
        return self._skills_manager.protocols_prompt

    def register_entry_point(self, spec: EntryPointSpec) -> None:
        """
        Register a named entry point for the agent.

        Args:
            spec: Entry point specification

        Raises:
            ValueError: If entry point ID already registered
            RuntimeError: If runtime is already running
        """
        if self._running:
            raise RuntimeError("Cannot register entry points while runtime is running")

        if spec.id in self._entry_points:
            raise ValueError(f"Entry point '{spec.id}' already registered")

        # Validate entry node exists in graph
        if self.graph.get_node(spec.entry_node) is None:
            raise ValueError(f"Entry node '{spec.entry_node}' not found in graph")

        self._entry_points[spec.id] = spec
        logger.info(f"Registered entry point: {spec.id} -> {spec.entry_node}")

    def unregister_entry_point(self, entry_point_id: str) -> bool:
        """
        Unregister an entry point.

        Args:
            entry_point_id: Entry point to remove

        Returns:
            True if removed, False if not found

        Raises:
            RuntimeError: If runtime is running
        """
        if self._running:
            raise RuntimeError("Cannot unregister entry points while runtime is running")

        if entry_point_id in self._entry_points:
            del self._entry_points[entry_point_id]
            return True
        return False

    async def start(self) -> None:
        """Start the agent runtime and all registered entry points."""
        if self._running:
            return

        async with self._lock:
            # Start storage
            await self._storage.start()

            # Initialize pipeline stages FIRST -- they inject LLM, tools,
            # credentials, and skills into the host before streams are created.
            await self._pipeline.initialize_all()
            self._apply_pipeline_results()

            # Create streams for each entry point (uses pipeline results)
            for ep_id, spec in self._entry_points.items():
                stream = ExecutionManager(
                    stream_id=ep_id,
                    entry_spec=spec,
                    graph=self.graph,
                    goal=self.goal,
                    state_manager=self._state_manager,
                    storage=self._storage,
                    outcome_aggregator=self._outcome_aggregator,
                    event_bus=self._event_bus,
                    llm=self._llm,
                    tools=self._tools,
                    tool_executor=self._tool_executor,
                    result_retention_max=self._config.execution_result_max,
                    result_retention_ttl_seconds=self._config.execution_result_ttl_seconds,
                    runtime_log_store=self._runtime_log_store,
                    session_store=self._session_store,
                    checkpoint_config=self._checkpoint_config,
                    graph_id=self._graph_id,
                    accounts_prompt=self._accounts_prompt,
                    accounts_data=self._accounts_data,
                    tool_provider_map=self._tool_provider_map,
                    skills_catalog_prompt=self.skills_catalog_prompt,
                    protocols_prompt=self.protocols_prompt,
                    skill_dirs=self.skill_dirs,
                    context_warn_ratio=self.context_warn_ratio,
                    batch_init_nudge=self.batch_init_nudge,
                    dynamic_memory_provider_factory=self._dynamic_memory_provider_factory,
                )
                await stream.start()
                self._streams[ep_id] = stream

            # Start webhook server if routes are configured
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

            # Subscribe event-driven entry points to EventBus
            from framework.host.event_bus import EventType as _ET

            for ep_id, spec in self._entry_points.items():
                if spec.trigger_type != "event":
                    continue

                tc = spec.trigger_config
                event_types = [_ET(et) for et in tc.get("event_types", [])]
                if not event_types:
                    logger.warning(
                        f"Entry point '{ep_id}' has trigger_type='event' but no event_types in trigger_config"
                    )
                    continue

                # Capture ep_id and config in closure
                exclude_own = tc.get("exclude_own_graph", False)

                def _make_handler(entry_point_id: str, _exclude_own: bool):
                    _persistent_session_id: str | None = None

                    async def _on_event(event):
                        nonlocal _persistent_session_id
                        if not self._running or entry_point_id not in self._streams:
                            return
                        # Skip events originating from this graph's own
                        # executions (e.g. guardian should not fire on
                        # queen failures — only secondary graphs).
                        if _exclude_own and event.graph_id == self._graph_id:
                            return
                        ep_spec = self._entry_points.get(entry_point_id)
                        is_isolated = ep_spec and ep_spec.isolation_level == "isolated"
                        if is_isolated:
                            if _persistent_session_id:
                                session_state = {"resume_session_id": _persistent_session_id}
                            else:
                                session_state = None
                        else:
                            # Run in the same session as the primary entry
                            # point so memory (e.g. user-defined rules) is
                            # shared and logs land in one session directory.
                            session_state = self._get_primary_session_state(exclude_entry_point=entry_point_id)
                        exec_id = await self.trigger(
                            entry_point_id,
                            {"event": event.to_dict()},
                            session_state=session_state,
                        )
                        if not _persistent_session_id and is_isolated:
                            _persistent_session_id = exec_id

                    return _on_event

                sub_id = self._event_bus.subscribe(
                    event_types=event_types,
                    handler=_make_handler(ep_id, exclude_own),
                    filter_stream=tc.get("filter_stream"),
                    filter_node=tc.get("filter_node"),
                    filter_graph=tc.get("filter_graph"),
                )
                self._event_subscriptions.append(sub_id)

            # Start timer-driven entry points
            await self._start_timers()

            # Start skill hot-reload watcher (no-op if watchfiles not installed)
            await self._skills_manager.start_watching()

            self._running = True
            self._timers_paused = False
            n_stages = len(self._pipeline.stages)
            logger.info(
                "AgentHost started with %d streams, %d pipeline stages",
                len(self._streams),
                n_stages,
            )

    async def _start_timers(self) -> None:
        """Start timer-driven entry points (extracted from start())."""
        for ep_id, spec in self._entry_points.items():
            if spec.trigger_type != "timer":
                continue

            tc = spec.trigger_config
            cron_expr = tc.get("cron")
            _raw_interval = tc.get("interval_minutes")
            interval = float(_raw_interval) if _raw_interval is not None else None
            run_immediately = tc.get("run_immediately", False)

            if cron_expr:
                # Cron expression mode — takes priority over interval_minutes
                try:
                    from croniter import croniter
                except ImportError as e:
                    raise RuntimeError(
                        "croniter is required for cron-based entry points. Install it with: uv pip install croniter"
                    ) from e

                try:
                    if not croniter.is_valid(cron_expr):
                        raise ValueError(f"Invalid cron expression: {cron_expr}")
                except ValueError as e:
                    logger.warning(
                        "Entry point '%s' has invalid cron config: %s",
                        ep_id,
                        e,
                    )
                    continue

                def _make_cron_timer(
                    entry_point_id: str,
                    expr: str,
                    immediate: bool,
                    idle_timeout: float = 300,
                ):
                    async def _cron_loop():
                        from croniter import croniter

                        _persistent_session_id: str | None = None
                        if not immediate:
                            cron = croniter(expr, datetime.now())
                            next_dt = cron.get_next(datetime)
                            sleep_secs = (next_dt - datetime.now()).total_seconds()
                            self._timer_next_fire[entry_point_id] = time.monotonic() + sleep_secs
                            await asyncio.sleep(max(0, sleep_secs))
                        while self._running:
                            # Calculate next fire time upfront (used by skip paths too)
                            cron = croniter(expr, datetime.now())
                            next_dt = cron.get_next(datetime)
                            sleep_secs = (next_dt - datetime.now()).total_seconds()

                            # Gate: skip tick if timers are explicitly paused
                            if self._timers_paused:
                                logger.debug(
                                    "Cron '%s': paused, skipping tick",
                                    entry_point_id,
                                )
                                self._timer_next_fire[entry_point_id] = time.monotonic() + sleep_secs
                                await asyncio.sleep(max(0, sleep_secs))
                                continue

                            # Gate: skip tick if ANY stream is actively working.
                            # If the execution is idle (no LLM/tool activity
                            # beyond idle_timeout) let the timer proceed —
                            # execute() will cancel the stale execution.
                            _any_active = False
                            _min_idle = float("inf")
                            for _s in self._streams.values():
                                if _s.active_execution_ids:
                                    _any_active = True
                                    _idle = _s.agent_idle_seconds
                                    if _idle < _min_idle:
                                        _min_idle = _idle
                            logger.info(
                                "Cron '%s': gate — active=%s, idle=%.1fs, timeout=%ds",
                                entry_point_id,
                                _any_active,
                                _min_idle,
                                idle_timeout,
                            )
                            if _any_active and _min_idle < idle_timeout:
                                logger.info(
                                    "Cron '%s': agent actively working, skipping tick",
                                    entry_point_id,
                                )
                                self._timer_next_fire[entry_point_id] = time.monotonic() + sleep_secs
                                await asyncio.sleep(max(0, sleep_secs))
                                continue

                            self._timer_next_fire.pop(entry_point_id, None)
                            try:
                                ep_spec = self._entry_points.get(entry_point_id)
                                is_isolated = ep_spec and ep_spec.isolation_level == "isolated"
                                if is_isolated:
                                    if _persistent_session_id:
                                        session_state = {"resume_session_id": _persistent_session_id}
                                    else:
                                        session_state = None
                                else:
                                    session_state = self._get_primary_session_state(exclude_entry_point=entry_point_id)
                                    # Gate: skip tick if no active session
                                    if session_state is None:
                                        logger.debug(
                                            "Cron '%s': no active session, skipping",
                                            entry_point_id,
                                        )
                                        self._timer_next_fire[entry_point_id] = time.monotonic() + sleep_secs
                                        await asyncio.sleep(max(0, sleep_secs))
                                        continue

                                exec_id = await self.trigger(
                                    entry_point_id,
                                    {
                                        "event": {
                                            "source": "timer",
                                            "reason": "scheduled",
                                        }
                                    },
                                    session_state=session_state,
                                )
                                if not _persistent_session_id and is_isolated:
                                    _persistent_session_id = exec_id
                                logger.info(
                                    "Cron fired for entry point '%s' (expr: %s)",
                                    entry_point_id,
                                    expr,
                                )
                            except Exception:
                                logger.error(
                                    "Cron trigger failed for '%s'",
                                    entry_point_id,
                                    exc_info=True,
                                )
                            # Calculate next fire from now
                            cron = croniter(expr, datetime.now())
                            next_dt = cron.get_next(datetime)
                            sleep_secs = (next_dt - datetime.now()).total_seconds()
                            self._timer_next_fire[entry_point_id] = time.monotonic() + sleep_secs
                            await asyncio.sleep(max(0, sleep_secs))

                    return _cron_loop

                task = asyncio.create_task(
                    _make_cron_timer(
                        ep_id,
                        cron_expr,
                        run_immediately,
                        idle_timeout=float(tc.get("idle_timeout_seconds", 300)),
                    )()
                )
                self._timer_tasks.append(task)
                logger.info(
                    "Started cron timer for entry point '%s' with expression '%s'%s",
                    ep_id,
                    cron_expr,
                    " (immediate first run)" if run_immediately else "",
                )

            elif interval and interval > 0:
                # Fixed interval mode (original behavior)
                def _make_timer(
                    entry_point_id: str,
                    mins: float,
                    immediate: bool,
                    idle_timeout: float = 300,
                ):
                    async def _timer_loop():
                        interval_secs = mins * 60
                        _persistent_session_id: str | None = None
                        if not immediate:
                            self._timer_next_fire[entry_point_id] = time.monotonic() + interval_secs
                            await asyncio.sleep(interval_secs)
                        while self._running:
                            # Gate: skip tick if timers are explicitly paused
                            if self._timers_paused:
                                logger.debug(
                                    "Timer '%s': paused, skipping tick",
                                    entry_point_id,
                                )
                                self._timer_next_fire[entry_point_id] = time.monotonic() + interval_secs
                                await asyncio.sleep(interval_secs)
                                continue

                            # Gate: skip tick if agent is actively working.
                            # Gate: skip tick if ANY stream is actively working.
                            _any_active = False
                            _min_idle = float("inf")
                            for _s in self._streams.values():
                                if _s.active_execution_ids:
                                    _any_active = True
                                    _idle = _s.agent_idle_seconds
                                    if _idle < _min_idle:
                                        _min_idle = _idle
                            logger.info(
                                "Timer '%s': gate — active=%s, idle=%.1fs, timeout=%ds",
                                entry_point_id,
                                _any_active,
                                _min_idle,
                                idle_timeout,
                            )
                            if _any_active and _min_idle < idle_timeout:
                                logger.info(
                                    "Timer '%s': agent actively working, skipping tick",
                                    entry_point_id,
                                )
                                self._timer_next_fire[entry_point_id] = time.monotonic() + interval_secs
                                await asyncio.sleep(interval_secs)
                                continue

                            self._timer_next_fire.pop(entry_point_id, None)
                            try:
                                ep_spec = self._entry_points.get(entry_point_id)
                                is_isolated = ep_spec and ep_spec.isolation_level == "isolated"
                                if is_isolated:
                                    if _persistent_session_id:
                                        session_state = {"resume_session_id": _persistent_session_id}
                                    else:
                                        session_state = None
                                else:
                                    session_state = self._get_primary_session_state(exclude_entry_point=entry_point_id)
                                    # Gate: skip tick if no active session
                                    if session_state is None:
                                        logger.debug(
                                            "Timer '%s': no active session, skipping",
                                            entry_point_id,
                                        )
                                        self._timer_next_fire[entry_point_id] = time.monotonic() + interval_secs
                                        await asyncio.sleep(interval_secs)
                                        continue

                                exec_id = await self.trigger(
                                    entry_point_id,
                                    {
                                        "event": {
                                            "source": "timer",
                                            "reason": "scheduled",
                                        }
                                    },
                                    session_state=session_state,
                                )
                                if not _persistent_session_id and is_isolated:
                                    _persistent_session_id = exec_id
                                logger.info(
                                    "Timer fired for entry point '%s' (next in %s min)",
                                    entry_point_id,
                                    mins,
                                )
                            except Exception:
                                logger.error(
                                    "Timer trigger failed for '%s'",
                                    entry_point_id,
                                    exc_info=True,
                                )
                            self._timer_next_fire[entry_point_id] = time.monotonic() + interval_secs
                            await asyncio.sleep(interval_secs)

                    return _timer_loop

                task = asyncio.create_task(
                    _make_timer(
                        ep_id,
                        interval,
                        run_immediately,
                        idle_timeout=float(tc.get("idle_timeout_seconds", 300)),
                    )()
                )
                self._timer_tasks.append(task)
                logger.info(
                    "Started timer for entry point '%s' every %s min%s",
                    ep_id,
                    interval,
                    " (immediate first run)" if run_immediately else "",
                )

            else:
                logger.warning(
                    "Entry point '%s' has trigger_type='timer' "
                    "but no 'cron' or valid 'interval_minutes' in trigger_config",
                    ep_id,
                )

            # Register primary graph
            self._graphs[self._graph_id] = _GraphRegistration(
                graph=self.graph,
                goal=self.goal,
                entry_points=dict(self._entry_points),
                streams=dict(self._streams),
                storage_subpath="",
                event_subscriptions=list(self._event_subscriptions),
                timer_tasks=list(self._timer_tasks),
                timer_next_fire=self._timer_next_fire,
            )

    async def stop(self) -> None:
        """Stop the agent runtime and all streams."""
        if not self._running:
            return

        async with self._lock:
            # Stop secondary graphs first
            secondary_ids = [gid for gid in self._graphs if gid != self._graph_id]
            for gid in secondary_ids:
                await self._teardown_graph(gid)

            # Cancel primary timer tasks
            for task in self._timer_tasks:
                task.cancel()
            self._timer_tasks.clear()

            # Unsubscribe primary event-driven entry points
            for sub_id in self._event_subscriptions:
                self._event_bus.unsubscribe(sub_id)
            self._event_subscriptions.clear()

            # Stop webhook server
            if self._webhook_server:
                await self._webhook_server.stop()
                self._webhook_server = None

            # Stop all primary streams
            for stream in self._streams.values():
                await stream.stop()

            self._streams.clear()
            self._graphs.clear()

            # Stop skill hot-reload watcher
            await self._skills_manager.stop_watching()

            # Stop storage
            await self._storage.stop()

            self._running = False
            logger.info("AgentHost stopped")

    def pause_timers(self) -> None:
        """Pause all timer-driven entry points.

        Timers will skip their ticks until ``resume_timers()`` is called.
        """
        self._timers_paused = True
        logger.info("Timers paused")

    def resume_timers(self) -> None:
        """Resume timer-driven entry points after a pause."""
        self._timers_paused = False
        logger.info("Timers resumed")

    def _resolve_stream(
        self,
        entry_point_id: str,
        graph_id: str | None = None,
    ) -> ExecutionManager | None:
        """Find the stream for an entry point, searching the active graph first.

        Lookup order:
        1. If *graph_id* is given, search that graph only.
        2. Otherwise search the active graph (``active_graph_id``).
        3. Fall back to the primary graph's streams (``self._streams``).
        """
        if graph_id:
            reg = self._graphs.get(graph_id)
            return reg.streams.get(entry_point_id) if reg else None

        # Active graph
        target = self._active_graph_id
        if target != self._graph_id:
            reg = self._graphs.get(target)
            if reg:
                stream = reg.streams.get(entry_point_id)
                if stream is not None:
                    return stream

        # Primary graph (also stored in self._streams)
        return self._streams.get(entry_point_id)

    def _apply_pipeline_results(self) -> None:
        """Read typed attributes from pipeline stages after initialization."""
        for stage in self._pipeline.stages:
            name = stage.__class__.__name__

            if stage.tool_registry is not None:
                tools = list(stage.tool_registry.get_tools().values())
                if tools:
                    self._tools = tools
                    self._tool_executor = stage.tool_registry.get_executor()
                    logger.info("Pipeline: %d tools from %s", len(tools), name)

            if stage.llm is not None and self._llm is None:
                self._llm = stage.llm
                logger.info("Pipeline: LLM from %s", name)

            if stage.accounts_prompt:
                self._accounts_prompt = stage.accounts_prompt
                self._accounts_data = stage.accounts_data
                self._tool_provider_map = stage.tool_provider_map

            if stage.skills_manager is not None:
                self._skills_manager = stage.skills_manager

    @staticmethod
    def _load_pipeline_from_config():
        """Build pipeline from ``~/.hive/configuration.json`` ``pipeline`` key.

        Returns an empty pipeline if no config is set.
        """
        from framework.config import get_hive_config
        from framework.pipeline.registry import build_pipeline_from_config
        from framework.pipeline.runner import PipelineRunner

        config = get_hive_config()
        stages_config = config.get("pipeline", {}).get("stages", [])
        if not stages_config:
            return PipelineRunner([])
        return build_pipeline_from_config(stages_config)

    async def _reload_pipeline(self) -> None:
        """Hot-reload pipeline from config.  Atomic swap."""
        new_pipeline = self._load_pipeline_from_config()
        await new_pipeline.initialize_all()
        self._pipeline = new_pipeline
        logger.info(
            "Pipeline reloaded: %d stages",
            len(new_pipeline.stages),
        )

    def _prune_idempotency_keys(self) -> None:
        """Prune expired idempotency keys based on TTL and max size."""
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

    async def trigger(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
        session_state: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        graph_id: str | None = None,
    ) -> str:
        """
        Trigger execution at a specific entry point.

        Non-blocking - returns immediately with execution ID.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            correlation_id: Optional ID to correlate related executions
            session_state: Optional session state to resume from (with paused_at, memory)
            idempotency_key: Optional key for deduplication. If a trigger with
                the same key was already processed within the TTL window, the
                cached execution_id is returned instead of starting a new
                execution. Useful for webhook providers that retry on timeout.
            graph_id: Graph to trigger on.  ``None`` uses the active graph
                first, then falls back to the primary graph.

        Returns:
            Execution ID for tracking

        Raises:
            ValueError: If entry point not found
            RuntimeError: If runtime not running
        """
        if not self._running:
            raise RuntimeError("AgentHost is not running")

        # Idempotency check: return cached execution_id for duplicate keys.
        if idempotency_key is not None:
            self._prune_idempotency_keys()
            cached = self._idempotency_keys.get(idempotency_key)
            if cached is not None:
                logger.debug(
                    "Idempotent trigger: key '%s' already seen, returning %s",
                    idempotency_key,
                    cached,
                )
                return cached

        # Run pipeline middleware (rate limiting, validation, cost guards, ...)
        # Raises PipelineRejectedError if any stage rejects.
        if self._pipeline.stages:
            from framework.pipeline.stage import PipelineContext

            pipeline_ctx = PipelineContext(
                entry_point_id=entry_point_id,
                input_data=input_data,
                correlation_id=correlation_id,
                session_state=session_state,
            )
            pipeline_ctx = await self._pipeline.run(pipeline_ctx)
            # Stages may have transformed the input_data.
            input_data = pipeline_ctx.input_data

        stream = self._resolve_stream(entry_point_id, graph_id)
        if stream is None:
            raise ValueError(f"Entry point '{entry_point_id}' not found")

        run_id = uuid.uuid4().hex[:12]
        exec_id = await stream.execute(input_data, correlation_id, session_state, run_id=run_id)

        # Cache after execute() so the value is always a real execution_id
        # that callers can use for tracking.
        if idempotency_key is not None:
            self._idempotency_keys[idempotency_key] = exec_id
            self._idempotency_times[idempotency_key] = time.time()

        return exec_id

    async def trigger_and_wait(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> ExecutionResult | None:
        """
        Trigger execution and wait for completion.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            timeout: Maximum time to wait (seconds)
            session_state: Optional session state to resume from (with paused_at, memory)
            idempotency_key: Optional key for deduplication (see trigger() for details).

        Returns:
            ExecutionResult or None if timeout
        """
        exec_id = await self.trigger(
            entry_point_id,
            input_data,
            session_state=session_state,
            idempotency_key=idempotency_key,
        )
        stream = self._resolve_stream(entry_point_id)
        if stream is None:
            raise ValueError(f"Entry point '{entry_point_id}' not found")
        return await stream.wait_for_completion(exec_id, timeout)

    # === MULTI-GRAPH MANAGEMENT ===

    async def add_graph(
        self,
        graph_id: str,
        graph: "GraphSpec",
        goal: "Goal",
        entry_points: dict[str, EntryPointSpec],
        storage_subpath: str | None = None,
    ) -> None:
        """Load a secondary graph into this runtime session.

        Creates execution streams for the graph's entry points, sets up
        event/timer triggers, and registers the graph. Shares the same
        EventBus, state.json, and data directory as the primary graph.

        Can be called while the runtime is running.

        Args:
            graph_id: Unique identifier for the graph
            graph: Graph specification
            goal: Goal driving this graph's execution
            entry_points: Entry point specs (ep_id -> spec)
            storage_subpath: Relative path under session root for this
                graph's conversations/checkpoints.  Defaults to
                ``"graphs/{graph_id}"``.

        Raises:
            ValueError: If graph_id already registered or entry node missing
        """
        if graph_id in self._graphs:
            raise ValueError(f"Graph '{graph_id}' already registered")

        subpath = storage_subpath or f"graphs/{graph_id}"

        # Validate entry nodes exist in graph
        for _ep_id, spec in entry_points.items():
            if graph.get_node(spec.entry_node) is None:
                raise ValueError(f"Entry node '{spec.entry_node}' not found in graph '{graph_id}'")

        # Secondary graphs get their own SessionStore AND RuntimeLogStore
        # so their sessions and logs don't pollute the worker's directories.
        graph_base = self._session_store.base_path / subpath
        graph_session_store = SessionStore(graph_base)
        graph_log_store = RuntimeLogStore(graph_base / "runtime_logs")

        # Create streams for each entry point
        streams: dict[str, ExecutionManager] = {}
        for ep_id, spec in entry_points.items():
            stream = ExecutionManager(
                stream_id=f"{graph_id}::{ep_id}",
                entry_spec=spec,
                graph=graph,
                goal=goal,
                state_manager=self._state_manager,
                storage=self._storage,
                outcome_aggregator=self._outcome_aggregator,
                event_bus=self._event_bus,
                llm=self._llm,
                tools=self._tools,
                tool_executor=self._tool_executor,
                result_retention_max=self._config.execution_result_max,
                result_retention_ttl_seconds=self._config.execution_result_ttl_seconds,
                runtime_log_store=graph_log_store,
                session_store=graph_session_store,
                checkpoint_config=self._checkpoint_config,
                graph_id=graph_id,
                accounts_prompt=self._accounts_prompt,
                accounts_data=self._accounts_data,
                tool_provider_map=self._tool_provider_map,
                skills_catalog_prompt=self.skills_catalog_prompt,
                protocols_prompt=self.protocols_prompt,
                skill_dirs=self.skill_dirs,
            )
            if self._running:
                await stream.start()
            streams[ep_id] = stream

        # Set up event-driven subscriptions
        from framework.host.event_bus import EventType as _ET

        event_subs: list[str] = []
        for ep_id, spec in entry_points.items():
            if spec.trigger_type != "event":
                continue
            tc = spec.trigger_config
            event_types = [_ET(et) for et in tc.get("event_types", [])]
            if not event_types:
                logger.warning(
                    "Entry point '%s::%s' has trigger_type='event' but no event_types in trigger_config",
                    graph_id,
                    ep_id,
                )
                continue

            namespaced_ep = f"{graph_id}::{ep_id}"
            exclude_own = tc.get("exclude_own_graph", False)

            def _make_handler(entry_point_id: str, gid: str, _exclude_own: bool):
                _persistent_session_id: str | None = None

                async def _on_event(event):
                    nonlocal _persistent_session_id
                    if not self._running or gid not in self._graphs:
                        return
                    # Skip events from this graph's own executions
                    if _exclude_own and event.graph_id == gid:
                        return
                    reg = self._graphs[gid]
                    local_ep = entry_point_id.split("::", 1)[-1]
                    stream = reg.streams.get(local_ep)
                    if stream is None:
                        return
                    ep_spec = reg.entry_points.get(local_ep)
                    is_isolated = ep_spec and ep_spec.isolation_level == "isolated"
                    if is_isolated:
                        if _persistent_session_id:
                            session_state = {"resume_session_id": _persistent_session_id}
                        else:
                            session_state = None
                    else:
                        session_state = self._get_primary_session_state(
                            local_ep,
                            source_graph_id=gid,
                        )
                    exec_id = await stream.execute(
                        {"event": event.to_dict()},
                        session_state=session_state,
                    )
                    if not _persistent_session_id and is_isolated:
                        _persistent_session_id = exec_id

                return _on_event

            sub_id = self._event_bus.subscribe(
                event_types=event_types,
                handler=_make_handler(namespaced_ep, graph_id, exclude_own),
                filter_stream=tc.get("filter_stream"),
                filter_node=tc.get("filter_node"),
                filter_graph=tc.get("filter_graph"),
            )
            event_subs.append(sub_id)

        # Set up timer-driven entry points
        timer_tasks: list[asyncio.Task] = []
        timer_next_fire: dict[str, float] = {}
        for ep_id, spec in entry_points.items():
            if spec.trigger_type != "timer":
                continue
            tc = spec.trigger_config
            _raw_interval = tc.get("interval_minutes")
            interval = float(_raw_interval) if _raw_interval is not None else None
            run_immediately = tc.get("run_immediately", False)

            if interval and interval > 0 and self._running:
                logger.info(
                    "Creating timer for '%s::%s': interval=%s min, immediate=%s, loop=%s",
                    graph_id,
                    ep_id,
                    interval,
                    run_immediately,
                    id(asyncio.get_event_loop()),
                )

                def _make_timer(
                    gid: str,
                    local_ep: str,
                    mins: float,
                    immediate: bool,
                    idle_timeout: float = 300,
                ):
                    async def _timer_loop():
                        interval_secs = mins * 60
                        # For isolated entry points, reuse ONE session across
                        # all timer ticks so conversation_mode="continuous"
                        # actually works and we don't create N sessions.
                        _persistent_session_id: str | None = None

                        logger.info(
                            "Timer loop started for '%s::%s' (sleep %ss)",
                            gid,
                            local_ep,
                            interval_secs,
                        )
                        if not immediate:
                            timer_next_fire[local_ep] = time.monotonic() + interval_secs
                            await asyncio.sleep(interval_secs)
                        while self._running and gid in self._graphs:
                            # Gate: skip tick if timers are explicitly paused
                            if self._timers_paused:
                                logger.debug(
                                    "Timer '%s::%s': paused, skipping tick",
                                    gid,
                                    local_ep,
                                )
                                timer_next_fire[local_ep] = time.monotonic() + interval_secs
                                await asyncio.sleep(interval_secs)
                                continue

                            # Gate: skip tick if ANY stream in this graph is actively working.
                            _reg = self._graphs.get(gid)
                            _any_active = False
                            _min_idle = float("inf")
                            if _reg:
                                for _sid, _s in _reg.streams.items():
                                    if _s.active_execution_ids:
                                        _any_active = True
                                        _idle = _s.agent_idle_seconds
                                        if _idle < _min_idle:
                                            _min_idle = _idle
                            logger.info(
                                "Timer '%s::%s': gate — active=%s, idle=%.1fs, timeout=%ds",
                                gid,
                                local_ep,
                                _any_active,
                                _min_idle,
                                idle_timeout,
                            )
                            if _any_active and _min_idle < idle_timeout:
                                logger.info(
                                    "Timer '%s::%s': agent actively working, skipping tick",
                                    gid,
                                    local_ep,
                                )
                                timer_next_fire[local_ep] = time.monotonic() + interval_secs
                                await asyncio.sleep(interval_secs)
                                continue

                            logger.info("Timer firing for '%s::%s'", gid, local_ep)
                            timer_next_fire.pop(local_ep, None)
                            try:
                                reg = self._graphs.get(gid)
                                if not reg:
                                    logger.warning("Timer: no reg for '%s', stopping", gid)
                                    break
                                stream = reg.streams.get(local_ep)
                                if not stream:
                                    logger.warning("Timer: no stream '%s' in '%s', stopping", local_ep, gid)
                                    break
                                # Isolated entry points get their own session;
                                # shared ones join the primary session.
                                ep_spec = reg.entry_points.get(local_ep)
                                if ep_spec and ep_spec.isolation_level == "isolated":
                                    if _persistent_session_id:
                                        session_state = {"resume_session_id": _persistent_session_id}
                                    else:
                                        session_state = None
                                else:
                                    session_state = self._get_primary_session_state(local_ep, source_graph_id=gid)
                                    # Gate: skip tick if no active session
                                    if session_state is None:
                                        logger.debug(
                                            "Timer '%s::%s': no active session, skipping",
                                            gid,
                                            local_ep,
                                        )
                                        timer_next_fire[local_ep] = time.monotonic() + interval_secs
                                        await asyncio.sleep(interval_secs)
                                        continue

                                exec_id = await stream.execute(
                                    {"event": {"source": "timer", "reason": "scheduled"}},
                                    session_state=session_state,
                                )
                                # Remember session ID for reuse on next tick
                                if not _persistent_session_id and ep_spec and ep_spec.isolation_level == "isolated":
                                    _persistent_session_id = exec_id
                            except Exception:
                                logger.error(
                                    "Timer trigger failed for '%s::%s'",
                                    gid,
                                    local_ep,
                                    exc_info=True,
                                )
                            timer_next_fire[local_ep] = time.monotonic() + interval_secs
                            await asyncio.sleep(interval_secs)
                        logger.info("Timer loop exited for '%s::%s'", gid, local_ep)

                    return _timer_loop

                task = asyncio.create_task(
                    _make_timer(
                        graph_id,
                        ep_id,
                        interval,
                        run_immediately,
                        idle_timeout=float(tc.get("idle_timeout_seconds", 300)),
                    )()
                )
                timer_tasks.append(task)
                logger.info("Timer task created for '%s::%s': %s", graph_id, ep_id, task)

        self._graphs[graph_id] = _GraphRegistration(
            graph=graph,
            goal=goal,
            entry_points=entry_points,
            streams=streams,
            storage_subpath=subpath,
            event_subscriptions=event_subs,
            timer_tasks=timer_tasks,
            timer_next_fire=timer_next_fire,
        )
        logger.info(
            "Added graph '%s' with %d entry points (%d streams)",
            graph_id,
            len(entry_points),
            len(streams),
        )

    async def remove_graph(self, graph_id: str) -> None:
        """Remove a secondary graph from this runtime session.

        Stops all streams, cancels timers, unsubscribes events, and
        removes the registration. Cannot remove the primary graph.

        Args:
            graph_id: Graph to remove

        Raises:
            ValueError: If graph_id is the primary graph or not found
        """
        if graph_id == self._graph_id:
            raise ValueError("Cannot remove the primary graph")
        if graph_id not in self._graphs:
            raise ValueError(f"Graph '{graph_id}' not found")
        await self._teardown_graph(graph_id)
        logger.info("Removed graph '%s'", graph_id)

    async def _teardown_graph(self, graph_id: str) -> None:
        """Internal: stop and clean up all resources for a graph."""
        reg = self._graphs.pop(graph_id, None)
        if reg is None:
            return

        # Cancel timers
        for task in reg.timer_tasks:
            task.cancel()

        # Unsubscribe events
        for sub_id in reg.event_subscriptions:
            self._event_bus.unsubscribe(sub_id)

        # Stop streams
        for stream in reg.streams.values():
            await stream.stop()

        # Reset active graph if it was the removed one
        if self._active_graph_id == graph_id:
            self._active_graph_id = self._graph_id

    def list_graphs(self) -> list[str]:
        """Return all registered graph IDs (primary first)."""
        result = []
        if self._graph_id in self._graphs:
            result.append(self._graph_id)
        for gid in self._graphs:
            if gid != self._graph_id:
                result.append(gid)
        return result

    @property
    def graph_id(self) -> str:
        """The primary graph's ID."""
        return self._graph_id

    @property
    def colony_id(self) -> str:
        """Colony compatibility — returns the primary graph ID."""
        return self._graph_id

    def list_workers(self) -> list[str]:
        """Colony compatibility — returns registered graph IDs."""
        return self.list_graphs()

    def get_worker_registration(self, graph_id: str):
        """Colony compatibility — returns self for the matching graph."""
        if graph_id in self._graphs:
            return self
        return None

    @property
    def streams(self) -> dict:
        """Colony compatibility — returns _streams dict."""
        return self._streams

    @property
    def active_graph_id(self) -> str:
        """The currently focused graph (for TUI routing)."""
        return self._active_graph_id

    @active_graph_id.setter
    def active_graph_id(self, value: str) -> None:
        if value not in self._graphs:
            raise ValueError(f"Graph '{value}' not registered")
        self._active_graph_id = value

    def get_active_graph(self) -> "GraphSpec":
        """Return the GraphSpec for the currently active graph."""
        if self._active_graph_id == self._graph_id:
            return self.graph
        reg = self._graphs.get(self._active_graph_id)
        if reg is not None:
            return reg.graph
        return self.graph

    @property
    def user_idle_seconds(self) -> float:
        """Seconds since the user last provided input.

        Returns ``float('inf')`` if no input has been received yet.
        """
        if self._last_user_input_time == 0.0:
            return float("inf")
        return time.monotonic() - self._last_user_input_time

    @property
    def agent_idle_seconds(self) -> float:
        """Seconds since any stream last had activity (LLM call, tool call, etc.).

        Returns the *minimum* idle time across all streams with active
        executions.  Returns ``float('inf')`` if nothing is running.
        """
        min_idle = float("inf")
        for reg in self._graphs.values():
            for stream in reg.streams.values():
                idle = stream.agent_idle_seconds
                if idle < min_idle:
                    min_idle = idle
        return min_idle

    def get_graph_registration(self, graph_id: str) -> _GraphRegistration | None:
        """Get the registration for a specific graph (or None)."""
        return self._graphs.get(graph_id)

    def cancel_all_tasks(self, loop: asyncio.AbstractEventLoop) -> bool:
        """Cancel all running execution tasks across all graphs.

        Schedules the cancellation on *loop* (the agent event loop) so
        that ``_execution_tasks`` is only read from the thread that owns
        it, avoiding cross-thread dict access.  Safe to call from any
        thread (e.g. the Textual UI thread).

        Blocks the caller for up to 5 seconds waiting for the result.
        For async callers, use :meth:`cancel_all_tasks_async` instead.
        """
        future = asyncio.run_coroutine_threadsafe(self.cancel_all_tasks_async(), loop)
        try:
            return future.result(timeout=5)
        except Exception:
            logger.warning("cancel_all_tasks: timed out or failed")
            return False

    async def cancel_all_tasks_async(self) -> bool:
        """Cancel all running execution tasks (runs on the agent loop).

        Iterates ``_execution_tasks`` and calls ``task.cancel()`` directly.
        Must be awaited on the agent event loop so dict access is
        thread-safe.  Returns True if at least one task was cancelled.
        """
        cancelled = False
        for gid in self.list_graphs():
            reg = self.get_graph_registration(gid)
            if reg:
                for stream in reg.streams.values():
                    for task in list(stream._execution_tasks.values()):
                        if task and not task.done():
                            task.cancel()
                            cancelled = True
        return cancelled

    async def stop_all_workers(self) -> bool:
        """Alias for ``cancel_all_tasks_async`` used by queen-lifecycle tools.

        Queen tools (``stop_worker``, ``switch_to_reviewing``, etc.) call
        ``runtime.stop_all_workers()`` which is the :class:`ColonyRuntime`
        idiom. In the current architecture the session's runtime is an
        :class:`AgentHost`, which stops workers by cancelling their
        execution tasks. This alias bridges the two interfaces.
        """
        return await self.cancel_all_tasks_async()

    def _get_primary_session_state(
        self,
        exclude_entry_point: str,
        *,
        source_graph_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Build session_state so an async entry point runs in the primary session.

        Looks for an active execution from another stream (the "primary"
        session, e.g. the user-facing intake loop) and returns a
        ``session_state`` dict containing:

        - ``resume_session_id``: reuse the same session directory
        - ``data_buffer``: only the keys that the async entry node declares
          as inputs (e.g. ``rules``, ``max_emails``).  Stale outputs
          from previous runs (``emails``, ``actions_taken``, …) are
          excluded so each trigger starts fresh.

        The data buffer is read from the primary session's ``state.json``
        which is kept up-to-date by ``GraphExecutor._write_progress()``
        at every node transition.

        Searches across ALL graphs' streams (primary + secondary) so
        event-driven entry points on secondary graphs can share the
        primary session.

        Args:
            exclude_entry_point: Entry point ID to skip (the one being triggered)
            source_graph_id: Graph the exclude_entry_point belongs to (for
                resolving the entry node spec). Defaults to primary graph.

        Returns ``None`` if no primary session is active (the webhook
        execution will just create its own session).
        """
        import json as _json

        # Determine which data buffer keys the async entry node needs.
        allowed_keys: set[str] | None = None
        # Look up the entry node from the correct graph
        src_graph_id = source_graph_id or self._graph_id
        src_reg = self._graphs.get(src_graph_id)
        ep_spec = (
            src_reg.entry_points.get(exclude_entry_point) if src_reg else self._entry_points.get(exclude_entry_point)
        )
        if ep_spec:
            graph = src_reg.graph if src_reg else self.graph
            entry_node = graph.get_node(ep_spec.entry_node)
            if entry_node and entry_node.input_keys:
                allowed_keys = set(entry_node.input_keys)

        # Search primary graph's streams for an active session.
        # Skip isolated streams — they have their own session directories
        # and must never be used as a shared session.
        all_streams: list[tuple[str, ExecutionManager]] = []
        for _gid, reg in self._graphs.items():
            for ep_id, stream in reg.streams.items():
                # Skip isolated entry points — they run in their own namespace
                ep_spec = reg.entry_points.get(ep_id)
                if ep_spec and getattr(ep_spec, "isolation_level", "shared") == "isolated":
                    continue
                all_streams.append((ep_id, stream))

        for ep_id, stream in all_streams:
            if ep_id == exclude_entry_point:
                continue
            for exec_id in stream.active_execution_ids:
                state_path = self._storage.base_path / "sessions" / exec_id / "state.json"
                try:
                    if state_path.exists():
                        data = _json.loads(state_path.read_text(encoding="utf-8"))
                        full_buffer = data.get("data_buffer", data.get("memory", {}))
                        if not full_buffer:
                            continue
                        # Filter to only input keys so stale outputs
                        # from previous triggers don't leak through.
                        if allowed_keys is not None:
                            buffer_data = {k: v for k, v in full_buffer.items() if k in allowed_keys}
                        else:
                            buffer_data = full_buffer
                        if buffer_data:
                            return {
                                "resume_session_id": exec_id,
                                "data_buffer": buffer_data,
                            }
                except Exception:
                    logger.debug(
                        "Could not read state.json for %s: skipping",
                        exec_id,
                        exc_info=True,
                    )
        return None

    async def inject_input(
        self,
        node_id: str,
        content: str,
        graph_id: str | None = None,
        *,
        is_client_input: bool = False,
        image_content: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Inject user input into a running client-facing node.

        Routes input to the EventLoopNode identified by ``node_id``.
        Searches the specified graph (or active graph) first, then all others.

        Args:
            node_id: The node currently waiting for input
            content: The user's input text
            graph_id: Optional graph to search first (defaults to active graph)
            is_client_input: True when the message originates from a real
                human user (e.g. /chat endpoint), False for external events.
            image_content: Optional list of image content blocks (OpenAI
                image_url format) to include alongside the text.

        Returns:
            True if input was delivered, False if no matching node found
        """
        # Track user presence
        self._last_user_input_time = time.monotonic()

        # Search target graph first
        target = graph_id or self._active_graph_id
        if target in self._graphs:
            for stream in self._graphs[target].streams.values():
                if await stream.inject_input(
                    node_id, content, is_client_input=is_client_input, image_content=image_content
                ):
                    return True

        # Then search all other graphs
        for gid, reg in self._graphs.items():
            if gid == target:
                continue
            for stream in reg.streams.values():
                if await stream.inject_input(
                    node_id, content, is_client_input=is_client_input, image_content=image_content
                ):
                    return True
        return False

    async def get_goal_progress(self) -> dict[str, Any]:
        """
        Evaluate goal progress across all streams.

        Returns:
            Progress report including overall progress, criteria status,
            constraint violations, and metrics.
        """
        return await self._outcome_aggregator.evaluate_goal_progress()

    async def cancel_execution(
        self,
        entry_point_id: str,
        execution_id: str,
        graph_id: str | None = None,
    ) -> bool:
        """
        Cancel a running execution.

        Args:
            entry_point_id: Stream containing the execution
            execution_id: Execution to cancel
            graph_id: Graph to search (defaults to active graph)

        Returns:
            True if cancelled, False if not found
        """
        stream = self._resolve_stream(entry_point_id, graph_id)
        if stream is None:
            return False
        return await stream.cancel_execution(execution_id)

    # === QUERY OPERATIONS ===

    def get_entry_points(self, graph_id: str | None = None) -> list[EntryPointSpec]:
        """Get entry points for a graph.

        Args:
            graph_id: Graph to query.  ``None`` (default) uses the
                currently active graph (``active_graph_id``).

        Returns:
            List of EntryPointSpec for the requested graph. Falls back to
            the primary graph if the graph_id is not found.
        """
        gid = graph_id or self._active_graph_id
        if gid == self._graph_id:
            return list(self._entry_points.values())
        reg = self._graphs.get(gid)
        if reg is not None:
            return list(reg.entry_points.values())
        # Fallback: primary graph
        return list(self._entry_points.values())

    def get_timer_next_fire_in(self, entry_point_id: str) -> float | None:
        """Return seconds until the next timer fire for *entry_point_id*.

        Checks the primary graph's ``_timer_next_fire`` dict as well as
        all registered secondary graphs.  Returns ``None`` when no fire
        time is recorded (e.g. the timer is currently executing or the
        entry point is not a timer).
        """
        mono = self._timer_next_fire.get(entry_point_id)
        if mono is not None:
            return max(0.0, mono - time.monotonic())
        for reg in self._graphs.values():
            mono = reg.timer_next_fire.get(entry_point_id)
            if mono is not None:
                return max(0.0, mono - time.monotonic())
        return None

    def get_stream(self, entry_point_id: str) -> ExecutionManager | None:
        """Get a specific execution stream."""
        return self._streams.get(entry_point_id)

    def find_awaiting_node(self) -> tuple[str | None, str | None]:
        """Find a node that is currently awaiting user input.

        Searches all graphs and their streams for any active executor
        whose node has ``_awaiting_input`` set to ``True``.

        Returns:
            (node_id, graph_id) if found, else (None, None).
        """
        for graph_id, reg in self._graphs.items():
            for stream in reg.streams.values():
                for executor in stream._active_executors.values():
                    for node_id, node in executor.node_registry.items():
                        if getattr(node, "_awaiting_input", False):
                            # Skip escalation receivers — those are handled
                            # by the queen via inject_message(), not
                            # by the user directly.
                            if ":escalation:" in node_id:
                                continue
                            return node_id, graph_id
        return None, None

    def get_execution_result(
        self,
        entry_point_id: str,
        execution_id: str,
        graph_id: str | None = None,
    ) -> ExecutionResult | None:
        """Get result of a completed execution."""
        stream = self._resolve_stream(entry_point_id, graph_id)
        if stream:
            return stream.get_result(execution_id)
        return None

    # === EVENT SUBSCRIPTIONS ===

    def subscribe_to_events(
        self,
        event_types: list,
        handler: Callable,
        filter_stream: str | None = None,
        filter_graph: str | None = None,
    ) -> str:
        """
        Subscribe to agent events.

        Args:
            event_types: Types of events to receive
            handler: Async function to call when event occurs
            filter_stream: Only receive events from this stream
            filter_graph: Only receive events from this graph

        Returns:
            Subscription ID (use to unsubscribe)
        """
        return self._event_bus.subscribe(
            event_types=event_types,
            handler=handler,
            filter_stream=filter_stream,
            filter_graph=filter_graph,
        )

    def unsubscribe_from_events(self, subscription_id: str) -> bool:
        """Unsubscribe from events."""
        return self._event_bus.unsubscribe(subscription_id)

    # === STATS AND MONITORING ===

    def get_stats(self) -> dict:
        """Get comprehensive runtime statistics."""
        stream_stats = {}
        for ep_id, stream in self._streams.items():
            stream_stats[ep_id] = stream.get_stats()

        return {
            "running": self._running,
            "entry_points": len(self._entry_points),
            "streams": stream_stats,
            "goal_id": self.goal.id,
            "outcome_aggregator": self._outcome_aggregator.get_stats(),
            "event_bus": self._event_bus.get_stats(),
            "state_manager": self._state_manager.get_stats(),
        }

    def get_active_streams(self) -> list[dict[str, Any]]:
        """Return metadata for every stream that has active executions.

        Each dict contains: ``graph_id``, ``stream_id``, ``entry_point_id``,
        ``active_execution_ids``, ``is_awaiting_input``, ``waiting_nodes``.
        """
        result: list[dict[str, Any]] = []
        for graph_id, reg in self._graphs.items():
            for ep_id, stream in reg.streams.items():
                active = stream.active_execution_ids
                if not active:
                    continue
                result.append(
                    {
                        "graph_id": graph_id,
                        "stream_id": stream.stream_id,
                        "entry_point_id": ep_id,
                        "active_execution_ids": active,
                        "is_awaiting_input": stream.is_awaiting_input,
                        "waiting_nodes": stream.get_waiting_nodes(),
                    }
                )
        return result

    def get_waiting_nodes(self) -> list[dict[str, Any]]:
        """Return all nodes currently blocked waiting for client input.

        Each dict contains: ``graph_id``, ``stream_id``, ``node_id``,
        ``execution_id``.
        """
        result: list[dict[str, Any]] = []
        for graph_id, reg in self._graphs.items():
            for _ep_id, stream in reg.streams.items():
                for waiting in stream.get_waiting_nodes():
                    result.append(
                        {
                            "graph_id": graph_id,
                            "stream_id": stream.stream_id,
                            **waiting,
                        }
                    )
        return result

    # === PROPERTIES ===

    @property
    def state_manager(self) -> SharedBufferManager:
        """Access the shared state manager."""
        return self._state_manager

    @property
    def event_bus(self) -> EventBus:
        """Access the event bus."""
        return self._event_bus

    @property
    def outcome_aggregator(self) -> OutcomeAggregator:
        """Access the outcome aggregator."""
        return self._outcome_aggregator

    @property
    def webhook_server(self) -> Any:
        """Access the webhook server (None if no webhook entry points)."""
        return self._webhook_server

    @property
    def timers_paused(self) -> bool:
        """True when timer-driven entry points are paused (e.g. by stop_worker)."""
        return self._timers_paused

    @property
    def is_running(self) -> bool:
        """Check if runtime is running."""
        return self._running


# === CONVENIENCE FACTORY ===
