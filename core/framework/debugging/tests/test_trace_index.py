"""
Tests for TraceIndex schema.

Follows Hive patterns:
- pytest framework with descriptive test names
- Test classes grouping related tests
- Docstrings explaining test behavior
- Pydantic model validation testing

Reference: core/tests/test_llm_judge.py
"""

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from framework.debugging.trace_index import TraceIndex


class TestTraceIndexCreation:
    """Test TraceIndex model creation and validation."""

    def test_create_minimal_trace_index(self):
        """Minimal required fields creates valid TraceIndex."""
        trace = TraceIndex(
            run_id="test_run_123",
            agent_id="test_agent",
            session_id="session_20260212_120000_abc",
            status="success",
            summary_path="/fake/path/summary.json",
            details_path="/fake/path/details.jsonl",
            tool_logs_path="/fake/path/tool_logs.jsonl",
        )

        assert trace.run_id == "test_run_123"
        assert trace.agent_id == "test_agent"
        assert trace.status == "success"
        assert trace.total_latency_ms == 0
        assert trace.total_input_tokens == 0
        assert trace.node_ids == []

    def test_create_full_trace_index(self):
        """All fields can be set and are preserved."""
        trace = TraceIndex(
            run_id="test_run_456",
            agent_id="sales_agent",
            session_id="session_20260212_130000_def",
            status="failure",
            execution_quality="degraded",
            total_latency_ms=5000,
            total_input_tokens=1000,
            total_output_tokens=2000,
            node_count=5,
            error_message="Timeout in web_search",
            failed_node_id="research",
            timestamp=datetime(2026, 2, 12, 13, 0, 0),
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
            node_ids=["intake", "research", "analyze", "output"],
        )

        assert trace.run_id == "test_run_456"
        assert trace.status == "failure"
        assert trace.execution_quality == "degraded"
        assert trace.total_latency_ms == 5000
        assert trace.error_message == "Timeout in web_search"
        assert trace.failed_node_id == "research"
        assert len(trace.node_ids) == 4

    def test_timestamp_defaults_to_now(self):
        """Timestamp defaults to current time when not provided."""
        before = datetime.now()
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )
        after = datetime.now()

        assert before <= trace.timestamp <= after


class TestTraceIndexComputedFields:
    """Test computed properties follow Pydantic patterns."""

    def test_total_tokens_computed(self):
        """total_tokens sums input and output tokens."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            total_input_tokens=500,
            total_output_tokens=1500,
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        assert trace.total_tokens == 2000

    def test_total_tokens_with_zero_values(self):
        """total_tokens returns 0 when no tokens used."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        assert trace.total_tokens == 0

    def test_success_rate_for_success(self):
        """success_rate returns 1.0 for successful runs."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            node_count=5,
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        assert trace.success_rate == 1.0

    def test_success_rate_for_failure(self):
        """success_rate returns 0.0 for failed runs."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="failure",
            node_count=5,
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        assert trace.success_rate == 0.0

    def test_success_rate_with_zero_nodes(self):
        """success_rate returns 0.0 when node_count is 0."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            node_count=0,
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        assert trace.success_rate == 0.0


class TestTraceIndexSerialization:
    """Test JSON serialization/deserialization patterns."""

    def test_model_dump_json(self):
        """model_dump_json() produces valid JSON string."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            total_latency_ms=1000,
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        json_str = trace.model_dump_json()
        data = json.loads(json_str)

        assert data["run_id"] == "test_run"
        assert data["agent_id"] == "agent"
        assert data["status"] == "success"
        assert data["total_latency_ms"] == 1000

    def test_model_validate_from_dict(self):
        """TraceIndex can be created from dict (deserialization)."""
        data = {
            "run_id": "test_run",
            "agent_id": "agent",
            "session_id": "session",
            "status": "failure",
            "total_latency_ms": 2000,
            "total_input_tokens": 100,
            "total_output_tokens": 200,
            "summary_path": "/path/summary.json",
            "details_path": "/path/details.jsonl",
            "tool_logs_path": "/path/tool_logs.jsonl",
            "timestamp": "2026-02-12T13:00:00",
        }

        trace = TraceIndex.model_validate(data)

        assert trace.run_id == "test_run"
        assert trace.status == "failure"
        assert trace.total_latency_ms == 2000
        assert trace.total_tokens == 300

    def test_round_trip_serialization(self):
        """Serialize then deserialize preserves all data."""
        original = TraceIndex(
            run_id="test_run_789",
            agent_id="complex_agent",
            session_id="session_xyz",
            status="degraded",
            execution_quality="degraded",
            total_latency_ms=3500,
            total_input_tokens=1500,
            total_output_tokens=2500,
            node_count=7,
            error_message="Partial failure",
            failed_node_id="node_3",
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
            node_ids=["n1", "n2", "n3", "n4"],
        )

        json_str = original.model_dump_json()
        restored = TraceIndex.model_validate_json(json_str)

        assert restored.run_id == original.run_id
        assert restored.agent_id == original.agent_id
        assert restored.status == original.status
        assert restored.total_latency_ms == original.total_latency_ms
        assert restored.total_tokens == original.total_tokens
        assert restored.node_ids == original.node_ids

    def test_path_serialization(self):
        """Path strings remain as strings in serialized form."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            summary_path="/path/to/summary.json",
            details_path="/path/to/details.jsonl",
            tool_logs_path="/path/to/tool_logs.jsonl",
        )

        data = trace.model_dump()

        assert isinstance(data["summary_path"], str)
        assert isinstance(data["details_path"], str)
        assert isinstance(data["tool_logs_path"], str)


class TestTraceIndexValidation:
    """Test Pydantic validation behavior."""

    def test_missing_required_field_raises_error(self):
        """Missing required field raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TraceIndex(
                # Missing run_id
                agent_id="agent",
                session_id="session",
                status="success",
                summary_path="/path/summary.json",
                details_path="/path/details.jsonl",
                tool_logs_path="/path/tool_logs.jsonl",
            )

        assert "run_id" in str(exc_info.value)

    def test_invalid_type_raises_error(self):
        """Invalid field type raises ValidationError."""
        with pytest.raises(ValidationError):
            TraceIndex(
                run_id="test_run",
                agent_id="agent",
                session_id="session",
                status="success",
                total_latency_ms="not_an_int",  # Should be int
                summary_path="/path/summary.json",
                details_path="/path/details.jsonl",
                tool_logs_path="/path/tool_logs.jsonl",
            )

    def test_none_for_optional_fields(self):
        """None values work for optional fields."""
        trace = TraceIndex(
            run_id="test_run",
            agent_id="agent",
            session_id="session",
            status="success",
            error_message=None,
            failed_node_id=None,
            summary_path="/path/summary.json",
            details_path="/path/details.jsonl",
            tool_logs_path="/path/tool_logs.jsonl",
        )

        assert trace.error_message is None
        assert trace.failed_node_id is None
