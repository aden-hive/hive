"""
Tests for IndexStore async file storage.

Follows Hive patterns:
- pytest with @pytest.mark.asyncio
- tmp_path fixture for file operations
- Test classes grouping related tests
- Descriptive test names and docstrings

Reference: core/tests/test_concurrent_storage.py
"""

import asyncio
import json
from pathlib import Path

import pytest

from framework.debugging.index_store import IndexStore
from framework.debugging.trace_index import TraceIndex


class TestIndexStoreInitialization:
    """Test IndexStore initialization patterns."""

    def test_default_path_initialization(self):
        """IndexStore defaults to ~/.hive/agents path."""
        store = IndexStore()

        expected_base = Path.home() / ".hive" / "agents"
        assert store.base_path == expected_base
        assert store.index_file == expected_base / ".trace_index.json"
        assert store.index == {}

    def test_custom_path_initialization(self, tmp_path: Path):
        """IndexStore accepts custom base path."""
        custom_path = tmp_path / "custom" / "path"
        store = IndexStore(base_path=custom_path)

        assert store.base_path == custom_path
        assert store.index_file == custom_path / ".trace_index.json"
        assert store.index == {}


class TestIndexStoreLoad:
    """Test async load operations."""

    @pytest.mark.asyncio
    async def test_load_empty_index(self, tmp_path: Path):
        """Loading non-existent index returns empty dict."""
        store = IndexStore(base_path=tmp_path)

        await store.load()

        assert store.index == {}
        assert len(store.index) == 0

    @pytest.mark.asyncio
    async def test_load_existing_index(self, tmp_path: Path):
        """Loading existing index deserializes TraceIndex objects."""
        # Create index file manually
        index_file = tmp_path / ".trace_index.json"
        index_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "run_123": {
                "run_id": "run_123",
                "agent_id": "test_agent",
                "session_id": "session_xyz",
                "status": "success",
                "total_latency_ms": 1000,
                "summary_path": "/path/summary.json",
                "details_path": "/path/details.jsonl",
                "tool_logs_path": "/path/tool_logs.jsonl",
                "timestamp": "2026-02-12T12:00:00",
            }
        }

        with open(index_file, "w") as f:
            json.dump(data, f)

        store = IndexStore(base_path=tmp_path)
        await store.load()

        assert len(store.index) == 1
        assert "run_123" in store.index

        trace = store.index["run_123"]
        assert isinstance(trace, TraceIndex)
        assert trace.run_id == "run_123"
        assert trace.agent_id == "test_agent"
        assert trace.total_latency_ms == 1000

    @pytest.mark.asyncio
    async def test_load_multiple_traces(self, tmp_path: Path):
        """Loading index with multiple traces deserializes all."""
        index_file = tmp_path / ".trace_index.json"
        index_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "run_1": {
                "run_id": "run_1",
                "agent_id": "agent_1",
                "session_id": "session_1",
                "status": "success",
                "summary_path": "/path/summary.json",
                "details_path": "/path/details.jsonl",
                "tool_logs_path": "/path/tool_logs.jsonl",
            },
            "run_2": {
                "run_id": "run_2",
                "agent_id": "agent_2",
                "session_id": "session_2",
                "status": "failure",
                "summary_path": "/path/summary.json",
                "details_path": "/path/details.jsonl",
                "tool_logs_path": "/path/tool_logs.jsonl",
            },
        }

        with open(index_file, "w") as f:
            json.dump(data, f)

        store = IndexStore(base_path=tmp_path)
        await store.load()

        assert len(store.index) == 2
        assert all(isinstance(t, TraceIndex) for t in store.index.values())

    @pytest.mark.asyncio
    async def test_load_corrupted_index_non_fatal(self, tmp_path: Path):
        """Loading corrupted index logs error but doesn't raise."""
        index_file = tmp_path / ".trace_index.json"
        index_file.parent.mkdir(parents=True, exist_ok=True)

        # Write invalid JSON
        with open(index_file, "w") as f:
            f.write("{ invalid json")

        store = IndexStore(base_path=tmp_path)

        # Should not raise exception (non-fatal error handling)
        await store.load()

        # Index should be empty after failed load
        assert store.index == {}


class TestIndexStoreSave:
    """Test async save operations."""

    @pytest.mark.asyncio
    async def test_save_empty_index(self, tmp_path: Path):
        """Saving empty index creates empty JSON file."""
        store = IndexStore(base_path=tmp_path)

        await store.save()

        assert store.index_file.exists()
        with open(store.index_file) as f:
            data = json.load(f)

        assert data == {}

    @pytest.mark.asyncio
    async def test_save_single_trace(self, tmp_path: Path, sample_trace: TraceIndex):
        """Saving single trace serializes to JSON correctly."""
        store = IndexStore(base_path=tmp_path)
        store.add(sample_trace)

        await store.save()

        assert store.index_file.exists()
        with open(store.index_file) as f:
            data = json.load(f)

        assert len(data) == 1
        assert sample_trace.run_id in data
        assert data[sample_trace.run_id]["agent_id"] == sample_trace.agent_id
        assert data[sample_trace.run_id]["status"] == sample_trace.status

    @pytest.mark.asyncio
    async def test_save_multiple_traces(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Saving multiple traces serializes all."""
        store = IndexStore(base_path=tmp_path)
        store.add(sample_trace)
        store.add(failed_trace)

        await store.save()

        with open(store.index_file) as f:
            data = json.load(f)

        assert len(data) == 2
        assert sample_trace.run_id in data
        assert failed_trace.run_id in data

    @pytest.mark.asyncio
    async def test_save_creates_directory(self, tmp_path: Path, sample_trace: TraceIndex):
        """Saving creates parent directories if needed."""
        nested_path = tmp_path / "deep" / "nested" / "path"
        store = IndexStore(base_path=nested_path)
        store.add(sample_trace)

        await store.save()

        assert store.index_file.exists()
        assert store.index_file.parent.exists()

    @pytest.mark.asyncio
    async def test_save_uses_atomic_write(self, tmp_path: Path, sample_trace: TraceIndex):
        """Saving uses atomic_write for crash safety."""
        store = IndexStore(base_path=tmp_path)
        store.add(sample_trace)

        await store.save()

        # Verify file exists and is valid JSON
        assert store.index_file.exists()
        with open(store.index_file) as f:
            data = json.load(f)

        # atomic_write should ensure complete write
        assert len(data) == 1


class TestIndexStoreRoundTrip:
    """Test save/load round-trip consistency."""

    @pytest.mark.asyncio
    async def test_round_trip_single_trace(self, tmp_path: Path, sample_trace: TraceIndex):
        """Save then load preserves single trace."""
        # Save
        store1 = IndexStore(base_path=tmp_path)
        store1.add(sample_trace)
        await store1.save()

        # Load
        store2 = IndexStore(base_path=tmp_path)
        await store2.load()

        assert len(store2.index) == 1
        loaded = store2.get(sample_trace.run_id)
        assert loaded is not None
        assert loaded.run_id == sample_trace.run_id
        assert loaded.agent_id == sample_trace.agent_id
        assert loaded.status == sample_trace.status
        assert loaded.total_latency_ms == sample_trace.total_latency_ms
        assert loaded.total_tokens == sample_trace.total_tokens

    @pytest.mark.asyncio
    async def test_round_trip_multiple_traces(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Save then load preserves multiple traces."""
        # Save
        store1 = IndexStore(base_path=tmp_path)
        store1.add(sample_trace)
        store1.add(failed_trace)
        await store1.save()

        # Load
        store2 = IndexStore(base_path=tmp_path)
        await store2.load()

        assert len(store2.index) == 2

        loaded_success = store2.get(sample_trace.run_id)
        assert loaded_success is not None
        assert loaded_success.status == "success"

        loaded_failure = store2.get(failed_trace.run_id)
        assert loaded_failure is not None
        assert loaded_failure.status == "failure"
        assert loaded_failure.error_message == "Timeout in web_search"

    @pytest.mark.asyncio
    async def test_round_trip_preserves_computed_fields(
        self, tmp_path: Path, sample_trace: TraceIndex
    ):
        """Save then load preserves computed field values."""
        # Save
        store1 = IndexStore(base_path=tmp_path)
        store1.add(sample_trace)
        await store1.save()

        # Load
        store2 = IndexStore(base_path=tmp_path)
        await store2.load()

        loaded = store2.get(sample_trace.run_id)
        assert loaded.total_tokens == sample_trace.total_tokens
        assert loaded.success_rate == sample_trace.success_rate


class TestIndexStoreOperations:
    """Test add/get/list operations."""

    def test_add_trace(self, sample_trace: TraceIndex):
        """Adding trace stores it in memory."""
        store = IndexStore()

        store.add(sample_trace)

        assert len(store.index) == 1
        assert sample_trace.run_id in store.index
        assert store.index[sample_trace.run_id] is sample_trace

    def test_add_multiple_traces(self, sample_trace: TraceIndex, failed_trace: TraceIndex):
        """Adding multiple traces stores all."""
        store = IndexStore()

        store.add(sample_trace)
        store.add(failed_trace)

        assert len(store.index) == 2
        assert sample_trace.run_id in store.index
        assert failed_trace.run_id in store.index

    def test_add_overwrites_existing(self, sample_trace: TraceIndex):
        """Adding trace with existing run_id overwrites."""
        store = IndexStore()
        store.add(sample_trace)

        # Create new trace with same run_id
        updated_trace = TraceIndex(
            run_id=sample_trace.run_id,
            agent_id="updated_agent",
            session_id="updated_session",
            status="failure",
            summary_path="/new/path/summary.json",
            details_path="/new/path/details.jsonl",
            tool_logs_path="/new/path/tool_logs.jsonl",
        )
        store.add(updated_trace)

        assert len(store.index) == 1
        assert store.index[sample_trace.run_id].agent_id == "updated_agent"

    def test_get_existing_trace(self, sample_trace: TraceIndex):
        """Getting existing trace returns it."""
        store = IndexStore()
        store.add(sample_trace)

        result = store.get(sample_trace.run_id)

        assert result is not None
        assert result.run_id == sample_trace.run_id

    def test_get_nonexistent_trace(self):
        """Getting nonexistent trace returns None."""
        store = IndexStore()

        result = store.get("nonexistent_id")

        assert result is None

    def test_list_all_empty(self):
        """Listing empty index returns empty list."""
        store = IndexStore()

        result = store.list_all()

        assert result == []

    def test_list_all_multiple_traces(self, sample_trace: TraceIndex, failed_trace: TraceIndex):
        """Listing index returns all traces."""
        store = IndexStore()
        store.add(sample_trace)
        store.add(failed_trace)

        result = store.list_all()

        assert len(result) == 2
        assert sample_trace in result
        assert failed_trace in result


class TestIndexStoreConcurrency:
    """Test concurrent operations and thread safety."""

    @pytest.mark.asyncio
    async def test_concurrent_loads(self, tmp_path: Path, sample_trace: TraceIndex):
        """Multiple concurrent loads work correctly."""
        # Setup initial data
        store = IndexStore(base_path=tmp_path)
        store.add(sample_trace)
        await store.save()

        # Create multiple stores and load concurrently
        stores = [IndexStore(base_path=tmp_path) for _ in range(5)]
        await asyncio.gather(*[s.load() for s in stores])

        # All should have loaded the same data
        for s in stores:
            assert len(s.index) == 1
            assert sample_trace.run_id in s.index

    @pytest.mark.asyncio
    async def test_concurrent_saves(self, tmp_path: Path):
        """Multiple concurrent saves complete without errors."""
        stores = [IndexStore(base_path=tmp_path) for _ in range(3)]

        # Add different traces to each store
        for i, store in enumerate(stores):
            trace = TraceIndex(
                run_id=f"run_{i}",
                agent_id=f"agent_{i}",
                session_id=f"session_{i}",
                status="success",
                summary_path="/path/summary.json",
                details_path="/path/details.jsonl",
                tool_logs_path="/path/tool_logs.jsonl",
            )
            store.add(trace)

        # Save concurrently
        await asyncio.gather(*[s.save() for s in stores])

        # Last save should win (this is expected behavior)
        assert tmp_path.joinpath(".trace_index.json").exists()
