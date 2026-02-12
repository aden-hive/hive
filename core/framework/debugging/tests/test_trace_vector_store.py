"""
Tests for TraceVectorStore.

Follows Hive patterns:
- pytest with @pytest.mark.asyncio
- tmp_path fixture for file operations
- Test classes grouping related tests
- Descriptive test names and docstrings

Reference: core/tests/test_concurrent_storage.py
"""

from pathlib import Path

import pytest

from framework.debugging.trace_index import TraceIndex
from framework.debugging.trace_vector_store import TraceVectorStore


def generate_mock_embedding(dimension: int = 128, seed: int = 0) -> list[float]:
    """Generate deterministic mock embedding for testing."""
    return [(i + seed) / dimension for i in range(dimension)]


class TestTraceVectorStoreInitialization:
    """Test TraceVectorStore initialization."""

    def test_initialization_default_path(self):
        """VectorStore initializes with default path."""
        store = TraceVectorStore(dimension=128)

        expected_path = Path.home() / ".hive" / "agents" / ".vector_index"
        assert store.storage_path == expected_path
        assert store.dimension == 128
        assert store.index is None
        assert store.metadata == {}
        assert store.index_to_run_id == []

    def test_initialization_custom_path(self, tmp_path: Path):
        """VectorStore accepts custom storage path."""
        custom_path = tmp_path / "custom" / "vector_store"
        store = TraceVectorStore(storage_path=custom_path, dimension=64)

        assert store.storage_path == custom_path
        assert store.dimension == 64

    @pytest.mark.asyncio
    async def test_initialize_creates_new_index(self, tmp_path: Path):
        """Initialize creates new FAISS index."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        await store.initialize()

        assert store.index is not None
        assert store.size() == 0


class TestTraceVectorStoreAddTraces:
    """Test adding traces to vector store."""

    @pytest.mark.asyncio
    async def test_add_single_trace(self, tmp_path: Path, sample_trace: TraceIndex):
        """Adding single trace stores it in index."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        embedding = generate_mock_embedding(128, seed=1)
        await store.add_traces([sample_trace], [embedding])

        assert store.size() == 1
        assert sample_trace.run_id in store.metadata
        assert len(store.index_to_run_id) == 1

    @pytest.mark.asyncio
    async def test_add_multiple_traces(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Adding multiple traces stores all."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        traces = [sample_trace, failed_trace]
        embeddings = [generate_mock_embedding(128, seed=1), generate_mock_embedding(128, seed=2)]

        await store.add_traces(traces, embeddings)

        assert store.size() == 2
        assert sample_trace.run_id in store.metadata
        assert failed_trace.run_id in store.metadata

    @pytest.mark.asyncio
    async def test_add_mismatched_lengths_raises_error(
        self, tmp_path: Path, sample_trace: TraceIndex
    ):
        """Adding traces with mismatched embeddings raises ValueError."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        traces = [sample_trace]
        embeddings = []  # Empty embeddings

        with pytest.raises(ValueError, match="must have same length"):
            await store.add_traces(traces, embeddings)

    @pytest.mark.asyncio
    async def test_add_without_initialize(self, tmp_path: Path, sample_trace: TraceIndex):
        """Adding traces without initialize auto-initializes."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        embedding = generate_mock_embedding(128)
        await store.add_traces([sample_trace], [embedding])

        assert store.index is not None
        assert store.size() == 1


class TestTraceVectorStoreSearch:
    """Test semantic search."""

    @pytest.mark.asyncio
    async def test_search_empty_index(self, tmp_path: Path):
        """Searching empty index returns empty list."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        query_embedding = generate_mock_embedding(128)
        results = await store.search(query_embedding, k=5)

        assert results == []

    @pytest.mark.asyncio
    async def test_search_returns_similar_traces(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Search returns traces sorted by similarity."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add traces with different embeddings
        traces = [sample_trace, failed_trace]
        embeddings = [
            generate_mock_embedding(128, seed=1),
            generate_mock_embedding(128, seed=10),  # More different
        ]
        await store.add_traces(traces, embeddings)

        # Search with query similar to first trace
        query_embedding = generate_mock_embedding(128, seed=2)
        results = await store.search(query_embedding, k=2)

        assert len(results) == 2
        # Each result is (TraceIndex, distance)
        assert isinstance(results[0][0], TraceIndex)
        assert isinstance(results[0][1], float)

    @pytest.mark.asyncio
    async def test_search_respects_k_limit(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Search respects k parameter."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add 3 traces
        trace1 = sample_trace
        trace2 = failed_trace
        trace3 = TraceIndex(
            run_id="run_3",
            agent_id="agent_3",
            session_id="session_3",
            status="success",
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        traces = [trace1, trace2, trace3]
        embeddings = [generate_mock_embedding(128, seed=i) for i in range(len(traces))]
        await store.add_traces(traces, embeddings)

        # Search with k=2
        query_embedding = generate_mock_embedding(128, seed=0)
        results = await store.search(query_embedding, k=2)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_search_returns_sorted_by_distance(
        self, tmp_path: Path, sample_trace: TraceIndex
    ):
        """Search results are sorted by distance (closest first)."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add multiple traces
        traces = [
            TraceIndex(
                run_id=f"run_{i}",
                agent_id="test_agent",
                session_id=f"session_{i}",
                status="success",
                summary_path="/path/summary.json",
                details_path="/path/details.jsonl",
                tool_logs_path="/path/tool_logs.jsonl",
            )
            for i in range(5)
        ]

        embeddings = [generate_mock_embedding(128, seed=i * 2) for i in range(5)]
        await store.add_traces(traces, embeddings)

        # Search
        query_embedding = generate_mock_embedding(128, seed=1)
        results = await store.search(query_embedding, k=5)

        # Verify distances are sorted
        distances = [dist for _, dist in results]
        assert distances == sorted(distances)


class TestTraceVectorStorePersistence:
    """Test save/load persistence."""

    @pytest.mark.asyncio
    async def test_save_empty_index(self, tmp_path: Path):
        """Saving empty index creates files."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        await store.save()

        # Verify files exist but index remains empty
        assert (tmp_path / "faiss.index").exists()
        assert (tmp_path / "metadata.json").exists()
        assert (tmp_path / "index_mapping.json").exists()

    @pytest.mark.asyncio
    async def test_save_and_load(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Save and load preserves index and metadata."""
        # Create and populate store
        store1 = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store1.initialize()

        traces = [sample_trace, failed_trace]
        embeddings = [generate_mock_embedding(128, seed=1), generate_mock_embedding(128, seed=2)]
        await store1.add_traces(traces, embeddings)

        # Save
        await store1.save()

        # Load in new store
        store2 = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store2.initialize()

        # Verify loaded state
        assert store2.size() == 2
        assert sample_trace.run_id in store2.metadata
        assert failed_trace.run_id in store2.metadata
        assert len(store2.index_to_run_id) == 2

    @pytest.mark.asyncio
    async def test_round_trip_preserves_search(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Save/load round trip preserves search functionality."""
        # Create and populate store
        store1 = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store1.initialize()

        traces = [sample_trace, failed_trace]
        embeddings = [generate_mock_embedding(128, seed=1), generate_mock_embedding(128, seed=2)]
        await store1.add_traces(traces, embeddings)

        # Search before save
        query_embedding = generate_mock_embedding(128, seed=1)
        results_before = await store1.search(query_embedding, k=2)

        # Save
        await store1.save()

        # Load and search
        store2 = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store2.initialize()
        results_after = await store2.search(query_embedding, k=2)

        # Results should be similar (same traces, similar distances)
        assert len(results_before) == len(results_after)
        assert results_before[0][0].run_id == results_after[0][0].run_id

    @pytest.mark.asyncio
    async def test_load_nonexistent_creates_new(self, tmp_path: Path):
        """Loading nonexistent index creates new index."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        # Initialize will try to load (fails) then create new
        await store.initialize()

        assert store.index is not None
        assert store.size() == 0


class TestTraceVectorStoreOperations:
    """Test store operations."""

    def test_size_empty_index(self, tmp_path: Path):
        """Size returns 0 for empty index."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        assert store.size() == 0

    @pytest.mark.asyncio
    async def test_size_after_adding(self, tmp_path: Path, sample_trace: TraceIndex):
        """Size returns correct count after adding traces."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        embedding = generate_mock_embedding(128)
        await store.add_traces([sample_trace], [embedding])

        assert store.size() == 1

    @pytest.mark.asyncio
    async def test_clear_resets_index(self, tmp_path: Path, sample_trace: TraceIndex):
        """Clear removes all traces and creates fresh index."""
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add trace
        embedding = generate_mock_embedding(128)
        await store.add_traces([sample_trace], [embedding])
        assert store.size() == 1

        # Clear
        store.clear()

        assert store.size() == 0
        assert store.metadata == {}
        assert store.index_to_run_id == []
        assert store.index is not None  # New index created


class TestTraceVectorStoreIntegration:
    """Integration tests for vector store."""

    @pytest.mark.asyncio
    async def test_full_workflow(
        self, tmp_path: Path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Full workflow: add → search → save → load → search."""
        # Step 1: Add traces
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        traces = [sample_trace, failed_trace]
        embeddings = [generate_mock_embedding(128, seed=1), generate_mock_embedding(128, seed=10)]
        await store.add_traces(traces, embeddings)

        # Step 2: Search
        query_embedding = generate_mock_embedding(128, seed=2)
        results1 = await store.search(query_embedding, k=2)
        assert len(results1) == 2

        # Step 3: Save
        await store.save()

        # Step 4: Load in new store
        store2 = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store2.initialize()

        # Step 5: Search again
        results2 = await store2.search(query_embedding, k=2)
        assert len(results2) == 2

        # Results should match
        assert results1[0][0].run_id == results2[0][0].run_id
