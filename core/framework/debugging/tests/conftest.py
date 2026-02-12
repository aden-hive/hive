"""
Shared fixtures for debugging tests.

Follows Hive pattern: Fixtures in conftest.py for reuse
Reference: tools/tests/conftest.py
"""

from datetime import datetime

import pytest

from framework.debugging.trace_index import TraceIndex


@pytest.fixture
def sample_trace() -> TraceIndex:
    """Create a sample successful TraceIndex for testing."""
    return TraceIndex(
        run_id="test_run_abc123",
        agent_id="test_agent",
        session_id="session_20260212_120000_xyz",
        status="success",
        execution_quality="clean",
        total_latency_ms=1500,
        total_input_tokens=500,
        total_output_tokens=1000,
        node_count=3,
        timestamp=datetime(2026, 2, 12, 12, 0, 0),
        summary_path="/fake/path/summary.json",
        details_path="/fake/path/details.jsonl",
        tool_logs_path="/fake/path/tool_logs.jsonl",
        node_ids=["intake", "process", "output"],
    )


@pytest.fixture
def failed_trace() -> TraceIndex:
    """Create a sample failed TraceIndex for testing."""
    return TraceIndex(
        run_id="test_run_def456",
        agent_id="another_agent",
        session_id="session_20260212_130000_abc",
        status="failure",
        execution_quality="failed",
        total_latency_ms=3000,
        total_input_tokens=1000,
        total_output_tokens=500,
        node_count=5,
        error_message="Timeout in web_search",
        failed_node_id="research",
        timestamp=datetime(2026, 2, 12, 13, 0, 0),
        summary_path="/fake/path2/summary.json",
        details_path="/fake/path2/details.jsonl",
        tool_logs_path="/fake/path2/tool_logs.jsonl",
        node_ids=["intake", "research", "analyze", "review", "output"],
    )
