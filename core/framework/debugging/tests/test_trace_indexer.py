"""
Tests for TraceIndexer.

Follows Hive patterns:
- pytest with @pytest.mark.asyncio
- tmp_path fixture for file operations
- Test classes grouping related tests
- Descriptive test names and docstrings

Reference: core/tests/test_concurrent_storage.py
"""

import json
from pathlib import Path

import pytest

from framework.debugging.index_store import IndexStore
from framework.debugging.trace_indexer import TraceIndexer


def create_session_logs(
    session_dir: Path,
    run_id: str,
    agent_id: str = "test_agent",
    status: str = "success",
    with_error: bool = False,
) -> None:
    """
    Create mock L1/L2/L3 log files for testing.

    Args:
        session_dir: Session directory path
        run_id: Run identifier
        agent_id: Agent identifier
        status: Run status
        with_error: Whether to include error information
    """
    logs_dir = session_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # L1: summary.json
    summary = {
        "run_id": run_id,
        "agent_id": agent_id,
        "goal_id": "test_goal",
        "status": status,
        "total_nodes_executed": 3,
        "node_path": ["intake", "process", "output"],
        "total_input_tokens": 1000,
        "total_output_tokens": 2000,
        "needs_attention": with_error,
        "attention_reasons": ["high_retry_count"] if with_error else [],
        "started_at": "2026-02-12T12:00:00",
        "duration_ms": 5000,
        "execution_quality": "degraded" if with_error else "clean",
    }

    with open(logs_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # L2: details.jsonl
    details = [
        {
            "node_id": "intake",
            "node_name": "Intake Node",
            "node_type": "event_loop",
            "success": True,
            "error": None,
            "total_steps": 2,
            "tokens_used": 500,
            "input_tokens": 200,
            "output_tokens": 300,
            "latency_ms": 1500,
            "exit_status": "success",
            "retry_count": 0,
            "needs_attention": False,
        },
        {
            "node_id": "process",
            "node_name": "Process Node",
            "node_type": "event_loop",
            "success": not with_error,
            "error": "Timeout in web_search" if with_error else None,
            "total_steps": 5,
            "tokens_used": 1500,
            "input_tokens": 600,
            "output_tokens": 900,
            "latency_ms": 2500,
            "exit_status": "escalate" if with_error else "success",
            "retry_count": 5 if with_error else 0,
            "needs_attention": with_error,
        },
        {
            "node_id": "output",
            "node_name": "Output Node",
            "node_type": "event_loop",
            "success": True,
            "error": None,
            "total_steps": 1,
            "tokens_used": 1000,
            "input_tokens": 200,
            "output_tokens": 800,
            "latency_ms": 1000,
            "exit_status": "success",
            "retry_count": 0,
            "needs_attention": False,
        },
    ]

    with open(logs_dir / "details.jsonl", "w") as f:
        for detail in details:
            f.write(json.dumps(detail) + "\n")

    # L3: tool_logs.jsonl (minimal for testing)
    steps = [
        {
            "node_id": "intake",
            "step_index": 0,
            "llm_text": "Processing intake",
            "tool_calls": [],
            "input_tokens": 100,
            "output_tokens": 150,
            "latency_ms": 750,
            "verdict": "ACCEPT",
        },
    ]

    with open(logs_dir / "tool_logs.jsonl", "w") as f:
        for step in steps:
            f.write(json.dumps(step) + "\n")


class TestTraceIndexerInitialization:
    """Test TraceIndexer initialization."""

    def test_initialization(self, tmp_path: Path):
        """TraceIndexer initializes with agent base path."""
        indexer = TraceIndexer(tmp_path)

        assert indexer.agent_base_path == tmp_path
        assert indexer.sessions_dir == tmp_path / "sessions"


class TestTraceIndexerDiscovery:
    """Test session discovery."""

    @pytest.mark.asyncio
    async def test_discover_no_sessions(self, tmp_path: Path):
        """No sessions returns empty list."""
        indexer = TraceIndexer(tmp_path)

        sessions = await indexer._discover_sessions()

        assert sessions == []

    @pytest.mark.asyncio
    async def test_discover_single_session(self, tmp_path: Path):
        """Single session directory is discovered."""
        sessions_dir = tmp_path / "sessions"
        session_dir = sessions_dir / "session_20260212_120000_abc"
        session_dir.mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        sessions = await indexer._discover_sessions()

        assert len(sessions) == 1
        assert sessions[0].name == "session_20260212_120000_abc"

    @pytest.mark.asyncio
    async def test_discover_multiple_sessions(self, tmp_path: Path):
        """Multiple session directories are discovered."""
        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "session_20260212_120000_abc").mkdir(parents=True)
        (sessions_dir / "session_20260212_130000_def").mkdir(parents=True)
        (sessions_dir / "session_20260212_140000_ghi").mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        sessions = await indexer._discover_sessions()

        assert len(sessions) == 3

    @pytest.mark.asyncio
    async def test_discover_ignores_non_session_dirs(self, tmp_path: Path):
        """Non-session directories are ignored."""
        sessions_dir = tmp_path / "sessions"
        (sessions_dir / "session_20260212_120000_abc").mkdir(parents=True)
        (sessions_dir / "other_dir").mkdir(parents=True)
        (sessions_dir / "not_a_session").mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        sessions = await indexer._discover_sessions()

        assert len(sessions) == 1
        assert sessions[0].name.startswith("session_")


class TestTraceIndexerReadLogs:
    """Test reading L1/L2/L3 logs."""

    @pytest.mark.asyncio
    async def test_read_summary_success(self, tmp_path: Path):
        """Reading valid summary.json returns RunSummaryLog."""
        session_dir = tmp_path / "sessions" / "session_test"
        create_session_logs(session_dir, run_id="run_123", agent_id="test_agent")

        indexer = TraceIndexer(tmp_path)
        summary = await indexer._read_summary(session_dir / "logs")

        assert summary is not None
        assert summary.run_id == "run_123"
        assert summary.agent_id == "test_agent"
        assert summary.status == "success"

    @pytest.mark.asyncio
    async def test_read_summary_missing(self, tmp_path: Path):
        """Reading missing summary.json returns None."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        summary = await indexer._read_summary(logs_dir)

        assert summary is None

    @pytest.mark.asyncio
    async def test_read_summary_corrupted(self, tmp_path: Path):
        """Reading corrupted summary.json returns None."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        # Write invalid JSON
        with open(logs_dir / "summary.json", "w") as f:
            f.write("{ invalid json")

        indexer = TraceIndexer(tmp_path)
        summary = await indexer._read_summary(logs_dir)

        assert summary is None

    @pytest.mark.asyncio
    async def test_read_details_success(self, tmp_path: Path):
        """Reading valid details.jsonl returns list of NodeDetail."""
        session_dir = tmp_path / "sessions" / "session_test"
        create_session_logs(session_dir, run_id="run_123", agent_id="test_agent")

        indexer = TraceIndexer(tmp_path)
        details = await indexer._read_details(session_dir / "logs")

        assert details is not None
        assert len(details) == 3
        assert details[0].node_id == "intake"
        assert details[1].node_id == "process"
        assert details[2].node_id == "output"

    @pytest.mark.asyncio
    async def test_read_details_missing(self, tmp_path: Path):
        """Reading missing details.jsonl returns None."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        details = await indexer._read_details(logs_dir)

        assert details is None

    @pytest.mark.asyncio
    async def test_read_details_skips_corrupt_lines(self, tmp_path: Path):
        """Reading details.jsonl skips corrupt lines."""
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir(parents=True)

        with open(logs_dir / "details.jsonl", "w") as f:
            # Valid line
            f.write(
                json.dumps(
                    {
                        "node_id": "node1",
                        "success": True,
                        "total_steps": 1,
                    }
                )
                + "\n"
            )
            # Corrupt line
            f.write("{ invalid\n")
            # Another valid line
            f.write(
                json.dumps(
                    {
                        "node_id": "node2",
                        "success": True,
                        "total_steps": 2,
                    }
                )
                + "\n"
            )

        indexer = TraceIndexer(tmp_path)
        details = await indexer._read_details(logs_dir)

        assert details is not None
        assert len(details) == 2
        assert details[0].node_id == "node1"
        assert details[1].node_id == "node2"


class TestTraceIndexerIndexSession:
    """Test indexing a single session."""

    @pytest.mark.asyncio
    async def test_index_successful_session(self, tmp_path: Path):
        """Indexing successful session creates TraceIndex."""
        session_dir = tmp_path / "sessions" / "session_20260212_120000_abc"
        create_session_logs(
            session_dir,
            run_id="session_20260212_120000_abc",
            agent_id="test_agent",
            status="success",
        )

        indexer = TraceIndexer(tmp_path)
        trace = await indexer.index_session(session_dir)

        assert trace is not None
        assert trace.run_id == "session_20260212_120000_abc"
        assert trace.agent_id == "test_agent"
        assert trace.session_id == "session_20260212_120000_abc"
        assert trace.status == "success"
        assert trace.execution_quality == "clean"
        assert trace.total_latency_ms == 5000
        assert trace.total_input_tokens == 1000
        assert trace.total_output_tokens == 2000
        assert trace.node_count == 3
        assert trace.node_ids == ["intake", "process", "output"]
        assert trace.error_message is None
        assert trace.failed_node_id is None

    @pytest.mark.asyncio
    async def test_index_failed_session(self, tmp_path: Path):
        """Indexing failed session captures error information."""
        session_dir = tmp_path / "sessions" / "session_20260212_130000_def"
        create_session_logs(
            session_dir,
            run_id="session_20260212_130000_def",
            agent_id="test_agent",
            status="failure",
            with_error=True,
        )

        indexer = TraceIndexer(tmp_path)
        trace = await indexer.index_session(session_dir)

        assert trace is not None
        assert trace.status == "failure"
        assert trace.execution_quality == "degraded"
        assert trace.error_message == "Timeout in web_search"
        assert trace.failed_node_id == "process"

    @pytest.mark.asyncio
    async def test_index_session_no_logs(self, tmp_path: Path):
        """Indexing session without logs returns None."""
        session_dir = tmp_path / "sessions" / "session_empty"
        session_dir.mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        trace = await indexer.index_session(session_dir)

        assert trace is None

    @pytest.mark.asyncio
    async def test_index_session_no_summary(self, tmp_path: Path):
        """Indexing session without summary.json returns None."""
        session_dir = tmp_path / "sessions" / "session_incomplete"
        logs_dir = session_dir / "logs"
        logs_dir.mkdir(parents=True)

        # Create only details.jsonl (no summary)
        with open(logs_dir / "details.jsonl", "w") as f:
            f.write(json.dumps({"node_id": "test"}) + "\n")

        indexer = TraceIndexer(tmp_path)
        trace = await indexer.index_session(session_dir)

        assert trace is None

    @pytest.mark.asyncio
    async def test_index_session_paths(self, tmp_path: Path):
        """Indexed session contains correct file paths."""
        session_dir = tmp_path / "sessions" / "session_test"
        create_session_logs(session_dir, run_id="session_test", agent_id="test_agent")

        indexer = TraceIndexer(tmp_path)
        trace = await indexer.index_session(session_dir)

        assert trace is not None
        assert trace.summary_path.endswith("summary.json")
        assert trace.details_path.endswith("details.jsonl")
        assert trace.tool_logs_path.endswith("tool_logs.jsonl")


class TestTraceIndexerIndexAll:
    """Test indexing all sessions."""

    @pytest.mark.asyncio
    async def test_index_all_no_sessions(self, tmp_path: Path):
        """Indexing with no sessions returns zero counts."""
        indexer = TraceIndexer(tmp_path)
        store = IndexStore(base_path=tmp_path / "index")

        stats = await indexer.index_all_sessions(store)

        assert stats["indexed"] == 0
        assert stats["skipped"] == 0
        assert stats["errors"] == 0
        assert len(store.index) == 0

    @pytest.mark.asyncio
    async def test_index_all_single_session(self, tmp_path: Path):
        """Indexing single session populates store."""
        session_dir = tmp_path / "sessions" / "session_20260212_120000_abc"
        create_session_logs(
            session_dir, run_id="session_20260212_120000_abc", agent_id="test_agent"
        )

        indexer = TraceIndexer(tmp_path)
        store = IndexStore(base_path=tmp_path / "index")

        stats = await indexer.index_all_sessions(store)

        assert stats["indexed"] == 1
        assert stats["skipped"] == 0
        assert stats["errors"] == 0
        assert len(store.index) == 1
        assert "session_20260212_120000_abc" in store.index

    @pytest.mark.asyncio
    async def test_index_all_multiple_sessions(self, tmp_path: Path):
        """Indexing multiple sessions populates store with all."""
        sessions_dir = tmp_path / "sessions"

        # Create 3 sessions
        for i, session_id in enumerate(
            [
                "session_20260212_120000_abc",
                "session_20260212_130000_def",
                "session_20260212_140000_ghi",
            ]
        ):
            session_dir = sessions_dir / session_id
            create_session_logs(session_dir, run_id=session_id, agent_id=f"agent_{i}")

        indexer = TraceIndexer(tmp_path)
        store = IndexStore(base_path=tmp_path / "index")

        stats = await indexer.index_all_sessions(store)

        assert stats["indexed"] == 3
        assert stats["skipped"] == 0
        assert stats["errors"] == 0
        assert len(store.index) == 3

    @pytest.mark.asyncio
    async def test_index_all_mixed_sessions(self, tmp_path: Path):
        """Indexing mix of complete and incomplete sessions."""
        sessions_dir = tmp_path / "sessions"

        # Complete session
        create_session_logs(
            sessions_dir / "session_complete", run_id="session_complete", agent_id="test_agent"
        )

        # Incomplete session (no logs)
        (sessions_dir / "session_incomplete").mkdir(parents=True)

        # Empty session (no logs dir)
        (sessions_dir / "session_empty").mkdir(parents=True)

        indexer = TraceIndexer(tmp_path)
        store = IndexStore(base_path=tmp_path / "index")

        stats = await indexer.index_all_sessions(store)

        assert stats["indexed"] == 1
        assert stats["skipped"] == 2
        assert len(store.index) == 1

    @pytest.mark.asyncio
    async def test_index_all_handles_errors(self, tmp_path: Path):
        """Indexing continues after errors in individual sessions."""
        sessions_dir = tmp_path / "sessions"

        # Good session
        create_session_logs(
            sessions_dir / "session_good", run_id="session_good", agent_id="test_agent"
        )

        # Corrupted session (invalid JSON)
        corrupted_dir = sessions_dir / "session_corrupted"
        logs_dir = corrupted_dir / "logs"
        logs_dir.mkdir(parents=True)
        with open(logs_dir / "summary.json", "w") as f:
            f.write("{ invalid json")

        indexer = TraceIndexer(tmp_path)
        store = IndexStore(base_path=tmp_path / "index")

        stats = await indexer.index_all_sessions(store)

        # Good session indexed, corrupted skipped (no summary)
        assert stats["indexed"] == 1
        assert stats["skipped"] == 1


class TestTraceIndexerIntegration:
    """Integration tests for full indexing workflow."""

    @pytest.mark.asyncio
    async def test_full_indexing_workflow(self, tmp_path: Path):
        """Full workflow: index sessions, save, load, query."""
        sessions_dir = tmp_path / "agent" / "sessions"

        # Create multiple sessions
        create_session_logs(
            sessions_dir / "session_success_1",
            run_id="session_success_1",
            agent_id="sales_agent",
            status="success",
        )

        create_session_logs(
            sessions_dir / "session_failure_1",
            run_id="session_failure_1",
            agent_id="sales_agent",
            status="failure",
            with_error=True,
        )

        # Index sessions
        indexer = TraceIndexer(tmp_path / "agent")
        store = IndexStore(base_path=tmp_path / "agent")

        stats = await indexer.index_all_sessions(store)

        assert stats["indexed"] == 2

        # Save index
        await store.save()

        # Load in new store
        store2 = IndexStore(base_path=tmp_path / "agent")
        await store2.load()

        assert len(store2.index) == 2

        # Query by status
        success_traces = [t for t in store2.list_all() if t.status == "success"]
        assert len(success_traces) == 1

        failure_traces = [t for t in store2.list_all() if t.status == "failure"]
        assert len(failure_traces) == 1
        assert failure_traces[0].error_message == "Timeout in web_search"
