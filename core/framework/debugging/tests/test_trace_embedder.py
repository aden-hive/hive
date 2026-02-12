"""
Tests for TraceEmbedder.

Follows Hive patterns:
- pytest with @pytest.mark.asyncio
- Mock external dependencies
- Test classes grouping related tests
- Descriptive test names and docstrings

Reference: core/tests/test_concurrent_storage.py
"""

import pytest

from framework.debugging.trace_embedder import TraceEmbedder
from framework.debugging.trace_index import TraceIndex


class MockEmbeddings:
    """Mock embeddings provider for testing."""

    def __init__(self, dimension: int = 1024):
        self.dimension = dimension
        self.call_count = 0

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Mock batch embedding."""
        self.call_count += 1
        return [[0.1] * self.dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        """Mock single query embedding."""
        self.call_count += 1
        return [0.1] * self.dimension


class TestTraceEmbedderInitialization:
    """Test TraceEmbedder initialization."""

    def test_initialization_with_custom_provider(self):
        """TraceEmbedder accepts custom embeddings provider."""
        mock_embeddings = MockEmbeddings()
        embedder = TraceEmbedder(embeddings_provider=mock_embeddings)

        assert embedder.embeddings is mock_embeddings


class TestTraceEmbedderDocumentConversion:
    """Test converting TraceIndex to text documents."""

    def test_trace_to_document_minimal(self, sample_trace: TraceIndex):
        """Minimal trace converts to structured document."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())

        document = embedder.trace_to_document(sample_trace)

        assert sample_trace.run_id in document
        assert sample_trace.agent_id in document
        assert sample_trace.status in document
        assert str(sample_trace.total_latency_ms) in document

    def test_trace_to_document_with_nodes(self, sample_trace: TraceIndex):
        """Trace with nodes includes execution sequence."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())

        document = embedder.trace_to_document(sample_trace)

        assert "Nodes Executed:" in document
        assert "intake" in document
        assert "process" in document
        assert "output" in document

    def test_trace_to_document_with_error(self, failed_trace: TraceIndex):
        """Failed trace includes error information."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())

        document = embedder.trace_to_document(failed_trace)

        assert "Error:" in document
        assert failed_trace.error_message in document
        assert "Failed at Node:" in document
        assert failed_trace.failed_node_id in document

    def test_trace_to_document_structure(self, sample_trace: TraceIndex):
        """Document has consistent structure."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())

        document = embedder.trace_to_document(sample_trace)

        lines = document.split("\n")
        assert any("Run ID:" in line for line in lines)
        assert any("Agent:" in line for line in lines)
        assert any("Status:" in line for line in lines)
        assert any("Execution Quality:" in line for line in lines)
        assert any("Total Latency:" in line for line in lines)


class TestTraceEmbedderEmbedding:
    """Test embedding generation."""

    @pytest.mark.asyncio
    async def test_embed_single_trace(self, sample_trace: TraceIndex):
        """Embedding single trace returns vector."""
        mock_embeddings = MockEmbeddings(dimension=128)
        embedder = TraceEmbedder(embeddings_provider=mock_embeddings)

        embedding = await embedder.embed_trace(sample_trace)

        assert isinstance(embedding, list)
        assert len(embedding) == 128
        assert all(isinstance(x, float) for x in embedding)
        assert mock_embeddings.call_count == 1

    @pytest.mark.asyncio
    async def test_embed_multiple_traces(self, sample_trace: TraceIndex, failed_trace: TraceIndex):
        """Embedding multiple traces returns list of vectors."""
        mock_embeddings = MockEmbeddings(dimension=128)
        embedder = TraceEmbedder(embeddings_provider=mock_embeddings)

        traces = [sample_trace, failed_trace]
        embeddings = await embedder.embed_traces(traces)

        assert isinstance(embeddings, list)
        assert len(embeddings) == 2
        assert all(len(emb) == 128 for emb in embeddings)
        assert mock_embeddings.call_count == 1  # Batch call

    @pytest.mark.asyncio
    async def test_embed_query(self):
        """Embedding query string returns vector."""
        mock_embeddings = MockEmbeddings(dimension=128)
        embedder = TraceEmbedder(embeddings_provider=mock_embeddings)

        query = "find failed runs with timeout errors"
        embedding = await embedder.embed_query(query)

        assert isinstance(embedding, list)
        assert len(embedding) == 128
        assert mock_embeddings.call_count == 1

    @pytest.mark.asyncio
    async def test_batch_embedding_more_efficient(
        self, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Batch embedding uses fewer API calls than individual."""
        mock_embeddings = MockEmbeddings()
        embedder = TraceEmbedder(embeddings_provider=mock_embeddings)

        traces = [sample_trace, failed_trace]

        # Batch embedding
        await embedder.embed_traces(traces)
        batch_calls = mock_embeddings.call_count

        # Reset counter
        mock_embeddings.call_count = 0

        # Individual embeddings
        for trace in traces:
            await embedder.embed_trace(trace)
        individual_calls = mock_embeddings.call_count

        # Batch should use fewer calls (1 vs 2)
        assert batch_calls < individual_calls


class TestTraceEmbedderIntegration:
    """Integration tests for embedder."""

    @pytest.mark.asyncio
    async def test_end_to_end_workflow(self, sample_trace: TraceIndex, failed_trace: TraceIndex):
        """End-to-end workflow: traces to embeddings."""
        mock_embeddings = MockEmbeddings(dimension=64)
        embedder = TraceEmbedder(embeddings_provider=mock_embeddings)

        # Create traces list
        traces = [sample_trace, failed_trace]

        # Generate embeddings
        embeddings = await embedder.embed_traces(traces)

        # Verify results
        assert len(embeddings) == len(traces)
        assert all(len(emb) == 64 for emb in embeddings)

        # Each trace should produce unique document
        doc1 = embedder.trace_to_document(sample_trace)
        doc2 = embedder.trace_to_document(failed_trace)
        assert doc1 != doc2
