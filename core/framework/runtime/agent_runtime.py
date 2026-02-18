"""
Agent Runtime - Top-level orchestrator for multi-entry-point agents.

Manages agent lifecycle and coordinates multiple execution streams
while preserving the goal-driven approach.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
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
    # Webhook server config (only starts if webhook_routes is non-empty)
    webhook_host: str = "127.0.0.1"
    webhook_port: int = 8080
    webhook_routes: list[dict] = field(default_factory=list)
    # Each dict: {"source_id": str, "path": str, "methods": ["POST"], "secret": str|None}


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

        # Entry points and streams
        self._entry_points: dict[str, EntryPointSpec] = {}
        self._streams: dict[str, ExecutionStream] = {}

        # Webhook server (created on start if webhook_routes configured)
        self._webhook_server: Any = None
        # Event-driven entry point subscriptions
        self._event_subscriptions: list[str] = []
        # Timer tasks for scheduled entry points
        self._timer_tasks: list[asyncio.Task] = []
        # Next fire time for each timer entry point (ep_id -> datetime)
        self._timer_next_fire: dict[str, float] = {}

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

            # Start webhook server if routes are configured
            if self._config.webhook_routes:
                from framework.runtime.webhook_server import (
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
            from framework.runtime.event_bus import EventType as _ET

            for ep_id, spec in self._entry_points.items():
                if spec.trigger_type != "event":
                    continue

                tc = spec.trigger_config
                event_types = [_ET(et) for et in tc.get("event_types", [])]
                if not event_types:
                    logger.warning(
                        f"Entry point '{ep_id}' has trigger_type='event' "
                        "but no event_types in trigger_config"
                    )
                    continue

                # Capture ep_id in closure
                def _make_handler(entry_point_id: str):
                    async def _on_event(event):
                        if self._running and entry_point_id in self._streams:
                            # Run in the same session as the primary entry
                            # point so memory (e.g. user-defined rules) is
                            # shared and logs land in one session directory.
                            session_state = self._get_primary_session_state(
                                exclude_entry_point=entry_point_id
                            )
                            await self.trigger(
                                entry_point_id,
                                {"event": event.to_dict()},
                                session_state=session_state,
                            )

                    return _on_event

                sub_id = self._event_bus.subscribe(
                    event_types=event_types,
                    handler=_make_handler(ep_id),
                    filter_stream=tc.get("filter_stream"),
                    filter_node=tc.get("filter_node"),
                )
                self._event_subscriptions.append(sub_id)

            # Start timer-driven entry points
            for ep_id, spec in self._entry_points.items():
                if spec.trigger_type != "timer":
                    continue

                tc = spec.trigger_config
                interval = tc.get("interval_minutes")
                if not interval or interval <= 0:
                    logger.warning(
                        f"Entry point '{ep_id}' has trigger_type='timer' "
                        "but no valid interval_minutes in trigger_config"
                    )
                    continue

                run_immediately = tc.get("run_immediately", False)

                def _make_timer(entry_point_id: str, mins: float, immediate: bool):
                    async def _timer_loop():
                        interval_secs = mins * 60
                        if not immediate:
                            self._timer_next_fire[entry_point_id] = time.monotonic() + interval_secs
                            await asyncio.sleep(interval_secs)
                        while self._running:
                            self._timer_next_fire.pop(entry_point_id, None)
                            try:
                                session_state = self._get_primary_session_state(
                                    exclude_entry_point=entry_point_id
                                )
                                await self.trigger(
                                    entry_point_id,
                                    {"event": {"source": "timer", "reason": "scheduled"}},
                                    session_state=session_state,
                                )
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

                task = asyncio.create_task(_make_timer(ep_id, interval, run_immediately)())
                self._timer_tasks.append(task)
                logger.info(
                    "Started timer for entry point '%s' every %s min%s",
                    ep_id,
                    interval,
                    " (immediate first run)" if run_immediately else "",
                )

            self._running = True
            logger.info(f"AgentRuntime started with {len(self._streams)} streams")

    async def stop(self) -> None:
        """Stop the agent runtime and all streams."""
        if not self._running:
            return

        async with self._lock:
            # Cancel timer tasks
            for task in self._timer_tasks:
                task.cancel()
            self._timer_tasks.clear()

            # Unsubscribe event-driven entry points
            for sub_id in self._event_subscriptions:
                self._event_bus.unsubscribe(sub_id)
            self._event_subscriptions.clear()

            # Stop webhook server
            if self._webhook_server:
                await self._webhook_server.stop()
                self._webhook_server = None

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

    def _get_primary_session_state(self, exclude_entry_point: str) -> dict[str, Any] | None:
        """Build session_state so an async entry point runs in the primary session.

        Looks for an active execution from another stream (the "primary"
        session, e.g. the user-facing intake loop) and returns a
        ``session_state`` dict containing:

        - ``resume_session_id``: reuse the same session directory
        - ``memory``: only the keys that the async entry node declares
          as inputs (e.g. ``rules``, ``max_emails``).  Stale outputs
          from previous runs (``emails``, ``actions_taken``, …) are
          excluded so each trigger starts fresh.

        The memory is read from the primary session's ``state.json``
        which is kept up-to-date by ``GraphExecutor._write_progress()``
        at every node transition.

        Returns ``None`` if no primary session is active (the webhook
        execution will just create its own session).
        """
        import json as _json

        # Determine which memory keys the async entry node needs.
        allowed_keys: set[str] | None = None
        ep_spec = self._entry_points.get(exclude_entry_point)
        if ep_spec:
            entry_node = self.graph.get_node(ep_spec.entry_node)
            if entry_node and entry_node.input_keys:
                allowed_keys = set(entry_node.input_keys)

        for ep_id, stream in self._streams.items():
            if ep_id == exclude_entry_point:
                continue
            for exec_id in stream.active_execution_ids:
                state_path = self._storage.base_path / "sessions" / exec_id / "state.json"
                try:
                    if state_path.exists():
                        data = _json.loads(state_path.read_text(encoding="utf-8"))
                        full_memory = data.get("memory", {})
                        if not full_memory:
                            continue
                        # Filter to only input keys so stale outputs
                        # from previous triggers don't leak through.
                        if allowed_keys is not None:
                            memory = {k: v for k, v in full_memory.items() if k in allowed_keys}
                        else:
                            memory = full_memory
                        if memory:
                            return {
                                "resume_session_id": exec_id,
                                "memory": memory,
                            }
                except Exception:
                    logger.debug(
                        "Could not read state.json for %s: skipping",
                        exec_id,
                        exc_info=True,
                    )
        return None

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
    def webhook_server(self) -> Any:
        """Access the webhook server (None if no webhook entry points)."""
        return self._webhook_server

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
    )

    for spec in entry_points:
        runtime.register_entry_point(spec)

    return runtime
