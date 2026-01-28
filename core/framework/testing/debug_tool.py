"""
Debug tool for analyzing failed tests.

Provides detailed information for debugging:
- Test input and expected output
- Actual output and error details
- Error categorization
- Runtime logs and execution path
- Fix suggestions
"""

from typing import Any

from pydantic import BaseModel, Field

from framework.testing.categorizer import ErrorCategorizer
from framework.testing.test_case import Test
from framework.testing.test_result import ErrorCategory, TestResult
from framework.testing.test_storage import TestStorage


class DebugInfo(BaseModel):
    """
    Comprehensive debug information for a failed test.
    """

    test_id: str
    test_name: str

    # Test definition
    input: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)

    # Actual result
    actual: Any = None
    passed: bool = False

    # Error details
    error_message: str | None = None
    error_category: str | None = None
    stack_trace: str | None = None

    # Runtime data
    logs: list[dict[str, Any]] = Field(default_factory=list)
    runtime_data: dict[str, Any] = Field(default_factory=dict)

    # Fix guidance
    suggested_fix: str | None = None
    iteration_guidance: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON serialization."""
        return self.model_dump()


class DebugTool:
    """
    Debug tool for analyzing failed tests.

    Integrates with:
    - TestStorage for test and result data
    - Runtime storage (optional) for decision logs
    - ErrorCategorizer for classification
    """

    def __init__(
        self,
        test_storage: TestStorage,
        runtime_storage: Any | None = None,
    ):
        """
        Initialize debug tool.

        Args:
            test_storage: Storage for test and result data
            runtime_storage: Optional FileStorage for Runtime data
        """
        self.test_storage = test_storage
        self.runtime_storage = runtime_storage
        self.categorizer = ErrorCategorizer()

    def analyze(
        self,
        goal_id: str,
        test_id: str,
        run_id: str | None = None,
    ) -> DebugInfo:
        """
        Get detailed debug info for a failed test.

        Args:
            goal_id: Goal ID containing the test
            test_id: ID of the test to analyze
            run_id: Optional Runtime run ID for detailed logs

        Returns:
            DebugInfo with comprehensive debug data
        """
        # Load test
        test = self.test_storage.load_test(goal_id, test_id)
        if not test:
            return DebugInfo(
                test_id=test_id,
                test_name="unknown",
                error_message=f"Test {test_id} not found in goal {goal_id}",
            )

        # Load latest result
        result = self.test_storage.get_latest_result(test_id)

        # Build debug info
        debug_info = DebugInfo(
            test_id=test_id,
            test_name=test.test_name,
            input=test.input,
            expected=test.expected_output,
        )

        if result:
            debug_info.actual = result.actual_output
            debug_info.passed = result.passed
            debug_info.error_message = result.error_message
            debug_info.stack_trace = result.stack_trace
            debug_info.logs = result.runtime_logs

            # Set category
            if result.error_category:
                debug_info.error_category = result.error_category.value
            elif not result.passed:
                # Categorize if not already done
                category = self.categorizer.categorize(result)
                if category:
                    debug_info.error_category = category.value

        # Get runtime data if available
        if run_id and self.runtime_storage:
            debug_info.runtime_data = self._get_runtime_data(run_id)

        # Generate fix suggestions
        if debug_info.error_category:
            category = ErrorCategory(debug_info.error_category)
            debug_info.suggested_fix = self.categorizer.get_fix_suggestion(category)
            debug_info.iteration_guidance = self.categorizer.get_iteration_guidance(category)

        return debug_info

    def analyze_result(
        self,
        test: Test,
        result: TestResult,
        run_id: str | None = None,
    ) -> DebugInfo:
        """
        Analyze a test result directly (without loading from storage).

        Args:
            test: The Test that was run
            result: The TestResult to analyze
            run_id: Optional Runtime run ID

        Returns:
            DebugInfo with debug data
        """
        debug_info = DebugInfo(
            test_id=test.id,
            test_name=test.test_name,
            input=test.input,
            expected=test.expected_output,
            actual=result.actual_output,
            passed=result.passed,
            error_message=result.error_message,
            stack_trace=result.stack_trace,
            logs=result.runtime_logs,
        )

        # Categorize
        if result.error_category:
            debug_info.error_category = result.error_category.value
        elif not result.passed:
            category = self.categorizer.categorize(result)
            if category:
                debug_info.error_category = category.value

        # Runtime data
        if run_id and self.runtime_storage:
            debug_info.runtime_data = self._get_runtime_data(run_id)

        # Fix suggestions
        if debug_info.error_category:
            category = ErrorCategory(debug_info.error_category)
            debug_info.suggested_fix = self.categorizer.get_fix_suggestion(category)
            debug_info.iteration_guidance = self.categorizer.get_iteration_guidance(category)

        return debug_info

    def get_failure_summary(
        self,
        goal_id: str,
    ) -> dict[str, Any]:
        """
        Get summary of all failures for a goal.

        Returns:
            Dict with failure counts by category and test IDs
        """
        tests = self.test_storage.get_tests_by_goal(goal_id)

        failures_by_category: dict[str, list[str]] = {
            "logic_error": [],
            "implementation_error": [],
            "edge_case": [],
            "uncategorized": [],
        }

        for test in tests:
            if test.last_result == "failed":
                result = self.test_storage.get_latest_result(test.id)
                if result and result.error_category:
                    failures_by_category[result.error_category.value].append(test.id)
                else:
                    failures_by_category["uncategorized"].append(test.id)

        return {
            "goal_id": goal_id,
            "total_failures": sum(len(ids) for ids in failures_by_category.values()),
            "by_category": failures_by_category,
            "iteration_suggestions": self._get_iteration_suggestions(failures_by_category),
        }

    def _get_runtime_data(self, run_id: str) -> dict[str, Any]:
        """Extract runtime data from Runtime storage."""
        if not self.runtime_storage:
            return {}

        try:
            run = self.runtime_storage.load_run(run_id)
            if not run:
                return {"error": f"Run {run_id} not found"}

            return {
                "execution_path": run.metrics.nodes_executed if hasattr(run, "metrics") else [],
                "decisions": [
                    d.model_dump() if hasattr(d, "model_dump") else str(d)
                    for d in getattr(run, "decisions", [])
                ],
                "problems": [
                    p.model_dump() if hasattr(p, "model_dump") else str(p)
                    for p in getattr(run, "problems", [])
                ],
                "status": run.status.value if hasattr(run, "status") else "unknown",
            }
        except Exception as e:
            return {"error": f"Failed to load runtime data: {e}"}

    def _get_iteration_suggestions(
        self,
        failures_by_category: dict[str, list[str]],
    ) -> list[str]:
        """Generate iteration suggestions based on failure categories."""
        suggestions = []

        if failures_by_category["logic_error"]:
            suggestions.append(
                f"Found {len(failures_by_category['logic_error'])} logic errors. "
                "Review and update Goal success_criteria/constraints, then restart "
                "the full Goal → Agent → Eval flow."
            )

        if failures_by_category["implementation_error"]:
            suggestions.append(
                f"Found {len(failures_by_category['implementation_error'])} implementation errors. "
                "Fix agent node/edge code and re-run Eval."
            )

        if failures_by_category["edge_case"]:
            suggestions.append(
                f"Found {len(failures_by_category['edge_case'])} edge cases. "
                "These are new scenarios - add tests for them."
            )

        if failures_by_category["uncategorized"]:
            suggestions.append(
                f"Found {len(failures_by_category['uncategorized'])} uncategorized failures. "
                "Manual review required."
            )

        return suggestions
