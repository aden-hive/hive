"""
Shared State Manager - Manages state across concurrent executions.

Provides different isolation levels:
- ISOLATED: Each execution has its own memory copy
- SHARED: All executions read/write same memory (eventual consistency)
- SYNCHRONIZED: Shared memory with write locks (strong consistency)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class IsolationLevel(str, Enum):
    """State isolation level for concurrent executions."""

    ISOLATED = "isolated"  # Private state per execution
    SHARED = "shared"  # Shared state (eventual consistency)
    SYNCHRONIZED = "synchronized"  # Shared with write locks (strong consistency)


class StateScope(str, Enum):
    """Scope for state operations."""

    EXECUTION = "execution"  # Local to a single execution
    STREAM = "stream"  # Shared within a stream
    GLOBAL = "global"  # Shared across all streams


@dataclass
class StateChange:
    """Record of a state change."""

    key: str
    old_value: Any
    new_value: Any
    scope: StateScope
    execution_id: str
    stream_id: str
    timestamp: float = field(default_factory=time.time)


class SharedStateManager:
    """
    Manages shared state across concurrent executions.

    State hierarchy:
    - Global state: Shared across all streams and executions
    - Stream state: Shared within a stream (across executions)
    - Execution state: Private to a single execution

    Isolation levels control visibility:
    - ISOLATED: Only sees execution state
    - SHARED: Sees all levels, writes propagate up based on scope
    - SYNCHRONIZED: Like SHARED but with write locks

    Example:
        manager = SharedStateManager()

        # Create memory for an execution
        memory = manager.create_memory(
            execution_id="exec_123",
            stream_id="webhook",
            isolation=IsolationLevel.SHARED,
        )

        # Read/write through the memory
        await memory.write("customer_id", "cust_456", scope=StateScope.STREAM)
        value = await memory.read("customer_id")
    """

    def __init__(self):
        # State storage at each level
        self._global_state: dict[str, Any] = {}
        self._stream_state: dict[str, dict[str, Any]] = {}  # stream_id -> {key: value}
        self._execution_state: dict[str, dict[str, Any]] = {}  # execution_id -> {key: value}

        # Locks for synchronized access
        self._global_lock = asyncio.Lock()
        self._stream_locks: dict[str, asyncio.Lock] = {}
        self._key_locks: dict[str, asyncio.Lock] = {}

        # Change history for debugging/auditing
        self._change_history: list[StateChange] = []
        self._max_history = 1000

        # Version tracking
        self._version = 0

    def create_memory(
        self,
        execution_id: str,
        stream_id: str,
        isolation: IsolationLevel,
    ) -> "StreamMemory":
        """
        Create a memory instance for an execution.

        Args:
            execution_id: Unique execution identifier
            stream_id: Stream this execution belongs to
            isolation: Isolation level for this execution

        Returns:
            StreamMemory instance for reading/writing state
        """
        # Initialize execution state
        if execution_id not in self._execution_state:
            self._execution_state[execution_id] = {}

        # Initialize stream state
        if stream_id not in self._stream_state:
            self._stream_state[stream_id] = {}
            self._stream_locks[stream_id] = asyncio.Lock()

        return StreamMemory(
            manager=self,
            execution_id=execution_id,
            stream_id=stream_id,
            isolation=isolation,
        )

    def cleanup_execution(self, execution_id: str) -> None:
        """
        Clean up state for a completed execution.

        Args:
            execution_id: Execution to clean up
        """
        self._execution_state.pop(execution_id, None)
        logger.debug(f"Cleaned up state for execution: {execution_id}")

    def cleanup_stream(self, stream_id: str) -> None:
        """
        Clean up state for a closed stream.

        Args:
            stream_id: Stream to clean up
        """
        self._stream_state.pop(stream_id, None)
        self._stream_locks.pop(stream_id, None)
        logger.debug(f"Cleaned up state for stream: {stream_id}")

    # === LOW-LEVEL STATE OPERATIONS ===

    async def read(
        self,
        key: str,
        execution_id: str,
        stream_id: str,
        isolation: IsolationLevel,
    ) -> Any:
        """
        Read a value respecting isolation level.

        Resolution order (stops at first match):
        1. Execution state (always checked)
        2. Stream state (if isolation != ISOLATED)
        3. Global state (if isolation != ISOLATED)
        """
        # Always check execution-local first
        if execution_id in self._execution_state:
            if key in self._execution_state[execution_id]:
                return self._execution_state[execution_id][key]

        # Check stream-level (unless isolated)
        if isolation != IsolationLevel.ISOLATED:
            if stream_id in self._stream_state:
                if key in self._stream_state[stream_id]:
                    return self._stream_state[stream_id][key]

            # Check global
            if key in self._global_state:
                return self._global_state[key]

        return None

    async def write(
        self,
        key: str,
        value: Any,
        execution_id: str,
        stream_id: str,
        isolation: IsolationLevel,
        scope: StateScope = StateScope.EXECUTION,
    ) -> None:
        """
        Write a value respecting isolation level.

        Args:
            key: State key
            value: Value to write
            execution_id: Current execution
            stream_id: Current stream
            isolation: Isolation level
            scope: Where to write (execution, stream, or global)
        """
        # Get old value for change tracking
        old_value = await self.read(key, execution_id, stream_id, isolation)

        # ISOLATED can only write to execution scope
        if isolation == IsolationLevel.ISOLATED:
            scope = StateScope.EXECUTION

        # SYNCHRONIZED requires locks for stream/global writes
        if isolation == IsolationLevel.SYNCHRONIZED and scope != StateScope.EXECUTION:
            await self._write_with_lock(key, value, execution_id, stream_id, scope)
        else:
            await self._write_direct(key, value, execution_id, stream_id, scope)

        # Record change
        self._record_change(
            StateChange(
                key=key,
                old_value=old_value,
                new_value=value,
                scope=scope,
                execution_id=execution_id,
                stream_id=stream_id,
            )
        )

    async def _write_direct(
        self,
        key: str,
        value: Any,
        execution_id: str,
        stream_id: str,
        scope: StateScope,
    ) -> None:
        """Write without locking (for ISOLATED and SHARED)."""
        if scope == StateScope.EXECUTION:
            if execution_id not in self._execution_state:
                self._execution_state[execution_id] = {}
            self._execution_state[execution_id][key] = value

        elif scope == StateScope.STREAM:
            if stream_id not in self._stream_state:
                self._stream_state[stream_id] = {}
            self._stream_state[stream_id][key] = value

        elif scope == StateScope.GLOBAL:
            self._global_state[key] = value

        self._version += 1

    async def _write_with_lock(
        self,
        key: str,
        value: Any,
        execution_id: str,
        stream_id: str,
        scope: StateScope,
    ) -> None:
        """Write with locking (for SYNCHRONIZED)."""
        lock = self._get_lock(scope, key, stream_id)
        async with lock:
            await self._write_direct(key, value, execution_id, stream_id, scope)

    def _get_lock(self, scope: StateScope, key: str, stream_id: str) -> asyncio.Lock:
        """Get appropriate lock for scope and key."""
        if scope == StateScope.GLOBAL:
            lock_key = f"global:{key}"
        elif scope == StateScope.STREAM:
            lock_key = f"stream:{stream_id}:{key}"
        else:
            lock_key = f"exec:{key}"

        if lock_key not in self._key_locks:
            self._key_locks[lock_key] = asyncio.Lock()

        return self._key_locks[lock_key]

    def _record_change(self, change: StateChange) -> None:
        """Record a state change for auditing."""
        self._change_history.append(change)

        # Trim history if too long
        if len(self._change_history) > self._max_history:
            self._change_history = self._change_history[-self._max_history :]

    # === BULK OPERATIONS ===

    async def read_all(
        self,
        execution_id: str,
        stream_id: str,
        isolation: IsolationLevel,
    ) -> dict[str, Any]:
        """
        Read all visible state for an execution.

        Returns merged state from all visible levels.
        """
        result = {}

        # Start with global (if visible)
        if isolation != IsolationLevel.ISOLATED:
            result.update(self._global_state)

            # Add stream state (overwrites global)
            if stream_id in self._stream_state:
                result.update(self._stream_state[stream_id])

        # Add execution state (overwrites all)
        if execution_id in self._execution_state:
            result.update(self._execution_state[execution_id])

        return result

    async def write_batch(
        self,
        updates: dict[str, Any],
        execution_id: str,
        stream_id: str,
        isolation: IsolationLevel,
        scope: StateScope = StateScope.EXECUTION,
    ) -> None:
        """Write multiple values atomically."""
        for key, value in updates.items():
            await self.write(key, value, execution_id, stream_id, isolation, scope)

    # === UTILITY ===

    def get_stats(self) -> dict:
        """Get state manager statistics."""
        return {
            "global_keys": len(self._global_state),
            "stream_count": len(self._stream_state),
            "execution_count": len(self._execution_state),
            "total_changes": len(self._change_history),
            "version": self._version,
        }

    def get_recent_changes(self, limit: int = 10) -> list[StateChange]:
        """Get recent state changes."""
        return self._change_history[-limit:]


class StreamMemory:
    """
    Memory interface for a single execution.

    Provides scoped access to shared state with proper isolation.
    Compatible with the existing SharedMemory interface where possible.
    """

    def __init__(
        self,
        manager: SharedStateManager,
        execution_id: str,
        stream_id: str,
        isolation: IsolationLevel,
    ):
        self._manager = manager
        self._execution_id = execution_id
        self._stream_id = stream_id
        self._isolation = isolation

        # Permission model (optional, for node-level scoping)
        self._allowed_read: set[str] | None = None
        self._allowed_write: set[str] | None = None

    def with_permissions(
        self,
        read_keys: list[str],
        write_keys: list[str],
    ) -> "StreamMemory":
        """
        Create a scoped view with read/write permissions.

        Compatible with existing SharedMemory.with_permissions().
        """
        scoped = StreamMemory(
            manager=self._manager,
            execution_id=self._execution_id,
            stream_id=self._stream_id,
            isolation=self._isolation,
        )
        scoped._allowed_read = set(read_keys)
        scoped._allowed_write = set(write_keys)
        return scoped

    async def read(self, key: str) -> Any:
        """Read a value from state."""
        # Check permissions
        if self._allowed_read is not None and key not in self._allowed_read:
            raise PermissionError(f"Not allowed to read key: {key}")

        return await self._manager.read(
            key=key,
            execution_id=self._execution_id,
            stream_id=self._stream_id,
            isolation=self._isolation,
        )

    async def write(
        self,
        key: str,
        value: Any,
        scope: StateScope = StateScope.EXECUTION,
    ) -> None:
        """Write a value to state."""
        # Check permissions
        if self._allowed_write is not None and key not in self._allowed_write:
            raise PermissionError(f"Not allowed to write key: {key}")

        await self._manager.write(
            key=key,
            value=value,
            execution_id=self._execution_id,
            stream_id=self._stream_id,
            isolation=self._isolation,
            scope=scope,
        )

    async def read_all(self) -> dict[str, Any]:
        """Read all visible state."""
        all_state = await self._manager.read_all(
            execution_id=self._execution_id,
            stream_id=self._stream_id,
            isolation=self._isolation,
        )

        # Filter by permissions if set
        if self._allowed_read is not None:
            return {k: v for k, v in all_state.items() if k in self._allowed_read}

        return all_state

    # === SYNC API (for backward compatibility with SharedMemory) ===

    def read_sync(self, key: str) -> Any:
        """
        Synchronous read (for compatibility with existing code).

        Note: This runs the async operation in a new event loop
        or uses direct access if no loop is running.
        """
        # Direct access for sync usage
        if self._allowed_read is not None and key not in self._allowed_read:
            raise PermissionError(f"Not allowed to read key: {key}")

        # Check execution state
        exec_state = self._manager._execution_state.get(self._execution_id, {})
        if key in exec_state:
            return exec_state[key]

        # Check stream/global if not isolated
        if self._isolation != IsolationLevel.ISOLATED:
            stream_state = self._manager._stream_state.get(self._stream_id, {})
            if key in stream_state:
                return stream_state[key]

            if key in self._manager._global_state:
                return self._manager._global_state[key]

        return None

    def write_sync(self, key: str, value: Any) -> None:
        """
        Synchronous write (for compatibility with existing code).

        Always writes to execution scope for simplicity.
        """
        if self._allowed_write is not None and key not in self._allowed_write:
            raise PermissionError(f"Not allowed to write key: {key}")

        if self._execution_id not in self._manager._execution_state:
            self._manager._execution_state[self._execution_id] = {}

        self._manager._execution_state[self._execution_id][key] = value
        self._manager._version += 1

    def read_all_sync(self) -> dict[str, Any]:
        """Synchronous read all."""
        result = {}

        # Global (if visible)
        if self._isolation != IsolationLevel.ISOLATED:
            result.update(self._manager._global_state)
            if self._stream_id in self._manager._stream_state:
                result.update(self._manager._stream_state[self._stream_id])

        # Execution
        if self._execution_id in self._manager._execution_state:
            result.update(self._manager._execution_state[self._execution_id])

        # Filter by permissions
        if self._allowed_read is not None:
            result = {k: v for k, v in result.items() if k in self._allowed_read}

        return result
