"""
Security-hardened AgentRuntime with proper resource management
"""
import asyncio
import logging
import sys
import threading
import time
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from framework.graph.executor import ExecutionResult
from framework.runtime.event_bus import EventBus
from framework.runtime.execution_stream import EntryPointSpec, ExecutionStream
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.runtime.shared_state import SharedStateManager
from framework.storage.concurrent import ConcurrentStorage
from framework.security import AuditLogger, SecurityEvent, InputSanitizer, SecurityViolation

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.goal import Goal
    from framework.llm.provider import LLMProvider, Tool

logger = logging.getLogger(__name__)


@dataclass
class SecurityConfig:
    """Security configuration for AgentRuntime."""
    enable_sandbox: bool = True
    max_execution_time: float = 300.0  # 5 minutes
    max_memory_mb: int = 1024
    audit_enabled: bool = True
    sanitize_inputs: bool = True


@dataclass
class AgentRuntimeConfig:
    """Enhanced configuration for AgentRuntime."""
    max_concurrent_executions: int = 50  # Reduced for safety
    cache_ttl: float = 60.0
    batch_interval: float = 0.1
    max_history: int = 1000
    execution_result_max: int = 1000
    execution_result_ttl_seconds: float | None = None
    stream_cleanup_interval: float = 300.0  # 5 minutes
    max_stream_idle_time: float = 600.0    # 10 minutes
    security: SecurityConfig = field(default_factory=SecurityConfig)


class SecureAgentRuntime:
    """
    Security-hardened runtime that manages agent lifecycle and concurrent executions.
    
    Key improvements:
    - Proper resource management and cleanup
    - Thread-safe operations with validated locks
    - Input sanitization and audit logging
    - Memory leak prevention
    - Graceful shutdown handling
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
        """Initialize secure agent runtime."""
        self.graph = graph
        self.goal = goal
        self._config = config or AgentRuntimeConfig()

        # Initialize storage with enhanced error handling
        self._storage = ConcurrentStorage(
            base_path=storage_path,
            cache_ttl=self._config.cache_ttl,
            batch_interval=self._config.batch_interval,
        )

        # Initialize shared components
        self._state_manager = SharedStateManager()
        self._event_bus = EventBus(max_history=self._config.max_history)
        self._outcome_aggregator = OutcomeAggregator(goal, self._event_bus)

        # Security components
        self._input_sanitizer = InputSanitizer() if self._config.security.sanitize_inputs else None
        self._audit_logger = None
        if self._config.security.audit_enabled:
            try:
                self._audit_logger = AuditLogger(
                    log_file=Path(storage_path) / "audit.log",
                    max_file_size=50 * 1024 * 1024,  # 50MB
                    backup_count=5
                )
            except Exception as e:
                logger.warning(f"Failed to initialize audit logger: {e}")

        # LLM and tools
        self._llm = llm
        self._tools = tools or []
        self._tool_executor = tool_executor

        # Thread-safe collections
        self._entry_points: dict[str, EntryPointSpec] = {}
        self._streams: dict[str, ExecutionStream] = {}
        
        # Thread-safe locks with proper initialization
        self._streams_lock = threading.RLock()
        self._entry_points_lock = threading.RLock()
        self._global_lock = asyncio.Lock()
        
        # State and cleanup tracking
        self._running = False
        self._stream_last_used: dict[str, float] = {}
        self._cleanup_task: asyncio.Task | None = None

    def register_entry_point(self, spec: EntryPointSpec) -> None:
        """
        Register a named entry point for the agent with security validation.
        """
        if self._running:
            raise RuntimeError("Cannot register entry points while runtime is running")

        # Validate input
        if not spec.id or not spec.id.replace('_', '').replace('-', '').isalnum():
            raise ValueError(f"Invalid entry point ID: '{spec.id}'. Must be alphanumeric.")

        with self._entry_points_lock:
            if spec.id in self._entry_points:
                raise ValueError(f"Entry point '{spec.id}' already registered")

            # Validate entry node exists in graph
            if self.graph.get_node(spec.entry_node) is None:
                raise ValueError(f"Entry node '{spec.entry_node}' not found in graph")

            self._entry_points[spec.id] = spec
            
            if self._audit_logger:
                self._audit_logger.log_entry_point_registration(spec.id, spec.entry_node)
                
            logger.info(f"Registered entry point: {spec.id} -> {spec.entry_node}")

    def unregister_entry_point(self, entry_point_id: str) -> bool:
        """Unregister an entry point with proper cleanup."""
        if self._running:
            raise RuntimeError("Cannot unregister entry points while runtime is running")

        with self._entry_points_lock:
            if entry_point_id in self._entry_points:
                # Clean up any associated stream
                self._cleanup_stream(entry_point_id)
                del self._entry_points[entry_point_id]
                
                if self._audit_logger:
                    self._audit_logger.log_entry_point_unregistration(entry_point_id)
                    
                return True
            return False

    async def start(self) -> None:
        """
        Start the agent runtime with enhanced error handling and resource management.
        """
        if self._running:
            logger.warning("Runtime already running")
            return

        async with self._global_lock:
            try:
                # Start storage with error handling
                await self._storage.start()

                # Create streams for each entry point
                with self._streams_lock:
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
                        self._stream_last_used[ep_id] = asyncio.get_event_loop().time()

                # Start cleanup task
                self._cleanup_task = asyncio.create_task(self._periodic_cleanup())

                self._running = True
                logger.info(f"SecureAgentRuntime started with {len(self._streams)} streams")
                
                if self._audit_logger:
                    self._audit_logger.log_runtime_start(len(self._streams))

            except Exception as e:
                logger.error(f"Failed to start runtime: {e}")
                await self._cleanup_on_startup_failure()
                raise

    async def stop(self) -> None:
        """
        Stop the agent runtime with graceful shutdown and cleanup.
        """
        if not self._running:
            return

        async with self._global_lock:
            try:
                self._running = False

                # Stop cleanup task first
                if self._cleanup_task:
                    self._cleanup_task.cancel()
                    try:
                        await self._cleanup_task
                    except asyncio.CancelledError:
                        pass
                    self._cleanup_task = None

                # Stop all streams with proper error handling
                with self._streams_lock:
                    streams_to_stop = list(self._streams.values())
                    self._streams.clear()
                    self._stream_last_used.clear()

                # Stop streams concurrently
                if streams_to_stop:
                    await asyncio.gather(
                        *[self._safe_stop_stream(stream) for stream in streams_to_stop],
                        return_exceptions=True
                    )

                # Stop storage
                await self._storage.stop()

                # Cleanup audit logger
                if self._audit_logger:
                    self._audit_logger.cleanup()

                logger.info("SecureAgentRuntime stopped gracefully")
                
                if self._audit_logger:
                    self._audit_logger.log_runtime_stop()

            except Exception as e:
                logger.error(f"Error during runtime shutdown: {e}")
                raise

    async def trigger(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        correlation_id: str | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> str:
        """
        Trigger execution at a specific entry point with security validation.
        """
        if not self._running:
            raise RuntimeError("AgentRuntime is not running")

        # Sanitize input if enabled
        if self._input_sanitizer:
            try:
                input_data = self._input_sanitizer.sanitize_dict(input_data)
            except SecurityViolation as e:
                if self._audit_logger:
                    self._audit_logger.log_security_violation(
                        violation_type=e.violation_type,
                        description=e.description,
                        field_path=e.field_path,
                        original_value=e.original_value,
                        severity=e.severity
                    )
                if e.severity == "critical":
                    raise
                logger.warning(f"Input sanitization warning: {e.description}")

        # Validate input size
        if self._config.security.max_memory_mb:
            input_size = sys.getsizeof(input_data) / (1024 * 1024)
            if input_size > self._config.security.max_memory_mb:
                error_msg = f"Input data too large: {input_size:.2f}MB > {self._config.security.max_memory_mb}MB"
                if self._audit_logger:
                    self._audit_logger.log_resource_exceeded(
                        resource_type="memory",
                        current_value=input_size,
                        limit=self._config.security.max_memory_mb
                    )
                raise ValueError(error_msg)

        with self._streams_lock:
            stream = self._streams.get(entry_point_id)
            if stream is None:
                raise ValueError(f"Entry point '{entry_point_id}' not found")
            
            # Update last used time
            self._stream_last_used[entry_point_id] = asyncio.get_event_loop().time()

        execution_id = await stream.execute(input_data, correlation_id, session_state)
        
        if self._audit_logger:
            self._audit_logger.log_execution_trigger(entry_point_id, execution_id, correlation_id)

        return execution_id

    async def trigger_and_wait(
        self,
        entry_point_id: str,
        input_data: dict[str, Any],
        timeout: float | None = None,
        session_state: dict[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """Trigger execution and wait for completion with timeout enforcement."""
        exec_id = await self.trigger(entry_point_id, input_data, session_state=session_state)
        
        # Use security timeout if none provided
        if timeout is None:
            timeout = self._config.security.max_execution_time
            
        with self._streams_lock:
            stream = self._streams.get(entry_point_id)
            if stream is None:
                raise ValueError(f"Entry point '{entry_point_id}' not found")
                
        try:
            result = await asyncio.wait_for(
                stream.wait_for_completion(exec_id),
                timeout=timeout
            )
            
            # Log completion
            if self._audit_logger and result:
                self._audit_logger.log_execution_complete(
                    entry_point_id=entry_point_id,
                    execution_id=exec_id,
                    success=result.success,
                    duration_ms=result.total_latency_ms
                )
                
            return result
            
        except asyncio.TimeoutError:
            if self._audit_logger:
                self._audit_logger.log_execution_complete(
                    entry_point_id=entry_point_id,
                    execution_id=exec_id,
                    success=False,
                    duration_ms=int(timeout * 1000)
                )
            raise

    # === Resource Management ===

    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup of idle streams and expired data."""
        while self._running:
            try:
                await asyncio.sleep(self._config.stream_cleanup_interval)
                await self._cleanup_idle_streams()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")

    async def _cleanup_idle_streams(self) -> None:
        """Clean up streams that have been idle too long."""
        current_time = asyncio.get_event_loop().time()
        
        with self._streams_lock:
            idle_streams = [
                ep_id for ep_id, last_used in self._stream_last_used.items()
                if current_time - last_used > self._config.max_stream_idle_time
            ]
            
            for ep_id in idle_streams:
                logger.info(f"Cleaning up idle stream: {ep_id}")
                self._cleanup_stream(ep_id)

    def _cleanup_stream(self, entry_point_id: str) -> None:
        """Clean up a specific stream."""
        if entry_point_id in self._stream_last_used:
            del self._stream_last_used[entry_point_id]

    async def _safe_stop_stream(self, stream: ExecutionStream) -> None:
        """Safely stop a stream with error handling."""
        try:
            await stream.stop()
        except Exception as e:
            logger.error(f"Error stopping stream {stream.stream_id}: {e}")

    async def _cleanup_on_startup_failure(self) -> None:
        """Clean up resources if startup fails."""
        try:
            await self._storage.stop()
            if self._audit_logger:
                self._audit_logger.cleanup()
        except Exception:
            pass

    # === Query Operations (Thread-Safe) ===

    def get_entry_points(self) -> list[EntryPointSpec]:
        """Get all registered entry points (thread-safe)."""
        with self._entry_points_lock:
            return list(self._entry_points.values())

    def get_stream(self, entry_point_id: str) -> ExecutionStream | None:
        """Get a specific execution stream (thread-safe)."""
        with self._streams_lock:
            return self._streams.get(entry_point_id)

    def get_execution_result(
        self,
        entry_point_id: str,
        execution_id: str,
    ) -> ExecutionResult | None:
        """Get result of a completed execution (thread-safe)."""
        with self._streams_lock:
            stream = self._streams.get(entry_point_id)
            if stream:
                return stream.get_result(execution_id)
            return None

    # === Enhanced Monitoring ===

    def get_stats(self) -> dict:
        """Get comprehensive runtime statistics with security metrics."""
        with self._streams_lock:
            stream_stats = {}
            for ep_id, stream in self._streams.items():
                stream_stats[ep_id] = stream.get_stats()

        stats = {
            "running": self._running,
            "entry_points": len(self._entry_points),
            "streams": stream_stats,
            "goal_id": self.goal.id,
            "outcome_aggregator": self._outcome_aggregator.get_stats(),
            "event_bus": self._event_bus.get_stats(),
            "state_manager": self._state_manager.get_stats(),
            "security": {
                "sanitization_enabled": bool(self._input_sanitizer),
                "audit_enabled": bool(self._audit_logger),
                "max_execution_time": self._config.security.max_execution_time,
                "max_memory_mb": self._config.security.max_memory_mb,
            },
            "resource_usage": {
                "active_streams": len(self._streams),
                "idle_streams": len([
                    ep_id for ep_id, last_used in self._stream_last_used.items()
                    if asyncio.get_event_loop().time() - last_used > self._config.max_stream_idle_time
                ]),
            }
        }
        
        # Add audit logger stats if available
        if self._audit_logger:
            stats["audit"] = self._audit_logger.get_stats()
            
        return stats

    # === Properties ===

    @property
    def is_running(self) -> bool:
        """Check if runtime is running."""
        return self._running

    @property
    def state_manager(self) -> SharedStateManager:
        """Access to shared state manager."""
        return self._state_manager

    @property
    def event_bus(self) -> EventBus:
        """Access to event bus."""
        return self._event_bus

    @property
    def outcome_aggregator(self) -> OutcomeAggregator:
        """Access to outcome aggregator."""
        return self._outcome_aggregator


# === Factory Function ===

def create_secure_agent_runtime(
    graph: "GraphSpec",
    goal: "Goal",
    storage_path: str | Path,
    entry_points: list[EntryPointSpec],
    llm: "LLMProvider | None" = None,
    tools: list["Tool"] | None = None,
    tool_executor: Callable | None = None,
    config: AgentRuntimeConfig | None = None,
) -> SecureAgentRuntime:
    """
    Create and configure a SecureAgentRuntime with entry points.
    
    Security-enhanced factory function with proper validation.
    """
    runtime = SecureAgentRuntime(
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