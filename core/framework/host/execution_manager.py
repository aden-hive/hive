"""
Execution Stream - Manages concurrent executions for a single entry point.

Each stream has:
- Its own StreamRuntime for decision tracking
- Access to shared state (read/write based on isolation)
- Connection to the outcome aggregator
"""

import asyncio
import logging
import os
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from framework.host.event_bus import EventBus
from framework.host.shared_state import IsolationLevel, SharedBufferManager
from framework.host.stream_runtime import StreamDecisionTracker, StreamRuntimeAdapter
from framework.orchestrator.checkpoint_config import CheckpointConfig
from framework.orchestrator.orchestrator import ExecutionResult, Orchestrator

if TYPE_CHECKING:
    from framework.host.event_bus import AgentEvent
    from framework.host.outcome_aggregator import OutcomeAggregator
    from framework.llm.provider import LLMProvider, Tool
    from framework.orchestrator.edge import GraphSpec
    from framework.orchestrator.goal import Goal
    from framework.storage.concurrent import ConcurrentStorage
    from framework.storage.session_store import SessionStore


class ExecutionAlreadyRunningError(RuntimeError):
    """Raised when attempting to start an execution on a stream that already has one running."""

    def __init__(self, stream_id: str, active_ids: list[str]):
        self.stream_id = stream_id
        self.active_ids = active_ids
        super().__init__(
            f"Stream '{stream_id}' already has an active execution: {active_ids}. "
            "Concurrent executions on the same stream are not allowed."
        )


logger = logging.getLogger(__name__)


class GraphScopedEventBus(EventBus):
    """Proxy that stamps ``graph_id`` on every published event.

    The ``GraphExecutor`` and ``EventLoopNode`` emit events via the
    convenience methods on ``EventBus`` (e.g. ``emit_llm_text_delta``).
    Rather than threading ``graph_id`` through every one of those 20+
    methods, this subclass overrides ``publish()`` to stamp the id
    before forwarding to the real bus.

    Because the ``emit_*`` methods are *inherited* from ``EventBus``,
    ``self.publish()`` inside them resolves to this class's override —
    unlike a ``__getattr__``-based proxy where the delegated bound
    methods would call ``EventBus.publish`` directly, bypassing the
    stamp entirely.
    """

    def __init__(self, bus: "EventBus", graph_id: str) -> None:
        # Intentionally skip super().__init__() — we delegate all state
        # (subscriptions, history, semaphore, etc.) to the real bus.
        self._real_bus = bus
        self._scope_graph_id = graph_id
        self.last_activity_time: float = time.monotonic()

    async def publish(self, event: "AgentEvent") -> None:  # type: ignore[override]
        event.graph_id = self._scope_graph_id
        self.last_activity_time = time.monotonic()
        await self._real_bus.publish(event)

    # --- Delegate state-reading methods to the real bus ---
    # These access internal state (_subscriptions, _event_history, etc.)
    # that only exists on the real bus.

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


@dataclass
class EntryPointSpec:
    """Specification for an entry point."""

    id: str
    name: str
    entry_node: str  # Node ID to start from
    trigger_type: str  # "webhook", "api", "timer", "event", "manual"
    trigger_config: dict[str, Any] = field(default_factory=dict)
    isolation_level: str = "shared"  # "isolated" | "shared" | "synchronized"
    priority: int = 0
    max_concurrent: int = 10  # Max concurrent executions for this entry point
    max_resurrections: int = 3  # Auto-restart on non-fatal failure (0 to disable)

    def get_isolation_level(self) -> IsolationLevel:
        """Convert string isolation level to enum."""
        return IsolationLevel(self.isolation_level)


@dataclass
class ExecutionContext:
    """Context for a single execution."""

    id: str
    correlation_id: str
    stream_id: str
    entry_point: str
    input_data: dict[str, Any]
    isolation_level: IsolationLevel
    session_state: dict[str, Any] | None = None  # For resuming from pause
    run_id: str | None = None  # Unique ID per trigger() invocation
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    status: str = "pending"  # pending, running, completed, failed, paused


class ExecutionManager:
    """
    Manages concurrent executions for a single entry point.

    Each stream:
    - Has its own StreamRuntime for thread-safe decision tracking
    - Creates GraphExecutor instances per execution
    - Manages execution lifecycle with proper isolation

    Example:
        stream = ExecutionStream(
            stream_id="webhook",
            entry_spec=webhook_entry,
            graph=graph_spec,
            goal=goal,
            state_manager=shared_state,
            storage=concurrent_storage,
            outcome_aggregator=aggregator,
            event_bus=event_bus,
            llm=llm_provider,
        )

        await stream.start()

        # Trigger execution
        exec_id = await stream.execute({"ticket_id": "123"})

        # Wait for result
        result = await stream.wait_for_completion(exec_id)
    """

    def __init__(
        self,
        stream_id: str,
        entry_spec: EntryPointSpec,
        graph: "GraphSpec",
        goal: "Goal",
        state_manager: SharedBufferManager,
        storage: "ConcurrentStorage",
        outcome_aggregator: "OutcomeAggregator | None" = None,
        event_bus: "EventBus | None" = None,
        llm: "LLMProvider | None" = None,
        tools: list["Tool"] | None = None,
        tool_executor: Callable | None = None,
        result_retention_max: int | None = 1000,
        result_retention_ttl_seconds: float | None = None,
        runtime_log_store: Any = None,
        session_store: "SessionStore | None" = None,
        checkpoint_config: CheckpointConfig | None = None,
        graph_id: str | None = None,
        accounts_prompt: str = "",
        accounts_data: list[dict] | None = None,
        tool_provider_map: dict[str, str] | None = None,
        skills_catalog_prompt: str = "",
        protocols_prompt: str = "",
        skill_dirs: list[str] | None = None,
        context_warn_ratio: float | None = None,
        batch_init_nudge: str | None = None,
        dynamic_memory_provider_factory: Callable[[str], Callable[[], str] | None] | None = None,
    ):
        """
        Initialize execution stream.

        Args:
            stream_id: Unique identifier for this stream
            entry_spec: Entry point specification
            graph: Graph specification for this agent
            goal: Goal driving execution
            state_manager: Shared state manager
            storage: Concurrent storage backend
            outcome_aggregator: For cross-stream evaluation
            event_bus: Optional event bus for publishing events
            llm: LLM provider for nodes
            tools: Available tools
            tool_executor: Function to execute tools
            runtime_log_store: Optional RuntimeLogStore for per-execution logging
            session_store: Optional SessionStore for unified session storage
            checkpoint_config: Optional checkpoint configuration for resumable sessions
            graph_id: Optional graph identifier for multi-graph sessions
            accounts_prompt: Connected accounts block for system prompt injection
            accounts_data: Raw account data for per-node prompt generation
            tool_provider_map: Tool name to provider name mapping for account routing
            skills_catalog_prompt: Available skills catalog for system prompt
            protocols_prompt: Default skill operational protocols for system prompt
            skill_dirs: Skill base directories for Tier 3 resource access
            context_warn_ratio: Token usage ratio to trigger DS-13 preservation warning
            batch_init_nudge: System prompt nudge for DS-12 batch auto-detection
        """
        self.stream_id = stream_id
        self.entry_spec = entry_spec
        self.graph = graph
        self.goal = goal
        self.graph_id = graph_id
        self._state_manager = state_manager
        self._storage = storage
        self._outcome_aggregator = outcome_aggregator
        self._event_bus = event_bus
        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor
        self._result_retention_max = result_retention_max
        self._result_retention_ttl_seconds = result_retention_ttl_seconds
        self._runtime_log_store = runtime_log_store
        self._checkpoint_config = checkpoint_config
        self._session_store = session_store
        self._accounts_prompt = accounts_prompt
        self._accounts_data = accounts_data
        self._tool_provider_map = tool_provider_map
        self._skills_catalog_prompt = skills_catalog_prompt
        self._protocols_prompt = protocols_prompt
        self._skill_dirs: list[str] = skill_dirs or []
        self._context_warn_ratio: float | None = context_warn_ratio
        self._batch_init_nudge: str | None = batch_init_nudge
        self._dynamic_memory_provider_factory = dynamic_memory_provider_factory

        _es_logger = logging.getLogger(__name__)
        if protocols_prompt:
            _es_logger.info(
                "ExecutionStream[%s] received protocols_prompt (%d chars)",
                stream_id,
                len(protocols_prompt),
            )
        else:
            _es_logger.warning(
                "ExecutionStream[%s] received EMPTY protocols_prompt",
                stream_id,
            )

        # Create stream-scoped runtime
        self._runtime = StreamDecisionTracker(
            stream_id=stream_id,
            storage=storage,
        )

        # Execution tracking
        self._active_executions: dict[str, ExecutionContext] = {}
        self._execution_tasks: dict[str, asyncio.Task] = {}
        self._active_executors: dict[str, Orchestrator] = {}
        self._cancel_reasons: dict[str, str] = {}
        self._execution_results: OrderedDict[str, ExecutionResult] = OrderedDict()
        self._execution_result_times: dict[str, float] = {}
        self._completion_events: dict[str, asyncio.Event] = {}

        # Concurrency control
        self._semaphore = asyncio.Semaphore(entry_spec.max_concurrent)
        self._lock = asyncio.Lock()

        # Graph-scoped event bus (stamps graph_id on published events)
        # Always wrap in GraphScopedEventBus so we can track last_activity_time.
        if self._event_bus:
            self._scoped_event_bus = GraphScopedEventBus(self._event_bus, self.graph_id or "")
        else:
            self._scoped_event_bus = None

        # State
        self._running = False

    async def start(self) -> None:
        """Start the execution stream."""
        if self._running:
            return

        self._running = True
        logger.info(f"ExecutionStream '{self.stream_id}' started")

        # Emit stream started event
        if self._scoped_event_bus:
            from framework.host.event_bus import AgentEvent, EventType

            await self._scoped_event_bus.publish(
                AgentEvent(
                    type=EventType.STREAM_STARTED,
                    stream_id=self.stream_id,
                    data={"entry_point": self.entry_spec.id},
                )
            )

    @property
    def active_execution_ids(self) -> list[str]:
        """Return IDs of all currently active executions."""
        return list(self._active_executions.keys())

    @property
    def agent_idle_seconds(self) -> float:
        """Seconds since the last agent activity (LLM call, tool call, node transition).

        Returns ``float('inf')`` if no event bus is attached or no events have
        been published yet.  When there are no active executions, also returns
        ``float('inf')`` (nothing to be idle *about*).
        """
        if not self._active_executions:
            return float("inf")
        bus = self._scoped_event_bus
        if isinstance(bus, GraphScopedEventBus):
            return time.monotonic() - bus.last_activity_time
        return float("inf")

    @property
    def is_awaiting_input(self) -> bool:
        """True when an active execution is blocked waiting for client input."""
        if not self._active_executors:
            return False
        for executor in self._active_executors.values():
            for node in executor.node_registry.values():
                if getattr(node, "_awaiting_input", False):
                    return True
        return False

    def get_waiting_nodes(self) -> list[dict[str, str]]:
        """Return nodes currently blocked waiting for client input.

        Each entry is ``{"node_id": ..., "execution_id": ...}``.
        """
        waiting: list[dict[str, str]] = []
        for exec_id, executor in self._active_executors.items():
            for node_id, node in executor.node_registry.items():
                if getattr(node, "_awaiting_input", False):
                    waiting.append({"node_id": node_id, "execution_id": exec_id})
        return waiting

    def get_injectable_nodes(self) -> list[dict[str, str]]:
        """Return nodes that support message injection (have ``inject_event``).

        Each entry is ``{"node_id": ..., "execution_id": ...}``.
        The currently executing node is placed first so that
        ``inject_message`` targets the active node, not a stale one.
        """
        injectable: list[dict[str, str]] = []
        current_first: list[dict[str, str]] = []
        for exec_id, executor in self._active_executors.items():
            current = getattr(executor, "current_node_id", None)
            for node_id, node in executor.node_registry.items():
                if hasattr(node, "inject_event"):
                    entry = {"node_id": node_id, "execution_id": exec_id}
                    if node_id == current:
                        current_first.append(entry)
                    else:
                        injectable.append(entry)
        return current_first + injectable

    def _record_execution_result(self, execution_id: str, result: ExecutionResult) -> None:
        """Record a completed execution result with retention pruning."""
        self._execution_results[execution_id] = result
        self._execution_results.move_to_end(execution_id)
        self._execution_result_times[execution_id] = time.time()
        self._prune_execution_results()

    def _prune_execution_results(self) -> None:
        """Prune completed results based on TTL and max retention."""
        if self._result_retention_ttl_seconds is not None:
            cutoff = time.time() - self._result_retention_ttl_seconds
            for exec_id, recorded_at in list(self._execution_result_times.items()):
                if recorded_at < cutoff:
                    self._execution_result_times.pop(exec_id, None)
                    self._execution_results.pop(exec_id, None)

        if self._result_retention_max is not None:
            while len(self._execution_results) > self._result_retention_max:
                old_exec_id, _ = self._execution_results.popitem(last=False)
                self._execution_result_times.pop(old_exec_id, None)

    async def stop(self) -> None:
        """Stop the execution stream and cancel active executions."""
        if not self._running:
            return

        self._running = False

        # Cancel all active executions
        tasks_to_wait = []
        for _, task in self._execution_tasks.items():
            if not task.done():
                task.cancel()
                tasks_to_wait.append(task)

        if tasks_to_wait:
            # Wait briefly — don't block indefinitely if tasks are stuck
            # in long-running operations (LLM calls, tool executions).
            _, pending = await asyncio.wait(tasks_to_wait, timeout=5.0)
            if pending:
                logger.warning(
                    "%d execution task(s) did not finish within 5s after cancellation",
                    len(pending),
                )

        self._execution_tasks.clear()
        self._active_executions.clear()

        logger.info(f"ExecutionStream '{self.stream_id}' stopped")

        # Emit stream stopped event
        if self._scoped_event_bus:
            from framework.host.event_bus import AgentEvent, EventType

            await self._scoped_event_bus.publish(
                AgentEvent(
                    type=EventType.STREAM_STOPPED,
                    stream_id=self.stream_id,
                )
            )

    async def inject_input(
        self,
        node_id: str,
        content: str,
        *,
        is_client_input: bool = False,
        image_content: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Inject user input into a running client-facing EventLoopNode.

        Searches active executors for a node matching ``node_id`` and calls
        its ``inject_event()`` method to unblock ``_await_user_input()``.

        Returns True if input was delivered, False otherwise.
        """
        for executor in self._active_executors.values():
            node = executor.node_registry.get(node_id)
            if node is not None and hasattr(node, "inject_event"):
                await node.inject_event(content, is_client_input=is_client_input, image_content=image_content)
                return True
        return False

    async def inject_trigger(
        self,
        node_id: str,
        trigger: Any,
    ) -> bool:
        """Inject a trigger event into a running queen EventLoopNode.

        Searches active executors for a node matching ``node_id`` and calls
        its ``inject_trigger()`` method to wake the queen.

        Args:
            node_id: The queen EventLoopNode ID.
            trigger: A ``TriggerEvent`` instance (typed as Any to avoid
                circular imports with graph layer).

        Returns True if the trigger was delivered, False otherwise.
        """
        for executor in self._active_executors.values():
            node = executor.node_registry.get(node_id)
            if node is not None and hasattr(node, "inject_trigger"):
                await node.inject_trigger(trigger)
                return True
        return False

    async def execute(
        self,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
        session_state: dict[str, Any] | None = None,
        run_id: str | None = None,
    ) -> str:
        """
        Queue an execution and return its ID.

        Non-blocking - the execution runs in the background.

        Args:
            input_data: Input data for this execution
            correlation_id: Optional ID to correlate related executions
            session_state: Optional session state to resume from (with paused_at, memory)
            run_id: Unique ID for this trigger invocation (for run dividers)

        Returns:
            Execution ID for tracking
        """
        if not self._running:
            raise RuntimeError(f"ExecutionStream '{self.stream_id}' is not running")

        # Only one execution may run on a stream at a time — concurrent
        # executions corrupt shared session state.  Cancel any running
        # execution before starting the new one.  The cancelled execution
        # writes its state to disk before cleanup, and the new execution
        # runs in the same session directory (via resume_session_id).
        active = self.active_execution_ids
        for eid in active:
            logger.info(
                "Cancelling running execution %s on stream '%s' before starting new one",
                eid,
                self.stream_id,
            )
            executor = self._active_executors.get(eid)
            if executor:
                for node in executor.node_registry.values():
                    if hasattr(node, "signal_shutdown"):
                        node.signal_shutdown()
                    if hasattr(node, "cancel_current_turn"):
                        node.cancel_current_turn()
            await self.cancel_execution(eid, reason="Restarted with new execution")

        # When resuming, reuse the original session ID so the execution
        # continues in the same session directory instead of creating a new one.
        resume_session_id = session_state.get("resume_session_id") if session_state else None

        if resume_session_id:
            execution_id = resume_session_id
        elif self._session_store:
            execution_id = self._session_store.generate_session_id()
        else:
            # Fallback to old format if SessionStore not available (shouldn't happen)
            import warnings

            warnings.warn(
                "SessionStore not available, using deprecated exec_* ID format. "
                "Please ensure AgentRuntime is properly initialized.",
                DeprecationWarning,
                stacklevel=2,
            )
            execution_id = f"exec_{self.stream_id}_{uuid.uuid4().hex[:8]}"

        if correlation_id is None:
            correlation_id = execution_id

        # Create execution context
        effective_run_id = None
        if session_state:
            existing_run_id = session_state.get("run_id")
            if isinstance(existing_run_id, str) and existing_run_id:
                effective_run_id = existing_run_id
        if effective_run_id is None:
            effective_run_id = run_id

        ctx = ExecutionContext(
            id=execution_id,
            correlation_id=correlation_id,
            stream_id=self.stream_id,
            entry_point=self.entry_spec.id,
            input_data=input_data,
            isolation_level=self.entry_spec.get_isolation_level(),
            session_state=session_state,
            run_id=effective_run_id,
        )

        async with self._lock:
            self._active_executions[execution_id] = ctx
            self._completion_events[execution_id] = asyncio.Event()

        # Start execution task
        task = asyncio.create_task(self._run_execution(ctx))
        self._execution_tasks[execution_id] = task

        logger.debug(f"Queued execution {execution_id} for stream {self.stream_id}")
        return execution_id

    # Errors that indicate resurrection won't help — the same error will recur.
    # Includes both configuration/environment errors and deterministic node
    # failures where the conversation/state hasn't changed.
    _FATAL_ERROR_PATTERNS: tuple[str, ...] = (
        # Configuration / environment
        "credential",
        "authentication",
        "unauthorized",
        "forbidden",
        "api key",
        "import error",
        "module not found",
        "no module named",
        "permission denied",
        "invalid api",
        "configuration error",
        # Deterministic node failures — resurrecting at the same node with
        # the same conversation produces the same result.
        "node stalled",
        "ghost empty stream",
        "max iterations",
    )

    @classmethod
    def _is_fatal_error(cls, error: str | None) -> bool:
        """Return True if the error is life-threatening (no point resurrecting)."""
        if not error:
            return False
        error_lower = error.lower()
        return any(pat in error_lower for pat in cls._FATAL_ERROR_PATTERNS)

    async def _run_execution(self, ctx: ExecutionContext) -> None:
        """Run a single execution within the stream.

        Supports automatic resurrection: when the execution fails with a
        non-fatal error, it restarts from the failed node up to
        ``entry_spec.max_resurrections`` times (default 3).
        """
        execution_id = ctx.id

        # When sharing a session with another entry point (resume_session_id),
        # skip writing initial/final session state — the primary execution
        # owns the state.json and _write_progress() keeps memory up-to-date.
        _is_shared_session = bool(ctx.session_state and ctx.session_state.get("resume_session_id"))

        max_resurrections = self.entry_spec.max_resurrections
        _resurrection_count = 0
        _current_session_state = ctx.session_state
        _current_input_data = ctx.input_data

        # Acquire semaphore to limit concurrency
        async with self._semaphore:
            ctx.status = "running"

            try:
                # Emit started event
                if self._scoped_event_bus:
                    await self._scoped_event_bus.emit_execution_started(
                        stream_id=self.stream_id,
                        execution_id=execution_id,
                        input_data=ctx.input_data,
                        correlation_id=ctx.correlation_id,
                        run_id=ctx.run_id,
                    )
                self._write_run_event(execution_id, ctx.run_id, "run_started")

                # Create execution-scoped memory
                self._state_manager.create_buffer(
                    execution_id=execution_id,
                    stream_id=self.stream_id,
                    isolation=ctx.isolation_level,
                )

                # Create runtime adapter for this execution
                runtime_adapter = StreamRuntimeAdapter(self._runtime, execution_id)

                # Start run to set trace context (CRITICAL for observability)
                runtime_adapter.start_run(
                    goal_id=self.goal.id,
                    goal_description=self.goal.description,
                    input_data=ctx.input_data,
                )

                # Create per-execution runtime logger
                runtime_logger = None
                if self._runtime_log_store:
                    from framework.tracker.runtime_logger import RuntimeLogger

                    runtime_logger = RuntimeLogger(store=self._runtime_log_store, agent_id=self.graph.id)

                # Derive storage from session_store (graph-specific for secondary
                # graphs) so that all files — conversations, state, checkpoints,
                # data — land under the graph's own sessions/ directory, not the
                # primary worker's.
                if self._session_store:
                    exec_storage = self._session_store.sessions_dir / execution_id
                else:
                    exec_storage = self._storage.base_path / "sessions" / execution_id

                # Create modified graph with entry point
                # We need to override the entry_node to use our entry point
                modified_graph = self._create_modified_graph()

                # Write initial session state
                if not _is_shared_session:
                    await self._write_session_state(execution_id, ctx)

                # --- Resurrection loop ---
                # Each iteration creates a fresh executor. On non-fatal failure,
                # the executor's session_state (memory + resume_from) carries
                # forward so the next attempt resumes at the failed node.
                while True:
                    # Create executor for this execution.
                    executor = Orchestrator(
                        runtime=runtime_adapter,
                        llm=self._llm,
                        tools=self._tools,
                        tool_executor=self._tool_executor,
                        event_bus=self._scoped_event_bus,
                        stream_id=self.stream_id,
                        execution_id=execution_id,
                        run_id=ctx.run_id or "",
                        storage_path=exec_storage,
                        runtime_logger=runtime_logger,
                        loop_config=self.graph.loop_config,
                        accounts_prompt=self._accounts_prompt,
                        accounts_data=self._accounts_data,
                        tool_provider_map=self._tool_provider_map,
                        skills_catalog_prompt=self._skills_catalog_prompt,
                        protocols_prompt=self._protocols_prompt,
                        skill_dirs=self._skill_dirs,
                        context_warn_ratio=self._context_warn_ratio,
                        batch_init_nudge=self._batch_init_nudge,
                        dynamic_memory_provider=(
                            self._dynamic_memory_provider_factory(execution_id)
                            if self._dynamic_memory_provider_factory is not None
                            else None
                        ),
                    )
                    # Track executor so inject_input() can reach EventLoopNode instances
                    self._active_executors[execution_id] = executor

                    # Execute
                    result = await executor.execute(
                        graph=modified_graph,
                        goal=self.goal,
                        input_data=_current_input_data,
                        session_state=_current_session_state,
                        checkpoint_config=self._checkpoint_config,
                    )

                    # Clean up executor reference
                    self._active_executors.pop(execution_id, None)

                    # Check if resurrection is appropriate
                    if (
                        not result.success
                        and not result.paused_at
                        and _resurrection_count < max_resurrections
                        and result.session_state
                        and not self._is_fatal_error(result.error)
                    ):
                        _resurrection_count += 1
                        logger.warning(
                            "Execution %s failed (%s) — resurrecting (%d/%d) from node '%s'",
                            execution_id,
                            (result.error or "unknown")[:200],
                            _resurrection_count,
                            max_resurrections,
                            result.session_state.get("resume_from", "?"),
                        )

                        # Emit resurrection event
                        if self._scoped_event_bus:
                            from framework.host.event_bus import AgentEvent, EventType

                            await self._scoped_event_bus.publish(
                                AgentEvent(
                                    type=EventType.EXECUTION_RESURRECTED,
                                    stream_id=self.stream_id,
                                    execution_id=execution_id,
                                    data={
                                        "attempt": _resurrection_count,
                                        "max_resurrections": max_resurrections,
                                        "error": (result.error or "")[:500],
                                        "resume_from": result.session_state.get("resume_from"),
                                    },
                                )
                            )

                        # Resume from the failed node with preserved memory
                        _current_session_state = {
                            **result.session_state,
                            "resume_session_id": execution_id,
                        }
                        # On resurrection, input_data is already in memory —
                        # pass empty so we don't overwrite intermediate results.
                        _current_input_data = {}

                        # Brief cooldown before resurrection
                        await asyncio.sleep(2.0)
                        continue

                    break  # success, fatal failure, or resurrections exhausted

                # Store result with retention
                self._record_execution_result(execution_id, result)

                # End run to complete trace (for observability)
                runtime_adapter.end_run(
                    success=result.success,
                    narrative=f"Execution {'succeeded' if result.success else 'failed'}",
                    output_data=result.output,
                )

                # Update context
                ctx.completed_at = datetime.now()
                ctx.status = "completed" if result.success else "failed"
                if result.paused_at:
                    ctx.status = "paused"

                # Write final session state (skip for shared-session executions)
                if not _is_shared_session:
                    await self._write_session_state(execution_id, ctx, result=result)

                # Emit completion/failure/pause event
                if self._scoped_event_bus:
                    if result.success:
                        await self._scoped_event_bus.emit_execution_completed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            output=result.output,
                            correlation_id=ctx.correlation_id,
                            run_id=ctx.run_id,
                        )
                    elif result.paused_at:
                        # The executor returns paused_at on CancelledError but
                        # does NOT emit execution_paused itself — we must emit
                        # it here so the frontend can transition out of "running".
                        await self._scoped_event_bus.emit_execution_paused(
                            stream_id=self.stream_id,
                            node_id=result.paused_at,
                            reason=result.error or "Execution paused",
                            execution_id=execution_id,
                        )
                    else:
                        await self._scoped_event_bus.emit_execution_failed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            error=result.error or "Unknown error",
                            correlation_id=ctx.correlation_id,
                            run_id=ctx.run_id,
                        )

                # Write run event for historical restoration
                if result.success:
                    self._write_run_event(execution_id, ctx.run_id, "run_completed")
                elif result.paused_at:
                    self._write_run_event(execution_id, ctx.run_id, "run_paused")
                else:
                    self._write_run_event(
                        execution_id,
                        ctx.run_id,
                        "run_failed",
                        {"error": result.error or "Unknown error"},
                    )

                logger.debug(f"Execution {execution_id} completed: success={result.success}")

            except asyncio.CancelledError:
                # Execution was cancelled
                # The executor catches CancelledError and returns a paused result,
                # but if cancellation happened before executor started, we won't have a result
                logger.info(f"Execution {execution_id} cancelled")

                # Check if we have a result (executor completed and returned)
                try:
                    _ = result  # Check if result variable exists
                    has_result = True
                except NameError:
                    has_result = False
                    result = ExecutionResult(
                        success=False,
                        error="Execution cancelled",
                    )

                # Update context status based on result
                if has_result and result.paused_at:
                    ctx.status = "paused"
                    ctx.completed_at = datetime.now()
                else:
                    ctx.status = "cancelled"

                # Clean up executor reference
                self._active_executors.pop(execution_id, None)

                # Store result with retention
                self._record_execution_result(execution_id, result)

                # Write session state (skip for shared-session executions)
                if not _is_shared_session:
                    if has_result and result.paused_at:
                        await self._write_session_state(execution_id, ctx, result=result)
                    else:
                        await self._write_session_state(execution_id, ctx, error="Execution cancelled")

                # Emit SSE event so the frontend knows the execution stopped.
                # The executor does NOT emit on CancelledError, so there is no
                # risk of double-emitting.
                cancel_reason = self._cancel_reasons.pop(execution_id, "Execution cancelled")
                if self._scoped_event_bus:
                    if has_result and result.paused_at:
                        await self._scoped_event_bus.emit_execution_paused(
                            stream_id=self.stream_id,
                            node_id=result.paused_at,
                            reason=cancel_reason,
                            execution_id=execution_id,
                        )
                    else:
                        await self._scoped_event_bus.emit_execution_failed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            error=cancel_reason,
                            correlation_id=ctx.correlation_id,
                            run_id=ctx.run_id,
                        )

                self._write_run_event(execution_id, ctx.run_id, "run_cancelled")
                # Don't re-raise - we've handled it and saved state

            except Exception as e:
                ctx.status = "failed"
                logger.error(f"Execution {execution_id} failed: {e}")

                # Store error result with retention
                self._record_execution_result(
                    execution_id,
                    ExecutionResult(
                        success=False,
                        error=str(e),
                    ),
                )

                # Write error session state (skip for shared-session executions)
                if not _is_shared_session:
                    await self._write_session_state(execution_id, ctx, error=str(e))

                # End run with failure (for observability)
                try:
                    runtime_adapter.end_run(
                        success=False,
                        narrative=f"Execution failed: {str(e)}",
                        output_data={},
                    )
                except Exception:
                    pass  # Don't let end_run errors mask the original error

                # Emit failure event
                if self._scoped_event_bus:
                    await self._scoped_event_bus.emit_execution_failed(
                        stream_id=self.stream_id,
                        execution_id=execution_id,
                        error=str(e),
                        correlation_id=ctx.correlation_id,
                        run_id=ctx.run_id,
                    )
                self._write_run_event(execution_id, ctx.run_id, "run_failed", {"error": str(e)})

            finally:
                # Clean up state
                self._state_manager.cleanup_execution(execution_id)

                # Signal completion
                if execution_id in self._completion_events:
                    self._completion_events[execution_id].set()

                # Remove in-flight bookkeeping
                async with self._lock:
                    self._active_executions.pop(execution_id, None)
                    self._completion_events.pop(execution_id, None)
                    self._execution_tasks.pop(execution_id, None)

    def _write_run_event(
        self,
        execution_id: str,
        run_id: str | None,
        event: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Append a run lifecycle event to runs.jsonl for historical restoration."""
        if not self._session_store or not run_id:
            return
        import json as _json

        try:
            session_dir = self._session_store.get_session_path(execution_id)
        except ValueError:
            return
        runs_file = session_dir / "runs.jsonl"
        now = datetime.now()
        record = {
            "run_id": run_id,
            "event": event,
            "timestamp": now.isoformat(),
            "created_at": now.timestamp(),
        }
        if extra:
            record.update(extra)
        try:
            runs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(runs_file, "a", encoding="utf-8") as f:
                f.write(_json.dumps(record) + "\n")
        except OSError:
            pass  # Non-critical — don't break execution

    async def _write_session_state(
        self,
        execution_id: str,
        ctx: ExecutionContext,
        result: ExecutionResult | None = None,
        error: str | None = None,
    ) -> None:
        """
        Write state.json for a session.

        Args:
            execution_id: Session/execution ID
            ctx: Execution context
            result: Optional execution result (if completed)
            error: Optional error message (if failed)
        """
        # Only write if session_store is available
        if not self._session_store:
            return

        from framework.schemas.session_state import SessionState, SessionStatus

        try:
            # Determine status
            if result:
                if result.paused_at:
                    status = SessionStatus.PAUSED
                elif result.success:
                    status = SessionStatus.COMPLETED
                else:
                    status = SessionStatus.FAILED
            elif error:
                # Check if this is a cancellation
                if ctx.status == "cancelled" or "cancelled" in error.lower():
                    status = SessionStatus.CANCELLED
                else:
                    status = SessionStatus.FAILED
            else:
                status = SessionStatus.ACTIVE

            # Create SessionState
            if result:
                # Create from execution result
                state = SessionState.from_execution_result(
                    session_id=execution_id,
                    goal_id=self.goal.id,
                    result=result,
                    stream_id=self.stream_id,
                    correlation_id=ctx.correlation_id,
                    started_at=ctx.started_at.isoformat(),
                    input_data=ctx.input_data,
                    agent_id=self.graph.id,
                    entry_point=self.entry_spec.id,
                )
                state.current_run_id = ctx.run_id
            else:
                # Create initial state — when resuming, preserve the previous
                # execution's progress so crashes don't lose track of state.
                from framework.schemas.session_state import (
                    SessionProgress,
                    SessionTimestamps,
                )

                now = datetime.now().isoformat()
                ss = ctx.session_state or {}
                progress = SessionProgress(
                    current_node=ss.get("paused_at") or ss.get("resume_from"),
                    paused_at=ss.get("paused_at"),
                    resume_from=ss.get("paused_at") or ss.get("resume_from"),
                    path=ss.get("execution_path", []),
                    node_visit_counts=ss.get("node_visit_counts", {}),
                )
                state = SessionState(
                    session_id=execution_id,
                    stream_id=self.stream_id,
                    correlation_id=ctx.correlation_id,
                    goal_id=self.goal.id,
                    agent_id=self.graph.id,
                    entry_point=self.entry_spec.id,
                    status=status,
                    timestamps=SessionTimestamps(
                        started_at=ctx.started_at.isoformat(),
                        updated_at=now,
                    ),
                    progress=progress,
                    data_buffer=ss.get("data_buffer", ss.get("memory", {})),
                    input_data=ctx.input_data,
                    current_run_id=ctx.run_id,
                )

            # Handle error case
            if error:
                state.result.error = error

            # Stamp the owning process ID for cross-process stale detection
            state.pid = os.getpid()

            # Write state.json
            await self._session_store.write_state(execution_id, state)
            logger.debug(f"Wrote state.json for session {execution_id} (status={status})")

        except Exception as e:
            # Log but don't fail the execution
            logger.error(f"Failed to write state.json for {execution_id}: {e}")

    def _create_modified_graph(self) -> "GraphSpec":
        """Create a graph with the entry point overridden.

        Preserves the original graph's entry_points so that validation
        correctly considers ALL entry nodes reachable.
        Each stream only executes from its own entry_node, but the full
        graph must validate with all entry points accounted for.
        """
        from framework.orchestrator.edge import GraphSpec

        # Merge entry points: this stream's entry + original graph's primary
        # entry + any other entry points. This ensures all nodes are
        # reachable during validation even though this stream only starts
        # from self.entry_spec.entry_node.
        merged_entry_points = {
            "start": self.entry_spec.entry_node,
        }
        # Preserve the original graph's primary entry node
        if self.graph.entry_node:
            merged_entry_points["primary"] = self.graph.entry_node
        # Include any explicitly defined entry points from the graph
        merged_entry_points.update(self.graph.entry_points)

        return GraphSpec(
            id=self.graph.id,
            goal_id=self.graph.goal_id,
            version=self.graph.version,
            entry_node=self.entry_spec.entry_node,  # Use our entry point
            entry_points=merged_entry_points,
            terminal_nodes=self.graph.terminal_nodes,
            pause_nodes=self.graph.pause_nodes,
            nodes=self.graph.nodes,
            edges=self.graph.edges,
            default_model=self.graph.default_model,
            max_tokens=self.graph.max_tokens,
            max_steps=self.graph.max_steps,
            cleanup_llm_model=self.graph.cleanup_llm_model,
            loop_config=self.graph.loop_config,
            conversation_mode=self.graph.conversation_mode,
            identity_prompt=self.graph.identity_prompt,
        )

    async def wait_for_completion(
        self,
        execution_id: str,
        timeout: float | None = None,
    ) -> ExecutionResult | None:
        """
        Wait for an execution to complete.

        Args:
            execution_id: Execution to wait for
            timeout: Maximum time to wait (seconds)

        Returns:
            ExecutionResult or None if timeout
        """
        event = self._completion_events.get(execution_id)
        if event is None:
            # Execution not found or already cleaned up
            self._prune_execution_results()
            return self._execution_results.get(execution_id)

        try:
            if timeout:
                await asyncio.wait_for(event.wait(), timeout=timeout)
            else:
                await event.wait()

            self._prune_execution_results()
            return self._execution_results.get(execution_id)

        except TimeoutError:
            return None

    def get_result(self, execution_id: str) -> ExecutionResult | None:
        """Get result of a completed execution."""
        self._prune_execution_results()
        return self._execution_results.get(execution_id)

    def get_context(self, execution_id: str) -> ExecutionContext | None:
        """Get execution context."""
        return self._active_executions.get(execution_id)

    async def cancel_execution(self, execution_id: str, *, reason: str | None = None) -> bool:
        """
        Cancel a running execution.

        Args:
            execution_id: Execution to cancel
            reason: Human-readable reason for the cancellation (e.g.
                "Stopped by queen", "User requested pause"). If not
                provided, defaults to "Execution cancelled".

        Returns:
            True if cancelled, False if not found
        """
        task = self._execution_tasks.get(execution_id)
        if task and not task.done():
            # Store the reason so the CancelledError handler can use it
            # when emitting the pause/fail event.
            self._cancel_reasons[execution_id] = reason or "Execution cancelled"
            task.cancel()
            # Wait briefly for the task to finish. Don't block indefinitely —
            # the task may be stuck in a long LLM API call that doesn't
            # respond to cancellation quickly.
            done, _ = await asyncio.wait({task}, timeout=5.0)
            if not done:
                # Task didn't finish within timeout — clean up bookkeeping now
                # so the session doesn't think it still has running executions.
                # The task will continue winding down in the background and its
                # finally block will harmlessly pop already-removed keys.
                logger.warning(
                    "Execution %s did not finish within cancel timeout; force-cleaning bookkeeping",
                    execution_id,
                )
                async with self._lock:
                    self._active_executions.pop(execution_id, None)
                    self._execution_tasks.pop(execution_id, None)
                self._active_executors.pop(execution_id, None)
            return True
        return False

    # === STATS AND MONITORING ===

    def get_active_count(self) -> int:
        """Get count of active executions."""
        return len([ctx for ctx in self._active_executions.values() if ctx.status == "running"])

    def get_stats(self) -> dict:
        """Get stream statistics."""
        statuses = {}
        for ctx in self._active_executions.values():
            statuses[ctx.status] = statuses.get(ctx.status, 0) + 1

        # Calculate available slots from running count instead of accessing private _value
        running_count = statuses.get("running", 0)
        available_slots = self.entry_spec.max_concurrent - running_count

        return {
            "stream_id": self.stream_id,
            "entry_point": self.entry_spec.id,
            "running": self._running,
            "total_executions": len(self._active_executions),
            "completed_executions": len(self._execution_results),
            "status_counts": statuses,
            "max_concurrent": self.entry_spec.max_concurrent,
            "available_slots": available_slots,
        }
