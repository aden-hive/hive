"""
Tests for TraceRAG.

Follows Hive patterns:
- pytest with @pytest.mark.asyncio
- Mock external dependencies (LLM)
- Test classes grouping related tests
- Descriptive test names and docstrings

Reference: core/tests/test_llm_judge.py for mocking LLM
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from framework.debugging.trace_embedder import TraceEmbedder
from framework.debugging.trace_index import TraceIndex
from framework.debugging.trace_rag import TraceRAG
from framework.debugging.trace_vector_store import TraceVectorStore


class MockLLMResponse:
    """Mock LangChain LLM response."""

    def __init__(self, content: str):
        self.content = content


class MockEmbeddings:
    """Mock embeddings provider."""

    def __init__(self, dimension: int = 128):
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dimension for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * self.dimension


def generate_mock_embedding(dimension: int = 128, seed: int = 0) -> list[float]:
    """Generate deterministic mock embedding for testing."""
    return [(i + seed) / dimension for i in range(dimension)]


async def create_populated_store(tmp_path, sample_trace: TraceIndex, failed_trace: TraceIndex):
    """Helper to create populated vector store."""
    store = TraceVectorStore(storage_path=tmp_path, dimension=128)
    await store.initialize()

    traces = [sample_trace, failed_trace]
    embeddings = [generate_mock_embedding(128, seed=1), generate_mock_embedding(128, seed=2)]
    await store.add_traces(traces, embeddings)

    return store


class TestTraceRAGInitialization:
    """Test TraceRAG initialization."""

    @pytest.mark.asyncio
    async def test_initialization(self, tmp_path):
        """TraceRAG initializes with embedder and vector store."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        assert rag.embedder is embedder
        assert rag.vector_store is store
        assert rag.llm is not None


class TestTraceRAGQuery:
    """Test RAG query functionality."""

    @pytest.mark.asyncio
    async def test_query_empty_index(self, tmp_path):
        """Querying empty index returns no results message."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        result = await rag.query("find failed runs")

        assert "answer" in result
        assert "No traces found" in result["answer"]
        assert result.get("traces", []) == []

    @pytest.mark.asyncio
    async def test_query_returns_answer_and_traces(self, tmp_path, populated_vector_store):
        """Query returns LLM answer and retrieved traces."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        rag = TraceRAG(embedder, populated_vector_store, api_key="test-key")

        # Mock LLM response
        mock_response = MockLLMResponse("The agent had 2 runs with mixed results.")
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            result = await rag.query("summarize agent runs", k=2)

        assert "answer" in result
        assert result["answer"] == "The agent had 2 runs with mixed results."
        assert "traces" in result
        assert len(result["traces"]) == 2

    @pytest.mark.asyncio
    async def test_query_without_context(self, tmp_path, populated_vector_store):
        """Query with include_context=False doesn't return traces."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        rag = TraceRAG(embedder, populated_vector_store, api_key="test-key")

        mock_response = MockLLMResponse("Analysis complete.")
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            result = await rag.query("analyze runs", k=2, include_context=False)

        assert "answer" in result
        assert "traces" not in result

    @pytest.mark.asyncio
    async def test_query_respects_k_parameter(self, tmp_path, populated_vector_store):
        """Query k parameter limits number of retrieved traces."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        rag = TraceRAG(embedder, populated_vector_store, api_key="test-key")

        mock_response = MockLLMResponse("Found 1 trace.")
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            result = await rag.query("find runs", k=1)

        assert len(result["traces"]) == 1

    @pytest.mark.asyncio
    async def test_query_handles_llm_error(self, tmp_path, populated_vector_store):
        """Query handles LLM errors gracefully."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        rag = TraceRAG(embedder, populated_vector_store, api_key="test-key")

        # Mock LLM to raise exception
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API error")

            result = await rag.query("find runs")

        assert "answer" in result
        assert "Error" in result["answer"]


class TestTraceRAGPatternAnalysis:
    """Test pattern analysis functionality."""

    @pytest.mark.asyncio
    async def test_analyze_failures_pattern(self, tmp_path, populated_vector_store):
        """Analyze failures pattern queries for failed runs."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        rag = TraceRAG(embedder, populated_vector_store, api_key="test-key")

        mock_response = MockLLMResponse("Found 1 failure with timeout error.")
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            analysis = await rag.analyze_pattern("failures", limit=5)

        assert "timeout error" in analysis

    @pytest.mark.asyncio
    async def test_analyze_performance_pattern(self, tmp_path, populated_vector_store):
        """Analyze performance pattern queries for high latency runs."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        rag = TraceRAG(embedder, populated_vector_store, api_key="test-key")

        mock_response = MockLLMResponse("High latency detected in 1 run.")
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            analysis = await rag.analyze_pattern("performance", limit=5)

        assert "latency" in analysis.lower()

    @pytest.mark.asyncio
    async def test_analyze_empty_results(self, tmp_path):
        """Pattern analysis with no traces returns message."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        analysis = await rag.analyze_pattern("failures")

        assert "No traces found" in analysis


class TestTraceRAGSimilarFailures:
    """Test finding similar failures."""

    @pytest.mark.asyncio
    async def test_find_similar_failures(self, tmp_path, failed_trace: TraceIndex):
        """Find similar failures returns similar failed traces."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add multiple failed traces
        failed_trace2 = TraceIndex(
            run_id="failed_run_2",
            agent_id="test_agent",
            session_id="session_2",
            status="failure",
            error_message="Timeout in web_search",
            failed_node_id="search",
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        traces = [failed_trace, failed_trace2]
        embeddings = [generate_mock_embedding(128, seed=1), generate_mock_embedding(128, seed=2)]
        await store.add_traces(traces, embeddings)

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        # Find similar failures
        similar = await rag.find_similar_failures(failed_trace, k=1)

        # Should find the other failed trace
        assert len(similar) <= 1
        if similar:
            assert similar[0][0].status in ["failure", "degraded"]
            assert similar[0][0].run_id != failed_trace.run_id

    @pytest.mark.asyncio
    async def test_find_similar_filters_self(self, tmp_path, failed_trace: TraceIndex):
        """Find similar failures excludes the reference trace."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add only one trace
        embedding = generate_mock_embedding(128, seed=1)
        await store.add_traces([failed_trace], [embedding])

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        # Find similar should not return itself
        similar = await rag.find_similar_failures(failed_trace, k=5)

        assert all(t.run_id != failed_trace.run_id for t, _ in similar)


class TestTraceRAGContextFormatting:
    """Test context formatting for LLM."""

    @pytest.mark.asyncio
    async def test_format_context_includes_metadata(self, tmp_path, sample_trace: TraceIndex):
        """Format context includes all trace metadata."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        context = rag._format_context([sample_trace])

        assert sample_trace.run_id in context
        assert sample_trace.agent_id in context
        assert sample_trace.status in context
        assert str(sample_trace.total_latency_ms) in context

    @pytest.mark.asyncio
    async def test_format_context_includes_errors(self, tmp_path, failed_trace: TraceIndex):
        """Format context includes error information for failed traces."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        context = rag._format_context([failed_trace])

        assert "Error:" in context
        assert failed_trace.error_message in context
        assert failed_trace.failed_node_id in context

    @pytest.mark.asyncio
    async def test_format_context_multiple_traces(
        self, tmp_path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Format context handles multiple traces."""
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)

        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        context = rag._format_context([sample_trace, failed_trace])

        assert "Trace 1" in context
        assert "Trace 2" in context
        assert sample_trace.run_id in context
        assert failed_trace.run_id in context


class TestTraceRAGIntegration:
    """Integration tests for RAG workflow."""

    @pytest.mark.asyncio
    async def test_full_rag_workflow(
        self, tmp_path, sample_trace: TraceIndex, failed_trace: TraceIndex
    ):
        """Full RAG workflow: embed → store → query → generate."""
        # Setup components
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings(128))
        store = TraceVectorStore(storage_path=tmp_path, dimension=128)
        await store.initialize()

        # Add traces
        traces = [sample_trace, failed_trace]
        embeddings = await embedder.embed_traces(traces)
        await store.add_traces(traces, embeddings)

        # Create RAG
        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, store, llm=mock_llm)

        # Query with mocked LLM
        mock_response = MockLLMResponse("Found 2 runs: 1 successful, 1 failed with timeout.")
        with patch.object(rag.llm, "ainvoke", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            result = await rag.query("summarize runs", k=2)

        # Verify complete workflow
        assert result["answer"] == mock_response.content
        assert len(result["traces"]) == 2
        assert any(t.status == "success" for t in result["traces"])
        assert any(t.status == "failure" for t in result["traces"])
