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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, TYPE_CHECKING

from framework.graph.executor import GraphExecutor, ExecutionResult
from framework.runtime.stream_runtime import StreamRuntime, StreamRuntimeAdapter
from framework.runtime.shared_state import SharedStateManager, IsolationLevel, StreamMemory

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.goal import Goal
    from framework.storage.concurrent import ConcurrentStorage
    from framework.runtime.outcome_aggregator import OutcomeAggregator
    from framework.runtime.event_bus import EventBus
    from framework.llm.provider import LLMProvider, Tool

logger = logging.getLogger(__name__)


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
        """
        self.stream_id = stream_id
        self.entry_spec = entry_spec
        self.graph = graph
        self.goal = goal
        self._state_manager = state_manager
        self._storage = storage
        self._outcome_aggregator = outcome_aggregator
        self._event_bus = event_bus
        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor
        self._result_retention_max = result_retention_max
        self._result_retention_ttl_seconds = result_retention_ttl_seconds

        # Create stream-scoped runtime
        self._runtime = StreamRuntime(
            stream_id=stream_id,
            storage=storage,
            outcome_aggregator=outcome_aggregator,
        )

        # Execution tracking
        self._active_executions: dict[str, ExecutionContext] = {}
        self._execution_tasks: dict[str, asyncio.Task] = {}
        self._execution_results: OrderedDict[str, ExecutionResult] = OrderedDict()
        self._execution_result_times: dict[str, float] = {}
        self._completion_events: dict[str, asyncio.Event] = {}

        # Concurrency control
        self._semaphore = asyncio.Semaphore(entry_spec.max_concurrent)
        self._lock = asyncio.Lock()

        # State
        self._running = False

    async def start(self) -> None:
        """Start the execution stream."""
        if self._running:
            return

        self._running = True
        logger.info(f"ExecutionStream '{self.stream_id}' started")

        # Emit stream started event
        if self._event_bus:
            from framework.runtime.event_bus import EventType, AgentEvent
            await self._event_bus.publish(AgentEvent(
                type=EventType.STREAM_STARTED,
                stream_id=self.stream_id,
                data={"entry_point": self.entry_spec.id},
            ))

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
        for exec_id, task in self._execution_tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._execution_tasks.clear()
        self._active_executions.clear()

        logger.info(f"ExecutionStream '{self.stream_id}' stopped")

        # Emit stream stopped event
        if self._event_bus:
            from framework.runtime.event_bus import EventType, AgentEvent
            await self._event_bus.publish(AgentEvent(
                type=EventType.STREAM_STOPPED,
                stream_id=self.stream_id,
            ))

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

        # Generate execution ID
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

        # Acquire semaphore to limit concurrency
        async with self._semaphore:
            ctx.status = "running"

            try:
                # Emit started event
                if self._event_bus:
                    await self._event_bus.emit_execution_started(
                        stream_id=self.stream_id,
                        execution_id=execution_id,
                        input_data=ctx.input_data,
                        correlation_id=ctx.correlation_id,
                    )

                # Create execution-scoped memory
                memory = self._state_manager.create_memory(
                    execution_id=execution_id,
                    stream_id=self.stream_id,
                    isolation=ctx.isolation_level,
                )

                # Create runtime adapter for this execution
                runtime_adapter = StreamRuntimeAdapter(self._runtime, execution_id)

                # Create executor for this execution
                executor = GraphExecutor(
                    runtime=runtime_adapter,
                    llm=self._llm,
                    tools=self._tools,
                    tool_executor=self._tool_executor,
                )

                # Create modified graph with entry point
                # We need to override the entry_node to use our entry point
                modified_graph = self._create_modified_graph()

                # Execute
                result = await executor.execute(
                    graph=modified_graph,
                    goal=self.goal,
                    input_data=ctx.input_data,
                    session_state=ctx.session_state,
                )

                # Store result with retention
                self._record_execution_result(execution_id, result)

                # Update context
                ctx.completed_at = datetime.now()
                ctx.status = "completed" if result.success else "failed"
                if result.paused_at:
                    ctx.status = "paused"

                # Emit completion/failure event
                if self._event_bus:
                    if result.success:
                        await self._event_bus.emit_execution_completed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            output=result.output,
                            correlation_id=ctx.correlation_id,
                        )
                    else:
                        await self._event_bus.emit_execution_failed(
                            stream_id=self.stream_id,
                            execution_id=execution_id,
                            error=result.error or "Unknown error",
                            correlation_id=ctx.correlation_id,
                        )

                logger.debug(f"Execution {execution_id} completed: success={result.success}")

            except asyncio.CancelledError:
                ctx.status = "cancelled"
                raise

            except Exception as e:
                ctx.status = "failed"
                logger.error(f"Execution {execution_id} failed: {e}")

                # Store error result with retention
                self._record_execution_result(execution_id, ExecutionResult(
                    success=False,
                    error=str(e),
                ))

                # Emit failure event
                if self._event_bus:
                    await self._event_bus.emit_execution_failed(
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

    def _create_modified_graph(self) -> "GraphSpec":
        """Create a graph with the entry point overridden."""
        # Use the existing graph but override entry_node
        from framework.graph.edge import GraphSpec

        # Create a copy with modified entry node
        return GraphSpec(
            id=self.graph.id,
            goal_id=self.graph.goal_id,
            version=self.graph.version,
            entry_node=self.entry_spec.entry_node,  # Use our entry point
            entry_points={
                "start": self.entry_spec.entry_node,
                **self.graph.entry_points,
            },
            terminal_nodes=self.graph.terminal_nodes,
            pause_nodes=self.graph.pause_nodes,
            nodes=self.graph.nodes,
            edges=self.graph.edges,
            default_model=self.graph.default_model,
            max_tokens=self.graph.max_tokens,
            max_steps=self.graph.max_steps,
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

        except asyncio.TimeoutError:
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
        return len([
            ctx for ctx in self._active_executions.values()
            if ctx.status == "running"
        ])

    def get_stats(self) -> dict:
        """Get stream statistics."""
        statuses = {}
        for ctx in self._active_executions.values():
            statuses[ctx.status] = statuses.get(ctx.status, 0) + 1

        return {
            "stream_id": self.stream_id,
            "entry_point": self.entry_spec.id,
            "running": self._running,
            "total_executions": len(self._active_executions),
            "completed_executions": len(self._execution_results),
            "status_counts": statuses,
            "max_concurrent": self.entry_spec.max_concurrent,
            "available_slots": self._semaphore._value,
        }
