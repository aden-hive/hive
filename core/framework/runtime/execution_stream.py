"""
Execution Stream - Manages concurrent executions for a single entry point.

Each stream has:
- Its own StreamRuntime for decision tracking
- Access to shared state (read/write based on isolation)
- Connection to the outcome aggregator
"""

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.shared_state import IsolationLevel, SharedStateManager
from framework.runtime.stream_runtime import StreamRuntime, StreamRuntimeAdapter

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.goal import Goal
    from framework.llm.provider import LLMProvider, Tool
    from framework.runtime.event_bus import AgentEvent
    from framework.runtime.outcome_aggregator import OutcomeAggregator
    from framework.storage.concurrent import ConcurrentStorage
    from framework.storage.session_store import SessionStore

logger = logging.getLogger(__name__)


class _GraphScopedEventBus(EventBus):
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

    async def publish(self, event: "AgentEvent") -> None:  # type: ignore[override]
        event.graph_id = self._scope_graph_id
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
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    status: str = "pending"  # pending, running, completed, failed, paused


class ExecutionStream:
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
        state_manager: SharedStateManager,
        storage: "ConcurrentStorage",
        outcome_aggregator: "OutcomeAggregator",
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

        # Create stream-scoped runtime
        self._runtime = StreamRuntime(
            stream_id=stream_id,
            storage=storage,
            outcome_aggregator=outcome_aggregator,
        )

        # Execution tracking
        self._active_executions: dict[str, ExecutionContext] = {}
        self._execution_tasks: dict[str, asyncio.Task] = {}
        self._active_executors: dict[str, GraphExecutor] = {}
        self._execution_results: OrderedDict[str, ExecutionResult] = OrderedDict()
        self._execution_result_times: dict[str, float] = {}
        self._completion_events: dict[str, asyncio.Event] = {}

        # Concurrency control
        self._semaphore = asyncio.Semaphore(entry_spec.max_concurrent)
        self._lock = asyncio.Lock()

        # Graph-scoped event bus (stamps graph_id on published events)
        self._scoped_event_bus = self._event_bus
        if self._event_bus and self.graph_id:
            self._scoped_event_bus = _GraphScopedEventBus(self._event_bus, self.graph_id)

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
            from framework.runtime.event_bus import AgentEvent, EventType

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
    def is_awaiting_input(self) -> bool:
        """True when an active execution is blocked waiting for client input."""
        if not self._active_executors:
            return False
        for executor in self._active_executors.values():
            for node in executor.node_registry.values():
                if getattr(node, "_awaiting_input", False):
                    return True
        return False

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
        for _, task in self._execution_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except RuntimeError as e:
                    # Task may be attached to a different event loop (e.g., when TUI
                    # uses a separate loop). Log and continue cleanup.
                    if "attached to a different loop" in str(e):
                        logger.warning(f"Task cleanup skipped (different event loop): {e}")
                    else:
                        raise

        self._execution_tasks.clear()
        self._active_executions.clear()

        logger.info(f"ExecutionStream '{self.stream_id}' stopped")

        # Emit stream stopped event
        if self._scoped_event_bus:
            from framework.runtime.event_bus import AgentEvent, EventType

            await self._scoped_event_bus.publish(
                AgentEvent(
                    type=EventType.STREAM_STOPPED,
                    stream_id=self.stream_id,
                )
            )

    async def inject_input(self, node_id: str, content: str) -> bool:
        """Inject user input into a running client-facing EventLoopNode.

        Searches active executors for a node matching ``node_id`` and calls
        its ``inject_event()`` method to unblock ``_await_user_input()``.

        Returns True if input was delivered, False otherwise.
        """
        for executor in self._active_executors.values():
            node = executor.node_registry.get(node_id)
            if node is not None and hasattr(node, "inject_event"):
                await node.inject_event(content)
                return True
        return False

    async def execute(
        self,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> str:
        """
        Queue an execution and return its ID.

        Non-blocking - the execution runs in the background.

        Args:
            input_data: Input data for this execution
            correlation_id: Optional ID to correlate related executions
            session_state: Optional session state to resume from (with paused_at, memory)

        Returns:
            Execution ID for tracking
        """
        if not self._running:
            raise RuntimeError(f"ExecutionStream '{self.stream_id}' is not running")

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
        ctx = ExecutionContext(
            id=execution_id,
            correlation_id=correlation_id,
            stream_id=self.stream_id,
            entry_point=self.entry_spec.id,
            input_data=input_data,
            isolation_level=self.entry_spec.get_isolation_level(),
            session_state=session_state,
        )

        async with self._lock:
            self._active_executions[execution_id] = ctx
            self._completion_events[execution_id] = asyncio.Event()

        # Start execution task
        task = asyncio.create_task(self._run_execution(ctx))
        self._execution_tasks[execution_id] = task

        logger.debug(f"Queued execution {execution_id} for stream {self.stream_id}")
        return execution_id

    async def _run_execution(self, ctx: ExecutionContext) -> None:
        """Run a single execution within the stream."""
        execution_id = ctx.id

        # When sharing a session with another entry point (resume_session_id),
        # skip writing initial/final session state — the primary execution
        # owns the state.json and _write_progress() keeps memory up-to-date.
        _is_shared_session = bool(ctx.session_state and ctx.session_state.get("resume_session_id"))

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
                    )

                # Create execution-scoped memory
                self._state_manager.create_memory(
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
                    from framework.runtime.runtime_logger import RuntimeLogger

                    runtime_logger = RuntimeLogger(
                        store=self._runtime_log_store, agent_id=self.graph.id
                    )

                # Create executor for this execution.
                # Each execution gets its own storage under sessions/{exec_id}/
                # so conversations, spillover, and data files are all scoped
                # to this execution.  The executor sets data_dir via execution
                # context (contextvars) so data tools and spillover share the
                # same session-scoped directory.
                # Derive storage from session_store (graph-specific for secondary
                # graphs) so that all files — conversations, state, checkpoints,
                # data — land under the graph's own sessions/ directory, not the
                # primary worker's.
                if self._session_store:
                    exec_storage = self._session_store.sessions_dir / execution_id
                else:
                    exec_storage = self._storage.base_path / "sessions" / execution_id
                executor = GraphExecutor(
                    runtime=runtime_adapter,
                    llm=self._llm,
                    tools=self._tools,
                    tool_executor=self._tool_executor,
                    event_bus=self._scoped_event_bus,
                    stream_id=self.stream_id,
                    storage_path=exec_storage,
                    runtime_logger=runtime_logger,
                    loop_config=self.graph.loop_config,
                    accounts_prompt=self._accounts_prompt,
                    accounts_data=self._accounts_data,
                    tool_provider_map=self._tool_provider_map,
                )
                # Track executor so inject_input() can reach EventLoopNode instances
                self._active_executors[execution_id] = executor

                # Write initial session state
                if not _is_shared_session:
                    await self._write_session_state(execution_id, ctx)

                # Create modified graph with entry point
                # We need to override the entry_node to use our entry point
                modified_graph = self._create_modified_graph()

                # Execute
                result = await executor.execute(
                    graph=modified_graph,
                    goal=self.goal,
                    input_data=ctx.input_data,
                    session_state=ctx.session_state,
                    checkpoint_config=self._checkpoint_config,
                )

                # Clean up executor reference
                self._active_executors.pop(execution_id, None)

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

                # Emit completion/failure event
                if self._scoped_event_bus:
                    if result.success:
                        await self._scoped_event_bus.emit_execution_completed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            output=result.output,
                            correlation_id=ctx.correlation_id,
                        )
                    else:
                        await self._scoped_event_bus.emit_execution_failed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            error=result.error or "Unknown error",
                            correlation_id=ctx.correlation_id,
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
                        await self._write_session_state(
                            execution_id, ctx, error="Execution cancelled"
                        )

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
                    )

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
                    memory=ss.get("memory", {}),
                    input_data=ctx.input_data,
                )

            # Handle error case
            if error:
                state.result.error = error

            # Write state.json
            await self._session_store.write_state(execution_id, state)
            logger.debug(f"Wrote state.json for session {execution_id} (status={status})")

        except Exception as e:
            # Log but don't fail the execution
            logger.error(f"Failed to write state.json for {execution_id}: {e}")

    def _create_modified_graph(self) -> "GraphSpec":
        """Create a graph with the entry point overridden.

        Preserves the original graph's entry_points and async_entry_points
        so that validation correctly considers ALL entry nodes reachable.
        Each stream only executes from its own entry_node, but the full
        graph must validate with all entry points accounted for.
        """
        from framework.graph.edge import GraphSpec

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
            async_entry_points=self.graph.async_entry_points,
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

    async def cancel_execution(self, execution_id: str) -> bool:
        """
        Cancel a running execution.

        Args:
            execution_id: Execution to cancel

        Returns:
            True if cancelled, False if not found
        """
        task = self._execution_tasks.get(execution_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
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
