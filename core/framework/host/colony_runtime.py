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
from framework.host.event_bus import AgentEvent, EventBus, EventType
from framework.host.triggers import TriggerDefinition
from framework.host.worker import Worker, WorkerInfo, WorkerResult
from framework.schemas.goal import Goal
from framework.storage.concurrent import ConcurrentStorage
from framework.storage.session_store import SessionStore

if TYPE_CHECKING:
    from framework.llm.provider import LLMProvider, Tool
    from framework.skills.manager import SkillsManagerConfig
    from framework.tracker.runtime_log_store import RuntimeLogStore

logger = logging.getLogger(__name__)


def _format_spawn_task_message(task: str, input_data: dict[str, Any]) -> str:
    """Render the spawn task into the worker's next user message.

    Spawned workers inherit the queen's conversation via
    ``ColonyRuntime._fork_parent_conversation``; this helper builds
    the content of the trailing user message that carries the new
    task. The queen's chat already provides the context for the
    task, so we frame this as an explicit hand-off.

    Additional keys from ``input_data`` (other than the task itself)
    are rendered below the hand-off line so the worker sees them as
    structured hand-off data. This mirrors the fresh-path
    ``AgentLoop._build_initial_message`` shape so worker prompts look
    roughly the same whether or not inheritance fired.
    """
    lines = [
        "# New task delegated by the queen",
        "",
        "The queen's conversation up to this point is visible above. "
        "Use it as context (who the user is, what was already decided, "
        "which skills apply). Your own system prompt and tool set are "
        "set by the framework — the queen's tools may differ from "
        "yours, so treat her prior tool calls as history only.",
        "",
        f"task: {task}",
    ]
    for key, value in (input_data or {}).items():
        if key in ("task", "user_request"):
            # Already rendered above; don't duplicate.
            continue
        if value is None:
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


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


# Laptop-safe default. Each worker is a full AgentLoop (Claude SDK session +
# tool catalog), so ~4 concurrent is the realistic ceiling on a dev machine.
# Override via HIVE_MAX_CONCURRENT_WORKERS for servers.
_DEFAULT_MAX_CONCURRENT_WORKERS = _env_int("HIVE_MAX_CONCURRENT_WORKERS", 4)


@dataclass
class ColonyConfig:
    max_concurrent_workers: int = _DEFAULT_MAX_CONCURRENT_WORKERS
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
            self._skills_manager = SkillsManager.from_precomputed(skills_catalog_prompt, protocols_prompt)
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
        # Background tasks owned by the runtime that aren't timers —
        # e.g. the per-spawn soft/hard timeout watchers kicked off by
        # run_parallel_workers. We hold strong references so asyncio
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
            logger.info("ColonyRuntime stopped: colony_id=%s", self._colony_id)

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

    async def _fork_parent_conversation(
        self,
        dest_conv_dir: Path,
        *,
        task: str,
        input_data: dict[str, Any] | None = None,
    ) -> None:
        """Fork the colony's parent queen conversation into ``dest_conv_dir``.

        Copies the queen's ``parts/*.json`` and ``meta.json`` into the
        worker's fresh conversation dir, then appends a synthetic user
        message carrying the new task. The worker's subsequent
        ``AgentLoop._restore`` reads this conversation via the usual
        path — the queen's history is visible as prior turns, the task
        appears as the most recent user message, and the worker starts
        acting on it with full context.

        This is a no-op if the colony runtime doesn't own a parent
        queen conversation (e.g. a standalone colony started without a
        queen wrapper).

        Notes on filtering compatibility:
          - Queen parts have ``phase_id=None``. When the worker's
            restore applies its own phase filter, the backward-compat
            fallback in NodeConversation.restore kicks in: an
            all-None-phased store bypasses the filter. See
            ``conversation.py:1369-1378``.
          - ``cursor.json`` is deliberately NOT copied. The worker
            should start fresh at iteration 0; copying the queen's
            cursor would make the worker think it had already done
            work.
          - The queen's ``meta.json`` is copied but the AgentLoop
            immediately rebuilds ``system_prompt`` from the worker's
            own context post-restore (see agent_loop.py:533-535), so
            the queen's system prompt does not leak into the worker.
        """
        # Resolve the queen's own conversation dir. For a queen-backed
        # ColonyRuntime, storage_path points at the queen's session dir
        # and conversations/ lives inside it. For standalone runtimes
        # (tests, legacy fork path under ~/.hive/agents/{name}/worker/)
        # there's no parent conversation — fall through to the fresh
        # spawn path.
        src_conv_dir = self._storage_path / "conversations"
        src_parts_dir = src_conv_dir / "parts"
        if not src_parts_dir.exists():
            # No queen conversation to inherit — the worker starts with
            # only the task, same as the pre-fork behavior. AgentLoop's
            # fresh-conversation branch will call _build_initial_message
            # and render input_data into the worker's first user message.
            return

        def _copy_and_append() -> None:
            dest_parts = dest_conv_dir / "parts"
            dest_parts.mkdir(parents=True, exist_ok=True)

            # Copy each queen part. Use json.dumps round-trip (not raw
            # file copy) so we can be defensive about unreadable files —
            # a corrupted queen part file shouldn't take down the worker
            # spawn, just drop that one part.
            max_seq = -1
            for part_file in sorted(src_parts_dir.glob("*.json")):
                try:
                    data = json.loads(part_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning(
                        "spawn fork: skipping unreadable queen part %s: %s",
                        part_file.name,
                        exc,
                    )
                    continue
                seq = data.get("seq")
                if isinstance(seq, int) and seq > max_seq:
                    max_seq = seq
                (dest_parts / part_file.name).write_text(
                    json.dumps(data, ensure_ascii=False),
                    encoding="utf-8",
                )

            # Copy the queen's meta.json so the worker's restore finds
            # the conversation during its first run. The meta fields
            # (system_prompt, max_context_tokens, etc.) get overridden
            # by the worker's own AgentLoop config + context after
            # restore, so nothing here bleeds into runtime behavior.
            src_meta = src_conv_dir / "meta.json"
            if src_meta.exists():
                try:
                    meta_data = json.loads(src_meta.read_text(encoding="utf-8"))
                    (dest_conv_dir / "meta.json").write_text(
                        json.dumps(meta_data, ensure_ascii=False),
                        encoding="utf-8",
                    )
                except (json.JSONDecodeError, OSError) as exc:
                    logger.warning("spawn fork: failed to copy queen meta.json: %s", exc)

            # Append the task as the next user message so the worker's
            # LLM sees it as the most recent turn in the conversation
            # after restore. This replaces the fresh-path call to
            # _build_initial_message for spawned workers.
            task_content = _format_spawn_task_message(task, input_data or {})
            next_seq = max_seq + 1
            task_part = {
                "seq": next_seq,
                "role": "user",
                "content": task_content,
                # phase_id omitted (None) so the backward-compat
                # fallback in NodeConversation.restore keeps it visible
                # to both queen-style and phase-filtered restores.
                # run_id omitted so the worker's run_id filter (off by
                # default since ctx.run_id is empty) doesn't reject it.
            }
            task_filename = f"{next_seq:010d}.json"
            (dest_parts / task_filename).write_text(
                json.dumps(task_part, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info(
                "spawn fork: inherited %d queen parts + appended task at seq %d",
                max_seq + 1,
                next_seq,
            )

        await asyncio.to_thread(_copy_and_append)

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
        stream_id: str | None = None,
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

        from framework.agent_loop.agent_loop import AgentLoop
        from framework.storage.conversation_store import FileConversationStore

        # Resolve per-spawn vs colony-default code identity
        spawn_spec = agent_spec or self._agent_spec
        spawn_tools = tools if tools is not None else self._tools
        spawn_executor = tool_executor or self._tool_executor

        # Colony progress tracker: when the caller supplied a db_path
        # in input_data, this worker is part of a SQLite task queue
        # and must see the hive.colony-progress-tracker skill body in
        # its system prompt from turn 0. Rebuild the catalog with the
        # skill pre-activated; falls back to the colony default when
        # no db_path is present.
        _spawn_catalog = self.skills_catalog_prompt
        _spawn_skill_dirs = self.skill_dirs
        if isinstance(input_data, dict) and input_data.get("db_path"):
            try:
                from framework.skills.config import SkillsConfig
                from framework.skills.manager import SkillsManager, SkillsManagerConfig

                _pre = SkillsManager(
                    SkillsManagerConfig(
                        skills_config=SkillsConfig.from_agent_vars(
                            skills=["hive.colony-progress-tracker"],
                        ),
                    )
                )
                _pre.load()
                _spawn_catalog = _pre.skills_catalog_prompt
                _spawn_skill_dirs = (
                    list(_pre.allowlisted_dirs)
                    if hasattr(_pre, "allowlisted_dirs")
                    else self.skill_dirs
                )
                logger.info(
                    "spawn: pre-activated hive.colony-progress-tracker "
                    "(catalog %d → %d chars) for worker with db_path=%s",
                    len(self.skills_catalog_prompt),
                    len(_spawn_catalog),
                    input_data.get("db_path"),
                )
            except Exception as exc:
                logger.warning(
                    "spawn: failed to pre-activate colony-progress-tracker "
                    "skill, falling back to base catalog: %s",
                    exc,
                )

        # Resolve the SSE stream_id once. When the caller didn't supply
        # one we use the per-worker fan-out tag (filtered out by the
        # SSE handler). When the caller passed an explicit value we
        # honor it across the whole batch — typically count=1 for the
        # primary loaded worker that needs to stream to the queen DM.
        explicit_stream_id = stream_id

        worker_ids = []
        for i in range(count):
            worker_id = self._session_store.generate_session_id()

            # Each parallel worker gets its own storage dir under
            # {colony_session}/workers/{worker_id}/ so its conversation,
            # events, and data never leak into the overseer's tree or
            # (worse) the process CWD.
            worker_storage = self._storage_path / "workers" / worker_id
            worker_storage.mkdir(parents=True, exist_ok=True)

            # Fork the queen's conversation into the worker's store.
            # The queen already accumulated the user chat, read relevant
            # skills, and made decisions about how to approach the task;
            # the worker would repeat that discovery work (and often
            # mis-step — see the 2026-04-14 "dummy-target" incident)
            # if spawned with a blank store. We snapshot the queen's
            # parts + meta at spawn time, then append the task as the
            # next user message so the worker's AgentLoop restores into
            # a conversation that already ends with its new instruction.
            await self._fork_parent_conversation(
                worker_storage / "conversations",
                task=task,
                input_data=input_data,
            )

            worker_conv_store = FileConversationStore(worker_storage / "conversations")

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
                skills_catalog_prompt=_spawn_catalog,
                protocols_prompt=self.protocols_prompt,
                skill_dirs=_spawn_skill_dirs,
                execution_id=worker_id,
                stream_id=explicit_stream_id or f"worker:{worker_id}",
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
        *,
        tools_override: list[Any] | None = None,
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

        When ``tools_override`` is supplied, every spawned worker
        receives that tool list instead of the colony's default.  Used
        by ``run_parallel_workers`` to drop tools whose credentials
        failed the pre-flight check (so the spawned workers don't
        waste a startup trying to use them).
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
                tools=tools_override,
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
            raise RuntimeError("start_overseer requires the ColonyRuntime to be running (call start() first)")

        from framework.agent_loop.agent_loop import AgentLoop
        from framework.storage.conversation_store import FileConversationStore

        overseer_id = f"overseer:{self._colony_id}"

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
