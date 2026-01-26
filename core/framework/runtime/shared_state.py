"""
Shared State Manager - Manages state across concurrent executions.
Includes Performance Enhancements: Compaction, Ephemeral Scope, and TTL.
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
    ISOLATED = "isolated"
    SHARED = "shared"
    SYNCHRONIZED = "synchronized"


class StateScope(str, Enum):
    """Scope for state operations."""
    EXECUTION = "execution"   # Local to a single execution
    STREAM = "stream"         # Shared within a stream
    GLOBAL = "global"         # Shared across all streams
    EPHEMERAL = "ephemeral"   # Delete after first read


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
    def __init__(self, max_history: int = 1000, cache_ttl: int = 3600):
        self._global_state: dict[str, Any] = {}
        self._stream_state: dict[str, dict[str, Any]] = {}
        self._execution_state: dict[str, dict[str, Any]] = {}
        self._execution_last_active: dict[str, float] = {}

        self._global_lock = asyncio.Lock()
        self._stream_locks: dict[str, asyncio.Lock] = {}
        self._key_locks: dict[str, asyncio.Lock] = {}

        self._change_history: list[StateChange] = []
        self._max_history = max_history
        self._cache_ttl = cache_ttl
        self._version = 0

    def create_memory(self, execution_id: str, stream_id: str, isolation: IsolationLevel) -> "StreamMemory":
        if execution_id not in self._execution_state:
            self._execution_state[execution_id] = {}
        self._execution_last_active[execution_id] = time.time()

        if stream_id not in self._stream_state:
            self._stream_state[stream_id] = {}
            self._stream_locks[stream_id] = asyncio.Lock()

        return StreamMemory(manager=self, execution_id=execution_id, stream_id=stream_id, isolation=isolation)

    def cleanup_execution(self, execution_id: str) -> None:
        self._execution_state.pop(execution_id, None)
        self._execution_last_active.pop(execution_id, None)
        logger.debug(f"Cleaned up state for execution: {execution_id}")

    def cleanup_stream(self, stream_id: str) -> None:
        self._stream_state.pop(stream_id, None)
        self._stream_locks.pop(stream_id, None)
        logger.debug(f"Cleaned up state for stream: {stream_id}")

    def purge_expired_state(self) -> int:
        """Purges stale states based on TTL cleanup."""
        now = time.time()
        expired_ids = [eid for eid, last in self._execution_last_active.items() if (now - last) > self._cache_ttl]
        for eid in expired_ids:
            self.cleanup_execution(eid)
        return len(expired_ids)

    async def read(self, key: str, execution_id: str, stream_id: str, isolation: IsolationLevel) -> Any:
        self._execution_last_active[execution_id] = time.time()
        if execution_id in self._execution_state:
            if key in self._execution_state[execution_id]:
                val = self._execution_state[execution_id][key]
                is_ephemeral = any(c.key == key and c.execution_id == execution_id and c.scope == StateScope.EPHEMERAL 
                                   for c in reversed(self._change_history[-10:]))
                if is_ephemeral:
                    self._execution_state[execution_id].pop(key)
                return val

        if isolation != IsolationLevel.ISOLATED:
            if stream_id in self._stream_state:
                if key in self._stream_state[stream_id]:
                    return self._stream_state[stream_id][key]
            if key in self._global_state:
                return self._global_state[key]
        return None

    async def write(self, key: str, value: Any, execution_id: str, stream_id: str, isolation: IsolationLevel, scope: StateScope = StateScope.EXECUTION) -> None:
        self._execution_last_active[execution_id] = time.time()
        old_value = await self.read(key, execution_id, stream_id, isolation)
        if isolation == IsolationLevel.ISOLATED:
            scope = StateScope.EXECUTION
        if isolation == IsolationLevel.SYNCHRONIZED and scope != StateScope.EXECUTION:
            await self._write_with_lock(key, value, execution_id, stream_id, scope)
        else:
            await self._write_direct(key, value, execution_id, stream_id, scope)
        self._record_change(StateChange(key=key, old_value=old_value, new_value=value, scope=scope, execution_id=execution_id, stream_id=stream_id))

    async def _write_direct(self, key: str, value: Any, execution_id: str, stream_id: str, scope: StateScope) -> None:
        if scope in (StateScope.EXECUTION, StateScope.EPHEMERAL):
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

    async def _write_with_lock(self, key, value, execution_id, stream_id, scope) -> None:
        lock = self._get_lock(scope, key, stream_id)
        async with lock:
            await self._write_direct(key, value, execution_id, stream_id, scope)

    def _get_lock(self, scope, key, stream_id):
        lock_key = f"global:{key}" if scope == StateScope.GLOBAL else f"stream:{stream_id}:{key}" if scope == StateScope.STREAM else f"exec:{key}"
        if lock_key not in self._key_locks:
            self._key_locks[lock_key] = asyncio.Lock()
        return self._key_locks[lock_key]

    def _truncate_value(self, value, max_length=100):
        if isinstance(value, str) and len(value) > 1024:
            return f"{value[:max_length]}... [truncated]"
        return value

    def _record_change(self, change):
        change.old_value = self._truncate_value(change.old_value)
        change.new_value = self._truncate_value(change.new_value)
        self._change_history.append(change)
        if len(self._change_history) > self._max_history:
            self._change_history = self._change_history[-self._max_history:]

    async def read_all(self, execution_id: str, stream_id: str, isolation: IsolationLevel) -> dict[str, Any]:
        result = {}
        if isolation != IsolationLevel.ISOLATED:
            result.update(self._global_state)
            if stream_id in self._stream_state:
                result.update(self._stream_state[stream_id])
        if execution_id in self._execution_state:
            result.update(self._execution_state[execution_id])
        return result

    def get_stats(self) -> dict:
        return {
            "global_keys": len(self._global_state),
            "stream_count": len(self._stream_state),
            "execution_count": len(self._execution_state),
            "total_changes": len(self._change_history),
            "version": self._version,
        }


class StreamMemory:
    """Memory interface for a single execution with permission support."""
    def __init__(self, manager: SharedStateManager, execution_id: str, stream_id: str, isolation: IsolationLevel):
        self._manager = manager
        self._execution_id = execution_id
        self._stream_id = stream_id
        self._isolation = isolation
        self._allowed_read: set[str] | None = None
        self._allowed_write: set[str] | None = None

    def with_permissions(self, read_keys: list[str], write_keys: list[str]) -> "StreamMemory":
        scoped = StreamMemory(self._manager, self._execution_id, self._stream_id, self._isolation)
        scoped._allowed_read = set(read_keys)
        scoped._allowed_write = set(write_keys)
        return scoped

    async def read(self, key: str) -> Any:
        if self._allowed_read is not None and key not in self._allowed_read:
            raise PermissionError(f"Not allowed to read key: {key}")
        return await self._manager.read(key, self._execution_id, self._stream_id, self._isolation)

    async def write(self, key: str, value: Any, scope: StateScope = StateScope.EXECUTION) -> None:
        if self._allowed_write is not None and key not in self._allowed_write:
            raise PermissionError(f"Not allowed to write key: {key}")
        await self._manager.write(key, value, self._execution_id, self._stream_id, self._isolation, scope)

    async def read_all(self) -> dict[str, Any]:
        all_state = await self._manager.read_all(self._execution_id, self._stream_id, self._isolation)
        if self._allowed_read is not None:
            return {k: v for k, v in all_state.items() if k in self._allowed_read}
        return all_state

    # === BACKWARD COMPATIBILITY SYNC API ===
    def read_sync(self, key: str) -> Any:
        if self._allowed_read is not None and key not in self._allowed_read:
            raise PermissionError(f"Not allowed to read key: {key}")
        exec_state = self._manager._execution_state.get(self._execution_id, {})
        if key in exec_state: return exec_state[key]
        if self._isolation != IsolationLevel.ISOLATED:
            stream_state = self._manager._stream_state.get(self._stream_id, {})
            if key in stream_state: return stream_state[key]
            if key in self._manager._global_state: return self._manager._global_state[key]
        return None

    def write_sync(self, key: str, value: Any) -> None:
        if self._allowed_write is not None and key not in self._allowed_write:
            raise PermissionError(f"Not allowed to write key: {key}")
        if self._execution_id not in self._manager._execution_state:
            self._manager._execution_state[self._execution_id] = {}
        self._manager._execution_state[self._execution_id][key] = value
        self._manager._version += 1