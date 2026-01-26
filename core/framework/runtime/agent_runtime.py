"""
Agent Runtime - Top-level orchestrator for multi-entry-point agents.

Manages agent lifecycle and coordinates multiple execution streams
while preserving the goal-driven approach.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.graph.executor import ExecutionResult
from framework.runtime.event_bus import EventBus
from framework.runtime.execution_stream import EntryPointSpec, ExecutionStream
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage
from framework.graph.mutation import GraphDelta

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
        
        # Initialize Memory Hub (MVP Integration)
        # In production this would be injected or configured via config
        from framework.memory.providers.local import LocalJSONLProvider
        from framework.memory.hub import MemoryHub
        
        # Quick Mock Embedder for Runtime (so valid agents don't crash)
        from framework.memory.provider import BaseEmbeddingProvider
        class RuntimeMockEmbedder(BaseEmbeddingProvider):
            async def embed(self, text: str) -> list[float]:
                # Deterministic fake embedding
                val = len(text) % 10 / 10.0
                return [val, 0.5, 0.5]

        # Use shared memory file in .hive storage
        mem_path = Path(storage_path) / "agent_memory.jsonl"
        self.memory_hub = MemoryHub(
            provider=LocalJSONLProvider(str(mem_path)),
            embedder=RuntimeMockEmbedder()
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

        # State
        self._running = False
        self._lock = asyncio.Lock()

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
    def is_running(self) -> bool:
        """Check if runtime is running."""
        return self._running

    async def apply_mutation(self, delta: "GraphDelta") -> bool:
        """
        Applies a structural change (mutation) to the active graph.
        
        Args:
            delta: The structural changes to apply.
            
        Returns:
            True if applied successfully.
        """
        logger.info(f"Applying graph mutation: {delta.reason}")
        
        # 1. Validation (Safety)
        # Create a simulation of the graph to check safety BEFORE applying
        import copy
        from framework.graph.validator import GraphValidator
        
        # Deep copy the current graph structure (nodes/edges lists) to simulate delta
        # We need a temporary object that looks like GraphSpec
        # Since GraphSpec is pydantic, we can try to copy it, or just build a dummy object with the lists
        
        class GraphSimulation:
            def __init__(self, nodes, edges, entry_node):
                self.nodes = copy.deepcopy(nodes)
                self.edges = copy.deepcopy(edges)
                self.entry_node = entry_node
        
        sim_graph = GraphSimulation(self.graph.nodes, self.graph.edges, self.graph.entry_node)
        
        # Apply Delta to Simulation
        # (Replicating logic - ideally logic should be a shared method, but for now inline is fine for MVP)
        for node_spec in delta.nodes_to_add:
            existing_idx = next((i for i, n in enumerate(sim_graph.nodes) if n.id == node_spec.id), -1)
            if existing_idx >= 0:
                sim_graph.nodes[existing_idx] = node_spec
            else:
                sim_graph.nodes.append(node_spec)
                
        for node_id in delta.nodes_to_remove:
            sim_graph.nodes = [n for n in sim_graph.nodes if n.id != node_id]

        from framework.graph.edge import EdgeSpec
        for src, tgt in delta.edges_to_add.items():
            existing_edge = next((e for e in sim_graph.edges if e.source == src and e.target == tgt), None)
            if not existing_edge:
                sim_graph.edges.append(EdgeSpec(id=f"{src}_{tgt}", source=src, target=tgt))
        
        for src, tgt in delta.edges_to_remove.items():
            sim_graph.edges = [e for e in sim_graph.edges if not (e.source == src and e.target == tgt)]

        # Validate Simulation
        validation = GraphValidator.validate(sim_graph)
        if not validation.valid:
            logger.error(f"Mutation REJECTED by GraphValidator: {validation.error}")
            
            # Record failure in memory
            await self.memory_hub.remember(
                f"Graph mutation rejected: {validation.error}",
                {"mutation_reason": delta.reason},
                outcome="failure",
                source_type="system",
                agent_version="evolution-1.0"
            )
            return False

        logger.info("Mutation validated successfully. Applying to live graph.")
        
        # 2. Apply Changes under lock
        async with self._lock:
            # Add Nodes
            for node_spec in delta.nodes_to_add:
                # Dynamic import/instantiation logic would go here
                # For MVP, we assume the node instances are pre-built or we use a factory
                # This is a placeholder for the actual dynamic instantiation
                logger.info(f"Mutating: Adding node {node_spec.id} ({node_spec.node_type})")
                
                # Actual Graph Mutation
                # GraphSpec.nodes is a list of NodeSpec objects
                
                # Check if node already exists (update)
                existing_idx = next((i for i, n in enumerate(self.graph.nodes) if n.id == node_spec.id), -1)
                if existing_idx >= 0:
                     self.graph.nodes[existing_idx] = node_spec
                     logger.info(f"Mutating: Updated node {node_spec.id}")
                else:
                     self.graph.nodes.append(node_spec)
                     logger.info(f"Mutating: Added node {node_spec.id} ({node_spec.node_type})")
                
            # Remove Nodes
            for node_id in delta.nodes_to_remove:
                # Filter out the node to remove
                initial_len = len(self.graph.nodes)
                self.graph.nodes = [n for n in self.graph.nodes if n.id != node_id]
                if len(self.graph.nodes) < initial_len:
                    logger.info(f"Mutating: Removed node {node_id}")
                
            # Update Edges
            for src, tgt in delta.edges_to_add.items():
                # GraphSpec.edges is a list of EdgeSpec objects
                # Need to check if edge exists or add new EdgeSpec
                from framework.graph.edge import EdgeSpec
                
                # Check existing edge src->tgt
                existing_edge = next((e for e in self.graph.edges if e.source == src and e.target == tgt), None)
                if not existing_edge:
                    edge_id = f"{src}_to_{tgt}"
                    # Add new edge
                    new_edge = EdgeSpec(id=edge_id, source=src, target=tgt)
                    self.graph.edges.append(new_edge)
                    logger.info(f"Mutating: Added edge {src} -> {tgt}")

            for src, tgt in delta.edges_to_remove.items():
                 self.graph.edges = [e for e in self.graph.edges if not (e.source == src and e.target == tgt)]
                 logger.info(f"Mutating: Removed edge {src} -> {tgt}")
                
        # 3. Memory Event
        if delta.source_memory_id:
            await self.memory_hub.remember(
                f"Graph mutated: {delta.reason}",
                {"mutation_id": str(delta.source_memory_id)},
                outcome="success", 
                source_type="system",
                agent_version="evolution-1.0"
            )
            
        return True


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
