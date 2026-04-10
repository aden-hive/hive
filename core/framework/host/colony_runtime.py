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
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.agent_loop.types import AgentContext, AgentSpec
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.triggers import TriggerDefinition
from framework.host.worker import Worker, WorkerInfo, WorkerResult, WorkerStatus
from framework.observability import set_trace_context
from framework.schemas.goal import Goal
from framework.storage.concurrent import ConcurrentStorage
from framework.storage.session_store import SessionStore

if TYPE_CHECKING:
    from framework.agent_loop.agent_loop import AgentLoop
    from framework.llm.provider import LLMProvider, Tool
    from framework.pipeline.runner import PipelineRunner
    from framework.skills.manager import SkillsManagerConfig
    from framework.tracker.runtime_log_store import RuntimeLogStore

logger = logging.getLogger(__name__)


@dataclass
class ColonyConfig:
    max_concurrent_workers: int = 100
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
    """Proxy that stamps ``colony_id`` on every published event."""

    def __init__(self, bus: EventBus, colony_id: str) -> None:
        self._real_bus = bus
        self._colony_id = colony_id
        self.last_activity_time: float = time.monotonic()

    async def publish(self, event: AgentEvent) -> None:
        event.colony_id = self._colony_id
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
        colony_id: str | None = None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
        event_bus: EventBus | None = None,
        skills_manager_config: SkillsManagerConfig | None = None,
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
        skill_dirs: list[str] | None = None,
        pipeline_stages: list | None = None,
    ):
        from framework.pipeline.runner import PipelineRunner
        from framework.skills.manager import SkillsManager

        self._agent_spec = agent_spec
        self._goal = goal
        self._config = config or ColonyConfig()
        self._runtime_log_store = runtime_log_store

        if pipeline_stages:
            self._pipeline = PipelineRunner(pipeline_stages)
        else:
            self._pipeline = self._load_pipeline_from_config()

        if skills_manager_config is not None:
            self._skills_manager = SkillsManager(skills_manager_config)
            self._skills_manager.load()
        elif skills_catalog_prompt or protocols_prompt:
            import warnings

            warnings.warn(
                "Passing pre-rendered skills_catalog_prompt/protocols_prompt "
                "is deprecated. Pass skills_manager_config instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            self._skills_manager = SkillsManager.from_precomputed(
                skills_catalog_prompt, protocols_prompt
            )
        else:
            self._skills_manager = SkillsManager()
            self._skills_manager.load()

        self.skill_dirs: list[str] = self._skills_manager.allowlisted_dirs
        self.context_warn_ratio: float | None = self._skills_manager.context_warn_ratio
        self.batch_init_nudge: str | None = self._skills_manager.batch_init_nudge

        self._colony_id: str = colony_id or "primary"
        self._accounts_prompt = accounts_prompt
        self._accounts_data = accounts_data
        self._tool_provider_map = tool_provider_map
        self._dynamic_memory_provider_factory: Callable[[str], Callable[[], str] | None] | None = (
            None
        )

        storage_path_obj = Path(storage_path) if isinstance(storage_path, str) else storage_path
        self._storage_path: Path = storage_path_obj
        self._storage = ConcurrentStorage(
            base_path=storage_path_obj,
            cache_ttl=self._config.cache_ttl,
            batch_interval=self._config.batch_interval,
        )
        self._session_store = SessionStore(storage_path_obj)

        self._event_bus = event_bus or EventBus(max_history=self._config.max_history)
        self._scoped_event_bus = StreamEventBus(self._event_bus, self._colony_id)

        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor

        # Worker management
        self._workers: dict[str, Worker] = {}
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
        return self._skills_manager.skills_catalog_prompt

    @property
    def protocols_prompt(self) -> str:
        return self._skills_manager.protocols_prompt

    @property
    def colony_id(self) -> str:
        return self._colony_id

    @property
    def agent_id(self) -> str:
        return self._colony_id

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

    def _apply_pipeline_results(self) -> None:
        for stage in self._pipeline.stages:
            if stage.tool_registry is not None:
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

    # ── Lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return

        async with self._lock:
            await self._storage.start()
            await self._pipeline.initialize_all()
            self._apply_pipeline_results()

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
                self._colony_id,
                len(self._triggers),
            )

    async def stop(self) -> None:
        if not self._running:
            return

        async with self._lock:
            await self.stop_all_workers()

            for task in self._timer_tasks:
                task.cancel()
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
            logger.info("ColonyRuntime stopped: colony_id=%s", self._colony_id)

    def pause_timers(self) -> None:
        self._timers_paused = True

    def resume_timers(self) -> None:
        self._timers_paused = False

    # ── Worker Spawning ─────────────────────────────────────────

    async def spawn(
        self,
        task: str,
        count: int = 1,
        input_data: dict[str, Any] | None = None,
        session_state: dict[str, Any] | None = None,
        agent_spec: AgentSpec | None = None,
        tools: list[Any] | None = None,
        tool_executor: Callable | None = None,
    ) -> list[str]:
        """Spawn worker clones and start them in the background.

        By default each spawn uses the colony's own ``agent_spec``,
        ``tools``, and ``tool_executor`` (set at construction). Pass
        the per-spawn override args to spawn a worker that runs
        DIFFERENT code from the colony default — used by the queen's
        ``run_agent_with_input`` tool to spawn the loaded honeycomb /
        custom worker through the unified runtime, instead of going
        through the deprecated ``AgentHost.trigger`` → ``Orchestrator``
        path that silently dropped ``user_request`` via the buffer
        filter.

        Returns list of worker IDs.
        """
        if not self._running:
            raise RuntimeError("ColonyRuntime is not running")

        from framework.agent_loop.agent_loop import AgentLoop
        from framework.storage.conversation_store import FileConversationStore

        # Resolve per-spawn vs colony-default code identity
        spawn_spec = agent_spec or self._agent_spec
        spawn_tools = tools if tools is not None else self._tools
        spawn_executor = tool_executor or self._tool_executor

        worker_ids = []
        for i in range(count):
            worker_id = self._session_store.generate_session_id()

            # Each parallel worker gets its own storage dir under
            # {colony_session}/workers/{worker_id}/ so its conversation,
            # events, and data never leak into the overseer's tree or
            # (worse) the process CWD.
            worker_storage = self._storage_path / "workers" / worker_id
            worker_storage.mkdir(parents=True, exist_ok=True)
            worker_conv_store = FileConversationStore(
                worker_storage / "conversations"
            )

            # AgentLoop takes bus/judge/config/executor at construction;
            # LLM, tools, stream_id, execution_id all come from the
            # AgentContext passed to execute().
            agent_loop = AgentLoop(
                event_bus=self._scoped_event_bus,
                tool_executor=spawn_executor,
                conversation_store=worker_conv_store,
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
                skills_catalog_prompt=self.skills_catalog_prompt,
                protocols_prompt=self.protocols_prompt,
                skill_dirs=self.skill_dirs,
                execution_id=worker_id,
                stream_id=f"worker:{worker_id}",
            )

            worker = Worker(
                worker_id=worker_id,
                task=task,
                agent_loop=agent_loop,
                context=agent_context,
                event_bus=self._scoped_event_bus,
                colony_id=self._colony_id,
                storage_path=worker_storage,
            )

            self._workers[worker_id] = worker
            await worker.start_background()
            worker_ids.append(worker_id)

            logger.info(
                "Spawned worker %s (%d/%d) using %s — task: %s",
                worker_id,
                i + 1,
                count,
                "override spec" if agent_spec else "colony default spec",
                task[:80],
            )

        return worker_ids

    async def spawn_batch(
        self,
        tasks: list[dict[str, Any]],
    ) -> list[str]:
        """Spawn a batch of parallel workers, one per task spec.

        Each task spec is a dict ``{"task": str, "data": dict | None}``.
        Workers start as independent asyncio background tasks and run
        concurrently; this method returns their IDs immediately without
        waiting for completion. Use ``wait_for_worker_reports(ids,
        timeout)`` to block until they all finish.

        The overseer's ``run_parallel_workers`` tool is the usual
        caller; it pairs ``spawn_batch`` + ``wait_for_worker_reports``
        into a single fan-out/fan-in primitive.
        """
        worker_ids: list[str] = []
        for spec in tasks:
            task_text = str(spec.get("task", ""))
            task_data = spec.get("data")
            if task_data is not None and not isinstance(task_data, dict):
                task_data = {"value": task_data}
            ids = await self.spawn(
                task=task_text,
                count=1,
                input_data=task_data or {"task": task_text},
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
                    report = await asyncio.wait_for(
                        report_queue.get(), timeout=remaining
                    )
                except TimeoutError:
                    break
                wid = report.get("worker_id")
                if wid in pending_ids:
                    collected[wid] = report
                    pending_ids.discard(wid)
        finally:
            self._scoped_event_bus.unsubscribe(sub_id)

        # Any still-pending workers are timed out — force-stop them and
        # synthesise a timeout report.
        for wid in list(pending_ids):
            try:
                await self.stop_worker(wid)
            except Exception:
                logger.exception("Failed to force-stop worker %s on timeout", wid)
            worker = self._workers.get(wid)
            duration = 0.0
            tokens = 0
            if worker is not None and worker._started_at > 0:
                duration = time.monotonic() - worker._started_at
            if worker is not None and worker._result is not None:
                tokens = worker._result.tokens_used
            collected[wid] = {
                "worker_id": wid,
                "status": "timeout",
                "summary": f"Worker did not report within {timeout:.0f}s.",
                "data": {},
                "error": "timeout",
                "duration_seconds": duration,
                "tokens_used": tokens,
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
        ``run_parallel_workers`` tool which calls ``spawn_batch`` +
        ``wait_for_worker_reports`` under the hood.

        Pass ``seed_conversation`` to pre-populate the overseer's
        conversation history — used when forking a DM to a colony so
        the overseer starts with the DM's prior context loaded.

        Must be called after ``start()``. Idempotent: calling a second
        time returns the already-started overseer.
        """
        if self._overseer is not None:
            return self._overseer

        if not self._running:
            raise RuntimeError(
                "start_overseer requires the ColonyRuntime to be running "
                "(call start() first)"
            )

        from framework.agent_loop.agent_loop import AgentLoop
        from framework.storage.conversation_store import FileConversationStore

        overseer_id = f"overseer:{self._colony_id}"

        # The overseer's conversation lives at the colony session root:
        # {colony_session}/conversations/. Workers get their own sub-dirs
        # under workers/{worker_id}/; the overseer is the root occupant.
        self._storage_path.mkdir(parents=True, exist_ok=True)
        overseer_conv_store = FileConversationStore(
            self._storage_path / "conversations"
        )
        agent_loop = AgentLoop(
            event_bus=self._scoped_event_bus,
            tool_executor=self._tool_executor,
            conversation_store=overseer_conv_store,
        )

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
            execution_id=overseer_id,
            stream_id="overseer",
        )

        overseer = Worker(
            worker_id=overseer_id,
            task="",  # no finite task — persistent conversation
            agent_loop=agent_loop,
            context=overseer_ctx,
            event_bus=self._scoped_event_bus,
            colony_id=self._colony_id,
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
            self._colony_id,
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

    async def stop_worker(self, worker_id: str) -> None:
        worker = self._workers.get(worker_id)
        if worker:
            await worker.stop()
            logger.info("Stopped worker %s", worker_id)

    async def stop_all_workers(self) -> None:
        tasks = []
        for worker in self._workers.values():
            if worker.is_active:
                tasks.append(worker.stop())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()

    async def send_to_worker(self, worker_id: str, message: str) -> bool:
        worker = self._workers.get(worker_id)
        if worker and worker.is_active:
            await worker.inject(message)
            return True
        return False

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

    async def wait_for_worker(
        self, worker_id: str, timeout: float | None = None
    ) -> WorkerResult | None:
        worker = self._workers.get(worker_id)
        if worker is None:
            return self._execution_results.get(worker_id)
        if worker._task_handle is None:
            return worker.info.result
        try:
            await asyncio.wait_for(asyncio.shield(worker._task_handle), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        return worker.info.result

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "colony_id": self._colony_id,
            "active_workers": self.active_worker_count,
            "total_workers": len(self._workers),
            "triggers": len(self._triggers),
            "event_bus": self._event_bus.get_stats(),
        }

    def get_active_streams(self) -> list[dict[str, Any]]:
        result = []
        for wid, worker in self._workers.items():
            if worker.is_active:
                result.append(
                    {
                        "colony_id": self._colony_id,
                        "worker_id": wid,
                        "status": worker.status.value,
                        "task": worker.task[:100],
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
                await loop.inject_event(
                    content, is_client_input=is_client_input, image_content=image_content
                )
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
                task = asyncio.create_task(self._timer_loop(trig_id, interval, run_immediately))
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
