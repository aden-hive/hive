"""
Unit tests for the Execution Evidence model.

Tests cover:
- EvidenceType enum values
- ExecutionAttempt creation and properties
- Duration calculation
- Integration with NodeStepLog
- Evidence classification scenarios
"""

import pytest
from datetime import datetime, timedelta

from framework.runtime.evidence import ExecutionAttempt, EvidenceType
from framework.runtime.runtime_log_schemas import NodeStepLog


class TestEvidenceType:
    """Test EvidenceType enum."""

    def test_evidence_types_exist(self):
        """All evidence types should be defined."""
        assert EvidenceType.OBSERVED == "observed"
        assert EvidenceType.CONFIRMED == "confirmed"
        assert EvidenceType.ASSUMED == "assumed"
        assert EvidenceType.UNKNOWN == "unknown"

    def test_evidence_type_is_string_enum(self):
        """EvidenceType should be a string enum."""
        assert isinstance(EvidenceType.OBSERVED.value, str)
        assert isinstance(EvidenceType.CONFIRMED.value, str)


class TestExecutionAttempt:
    """Test ExecutionAttempt dataclass."""

    def test_create_minimal_attempt(self):
        """Should create attempt with minimal fields."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
        )

        assert attempt.attempt_id == "test_1"
        assert attempt.node_id == "test_node"
        assert attempt.step_index == 0
        assert attempt.evidence_type == EvidenceType.UNKNOWN
        assert attempt.finished_at is None

    def test_create_with_all_fields(self):
        """Should create attempt with all fields."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 1)

        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
            step_index=5,
            started_at=start,
            finished_at=end,
            observed_result="Success",
            evidence_type=EvidenceType.CONFIRMED,
            error=None,
            is_partial=False,
            retry_of="test_0",
        )

        assert attempt.step_index == 5
        assert attempt.observed_result == "Success"
        assert attempt.evidence_type == EvidenceType.CONFIRMED
        assert attempt.retry_of == "test_0"

    def test_duration_calculation(self):
        """Should calculate duration correctly."""
        start = datetime(2024, 1, 1, 12, 0, 0)
        end = datetime(2024, 1, 1, 12, 0, 1, 500000)  # 1.5 seconds later

        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
            started_at=start,
            finished_at=end,
        )

        assert attempt.duration_ms == 1500

    def test_duration_when_not_finished(self):
        """Should return 0 when execution not finished."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
        )

        assert attempt.duration_ms == 0

    def test_set_evidence_type(self):
        """Should allow setting evidence type."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
        )

        attempt.evidence_type = EvidenceType.CONFIRMED
        assert attempt.evidence_type == EvidenceType.CONFIRMED

        attempt.evidence_type = EvidenceType.OBSERVED
        assert attempt.evidence_type == EvidenceType.OBSERVED

    def test_track_retry_chain(self):
        """Should track retry relationships."""
        first_attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
        )

        retry_attempt = ExecutionAttempt(
            attempt_id="test_2",
            node_id="test_node",
            retry_of="test_1",
        )

        assert retry_attempt.retry_of == first_attempt.attempt_id

    def test_partial_failure_tracking(self):
        """Should track partial failures."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="test_node",
            is_partial=True,
            error="Validation failed",
        )

        assert attempt.is_partial is True
        assert attempt.error == "Validation failed"

    def test_observed_result_storage(self):
        """Should store observed results."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="api_node",
            observed_result="{'status': 200, 'data': {...}}",
        )

        assert "status" in attempt.observed_result
        assert "200" in attempt.observed_result


class TestNodeStepLogIntegration:
    """Test integration with NodeStepLog."""

    def test_add_execution_attempt_to_step_log(self):
        """Should attach execution attempt to step log."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="api_node",
            evidence_type=EvidenceType.CONFIRMED,
        )

        step_log = NodeStepLog(
            node_id="api_node",
            execution_attempt=attempt,
            evidence_quality="confirmed",
        )

        assert step_log.execution_attempt == attempt
        assert step_log.evidence_quality == "confirmed"

    def test_step_log_without_attempt(self):
        """Should work without execution attempt (backward compat)."""
        step_log = NodeStepLog(
            node_id="simple_node",
        )

        assert step_log.execution_attempt is None
        assert step_log.evidence_quality == "unknown"

    def test_step_log_with_existing_fields(self):
        """Should work alongside existing NodeStepLog fields."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="llm_node",
            evidence_type=EvidenceType.OBSERVED,
        )

        step_log = NodeStepLog(
            node_id="llm_node",
            node_type="llm_tool_use",
            step_index=0,
            llm_text="Generated response",
            input_tokens=100,
            output_tokens=50,
            latency_ms=1500,
            execution_attempt=attempt,
            evidence_quality="observed",
        )

        assert step_log.node_type == "llm_tool_use"
        assert step_log.input_tokens == 100
        assert step_log.execution_attempt.evidence_type == EvidenceType.OBSERVED


class TestEvidenceClassification:
    """Test evidence classification scenarios."""

    def test_classify_confirmed_success(self):
        """Successful execution with verification should be CONFIRMED."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="api_node",
        )

        # Simulate successful verified execution
        attempt.finished_at = datetime.now()
        attempt.observed_result = "Success: verified in database"
        attempt.evidence_type = EvidenceType.CONFIRMED

        assert attempt.evidence_type == EvidenceType.CONFIRMED
        assert attempt.observed_result is not None
        assert attempt.error is None

    def test_classify_observed_success(self):
        """Successful execution without verification should be OBSERVED."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="api_node",
        )

        # Simulate successful but unverified execution
        attempt.finished_at = datetime.now()
        attempt.observed_result = "200 OK"
        attempt.evidence_type = EvidenceType.OBSERVED

        assert attempt.evidence_type == EvidenceType.OBSERVED
        assert attempt.observed_result is not None

    def test_classify_timeout_assumed(self):
        """Timeout with likely success should be ASSUMED."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="slow_api",
        )

        # Simulate timeout
        attempt.finished_at = datetime.now()
        attempt.error = "Timeout after 30s"
        attempt.evidence_type = EvidenceType.ASSUMED

        assert attempt.evidence_type == EvidenceType.ASSUMED
        assert "Timeout" in attempt.error

    def test_classify_failure_unknown(self):
        """Failed execution should be UNKNOWN."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="api_node",
        )

        # Simulate failure
        attempt.finished_at = datetime.now()
        attempt.error = "Network error"
        attempt.evidence_type = EvidenceType.UNKNOWN

        assert attempt.evidence_type == EvidenceType.UNKNOWN
        assert attempt.error is not None

    def test_classify_partial_failure(self):
        """Partial failure should be tracked."""
        attempt = ExecutionAttempt(
            attempt_id="test_1",
            node_id="validation_node",
        )

        # Simulate partial failure
        attempt.finished_at = datetime.now()
        attempt.observed_result = "Partial data returned"
        attempt.evidence_type = EvidenceType.OBSERVED
        attempt.is_partial = True
        attempt.error = "Validation errors in fields: email, phone"

        assert attempt.is_partial is True
        assert attempt.evidence_type == EvidenceType.OBSERVED
        assert attempt.error is not None


class TestRetryScenarios:
    """Test retry tracking scenarios."""

    def test_first_attempt_no_retry(self):
        """First attempt should have no retry_of."""
        attempt = ExecutionAttempt(
            attempt_id="node_1_attempt_1",
            node_id="flaky_api",
        )

        assert attempt.retry_of is None

    def test_retry_chain(self):
        """Should track retry chain."""
        attempts = []

        for i in range(3):
            attempt = ExecutionAttempt(
                attempt_id=f"node_1_attempt_{i+1}",
                node_id="flaky_api",
                retry_of=f"node_1_attempt_{i}" if i > 0 else None,
            )
            attempts.append(attempt)

        assert attempts[0].retry_of is None
        assert attempts[1].retry_of == "node_1_attempt_1"
        assert attempts[2].retry_of == "node_1_attempt_2"

    def test_retry_with_different_evidence(self):
        """Retries may have different evidence types."""
        first = ExecutionAttempt(
            attempt_id="attempt_1",
            node_id="api",
            evidence_type=EvidenceType.UNKNOWN,
            error="Timeout",
        )

        retry = ExecutionAttempt(
            attempt_id="attempt_2",
            node_id="api",
            retry_of="attempt_1",
            evidence_type=EvidenceType.CONFIRMED,
            observed_result="Success",
        )

        assert first.evidence_type == EvidenceType.UNKNOWN
        assert retry.evidence_type == EvidenceType.CONFIRMED
        assert retry.retry_of == first.attempt_id
