"""
Agent Runtime - Top-level orchestrator for multi-entry-point agents.

Manages agent lifecycle and coordinates multiple execution streams
while preserving the goal-driven approach.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING, Optional

from framework.graph.executor import ExecutionResult
from framework.runtime.shared_state import SharedStateManager
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.event_bus import EventBus
from framework.runtime.execution_stream import ExecutionStream, EntryPointSpec
from framework.storage.concurrent import ConcurrentStorage

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.goal import Goal
    from framework.llm.provider import LLMProvider, Tool

logger = logging.getLogger(__name__)


@dataclass
class AgentRuntimeConfig:
    """Configuration for AgentRuntime."""
    max_concurrent_executions: int = 100
    cache_ttl: float = 3600.0  # Default to 1 hour
    batch_interval: float = 0.1
    max_history: int = 1000


class AgentRuntime:
    """
    Top-level runtime that manages agent lifecycle and concurrent executions.
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
        self.graph = graph
        self.goal = goal
        self._config = config or AgentRuntimeConfig()

        # Initialize storage
        self._storage = ConcurrentStorage(
            base_path=storage_path,
            cache_ttl=self._config.cache_ttl,
            batch_interval=self._config.batch_interval,
        )

        # Initialize shared components with config values
        self._state_manager = SharedStateManager(
            max_history=self._config.max_history,
            cache_ttl=int(self._config.cache_ttl)
        )
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
        self._cleanup_task: Optional[asyncio.Task] = None

    async def _cleanup_loop(self):
        """Background task to periodically purge expired state (TTL Cleanup)."""
        while True:
            try:
                # Wait for 5 minutes between sweeps
                await asyncio.sleep(300) 
                
                if self._state_manager:
                    count = self._state_manager.purge_expired_state()
                    if count > 0:
                        logger.info(f"Background Cleanup: Purged {count} stale execution states.")
            except asyncio.CancelledError:
                # Cleanup task was stopped
                break
            except Exception as e:
                logger.error(f"Error in background cleanup loop: {e}")
                await asyncio.sleep(60) # Wait a minute before retrying

    async def start(self) -> None:
        """Start the agent runtime, streams, and background cleanup."""
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
                )
                await stream.start()
                self._streams[ep_id] = stream

            # Start background TTL cleanup task
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

            self._running = True
            logger.info(f"AgentRuntime started with {len(self._streams)} streams and TTL cleanup active")

    async def stop(self) -> None:
        """Stop the agent runtime, all streams, and the cleanup task."""
        if not self._running:
            return

        async with self._lock:
            # Stop the cleanup task
            if self._cleanup_task:
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
                self._cleanup_task = None

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
        exec_id = await self.trigger(entry_point_id, input_data, session_state=session_state)
        stream = self._streams[entry_point_id]
        return await stream.wait_for_completion(exec_id, timeout)

    async def get_goal_progress(self) -> dict[str, Any]:
        return await self._outcome_aggregator.evaluate_goal_progress()

    def get_stats(self) -> dict:
        stream_stats = {ep_id: s.get_stats() for ep_id, s in self._streams.items()}
        return {
            "running": self._running,
            "entry_points": len(self._entry_points),
            "streams": stream_stats,
            "state_manager": self._state_manager.get_stats(),
        }

    @property
    def state_manager(self) -> SharedStateManager:
        return self._state_manager

    @property
    def is_running(self) -> bool:
        return self._running