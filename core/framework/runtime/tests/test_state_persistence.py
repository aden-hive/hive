"""
Tests for SharedStateManager persistence and lazy loading.

Verifies:
1. State is written to disk via ConcurrentStorage
2. State is lazily loaded from disk on cache miss
3. Scope isolation (Global vs Stream vs Execution) works with persistence
"""

import asyncio
import json
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from framework.runtime.shared_state import (
    IsolationLevel,
    SharedStateManager,
    StateScope,
)
from framework.storage.concurrent import ConcurrentStorage


@pytest.fixture
def temp_storage_path():
    """Create a temporary storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@asynccontextmanager
async def active_storage(path: Path):
    """Async context manager to handle storage lifecycle."""
    s = ConcurrentStorage(path, batch_interval=0.01)
    await s.start()
    try:
        yield s
    finally:
        await s.stop()


@pytest.mark.asyncio
class TestStatePersistence:
    """Tests for persistent shared state."""

    async def test_global_state_persistence(self, temp_storage_path):
        """Test that global state is persisted to disk and recoverable."""
        async with active_storage(temp_storage_path) as storage:
            # 1. Initialize Manager with Storage
            manager = SharedStateManager(storage=storage)

            # 2. Write to global state
            await manager.write(
                key="app_name",
                value="AdenHive",
                execution_id="exec-1",
                stream_id="stream-1",
                isolation=IsolationLevel.SHARED,
                scope=StateScope.GLOBAL,
            )

            # 3. Force flush storage (wait for batch interval)
            await asyncio.sleep(0.05)

            # 4. Verify file exists on disk
            state_file = temp_storage_path / "states" / "global" / "default.json"
            assert state_file.exists()

            with open(state_file) as f:
                data = json.load(f)
                assert data["app_name"] == "AdenHive"

            # 5. Simulate Restart: Create NEW manager with SAME storage
            new_manager = SharedStateManager(storage=storage)

            # Verify memory is empty initially
            assert "app_name" not in new_manager._global_state

            # 6. Read (Trigger Lazy Load)
            val = await new_manager.read(
                "app_name", "exec-new", "stream-new", IsolationLevel.SHARED
            )

            assert val == "AdenHive"
            # Verify it's now in memory
            assert "app_name" in new_manager._global_state

    async def test_stream_state_persistence(self, temp_storage_path):
        """Test that stream state is persisted to correct file."""
        async with active_storage(temp_storage_path) as storage:
            manager = SharedStateManager(storage=storage)
            stream_id = "webhook-stream-123"

            # Write to stream scope
            await manager.write(
                key="last_ticket_id",
                value=999,
                execution_id="exec-1",
                stream_id=stream_id,
                isolation=IsolationLevel.SHARED,
                scope=StateScope.STREAM,
            )

            await asyncio.sleep(0.05)

            # Verify stream file exists
            state_file = temp_storage_path / "states" / "stream" / f"{stream_id}.json"
            assert state_file.exists()

            with open(state_file) as f:
                data = json.load(f)
                assert data["last_ticket_id"] == 999

            # Verify isolation: another stream shouldn't see this file
            other_file = temp_storage_path / "states" / "stream" / "other-stream.json"
            assert not other_file.exists()

    async def test_execution_state_persistence(self, temp_storage_path):
        """Test that execution state is persisted (if configured)."""
        async with active_storage(temp_storage_path) as storage:
            manager = SharedStateManager(storage=storage)
            exec_id = "exec-abc-789"

            # Write to execution scope
            await manager.write(
                key="local_var",
                value="temp",
                execution_id=exec_id,
                stream_id="stream-1",
                isolation=IsolationLevel.ISOLATED,  # Forced to execution scope
            )

            await asyncio.sleep(0.05)

            # Verify execution file exists
            state_file = temp_storage_path / "states" / "execution" / f"{exec_id}.json"
            assert state_file.exists()

    async def test_lazy_loading_isolation(self, temp_storage_path):
        """Test that lazy loading respects scopes (Stream A doesn't load Stream B)."""
        async with active_storage(temp_storage_path) as storage:
            manager1 = SharedStateManager(storage=storage)

            # Setup: Persist data for Stream A and Stream B
            await manager1.write(
                "key", "val_A", "e1", "stream_A", IsolationLevel.SHARED, StateScope.STREAM
            )
            await manager1.write(
                "key", "val_B", "e2", "stream_B", IsolationLevel.SHARED, StateScope.STREAM
            )

            await asyncio.sleep(0.05)

            # Restart
            manager2 = SharedStateManager(storage=storage)

            # Read Stream A -> Should load Stream A file
            val_a = await manager2.read("key", "e3", "stream_A", IsolationLevel.SHARED)
            assert val_a == "val_A"

            # Verify Stream B is NOT loaded yet
            assert "stream_B" not in manager2._stream_state

            # Read Stream B
            val_b = await manager2.read("key", "e4", "stream_B", IsolationLevel.SHARED)
            assert val_b == "val_B"

    async def test_mixed_mode_operation(self, temp_storage_path):
        """Test manager works fine WITHOUT storage (backward compatibility)."""
        # No storage provided
        manager = SharedStateManager(storage=None)

        await manager.write("key", "val", "e1", "s1", IsolationLevel.SHARED, StateScope.GLOBAL)

        val = await manager.read("key", "e1", "s1", IsolationLevel.SHARED)
        assert val == "val"

        # Verify nothing wrote to disk
        assert not (temp_storage_path / "states").exists()

    async def test_concurrent_writes(self, temp_storage_path):
        """Test rapid concurrent writes are handled safely."""
        async with active_storage(temp_storage_path) as storage:
            manager = SharedStateManager(storage=storage)

            # Fire 50 writes concurrently
            tasks = []
            for i in range(50):
                tasks.append(
                    manager.write(
                        f"key_{i}",
                        i,
                        "exec-1",
                        "stream-1",
                        IsolationLevel.SHARED,
                        StateScope.GLOBAL,
                    )
                )

            await asyncio.gather(*tasks)
            await asyncio.sleep(0.1)  # Wait for batch

            # Verify all present in new manager
            manager2 = SharedStateManager(storage=storage)

            # Check a few
            assert await manager2.read("key_0", "e", "s", IsolationLevel.SHARED) == 0
            assert await manager2.read("key_49", "e", "s", IsolationLevel.SHARED) == 49
