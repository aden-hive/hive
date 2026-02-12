"""
Agent Runtime - Top-level orchestrator for multi-entry-point agents.

Manages agent lifecycle and coordinates multiple execution streams
while preserving the goal-driven approach.
"""

import asyncio
import logging
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.graph.checkpoint_config import CheckpointConfig
from framework.graph.executor import ExecutionResult
from framework.runtime.event_bus import EventBus
from framework.runtime.execution_stream import EntryPointSpec, ExecutionStream
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage
from framework.storage.session_store import SessionStore
try:
    # Prefer the full EvolutionGuard implementation if provided by core.safety
    from core.safety.evolution_guard import EvolutionGuard, ValidationResult
except Exception:
    # Fallback to the local skeleton (keeps compatibility during iterative work)
    from framework.runtime.evolution_guard import EvolutionGuard, ValidationResult

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.goal import Goal
    from framework.llm.provider import LLMProvider, Tool

logger = logging.getLogger(__name__)


@dataclass
class AgentRuntimeConfig:
    """Configuration for AgentRuntime."""

    max_concurrent_executions: int = 100
    cache_ttl: float = 60.0
    batch_interval: float = 0.1
    max_history: int = 1000
    execution_result_max: int = 1000
    execution_result_ttl_seconds: float | None = None


class AgentRuntime:
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
        evolution_guard: EvolutionGuard | None = None,
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
        """
        self.graph = graph
        self.goal = goal
        self._config = config or AgentRuntimeConfig()
        self._runtime_log_store = runtime_log_store
        self._checkpoint_config = checkpoint_config

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
        self._state_manager = SharedStateManager()
        self._event_bus = EventBus(max_history=self._config.max_history)
        self._outcome_aggregator = OutcomeAggregator(goal, self._event_bus)

        # LLM and tools
        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor
        # Optional EvolutionGuard to provide snapshot/probation/rollback hooks
        self._evolution_guard = evolution_guard

        # Entry points and streams
        self._entry_points: dict[str, EntryPointSpec] = {}
        self._streams: dict[str, ExecutionStream] = {}

        # State
        self._running = False
        self._lock = asyncio.Lock()

        # Optional greeting shown to user on TUI load (set by AgentRunner)
        self.intro_message: str = ""

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

            # Create streams for each entry point
            for ep_id, spec in self._entry_points.items():
                stream = ExecutionStream(
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
                )
                await stream.start()
                self._streams[ep_id] = stream

            self._running = True
            logger.info(f"AgentRuntime started with {len(self._streams)} streams")

    async def stop(self) -> None:
        """Stop the agent runtime and all streams."""
        if not self._running:
            return

        async with self._lock:
            # Stop all streams
            for stream in self._streams.values():
                await stream.stop()

            self._streams.clear()

            # Stop storage
            await self._storage.stop()

            self._running = False
            logger.info("AgentRuntime stopped")

    async def trigger(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> str:
        """
        Trigger execution at a specific entry point.

        Non-blocking - returns immediately with execution ID.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            correlation_id: Optional ID to correlate related executions
            session_state: Optional session state to resume from (with paused_at, memory)

        Returns:
            Execution ID for tracking

        Raises:
            ValueError: If entry point not found
            RuntimeError: If runtime not running
        """
        if not self._running:
            raise RuntimeError("AgentRuntime is not running")

        stream = self._streams.get(entry_point_id)
        if stream is None:
            raise ValueError(f"Entry point '{entry_point_id}' not found")

        return await stream.execute(input_data, correlation_id, session_state)

    async def trigger_and_wait(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """
        Trigger execution and wait for completion.

        Args:
            entry_point_id: Which entry point to trigger
            input_data: Input data for the execution
            timeout: Maximum time to wait (seconds)
            session_state: Optional session state to resume from (with paused_at, memory)

        Returns:
            ExecutionResult or None if timeout
        """
        exec_id = await self.trigger(entry_point_id, input_data, session_state=session_state)
        stream = self._streams.get(entry_point_id)
        if stream is None:
            raise ValueError(f"Entry point '{entry_point_id}' not found")
        return await stream.wait_for_completion(exec_id, timeout)

    async def inject_input(self, node_id: str, content: str) -> bool:
        """Inject user input into a running client-facing node.

        Routes input to the EventLoopNode identified by ``node_id``
        across all active streams. Used by the TUI ChatRepl to deliver
        user responses during client-facing node execution.

        Args:
            node_id: The node currently waiting for input
            content: The user's input text

        Returns:
            True if input was delivered, False if no matching node found
        """
        for stream in self._streams.values():
            if await stream.inject_input(node_id, content):
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
    ) -> bool:
        """
        Cancel a running execution.

        Args:
            entry_point_id: Stream containing the execution
            execution_id: Execution to cancel

        Returns:
            True if cancelled, False if not found
        """
        stream = self._streams.get(entry_point_id)
        if stream is None:
            return False
        return await stream.cancel_execution(execution_id)

    # === QUERY OPERATIONS ===

    def get_entry_points(self) -> list[EntryPointSpec]:
        """Get all registered entry points."""
        return list(self._entry_points.values())

    def get_stream(self, entry_point_id: str) -> ExecutionStream | None:
        """Get a specific execution stream."""
        return self._streams.get(entry_point_id)

    def get_execution_result(
        self,
        entry_point_id: str,
        execution_id: str,
    ) -> ExecutionResult | None:
        """Get result of a completed execution."""
        stream = self._streams.get(entry_point_id)
        if stream:
            return stream.get_result(execution_id)
        return None

    async def update_graph(
        self,
        new_graph: "GraphSpec",
        *,
        correlation_id: str | None = None,
        probation_steps: int = 10,
    ) -> None:
        """Replace the current graph with a new GraphSpec and emit a GRAPH_EVOLVED event.

        This is a convenience method that callers (e.g. a CodingAgent or management
        API) can use to notify the runtime that the graph has been updated. The
        TUI and other subscribers can listen for EventType.GRAPH_EVOLVED to render
        visual diffs or take other actions.
        """
        old_graph = getattr(self, "graph", None)

        # Try to serialize graphs to plain dicts for event payloads
        def _serialize(g):
            if g is None:
                return {}
            try:
                return g.model_dump()
            except Exception:
                try:
                    return g.dict()
                except Exception:
                    # Fallback: minimal representation
                    return {"id": getattr(g, "id", str(g))}

        old_ser = _serialize(old_graph)
        new_ser = _serialize(new_graph)

        # If an EvolutionGuard is provided, run the probation/approval flow.
        if self._evolution_guard is not None:
            try:
                snapshot_id = None
                try:
                    snapshot_id = self._evolution_guard.snapshot(old_graph)
                except Exception:
                    # Snapshot failing should not silently allow unsafe applies.
                    logger.exception("EvolutionGuard.snapshot failed; rejecting candidate")
                    # Emit rejected event with error
                    await self._event_bus.emit_graph_evolution_rejected(
                        stream_id="agent_runtime",
                        validation={"passed": False, "violations": ["snapshot_failed"]},
                        correlation_id=correlation_id,
                    )
                    return

                # Run probation (may be async) to validate candidate behavior
                try:
                    result: ValidationResult = await self._evolution_guard.probation_run(
                        snapshot_id, new_graph, steps=probation_steps
                    )
                except Exception:
                    logger.exception("EvolutionGuard.probation_run failed; rejecting")
                    try:
                        if snapshot_id:
                            self._evolution_guard.rollback(snapshot_id)
                    except Exception:
                        logger.exception("EvolutionGuard.rollback failed")
                    await self._event_bus.emit_graph_evolution_rejected(
                        stream_id="agent_runtime",
                        validation={
                            "passed": False,
                            "violations": ["probation_error"],
                        },
                        correlation_id=correlation_id,
                    )
                    return

                # Decide based on guard approve() and ValidationResult
                approved = False
                try:
                    approved = self._evolution_guard.approve(result)
                except Exception:
                    logger.exception("EvolutionGuard.approve raised; rejecting candidate")
                    approved = False

                # Audit the attempt
                try:
                    audit_entry = {
                        "snapshot_id": snapshot_id,
                        "candidate_graph_id": getattr(new_graph, "id", None),
                        "result": {
                            "passed": bool(result.passed),
                            "violations": result.violations,
                            "metrics": result.metrics,
                        },
                        "correlation_id": correlation_id,
                        "timestamp": time.time(),
                    }

                    try:
                        self._evolution_guard.audit_log(audit_entry)
                    except Exception:
                        logger.exception("EvolutionGuard.audit_log failed")

                    # Persist audit entry: prefer runtime_log_store if available,
                    # otherwise write a JSON file under storage path.
                    try:
                        persisted = False
                        if self._runtime_log_store is not None:
                            # Best-effort: try common method names
                            if hasattr(self._runtime_log_store, "write"):
                                try:
                                    self._runtime_log_store.write(audit_entry)
                                    persisted = True
                                except Exception:
                                    pass
                            if not persisted and hasattr(self._runtime_log_store, "append"):
                                try:
                                    self._runtime_log_store.append(audit_entry)
                                    persisted = True
                                except Exception:
                                    pass

                        if not persisted:
                            base = getattr(self._storage, "base_path", Path("."))
                            audit_dir = Path(base) / "evolution_audit"
                            audit_dir.mkdir(parents=True, exist_ok=True)
                            fname = correlation_id or snapshot_id or str(int(time.time() * 1000))
                            with open(audit_dir / f"{fname}.json", "w", encoding="utf-8") as fh:
                                json.dump(audit_entry, fh, indent=2, default=str)
                    except Exception:
                        logger.exception("Failed to persist evolution audit entry")
                except Exception:
                    logger.exception("EvolutionGuard.audit_log failed")

                if not approved:
                    # Rollback to snapshot and emit REJECTED event with details
                    try:
                        if snapshot_id:
                            self._evolution_guard.rollback(snapshot_id)
                    except Exception:
                        logger.exception("EvolutionGuard.rollback failed after rejection")

                    # Publish rejection with validation details so UIs can surface reasons
                    try:
                        await self._event_bus.emit_graph_evolution_rejected(
                            stream_id="agent_runtime",
                            validation={
                                "passed": bool(result.passed),
                                "violations": result.violations,
                                "metrics": result.metrics,
                            },
                            correlation_id=correlation_id,
                        )
                    except Exception:
                        logger.exception("Failed to emit GRAPH_EVOLUTION_REJECTED event")

                    return

                # Approved: proceed to apply below
            except Exception:
                logger.exception("Unexpected error in EvolutionGuard flow; rejecting candidate")
                try:
                    await self._event_bus.emit_graph_evolution_rejected(
                        stream_id="agent_runtime",
                        validation={"passed": False, "violations": ["unexpected_error"]},
                        correlation_id=correlation_id,
                    )
                except Exception:
                    logger.exception("Failed to emit GRAPH_EVOLUTION_REJECTED")
                return

        # Replace graph
        self.graph = new_graph

        # Emit event to notify subscribers
        try:
            await self._event_bus.emit_graph_evolved(
                stream_id="agent_runtime",
                old_graph=old_ser,
                new_graph=new_ser,
                correlation_id=correlation_id,
            )
        except Exception:
            logger.exception("Failed to emit GRAPH_EVOLVED event")

    # === EVENT SUBSCRIPTIONS ===

    def subscribe_to_events(
        self,
        event_types: list,
        handler: Callable,
        filter_stream: str | None = None,
    ) -> str:
        """
        Subscribe to agent events.

        Args:
            event_types: Types of events to receive
            handler: Async function to call when event occurs
            filter_stream: Only receive events from this stream

        Returns:
            Subscription ID (use to unsubscribe)
        """
        return self._event_bus.subscribe(
            event_types=event_types,
            handler=handler,
            filter_stream=filter_stream,
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

    # === PROPERTIES ===

    @property
    def state_manager(self) -> SharedStateManager:
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
    def is_running(self) -> bool:
        """Check if runtime is running."""
        return self._running


# === CONVENIENCE FACTORY ===


def create_agent_runtime(
    graph: "GraphSpec",
    goal: "Goal",
    storage_path: str | Path,
    entry_points: list[EntryPointSpec],
    llm: "LLMProvider | None" = None,
    tools: list["Tool"] | None = None,
    tool_executor: Callable | None = None,
    config: AgentRuntimeConfig | None = None,
    runtime_log_store: Any = None,
    enable_logging: bool = True,
    checkpoint_config: CheckpointConfig | None = None,
    evolution_guard: EvolutionGuard | None = None,
) -> AgentRuntime:
    """
    Create and configure an AgentRuntime with entry points.

    Convenience factory that creates runtime and registers entry points.
    Runtime logging is enabled by default for observability.

    Args:
        graph: Graph specification
        goal: Goal driving execution
        storage_path: Path for persistent storage
        entry_points: Entry point specifications
        llm: LLM provider
        tools: Available tools
        tool_executor: Tool executor function
        config: Runtime configuration
        runtime_log_store: Optional RuntimeLogStore for per-execution logging.
            If None and enable_logging=True, creates one automatically.
        enable_logging: Whether to enable runtime logging (default: True).
            Set to False to disable logging entirely.
        checkpoint_config: Optional checkpoint configuration for resumable sessions.
            If None, uses default checkpointing behavior.

    Returns:
        Configured AgentRuntime (not yet started)
    """
    # Auto-create runtime log store if logging is enabled and not provided
    if enable_logging and runtime_log_store is None:
        from framework.runtime.runtime_log_store import RuntimeLogStore

        storage_path_obj = Path(storage_path) if isinstance(storage_path, str) else storage_path
        runtime_log_store = RuntimeLogStore(storage_path_obj / "runtime_logs")

    # If an EvolutionGuard instance wasn't provided, attempt to instantiate
    # the concrete implementation from core.safety if available.
    if evolution_guard is None:
        try:
            from core.safety.evolution_guard import EvolutionGuard as ConcreteGuard

            evolution_guard = ConcreteGuard()
        except Exception:
            # Leave as None — runtime will operate without guard.
            evolution_guard = None

    runtime = AgentRuntime(
        graph=graph,
        goal=goal,
        storage_path=storage_path,
        llm=llm,
        tools=tools,
        tool_executor=tool_executor,
        config=config,
        runtime_log_store=runtime_log_store,
        checkpoint_config=checkpoint_config,
        evolution_guard=evolution_guard,
    )

    for spec in entry_points:
        runtime.register_entry_point(spec)

    return runtime
