"""
Tests for Failure Recording Mechanism.

Tests the complete failure recording pipeline:
1. FailureRecord schema validation
2. FailureStorage operations (record, query, stats)
3. Runtime integration
4. CLI commands
"""

import json
import pytest
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

from framework.testing.failure_record import (
    FailureRecord,
    FailureSeverity,
    FailureSource,
    FailureStats,
)
from framework.testing.failure_storage import FailureStorage


# ============================================================================
# FailureRecord Schema Tests
# ============================================================================

class TestFailureRecordSchema:
    """Test FailureRecord Pydantic schema."""
    
    def test_create_minimal_failure_record(self):
        """Create failure record with minimal required fields."""
        record = FailureRecord(
            run_id="run_123",
            goal_id="goal_456",
            error_type="ValueError",
            error_message="Invalid input",
        )
        
        assert record.run_id == "run_123"
        assert record.goal_id == "goal_456"
        assert record.error_type == "ValueError"
        assert record.error_message == "Invalid input"
        assert record.id is not None  # Auto-generated
        assert record.severity == FailureSeverity.ERROR  # Default
        assert record.source == FailureSource.UNKNOWN  # Default
    
    def test_create_full_failure_record(self):
        """Create failure record with all fields."""
        record = FailureRecord(
            run_id="run_123",
            goal_id="goal_456",
            node_id="node_789",
            severity=FailureSeverity.CRITICAL,
            source=FailureSource.LLM_CALL,
            error_type="RateLimitError",
            error_message="API rate limit exceeded",
            stack_trace="Traceback (most recent call last):\n  ...",
            input_data={"prompt": "Hello"},
            memory_snapshot={"key": "value"},
            execution_path=["node_1:intent_1", "node_2:intent_2"],
            decisions_before_failure=[
                {"id": "dec_1", "intent": "Process input"}
            ],
            attempt_number=3,
            max_attempts=5,
            environment={"model": "gpt-4"},
            test_id="test_123",
        )
        
        assert record.severity == FailureSeverity.CRITICAL
        assert record.source == FailureSource.LLM_CALL
        assert record.node_id == "node_789"
        assert record.attempt_number == 3
        assert record.max_attempts == 5
        assert len(record.execution_path) == 2
    
    def test_failure_severity_enum(self):
        """Test FailureSeverity enum values."""
        assert FailureSeverity.CRITICAL.value == "critical"
        assert FailureSeverity.ERROR.value == "error"
        assert FailureSeverity.WARNING.value == "warning"
    
    def test_failure_source_enum(self):
        """Test FailureSource enum values."""
        assert FailureSource.NODE_EXECUTION.value == "node_execution"
        assert FailureSource.LLM_CALL.value == "llm_call"
        assert FailureSource.TOOL_EXECUTION.value == "tool_execution"
        assert FailureSource.VALIDATION.value == "validation"
    
    def test_failure_record_serialization(self):
        """Test JSON serialization of failure record."""
        record = FailureRecord(
            run_id="run_123",
            goal_id="goal_456",
            error_type="TypeError",
            error_message="Test error",
        )
        
        json_str = record.model_dump_json()
        data = json.loads(json_str)
        
        assert data["run_id"] == "run_123"
        assert data["goal_id"] == "goal_456"
        assert data["error_type"] == "TypeError"
        
        # Deserialize back
        restored = FailureRecord.model_validate_json(json_str)
        assert restored.run_id == record.run_id
        assert restored.id == record.id
    
    def test_failure_stats_schema(self):
        """Test FailureStats schema."""
        stats = FailureStats(
            goal_id="goal_123",
            total_failures=10,
            by_severity={"error": 7, "critical": 3},
            by_source={"llm_call": 5, "node_execution": 5},
            top_errors=[{"error_type": "ValueError", "count": 5}],
        )
        
        assert stats.total_failures == 10
        assert stats.by_severity["error"] == 7


# ============================================================================
# FailureStorage Tests
# ============================================================================

class TestFailureStorage:
    """Test FailureStorage operations."""
    
    @pytest.fixture
    def storage(self):
        """Create a temporary storage for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FailureStorage(tmpdir)
    
    @pytest.fixture
    def sample_failure(self):
        """Create a sample failure record."""
        return FailureRecord(
            run_id="run_test_123",
            goal_id="goal_test_456",
            node_id="node_test_789",
            severity=FailureSeverity.ERROR,
            source=FailureSource.LLM_CALL,
            error_type="TestError",
            error_message="This is a test error",
        )
    
    def test_record_failure(self, storage, sample_failure):
        """Test recording a failure."""
        failure_id = storage.record_failure(sample_failure)
        
        assert failure_id == sample_failure.id
        
        # Verify file was created
        failure_path = storage.base_path / "failures" / sample_failure.goal_id / f"{failure_id}.json"
        assert failure_path.exists()
    
    def test_get_failure(self, storage, sample_failure):
        """Test retrieving a failure by ID."""
        storage.record_failure(sample_failure)
        
        retrieved = storage.get_failure(sample_failure.goal_id, sample_failure.id)
        
        assert retrieved is not None
        assert retrieved.id == sample_failure.id
        assert retrieved.error_type == "TestError"
        assert retrieved.run_id == "run_test_123"
    
    def test_get_nonexistent_failure(self, storage):
        """Test getting a failure that doesn't exist."""
        result = storage.get_failure("no_goal", "no_failure")
        assert result is None
    
    def test_delete_failure(self, storage, sample_failure):
        """Test deleting a failure."""
        storage.record_failure(sample_failure)
        
        # Verify it exists
        assert storage.get_failure(sample_failure.goal_id, sample_failure.id) is not None
        
        # Delete
        result = storage.delete_failure(sample_failure.goal_id, sample_failure.id)
        assert result is True
        
        # Verify it's gone
        assert storage.get_failure(sample_failure.goal_id, sample_failure.id) is None
    
    def test_get_failures_by_goal(self, storage):
        """Test querying failures by goal."""
        goal_id = "test_goal"
        
        # Create multiple failures for same goal
        for i in range(5):
            failure = FailureRecord(
                run_id=f"run_{i}",
                goal_id=goal_id,
                error_type=f"Error{i}",
                error_message=f"Test error {i}",
            )
            storage.record_failure(failure)
        
        failures = storage.get_failures_by_goal(goal_id)
        
        assert len(failures) == 5
    
    def test_get_failures_by_goal_with_severity_filter(self, storage):
        """Test filtering failures by severity."""
        goal_id = "test_goal"
        
        # Create failures with different severities
        for severity in [FailureSeverity.ERROR, FailureSeverity.ERROR, FailureSeverity.CRITICAL]:
            failure = FailureRecord(
                run_id="run",
                goal_id=goal_id,
                severity=severity,
                error_type="Error",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        errors = storage.get_failures_by_goal(goal_id, severity=FailureSeverity.ERROR)
        critical = storage.get_failures_by_goal(goal_id, severity=FailureSeverity.CRITICAL)
        
        assert len(errors) == 2
        assert len(critical) == 1
    
    def test_get_failures_by_node(self, storage):
        """Test querying failures by node."""
        node_id = "test_node"
        
        # Create failures for same node in different goals
        for i in range(3):
            failure = FailureRecord(
                run_id=f"run_{i}",
                goal_id=f"goal_{i}",
                node_id=node_id,
                error_type="NodeError",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        failures = storage.get_failures_by_node(node_id)
        assert len(failures) == 3
    
    def test_get_failures_by_error_type(self, storage):
        """Test querying failures by error type."""
        error_type = "SpecialError"
        
        for i in range(4):
            failure = FailureRecord(
                run_id=f"run_{i}",
                goal_id=f"goal_{i}",
                error_type=error_type if i < 3 else "OtherError",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        failures = storage.get_failures_by_error_type(error_type)
        assert len(failures) == 3
    
    def test_get_failures_by_run(self, storage):
        """Test querying failures by run ID."""
        run_id = "specific_run"
        
        for i in range(3):
            failure = FailureRecord(
                run_id=run_id,
                goal_id=f"goal_{i}",
                error_type="Error",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        failures = storage.get_failures_by_run(run_id)
        assert len(failures) == 3
    
    def test_get_recent_failures(self, storage):
        """Test getting most recent failures."""
        # Create failures for multiple goals
        for i in range(10):
            failure = FailureRecord(
                run_id=f"run_{i}",
                goal_id=f"goal_{i % 3}",
                error_type="Error",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        recent = storage.get_recent_failures(limit=5)
        assert len(recent) == 5
    
    def test_get_failure_stats(self, storage):
        """Test failure statistics generation."""
        goal_id = "stats_test_goal"
        
        # Create varied failures
        failures = [
            FailureRecord(
                run_id="run_1",
                goal_id=goal_id,
                node_id="node_a",
                severity=FailureSeverity.ERROR,
                source=FailureSource.LLM_CALL,
                error_type="ValueError",
                error_message="Test 1",
            ),
            FailureRecord(
                run_id="run_2",
                goal_id=goal_id,
                node_id="node_a",
                severity=FailureSeverity.CRITICAL,
                source=FailureSource.LLM_CALL,
                error_type="ValueError",
                error_message="Test 2",
            ),
            FailureRecord(
                run_id="run_3",
                goal_id=goal_id,
                node_id="node_b",
                severity=FailureSeverity.ERROR,
                source=FailureSource.TOOL_EXECUTION,
                error_type="RuntimeError",
                error_message="Test 3",
            ),
        ]
        
        for f in failures:
            storage.record_failure(f)
        
        stats = storage.get_failure_stats(goal_id)
        
        assert stats.total_failures == 3
        assert stats.by_severity.get("error") == 2
        assert stats.by_severity.get("critical") == 1
        assert stats.by_node.get("node_a") == 2
        assert len(stats.top_errors) > 0
    
    def test_get_similar_failures(self, storage):
        """Test finding similar failures."""
        goal_id = "similarity_test"
        
        # Create similar failures
        target = FailureRecord(
            run_id="run_1",
            goal_id=goal_id,
            node_id="same_node",
            error_type="SameError",
            error_message="Original",
            input_data={"key1": "value1", "key2": "value2"},
        )
        
        similar1 = FailureRecord(
            run_id="run_2",
            goal_id=goal_id,
            node_id="same_node",
            error_type="SameError",
            error_message="Similar",
            input_data={"key1": "value1"},
        )
        
        different = FailureRecord(
            run_id="run_3",
            goal_id=goal_id,
            node_id="different_node",
            error_type="DifferentError",
            error_message="Different",
        )
        
        storage.record_failure(target)
        storage.record_failure(similar1)
        storage.record_failure(different)
        
        similar = storage.get_similar_failures(target.id, goal_id, limit=5)
        
        # Should find the similar failure but not itself
        assert len(similar) >= 1
        # The similar one should score higher
        if len(similar) >= 2:
            # First should be more similar
            assert similar[0].node_id == "same_node" or similar[0].error_type == "SameError"
    
    def test_list_all_goals(self, storage):
        """Test listing all goals with failures."""
        goals = ["goal_a", "goal_b", "goal_c"]
        
        for goal in goals:
            failure = FailureRecord(
                run_id="run",
                goal_id=goal,
                error_type="Error",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        listed = storage.list_all_goals()
        
        assert set(listed) == set(goals)
    
    def test_get_storage_stats(self, storage):
        """Test getting overall storage statistics."""
        # Create failures for multiple goals
        for i in range(5):
            failure = FailureRecord(
                run_id=f"run_{i}",
                goal_id=f"goal_{i % 2}",
                severity=FailureSeverity.ERROR if i % 2 == 0 else FailureSeverity.WARNING,
                error_type="Error",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        stats = storage.get_storage_stats()
        
        assert stats["total_goals"] == 2
        assert stats["total_failures"] == 5
        assert "by_severity" in stats
    
    def test_clear_all_failures(self, storage):
        """Test clearing all failures."""
        for i in range(5):
            failure = FailureRecord(
                run_id=f"run_{i}",
                goal_id=f"goal_{i % 2}",
                error_type="Error",
                error_message="Test",
            )
            storage.record_failure(failure)
        
        # Verify failures exist
        assert storage.get_storage_stats()["total_failures"] == 5
        
        # Clear all
        count = storage.clear_all()
        
        assert count == 5
        assert storage.get_storage_stats()["total_failures"] == 0
    
    def test_clear_failures_for_goal(self, storage):
        """Test clearing failures for a specific goal."""
        target_goal = "target_goal"
        
        # Create failures for multiple goals
        for i in range(3):
            storage.record_failure(FailureRecord(
                run_id=f"run_{i}",
                goal_id=target_goal,
                error_type="Error",
                error_message="Test",
            ))
        
        storage.record_failure(FailureRecord(
            run_id="run_other",
            goal_id="other_goal",
            error_type="Error",
            error_message="Test",
        ))
        
        # Clear only target goal
        count = storage.clear_all(goal_id=target_goal)
        
        assert count == 3
        assert len(storage.get_failures_by_goal(target_goal)) == 0
        assert len(storage.get_failures_by_goal("other_goal")) == 1
    
    def test_index_updates_on_record(self, storage, sample_failure):
        """Test that indexes are updated when recording failures."""
        storage.record_failure(sample_failure)
        
        # Check all indexes exist
        goal_index = storage._get_index("by_goal", sample_failure.goal_id)
        assert sample_failure.id in goal_index
        
        severity_index = storage._get_index("by_severity", sample_failure.severity.value)
        assert sample_failure.id in severity_index
        
        node_index = storage._get_index("by_node", sample_failure.node_id)
        assert sample_failure.id in node_index
    
    def test_index_updates_on_delete(self, storage, sample_failure):
        """Test that indexes are updated when deleting failures."""
        storage.record_failure(sample_failure)
        storage.delete_failure(sample_failure.goal_id, sample_failure.id)
        
        # Check all indexes are updated
        goal_index = storage._get_index("by_goal", sample_failure.goal_id)
        assert sample_failure.id not in goal_index
        
        severity_index = storage._get_index("by_severity", sample_failure.severity.value)
        assert sample_failure.id not in severity_index


# ============================================================================
# Runtime Integration Tests
# ============================================================================

class TestRuntimeIntegration:
    """Test failure recording integration with Runtime."""
    
    def test_runtime_has_failure_storage(self):
        """Test that Runtime initializes with FailureStorage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from framework.runtime.core import Runtime
            
            runtime = Runtime(tmpdir)
            
            assert hasattr(runtime, 'failure_storage')
            assert isinstance(runtime.failure_storage, FailureStorage)
    
    def test_runtime_record_failure(self):
        """Test recording failure through Runtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from framework.runtime.core import Runtime
            
            runtime = Runtime(tmpdir)
            
            # Start a run first
            runtime.start_run("test_goal", "Test goal description")
            
            # Record a failure
            error = ValueError("Test error message")
            failure_id = runtime.record_failure(
                exception=error,
                source=FailureSource.VALIDATION,
                severity=FailureSeverity.ERROR,
                node_id="test_node",
                input_data={"key": "value"},
            )
            
            assert failure_id is not None
            
            # Verify failure was stored
            failure = runtime.failure_storage.get_failure("test_goal", failure_id)
            assert failure is not None
            assert failure.error_type == "ValueError"
            assert failure.error_message == "Test error message"
    
    def test_runtime_record_failure_no_run(self):
        """Test that record_failure handles no active run gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from framework.runtime.core import Runtime
            
            runtime = Runtime(tmpdir)
            
            # Don't start a run
            error = ValueError("Test error")
            failure_id = runtime.record_failure(exception=error)
            
            # Should return None when no run
            assert failure_id is None
    
    def test_runtime_captures_execution_path(self):
        """Test that failure captures execution path from decisions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from framework.runtime.core import Runtime
            
            runtime = Runtime(tmpdir)
            runtime.start_run("test_goal", "Test")
            
            # Make some decisions
            runtime.decide(
                intent="Process input",
                options=[{"id": "opt1", "description": "Option 1"}],
                chosen="opt1",
                reasoning="Test",
                node_id="node_1",
            )
            runtime.decide(
                intent="Generate output",
                options=[{"id": "opt2", "description": "Option 2"}],
                chosen="opt2",
                reasoning="Test",
                node_id="node_2",
            )
            
            # Record failure
            error = RuntimeError("Failure!")
            failure_id = runtime.record_failure(exception=error)
            
            # Check execution path was captured
            failure = runtime.failure_storage.get_failure("test_goal", failure_id)
            assert len(failure.execution_path) == 2
            assert "node_1:Process input" in failure.execution_path
    
    def test_runtime_get_failure_stats(self):
        """Test getting failure stats through Runtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from framework.runtime.core import Runtime
            
            runtime = Runtime(tmpdir)
            runtime.start_run("test_goal", "Test")
            
            # Record some failures
            for i in range(3):
                runtime.record_failure(
                    exception=ValueError(f"Error {i}"),
                    severity=FailureSeverity.ERROR,
                )
            
            # Get stats
            stats = runtime.get_failure_stats("test_goal")
            
            assert stats["total_failures"] == 3
    
    def test_runtime_get_storage_stats(self):
        """Test getting storage stats through Runtime."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from framework.runtime.core import Runtime
            
            runtime = Runtime(tmpdir)
            runtime.start_run("goal_1", "Test 1")
            runtime.record_failure(exception=ValueError("Error"))
            runtime.end_run(success=False)
            
            runtime.start_run("goal_2", "Test 2")
            runtime.record_failure(exception=ValueError("Error"))
            runtime.end_run(success=False)
            
            stats = runtime.get_failure_stats()  # No goal_id = storage stats
            
            assert stats["total_goals"] == 2
            assert stats["total_failures"] == 2


# ============================================================================
# Edge Cases and Error Handling
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_long_error_message(self):
        """Test handling very long error messages."""
        long_message = "x" * 10000
        
        record = FailureRecord(
            run_id="run",
            goal_id="goal",
            error_type="Error",
            error_message=long_message,
        )
        
        assert len(record.error_message) == 10000
    
    def test_special_characters_in_error_type(self):
        """Test error types with special characters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FailureStorage(tmpdir)
            
            failure = FailureRecord(
                run_id="run",
                goal_id="goal",
                error_type="module/submodule:SpecialError<T>",
                error_message="Test",
            )
            
            storage.record_failure(failure)
            
            # Should sanitize for filename
            failures = storage.get_failures_by_error_type("module/submodule:SpecialError<T>")
            assert len(failures) == 1
    
    def test_concurrent_failure_recording(self):
        """Test that multiple failures can be recorded quickly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = FailureStorage(tmpdir)
            
            # Record many failures quickly
            for i in range(50):
                failure = FailureRecord(
                    run_id=f"run_{i}",
                    goal_id="concurrent_goal",
                    error_type="Error",
                    error_message=f"Test {i}",
                )
                storage.record_failure(failure)
            
            # All should be stored
            failures = storage.get_failures_by_goal("concurrent_goal", limit=100)
            assert len(failures) == 50
    
    def test_empty_input_data(self):
        """Test failure with empty input data."""
        record = FailureRecord(
            run_id="run",
            goal_id="goal",
            error_type="Error",
            error_message="Test",
            input_data={},
        )
        
        assert record.input_data == {}
    
    def test_nested_input_data(self):
        """Test failure with nested input data."""
        nested_data = {
            "level1": {
                "level2": {
                    "level3": [1, 2, 3],
                },
            },
            "list": [{"a": 1}, {"b": 2}],
        }
        
        record = FailureRecord(
            run_id="run",
            goal_id="goal",
            error_type="Error",
            error_message="Test",
            input_data=nested_data,
        )
        
        # Should serialize and deserialize correctly
        json_str = record.model_dump_json()
        restored = FailureRecord.model_validate_json(json_str)
        
        assert restored.input_data["level1"]["level2"]["level3"] == [1, 2, 3]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
