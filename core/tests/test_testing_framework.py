"""
Unit tests for the goal-based testing framework.

Tests cover:
- Schema validation
- Storage CRUD operations
- Error categorization heuristics
"""

import pytest

from framework.testing.categorizer import ErrorCategorizer
from framework.testing.debug_tool import DebugTool
from framework.testing.test_case import (
    ApprovalStatus,
    Test,
    TestType,
)
from framework.testing.test_result import (
    ErrorCategory,
    TestResult,
    TestSuiteResult,
)
from framework.testing.test_storage import TestStorage

# ============================================================================
# Test Schema Tests
# ============================================================================


class TestTestCaseSchema:
    """Tests for Test schema."""

    def test_create_test(self):
        """Test creating a basic test."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_api_limits",
            test_type=TestType.CONSTRAINT,
            test_name="test_constraint_api_limits",
            test_code="def test_constraint_api_limits(agent): pass",
            description="Tests API rate limits",
            input={"topic": "test"},
            expected_output={"count": 5},
        )

        assert test.id == "test_001"
        assert test.goal_id == "goal_001"
        assert test.test_type == TestType.CONSTRAINT
        assert test.approval_status == ApprovalStatus.PENDING
        assert not test.is_approved

    def test_approve_test(self):
        """Test approving a test."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_001",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="pass",
            description="test",
        )

        test.approve("test_user")

        assert test.approval_status == ApprovalStatus.APPROVED
        assert test.approved_by == "test_user"
        assert test.approved_at is not None
        assert test.is_approved

    def test_modify_test(self):
        """Test modifying a test before approval."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_001",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="original code",
            description="test",
        )

        test.modify("modified code", "test_user")

        assert test.approval_status == ApprovalStatus.MODIFIED
        assert test.original_code == "original code"
        assert test.test_code == "modified code"
        assert test.is_approved

    def test_reject_test(self):
        """Test rejecting a test."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_001",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="pass",
            description="test",
        )

        test.reject("Not a valid test case")

        assert test.approval_status == ApprovalStatus.REJECTED
        assert test.rejection_reason == "Not a valid test case"
        assert not test.is_approved

    def test_record_result(self):
        """Test recording test results."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_001",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="pass",
            description="test",
        )

        test.record_result(passed=True)
        assert test.last_result == "passed"
        assert test.run_count == 1
        assert test.pass_count == 1
        assert test.pass_rate == 1.0

        test.record_result(passed=False)
        assert test.last_result == "failed"
        assert test.run_count == 2
        assert test.pass_count == 1
        assert test.fail_count == 1
        assert test.pass_rate == 0.5


class TestTestResultSchema:
    """Tests for TestResult schema."""

    def test_create_passed_result(self):
        """Test creating a passed result."""
        result = TestResult(
            test_id="test_001",
            passed=True,
            duration_ms=100,
            actual_output={"status": "ok"},
            expected_output={"status": "ok"},
        )

        assert result.passed
        assert result.duration_ms == 100
        assert result.error_category is None

    def test_create_failed_result(self):
        """Test creating a failed result."""
        result = TestResult(
            test_id="test_001",
            passed=False,
            duration_ms=50,
            error_message="Assertion failed",
            error_category=ErrorCategory.IMPLEMENTATION_ERROR,
            stack_trace="Traceback...",
        )

        assert not result.passed
        assert result.error_category == ErrorCategory.IMPLEMENTATION_ERROR

    def test_summary_dict(self):
        """Test summary dict generation."""
        result = TestResult(
            test_id="test_001",
            passed=False,
            duration_ms=50,
            error_message="Very long error " * 20,
            error_category=ErrorCategory.LOGIC_ERROR,
        )

        summary = result.summary_dict()
        assert summary["test_id"] == "test_001"
        assert summary["passed"] is False
        assert summary["error_category"] == "logic_error"
        assert len(summary["error_message"]) == 100  # Truncated


class TestTestSuiteResult:
    """Tests for TestSuiteResult schema."""

    def test_suite_result_properties(self):
        """Test suite result calculation properties."""
        results = [
            TestResult(test_id="t1", passed=True, duration_ms=100),
            TestResult(test_id="t2", passed=True, duration_ms=50),
            TestResult(
                test_id="t3",
                passed=False,
                duration_ms=75,
                error_category=ErrorCategory.IMPLEMENTATION_ERROR,
            ),
        ]

        suite = TestSuiteResult(
            goal_id="goal_001",
            total=3,
            passed=2,
            failed=1,
            results=results,
            duration_ms=225,
        )

        assert not suite.all_passed
        assert suite.pass_rate == pytest.approx(2 / 3)
        assert len(suite.get_failed_results()) == 1

    def test_get_results_by_category(self):
        """Test filtering results by error category."""
        results = [
            TestResult(
                test_id="t1",
                passed=False,
                duration_ms=100,
                error_category=ErrorCategory.LOGIC_ERROR,
            ),
            TestResult(
                test_id="t2",
                passed=False,
                duration_ms=50,
                error_category=ErrorCategory.IMPLEMENTATION_ERROR,
            ),
            TestResult(
                test_id="t3",
                passed=False,
                duration_ms=75,
                error_category=ErrorCategory.IMPLEMENTATION_ERROR,
            ),
        ]

        suite = TestSuiteResult(
            goal_id="goal_001",
            total=3,
            passed=0,
            failed=3,
            results=results,
        )

        impl_errors = suite.get_results_by_category(ErrorCategory.IMPLEMENTATION_ERROR)
        assert len(impl_errors) == 2


# ============================================================================
# Storage Tests
# ============================================================================


class TestTestStorage:
    """Tests for TestStorage."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a temporary storage instance."""
        return TestStorage(tmp_path)

    def test_save_and_load_test(self, storage):
        """Test saving and loading a test."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_001",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="def test_something(agent): pass",
            description="A test",
        )

        storage.save_test(test)

        loaded = storage.load_test("goal_001", "test_001")
        assert loaded is not None
        assert loaded.id == "test_001"
        assert loaded.test_name == "test_something"

    def test_delete_test(self, storage):
        """Test deleting a test."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="constraint_001",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="pass",
            description="test",
        )

        storage.save_test(test)
        assert storage.load_test("goal_001", "test_001") is not None

        storage.delete_test("goal_001", "test_001")
        assert storage.load_test("goal_001", "test_001") is None

    def test_get_tests_by_goal(self, storage):
        """Test querying tests by goal."""
        for i in range(3):
            test = Test(
                id=f"test_{i}",
                goal_id="goal_001",
                parent_criteria_id=f"constraint_{i}",
                test_type=TestType.CONSTRAINT,
                test_name=f"test_{i}",
                test_code="pass",
                description="test",
            )
            storage.save_test(test)

        tests = storage.get_tests_by_goal("goal_001")
        assert len(tests) == 3

    def test_get_approved_tests(self, storage):
        """Test querying approved tests."""
        # Create tests with different approval statuses
        test1 = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="c1",
            test_type=TestType.CONSTRAINT,
            test_name="test_1",
            test_code="pass",
            description="test",
        )
        test1.approve()
        storage.save_test(test1)

        test2 = Test(
            id="test_002",
            goal_id="goal_001",
            parent_criteria_id="c2",
            test_type=TestType.CONSTRAINT,
            test_name="test_2",
            test_code="pass",
            description="test",
        )
        # Leave pending
        storage.save_test(test2)

        test3 = Test(
            id="test_003",
            goal_id="goal_001",
            parent_criteria_id="c3",
            test_type=TestType.CONSTRAINT,
            test_name="test_3",
            test_code="pass",
            description="test",
        )
        test3.modify("modified", "user")
        storage.save_test(test3)

        approved = storage.get_approved_tests("goal_001")
        assert len(approved) == 2  # approved and modified

    def test_save_and_load_result(self, storage):
        """Test saving and loading test results."""
        result = TestResult(
            test_id="test_001",
            passed=True,
            duration_ms=100,
        )

        storage.save_result("test_001", result)

        loaded = storage.get_latest_result("test_001")
        assert loaded is not None
        assert loaded.passed is True
        assert loaded.duration_ms == 100

    def test_result_history(self, storage):
        """Test getting result history."""
        # Save multiple results
        for i in range(5):
            result = TestResult(
                test_id="test_001",
                passed=(i % 2 == 0),
                duration_ms=100 + i,
            )
            storage.save_result("test_001", result)

        history = storage.get_result_history("test_001", limit=3)
        assert len(history) <= 3

    def test_get_stats(self, storage):
        """Test getting storage statistics."""
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="c1",
            test_type=TestType.CONSTRAINT,
            test_name="test_1",
            test_code="pass",
            description="test",
        )
        test.approve()
        storage.save_test(test)

        stats = storage.get_stats()
        assert stats["total_tests"] == 1
        assert stats["by_approval"]["approved"] == 1


# ============================================================================
# Error Categorizer Tests
# ============================================================================


class TestErrorCategorizer:
    """Tests for ErrorCategorizer."""

    @pytest.fixture
    def categorizer(self):
        return ErrorCategorizer()

    def test_categorize_passed(self, categorizer):
        """Test that passed results return None."""
        result = TestResult(test_id="t1", passed=True, duration_ms=100)
        assert categorizer.categorize(result) is None

    def test_categorize_logic_error(self, categorizer):
        """Test categorization of logic errors."""
        result = TestResult(
            test_id="t1",
            passed=False,
            duration_ms=100,
            error_message="goal not achieved: expected success criteria was not met",
        )
        assert categorizer.categorize(result) == ErrorCategory.LOGIC_ERROR

    def test_categorize_implementation_error(self, categorizer):
        """Test categorization of implementation errors."""
        result = TestResult(
            test_id="t1",
            passed=False,
            duration_ms=100,
            error_message="TypeError: 'NoneType' object has no attribute 'get'",
        )
        assert categorizer.categorize(result) == ErrorCategory.IMPLEMENTATION_ERROR

    def test_categorize_edge_case(self, categorizer):
        """Test categorization of edge cases."""
        result = TestResult(
            test_id="t1",
            passed=False,
            duration_ms=100,
            error_message="timeout: request took longer than expected",
        )
        assert categorizer.categorize(result) == ErrorCategory.EDGE_CASE

    def test_categorize_from_stack_trace(self, categorizer):
        """Test categorization from stack trace."""
        result = TestResult(
            test_id="t1",
            passed=False,
            duration_ms=100,
            error_message="Error occurred",
            stack_trace="KeyError: 'missing_key'\n  at line 42",
        )
        assert categorizer.categorize(result) == ErrorCategory.IMPLEMENTATION_ERROR

    def test_get_fix_suggestion(self, categorizer):
        """Test fix suggestions for each category."""
        assert "Goal" in categorizer.get_fix_suggestion(ErrorCategory.LOGIC_ERROR)
        assert "code" in categorizer.get_fix_suggestion(ErrorCategory.IMPLEMENTATION_ERROR).lower()
        assert "test" in categorizer.get_fix_suggestion(ErrorCategory.EDGE_CASE).lower()

    def test_get_iteration_guidance(self, categorizer):
        """Test iteration guidance."""
        guidance = categorizer.get_iteration_guidance(ErrorCategory.LOGIC_ERROR)
        assert guidance["stage"] == "Goal"
        assert guidance["restart_required"] is True

        guidance = categorizer.get_iteration_guidance(ErrorCategory.IMPLEMENTATION_ERROR)
        assert guidance["stage"] == "Agent"
        assert guidance["restart_required"] is False


# ============================================================================
# Debug Tool Tests
# ============================================================================


class TestDebugTool:
    """Tests for DebugTool."""

    @pytest.fixture
    def debug_tool(self, tmp_path):
        """Create a debug tool with temporary storage."""
        storage = TestStorage(tmp_path)
        return DebugTool(storage)

    def test_analyze_missing_test(self, debug_tool):
        """Test analyzing a non-existent test."""
        info = debug_tool.analyze("goal_001", "nonexistent")

        assert info.test_id == "nonexistent"
        assert "not found" in info.error_message.lower()

    def test_analyze_with_result(self, debug_tool, tmp_path):
        """Test analyzing a test with result."""
        storage = TestStorage(tmp_path)

        # Create and save test
        test = Test(
            id="test_001",
            goal_id="goal_001",
            parent_criteria_id="c1",
            test_type=TestType.CONSTRAINT,
            test_name="test_something",
            test_code="pass",
            description="A test",
            input={"key": "value"},
            expected_output={"result": "expected"},
        )
        storage.save_test(test)

        # Create and save result
        result = TestResult(
            test_id="test_001",
            passed=False,
            duration_ms=100,
            error_message="TypeError: something went wrong",
            error_category=ErrorCategory.IMPLEMENTATION_ERROR,
        )
        storage.save_result("test_001", result)

        # Create new debug tool with same storage
        debug_tool = DebugTool(storage)

        info = debug_tool.analyze("goal_001", "test_001")

        assert info.test_id == "test_001"
        assert info.test_name == "test_something"
        assert not info.passed
        assert info.error_category == "implementation_error"
        assert info.suggested_fix is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
