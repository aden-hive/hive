"""
End-to-end integration test for trace debugging workflow.

Tests the complete workflow:
1. Create mock session logs
2. Index traces
3. Build vector index
4. Query with RAG
5. Analyze patterns

This demonstrates the full user experience.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from framework.debugging.index_store import IndexStore
from framework.debugging.trace_embedder import TraceEmbedder
from framework.debugging.trace_indexer import TraceIndexer
from framework.debugging.trace_rag import TraceRAG
from framework.debugging.trace_vector_store import TraceVectorStore


def create_mock_session_with_logs(
    agent_path: Path,
    session_id: str,
    run_id: str,
    status: str = "success",
    with_error: bool = False,
):
    """Create a complete mock session with L1/L2/L3 logs."""
    import json
    from datetime import datetime

    session_dir = agent_path / "sessions" / session_id
    logs_dir = session_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # L1: summary.json
    summary = {
        "run_id": run_id,
        "agent_id": "sales_agent",
        "goal_id": "outreach_campaign",
        "status": status,
        "total_nodes_executed": 3,
        "node_path": ["intake", "research", "outreach"],
        "total_input_tokens": 2000,
        "total_output_tokens": 3000,
        "needs_attention": with_error,
        "attention_reasons": ["high_retry_count"] if with_error else [],
        "started_at": datetime.now().isoformat(),
        "duration_ms": 8000 if with_error else 5000,
        "execution_quality": "degraded" if with_error else "clean",
    }

    with open(logs_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # L2: details.jsonl
    details = [
        {
            "node_id": "intake",
            "node_name": "Intake Collector",
            "node_type": "event_loop",
            "success": True,
            "error": None,
            "total_steps": 2,
            "tokens_used": 1000,
            "input_tokens": 400,
            "output_tokens": 600,
            "latency_ms": 1500,
            "exit_status": "success",
            "retry_count": 0,
        },
        {
            "node_id": "research",
            "node_name": "Research Node",
            "node_type": "event_loop",
            "success": not with_error,
            "error": "Timeout in web_search" if with_error else None,
            "total_steps": 8 if with_error else 3,
            "tokens_used": 2500,
            "input_tokens": 1000,
            "output_tokens": 1500,
            "latency_ms": 5000 if with_error else 2500,
            "exit_status": "escalate" if with_error else "success",
            "retry_count": 6 if with_error else 0,
        },
        {
            "node_id": "outreach",
            "node_name": "Outreach Node",
            "node_type": "event_loop",
            "success": True,
            "error": None,
            "total_steps": 2,
            "tokens_used": 1500,
            "input_tokens": 600,
            "output_tokens": 900,
            "latency_ms": 1500,
            "exit_status": "success",
            "retry_count": 0,
        },
    ]

    with open(logs_dir / "details.jsonl", "w") as f:
        for detail in details:
            f.write(json.dumps(detail) + "\n")

    # L3: tool_logs.jsonl
    steps = [
        {
            "node_id": "intake",
            "step_index": 0,
            "llm_text": "Collecting lead information",
            "tool_calls": [],
            "input_tokens": 200,
            "output_tokens": 300,
            "latency_ms": 750,
            "verdict": "ACCEPT",
        },
        {
            "node_id": "research",
            "step_index": 0,
            "llm_text": "Searching for company info",
            "tool_calls": [],
            "input_tokens": 500,
            "output_tokens": 750,
            "latency_ms": 1200,
            "verdict": "RETRY" if with_error else "ACCEPT",
        },
    ]

    with open(logs_dir / "tool_logs.jsonl", "w") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")


class MockEmbeddings:
    """Mock embeddings for testing."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1 + i * 0.01] * 384 for i in range(len(texts))]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 384


class TestEndToEndWorkflow:
    """Test complete debugging workflow from start to finish."""

    @pytest.mark.asyncio
    async def test_complete_workflow(self, tmp_path: Path):
        """
        Complete workflow: Create sessions → Index → Build vectors → Query

        This is the full user experience.
        """
        # ====================================================================
        # SETUP: Create mock agent with sessions
        # ====================================================================
        agent_path = tmp_path / "agents" / "sales_agent"

        # Create 3 sessions: 2 successful, 1 failed
        create_mock_session_with_logs(
            agent_path,
            session_id="session_20260212_100000_abc",
            run_id="session_20260212_100000_abc",
            status="success",
            with_error=False,
        )

        create_mock_session_with_logs(
            agent_path,
            session_id="session_20260212_110000_def",
            run_id="session_20260212_110000_def",
            status="success",
            with_error=False,
        )

        create_mock_session_with_logs(
            agent_path,
            session_id="session_20260212_120000_ghi",
            run_id="session_20260212_120000_ghi",
            status="failure",
            with_error=True,
        )

        # ====================================================================
        # STEP 1: Index Traces
        # ====================================================================
        indexer = TraceIndexer(agent_path)
        store = IndexStore(base_path=agent_path)

        stats = await indexer.index_all_sessions(store)

        # Verify indexing
        assert stats["indexed"] == 3
        assert stats["skipped"] == 0
        assert len(store.index) == 3

        # Verify trace content
        traces = store.list_all()
        success_traces = [t for t in traces if t.status == "success"]
        failed_traces = [t for t in traces if t.status == "failure"]

        assert len(success_traces) == 2
        assert len(failed_traces) == 1
        assert failed_traces[0].error_message == "Timeout in web_search"

        # Save index
        await store.save()

        # ====================================================================
        # STEP 2: Build Vector Index
        # ====================================================================
        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        vector_store = TraceVectorStore(storage_path=agent_path / ".vector_index", dimension=384)
        await vector_store.initialize()

        # Generate embeddings and add to vector store
        embeddings = await embedder.embed_traces(traces)
        await vector_store.add_traces(traces, embeddings)

        # Verify vector index
        assert vector_store.size() == 3

        # Save vector index
        await vector_store.save()

        # ====================================================================
        # STEP 3: Query with RAG
        # ====================================================================
        # Create mock LLM
        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        # Mock response
        class MockResponse:
            content = (
                "Based on the traces, 1 run failed due to a timeout in the "
                "web_search tool during the research node. The run had 6 retry "
                "attempts before escalating. The other 2 runs were successful "
                "with clean execution."
            )

        mock_llm.ainvoke.return_value = MockResponse()

        rag = TraceRAG(embedder, vector_store, llm=mock_llm)

        # Query: "Why did runs fail?"
        result = await rag.query("Why did runs fail?", k=3)

        # Verify query results
        assert "answer" in result
        assert "timeout" in result["answer"].lower()
        assert "traces" in result
        assert len(result["traces"]) == 3

        # Verify LLM was called with proper context
        assert mock_llm.ainvoke.called
        call_args = mock_llm.ainvoke.call_args[0][0]
        assert len(call_args) == 2  # System + Human message
        assert "web_search" in str(call_args)

        # ====================================================================
        # STEP 4: Pattern Analysis
        # ====================================================================
        # Analyze failure patterns
        mock_llm.ainvoke.return_value.content = (
            "Failure Pattern Analysis:\n"
            "- 33% failure rate (1 of 3 runs)\n"
            "- Root cause: Timeout in web_search tool\n"
            "- High retry count (6 attempts) indicates persistent issue\n"
            "- Recommendation: Check web_search timeout settings"
        )

        analysis = await rag.analyze_pattern("failures", limit=5)

        # Verify analysis
        assert "timeout" in analysis.lower()
        assert "web_search" in analysis.lower()

        # ====================================================================
        # STEP 5: Find Similar Failures
        # ====================================================================
        failed_trace = failed_traces[0]
        similar = await rag.find_similar_failures(failed_trace, k=2)

        # Should not include the reference trace itself
        assert all(t.run_id != failed_trace.run_id for t, _ in similar)

        # ====================================================================
        # STEP 6: Reload and Query Again (Persistence Test)
        # ====================================================================
        # Create new instances (simulating new session)
        store2 = IndexStore(base_path=agent_path)
        await store2.load()

        vector_store2 = TraceVectorStore(storage_path=agent_path / ".vector_index")
        await vector_store2.initialize()

        # Verify persistence
        assert len(store2.index) == 3
        assert vector_store2.size() == 3

        # Query again
        rag2 = TraceRAG(embedder, vector_store2, llm=mock_llm)
        result2 = await rag2.query("What was the success rate?", k=3)

        assert "answer" in result2
        assert len(result2["traces"]) == 3

    @pytest.mark.asyncio
    async def test_incremental_indexing(self, tmp_path: Path):
        """Test adding new sessions incrementally."""
        agent_path = tmp_path / "agents" / "test_agent"

        # Index initial session
        create_mock_session_with_logs(
            agent_path, session_id="session_1", run_id="session_1", status="success"
        )

        indexer = TraceIndexer(agent_path)
        store = IndexStore(base_path=agent_path)

        stats = await indexer.index_all_sessions(store)
        assert stats["indexed"] == 1
        await store.save()

        # Add new session
        create_mock_session_with_logs(
            agent_path,
            session_id="session_2",
            run_id="session_2",
            status="failure",
            with_error=True,
        )

        # Re-index (should pick up new session)
        store2 = IndexStore(base_path=agent_path)
        await store2.load()
        assert len(store2.index) == 1  # Old session still there

        stats2 = await indexer.index_all_sessions(store2)
        assert stats2["indexed"] == 2  # Now has both
        assert len(store2.index) == 2

    @pytest.mark.asyncio
    async def test_search_similarity(self, tmp_path: Path):
        """Test semantic search finds similar traces."""
        agent_path = tmp_path / "agents" / "test_agent"

        # Create sessions with different characteristics
        # Session 1: Success with low latency
        create_mock_session_with_logs(agent_path, "session_fast", "session_fast", "success", False)

        # Session 2: Failure with timeout
        create_mock_session_with_logs(
            agent_path, "session_timeout", "session_timeout", "failure", True
        )

        # Index and build vectors
        indexer = TraceIndexer(agent_path)
        store = IndexStore(base_path=agent_path)
        await indexer.index_all_sessions(store)

        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        vector_store = TraceVectorStore(storage_path=agent_path / ".vector_index", dimension=384)
        await vector_store.initialize()

        traces = store.list_all()
        embeddings = await embedder.embed_traces(traces)
        await vector_store.add_traces(traces, embeddings)

        # Search for "timeout error"
        query_embedding = await embedder.embed_query("timeout error")
        results = await vector_store.search(query_embedding, k=2)

        # Should find both traces, sorted by similarity
        assert len(results) == 2
        # Results are (trace, distance) tuples
        assert all(isinstance(t[0].run_id, str) for t in results)
        assert all(isinstance(t[1], float) for t in results)

        # Distances should be sorted (closest first)
        distances = [dist for _, dist in results]
        assert distances == sorted(distances)


class TestWorkflowErrorHandling:
    """Test error handling in the workflow."""

    @pytest.mark.asyncio
    async def test_handle_missing_logs(self, tmp_path: Path):
        """Workflow handles sessions with missing logs gracefully."""
        agent_path = tmp_path / "agents" / "test_agent"

        # Create session without logs
        session_dir = agent_path / "sessions" / "session_incomplete"
        session_dir.mkdir(parents=True)

        # Index (should skip incomplete session)
        indexer = TraceIndexer(agent_path)
        store = IndexStore(base_path=agent_path)

        stats = await indexer.index_all_sessions(store)

        assert stats["indexed"] == 0
        assert stats["skipped"] == 1

    @pytest.mark.asyncio
    async def test_handle_corrupted_logs(self, tmp_path: Path):
        """Workflow handles corrupted logs gracefully."""
        agent_path = tmp_path / "agents" / "test_agent"

        # Create session with corrupted logs
        session_dir = agent_path / "sessions" / "session_corrupt"
        logs_dir = session_dir / "logs"
        logs_dir.mkdir(parents=True)

        # Write invalid JSON
        with open(logs_dir / "summary.json", "w") as f:
            f.write("{ invalid json")

        # Index (should skip corrupted session)
        indexer = TraceIndexer(agent_path)
        store = IndexStore(base_path=agent_path)

        stats = await indexer.index_all_sessions(store)

        # Should be skipped due to parse error
        assert stats["skipped"] == 1

    @pytest.mark.asyncio
    async def test_empty_vector_index_query(self, tmp_path: Path):
        """Querying empty vector index returns helpful message."""
        agent_path = tmp_path / "agents" / "test_agent"

        embedder = TraceEmbedder(embeddings_provider=MockEmbeddings())
        vector_store = TraceVectorStore(storage_path=agent_path / ".vector_index", dimension=384)
        await vector_store.initialize()

        mock_llm = Mock()
        mock_llm.ainvoke = AsyncMock()

        rag = TraceRAG(embedder, vector_store, llm=mock_llm)

        result = await rag.query("find failures", k=5)

        assert "No traces found" in result["answer"]
        assert result.get("traces", []) == []
