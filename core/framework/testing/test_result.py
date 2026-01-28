"""
Test result schemas for tracking test execution outcomes.

Results include detailed error information for debugging and
categorization for guiding iteration strategy.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ErrorCategory(str, Enum):
    """
    Category of test failure for guiding iteration.

    Each category has different implications for how to fix:
    - LOGIC_ERROR: Goal definition is wrong → update success_criteria/constraints
    - IMPLEMENTATION_ERROR: Code bug → fix nodes/edges in Agent stage
    - EDGE_CASE: New scenario discovered → add new test only
    """

    LOGIC_ERROR = "logic_error"
    IMPLEMENTATION_ERROR = "implementation_error"
    EDGE_CASE = "edge_case"


class TestResult(BaseModel):
    """
    Result of a single test execution.

    Captures:
    - Pass/fail status with timing
    - Actual vs expected output
    - Error details for debugging
    - Runtime logs and execution path
    """

    __test__ = False  # Not a pytest test class
    test_id: str
    passed: bool
    duration_ms: int = Field(ge=0, description="Test execution time in milliseconds")

    # Output comparison
    actual_output: Any = None
    expected_output: Any = None

    # Error details (populated on failure)
    error_message: str | None = None
    error_category: ErrorCategory | None = None
    stack_trace: str | None = None

    # Runtime data for debugging
    runtime_logs: list[dict[str, Any]] = Field(
        default_factory=list, description="Log entries from test execution"
    )
    node_outputs: dict[str, Any] = Field(
        default_factory=dict, description="Output from each node executed during test"
    )
    execution_path: list[str] = Field(
        default_factory=list, description="Sequence of nodes executed"
    )

    # Associated run ID (links to Runtime data)
    run_id: str | None = Field(default=None, description="Runtime run ID for detailed analysis")

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    def summary_dict(self) -> dict[str, Any]:
        """Return a summary dict for quick overview."""
        return {
            "test_id": self.test_id,
            "passed": self.passed,
            "duration_ms": self.duration_ms,
            "error_category": self.error_category.value if self.error_category else None,
            "error_message": self.error_message[:100] if self.error_message else None,
        }


class TestSuiteResult(BaseModel):
    """
    Aggregate result from running a test suite.

    Provides summary statistics and individual results.
    """

    __test__ = False  # Not a pytest test class
    goal_id: str
    total: int
    passed: int
    failed: int
    errors: int = 0  # Tests that couldn't run (e.g., exceptions in setup)
    skipped: int = 0

    results: list[TestResult] = Field(default_factory=list)

    duration_ms: int = Field(default=0, description="Total execution time in milliseconds")

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    @property
    def all_passed(self) -> bool:
        """Check if all tests passed."""
        return self.failed == 0 and self.errors == 0

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate."""
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    def summary_dict(self) -> dict[str, Any]:
        """Return summary for reporting."""
        return {
            "goal_id": self.goal_id,
            "overall_passed": self.all_passed,
            "summary": {
                "total": self.total,
                "passed": self.passed,
                "failed": self.failed,
                "errors": self.errors,
                "skipped": self.skipped,
            },
            "pass_rate": f"{self.pass_rate:.1%}",
            "duration_ms": self.duration_ms,
        }

    def get_failed_results(self) -> list[TestResult]:
        """Get all failed test results for debugging."""
        return [r for r in self.results if not r.passed]

    def get_results_by_category(self, category: ErrorCategory) -> list[TestResult]:
        """Get failed results by error category."""
        return [r for r in self.results if not r.passed and r.error_category == category]
