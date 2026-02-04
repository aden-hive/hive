"""
Agent Runtime - Top-level orchestrator for multi-entry-point agents.

Manages agent lifecycle and coordinates multiple execution streams
while preserving the goal-driven approach.
"""

import asyncio
import logging
import signal
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.graph.executor import ExecutionResult
from framework.runtime.event_bus import AgentEvent, EventBus, EventType
from framework.runtime.execution_stream import EntryPointSpec, ExecutionStream
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.goal import Goal
    from framework.llm.provider import LLMProvider, Tool

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """
    Lifecycle states for an agent runtime.

    State transitions:
        INITIALIZING -> READY -> RUNNING <-> PAUSED
                                    |
                                    v
                               DRAINING -> STOPPED
                                    |
                                    v
                                  ERROR
    """

    INITIALIZING = "initializing"  # Starting up, loading config
    READY = "ready"  # Can accept new executions, none running
    RUNNING = "running"  # Actively executing goals
    PAUSED = "paused"  # Temporarily suspended, state preserved
    DRAINING = "draining"  # Finishing current work, rejecting new
    STOPPED = "stopped"  # Fully stopped
    ERROR = "error"  # Unrecoverable error state

    @classmethod
    def valid_transitions(cls) -> dict["AgentState", set["AgentState"]]:
        """
        Define valid state transitions.

        Returns:
            Dict mapping each state to the set of states it can transition to.
        """
        return {
            cls.INITIALIZING: {cls.READY, cls.ERROR},
            cls.READY: {cls.RUNNING, cls.PAUSED, cls.DRAINING, cls.STOPPED, cls.ERROR},
            cls.RUNNING: {cls.READY, cls.PAUSED, cls.DRAINING, cls.ERROR},
            cls.PAUSED: {cls.READY, cls.RUNNING, cls.DRAINING, cls.STOPPED, cls.ERROR},
            cls.DRAINING: {cls.STOPPED, cls.ERROR},
            cls.STOPPED: {cls.INITIALIZING},  # Can restart
            cls.ERROR: {cls.STOPPED, cls.INITIALIZING},  # Can recover
        }

    def can_transition_to(self, target: "AgentState") -> bool:
        """
        Check if transition to target state is valid.

        Args:
            target: The state to transition to

        Returns:
            True if the transition is valid
        """
        return target in self.valid_transitions().get(self, set())


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
        """
        self.graph = graph
        self.goal = goal
        self._config = config or AgentRuntimeConfig()

        # Initialize storage
        self._storage = ConcurrentStorage(
            base_path=storage_path,
            cache_ttl=self._config.cache_ttl,
            batch_interval=self._config.batch_interval,
        )

        # Initialize shared components
        self._state_manager = SharedStateManager()
        self._event_bus = EventBus(max_history=self._config.max_history)
        self._outcome_aggregator = OutcomeAggregator(goal, self._event_bus)

        # LLM and tools
        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor

        # Entry points and streams
        self._entry_points: dict[str, EntryPointSpec] = {}
        self._streams: dict[str, ExecutionStream] = {}

        # Lifecycle state
        self._state = AgentState.INITIALIZING
        self._started_at: datetime | None = None
        self._running = False
        self._paused = False
        self._draining = False
        self._lock = asyncio.Lock()
        self._drain_event: asyncio.Event | None = None
        self._signal_handlers_installed = False

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
            # Emit starting event
            await self._emit_lifecycle_event(EventType.AGENT_STARTING)

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
                )
                await stream.start()
                self._streams[ep_id] = stream

            self._running = True
            self._started_at = datetime.now()
            self._state = AgentState.READY
            self._install_signal_handlers()

            await self._emit_lifecycle_event(EventType.AGENT_READY)
            logger.info(f"AgentRuntime started with {len(self._streams)} streams")

    async def stop(self) -> None:
        """Stop the agent runtime and all streams."""
        if not self._running:
            return

        async with self._lock:
            await self._emit_lifecycle_event(EventType.AGENT_STOPPING)

            # Stop all streams
            for stream in self._streams.values():
                await stream.stop()

            self._streams.clear()

            # Stop storage
            await self._storage.stop()

            self._running = False
            self._state = AgentState.STOPPED
            self._uninstall_signal_handlers()

            await self._emit_lifecycle_event(EventType.AGENT_STOPPED)
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
            RuntimeError: If runtime not running or paused/draining
        """
        if not self._running:
            raise RuntimeError("AgentRuntime is not running")

        if self._paused:
            raise RuntimeError("AgentRuntime is paused - call resume() first")

        if self._draining:
            raise RuntimeError("AgentRuntime is draining - not accepting new executions")

        stream = self._streams.get(entry_point_id)
        if stream is None:
            raise ValueError(f"Entry point '{entry_point_id}' not found")

        # Update state to RUNNING if we were READY
        if self._state == AgentState.READY:
            self._state = AgentState.RUNNING

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

    # === LIFECYCLE MANAGEMENT ===

    async def pause(self) -> None:
        """
        Pause the agent runtime.

        Stops accepting new executions but preserves current state.
        In-flight executions continue to completion.
        Call resume() to continue accepting new executions.

        Raises:
            RuntimeError: If runtime is not running or already paused
        """
        if not self._running:
            raise RuntimeError("AgentRuntime is not running")

        if self._paused:
            return  # Already paused, no-op

        if self._draining:
            raise RuntimeError("Cannot pause while draining")

        async with self._lock:
            await self._emit_lifecycle_event(EventType.AGENT_PAUSING)

            self._paused = True
            self._state = AgentState.PAUSED

            await self._emit_lifecycle_event(EventType.AGENT_PAUSED)
            logger.info("AgentRuntime paused")

    async def resume(self) -> None:
        """
        Resume a paused agent runtime.

        Starts accepting new executions again.

        Raises:
            RuntimeError: If runtime is not paused
        """
        if not self._paused:
            raise RuntimeError("AgentRuntime is not paused")

        async with self._lock:
            await self._emit_lifecycle_event(EventType.AGENT_RESUMING)

            self._paused = False
            # Return to READY or RUNNING based on active executions
            active = self._get_active_execution_count()
            self._state = AgentState.RUNNING if active > 0 else AgentState.READY

            await self._emit_lifecycle_event(EventType.AGENT_READY)
            logger.info("AgentRuntime resumed")

    async def drain(self, timeout_seconds: float = 30.0) -> bool:
        """
        Drain the agent runtime gracefully.

        Stops accepting new executions and waits for in-flight
        executions to complete before stopping.

        Args:
            timeout_seconds: Maximum time to wait for executions to complete

        Returns:
            True if all executions completed, False if timeout occurred

        Raises:
            RuntimeError: If runtime is not running
        """
        if not self._running:
            raise RuntimeError("AgentRuntime is not running")

        async with self._lock:
            await self._emit_lifecycle_event(EventType.AGENT_DRAINING)

            self._draining = True
            self._state = AgentState.DRAINING
            self._drain_event = asyncio.Event()

            logger.info(
                f"AgentRuntime draining, waiting up to {timeout_seconds}s for "
                f"{self._get_active_execution_count()} active executions"
            )

        # Wait for all executions to complete (outside lock)
        try:
            await asyncio.wait_for(
                self._wait_for_drain(),
                timeout=timeout_seconds,
            )
            logger.info("All executions completed, drain successful")
            return True
        except TimeoutError:
            logger.warning(
                f"Drain timeout after {timeout_seconds}s, "
                f"{self._get_active_execution_count()} executions still active"
            )
            return False
        finally:
            self._draining = False
            self._drain_event = None

    async def graceful_shutdown(self, timeout_seconds: float = 30.0) -> None:
        """
        Perform a graceful shutdown.

        Drains active executions then stops the runtime.
        This is called automatically on SIGTERM/SIGINT.

        Args:
            timeout_seconds: Maximum time to wait for drain
        """
        logger.info("Initiating graceful shutdown...")
        await self.drain(timeout_seconds)
        await self.stop()

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
            "state": self._state.value,
            "paused": self._paused,
            "draining": self._draining,
            "uptime_seconds": self.uptime_seconds,
            "active_executions": self._get_active_execution_count(),
            "entry_points": len(self._entry_points),
            "streams": stream_stats,
            "goal_id": self.goal.id,
            "outcome_aggregator": self._outcome_aggregator.get_stats(),
            "event_bus": self._event_bus.get_stats(),
            "state_manager": self._state_manager.get_stats(),
        }

    # === PROPERTIES ===

    @property
    def state(self) -> AgentState:
        """Get current lifecycle state."""
        return self._state

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

    @property
    def is_paused(self) -> bool:
        """Check if runtime is paused."""
        return self._paused

    @property
    def is_draining(self) -> bool:
        """Check if runtime is draining."""
        return self._draining

    @property
    def uptime_seconds(self) -> float:
        """Get uptime in seconds since start."""
        if self._started_at is None:
            return 0.0
        return (datetime.now() - self._started_at).total_seconds()

    @property
    def started_at(self) -> datetime | None:
        """Get the time when the runtime was started."""
        return self._started_at

    # === PRIVATE HELPERS ===

    def _get_active_execution_count(self) -> int:
        """Get total number of active executions across all streams."""
        total = 0
        for stream in self._streams.values():
            stats = stream.get_stats()
            total += stats.get("active_executions", 0)
        return total

    async def _wait_for_drain(self) -> None:
        """Wait for all active executions to complete."""
        while self._get_active_execution_count() > 0:
            await asyncio.sleep(0.1)

    async def _emit_lifecycle_event(self, event_type: EventType) -> None:
        """Emit a lifecycle event to the event bus."""
        event = AgentEvent(
            type=event_type,
            stream_id="__runtime__",
            data={
                "state": self._state.value,
                "uptime_seconds": self.uptime_seconds,
                "active_executions": self._get_active_execution_count(),
            },
        )
        await self._event_bus.publish(event)

    def _install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        if self._signal_handlers_installed:
            return

        # Only install on Unix-like systems (not Windows)
        if sys.platform == "win32":
            logger.debug("Signal handlers not supported on Windows")
            return

        try:
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(
                    sig,
                    lambda s=sig: asyncio.create_task(self._handle_signal(s)),
                )
            self._signal_handlers_installed = True
            logger.debug("Signal handlers installed for SIGTERM and SIGINT")
        except Exception as e:
            logger.warning(f"Failed to install signal handlers: {e}")

    def _uninstall_signal_handlers(self) -> None:
        """Remove signal handlers."""
        if not self._signal_handlers_installed:
            return

        if sys.platform == "win32":
            return

        try:
            loop = asyncio.get_event_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.remove_signal_handler(sig)
            self._signal_handlers_installed = False
            logger.debug("Signal handlers removed")
        except Exception as e:
            logger.warning(f"Failed to remove signal handlers: {e}")

    async def _handle_signal(self, sig: signal.Signals) -> None:
        """Handle a shutdown signal."""
        logger.info(f"Received signal {sig.name}, initiating graceful shutdown...")
        await self.graceful_shutdown()


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
) -> AgentRuntime:
    """
    Create and configure an AgentRuntime with entry points.

    Convenience factory that creates runtime and registers entry points.

    Args:
        graph: Graph specification
        goal: Goal driving execution
        storage_path: Path for persistent storage
        entry_points: Entry point specifications
        llm: LLM provider
        tools: Available tools
        tool_executor: Tool executor function
        config: Runtime configuration

    Returns:
        Configured AgentRuntime (not yet started)
    """
    runtime = AgentRuntime(
        graph=graph,
        goal=goal,
        storage_path=storage_path,
        llm=llm,
        tools=tools,
        tool_executor=tool_executor,
        config=config,
    )

    for spec in entry_points:
        runtime.register_entry_point(spec)

    return runtime
