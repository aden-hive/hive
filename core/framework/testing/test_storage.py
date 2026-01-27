"""
File-based storage backend for test data.

Follows the same pattern as framework/storage/backend.py (FileStorage),
storing tests as JSON files with indexes for efficient querying.
"""

import json
from datetime import datetime
from pathlib import Path

from framework.testing.test_case import ApprovalStatus, Test, TestType
from framework.testing.test_result import TestResult


class TestStorage:
    """
    File-based storage for tests and results.

    Directory structure:
    {base_path}/
      tests/
        {goal_id}/
          {test_id}.json           # Full test data
      indexes/
        by_goal/{goal_id}.json     # List of test IDs for this goal
        by_approval/{status}.json  # Tests by approval status
        by_type/{test_type}.json   # Tests by type
        by_criteria/{criteria_id}.json  # Tests by parent criteria
      results/
        {test_id}/
          {timestamp}.json         # Test run results
          latest.json              # Most recent result
      suites/
        {goal_id}_suite.json       # Test suite metadata
    """

    __test__ = False  # Not a pytest test class

    def __init__(self, base_path: str | Path):
        self.base_path = Path(base_path)
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create directory structure if it doesn't exist."""
        dirs = [
            self.base_path / "tests",
            self.base_path / "indexes" / "by_goal",
            self.base_path / "indexes" / "by_approval",
            self.base_path / "indexes" / "by_type",
            self.base_path / "indexes" / "by_criteria",
            self.base_path / "results",
            self.base_path / "suites",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    # === TEST OPERATIONS ===

    def save_test(self, test: Test) -> None:
        """Save a test to storage."""
        # Ensure goal directory exists
        goal_dir = self.base_path / "tests" / test.goal_id
        goal_dir.mkdir(parents=True, exist_ok=True)

        # Save full test
        test_path = goal_dir / f"{test.id}.json"
        with open(test_path, "w") as f:
            f.write(test.model_dump_json(indent=2))

        # Update indexes
        self._add_to_index("by_goal", test.goal_id, test.id)
        self._add_to_index("by_approval", test.approval_status.value, test.id)
        self._add_to_index("by_type", test.test_type.value, test.id)
        self._add_to_index("by_criteria", test.parent_criteria_id, test.id)

    def load_test(self, goal_id: str, test_id: str) -> Test | None:
        """Load a test from storage."""
        test_path = self.base_path / "tests" / goal_id / f"{test_id}.json"
        if not test_path.exists():
            return None
        with open(test_path) as f:
            return Test.model_validate_json(f.read())

    def delete_test(self, goal_id: str, test_id: str) -> bool:
        """Delete a test from storage."""
        test_path = self.base_path / "tests" / goal_id / f"{test_id}.json"

        if not test_path.exists():
            return False

        # Load test to get index keys
        test = self.load_test(goal_id, test_id)
        if test:
            self._remove_from_index("by_goal", test.goal_id, test_id)
            self._remove_from_index("by_approval", test.approval_status.value, test_id)
            self._remove_from_index("by_type", test.test_type.value, test_id)
            self._remove_from_index("by_criteria", test.parent_criteria_id, test_id)

        test_path.unlink()

        # Also delete results
        results_dir = self.base_path / "results" / test_id
        if results_dir.exists():
            for f in results_dir.iterdir():
                f.unlink()
            results_dir.rmdir()

        return True

    def update_test(self, test: Test) -> None:
        """
        Update an existing test.

        Handles index updates if approval_status changed.
        """
        # Load old test to check for index changes
        old_test = self.load_test(test.goal_id, test.id)
        if old_test and old_test.approval_status != test.approval_status:
            self._remove_from_index("by_approval", old_test.approval_status.value, test.id)
            self._add_to_index("by_approval", test.approval_status.value, test.id)

        # Update timestamp
        test.updated_at = datetime.now()

        # Save
        self.save_test(test)

    # === QUERY OPERATIONS ===

    def get_tests_by_goal(self, goal_id: str) -> list[Test]:
        """Get all tests for a goal."""
        test_ids = self._get_index("by_goal", goal_id)
        tests = []
        for test_id in test_ids:
            test = self.load_test(goal_id, test_id)
            if test:
                tests.append(test)
        return tests

    def get_tests_by_approval_status(self, status: ApprovalStatus) -> list[str]:
        """Get test IDs by approval status."""
        return self._get_index("by_approval", status.value)

    def get_tests_by_type(self, test_type: TestType) -> list[str]:
        """Get test IDs by test type."""
        return self._get_index("by_type", test_type.value)

    def get_tests_by_criteria(self, criteria_id: str) -> list[str]:
        """Get test IDs for a specific criteria."""
        return self._get_index("by_criteria", criteria_id)

    def get_pending_tests(self, goal_id: str) -> list[Test]:
        """Get all pending tests for a goal."""
        tests = self.get_tests_by_goal(goal_id)
        return [t for t in tests if t.approval_status == ApprovalStatus.PENDING]

    def get_approved_tests(self, goal_id: str) -> list[Test]:
        """Get all approved tests for a goal (approved or modified)."""
        tests = self.get_tests_by_goal(goal_id)
        return [t for t in tests if t.is_approved]

    def list_all_goals(self) -> list[str]:
        """List all goal IDs that have tests."""
        goals_dir = self.base_path / "indexes" / "by_goal"
        return [f.stem for f in goals_dir.glob("*.json")]

    # === RESULT OPERATIONS ===

    def save_result(self, test_id: str, result: TestResult) -> None:
        """Save a test result."""
        results_dir = self.base_path / "results" / test_id
        results_dir.mkdir(parents=True, exist_ok=True)

        # Save with timestamp
        timestamp = result.timestamp.strftime("%Y%m%d_%H%M%S")
        result_path = results_dir / f"{timestamp}.json"
        with open(result_path, "w") as f:
            f.write(result.model_dump_json(indent=2))

        # Update latest
        latest_path = results_dir / "latest.json"
        with open(latest_path, "w") as f:
            f.write(result.model_dump_json(indent=2))

    def get_latest_result(self, test_id: str) -> TestResult | None:
        """Get the most recent result for a test."""
        latest_path = self.base_path / "results" / test_id / "latest.json"
        if not latest_path.exists():
            return None
        with open(latest_path) as f:
            return TestResult.model_validate_json(f.read())

    def get_result_history(self, test_id: str, limit: int = 10) -> list[TestResult]:
        """Get result history for a test, most recent first."""
        results_dir = self.base_path / "results" / test_id
        if not results_dir.exists():
            return []

        # Get all result files except latest.json
        result_files = sorted(
            [f for f in results_dir.glob("*.json") if f.name != "latest.json"], reverse=True
        )[:limit]

        results = []
        for f in result_files:
            with open(f) as file:
                results.append(TestResult.model_validate_json(file.read()))

        return results

    # === INDEX OPERATIONS ===

    def _get_index(self, index_type: str, key: str) -> list[str]:
        """Get values from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        if not index_path.exists():
            return []
        with open(index_path) as f:
            return json.load(f)

    def _add_to_index(self, index_type: str, key: str, value: str) -> None:
        """Add a value to an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        values = self._get_index(index_type, key)
        if value not in values:
            values.append(value)
            with open(index_path, "w") as f:
                json.dump(values, f)

    def _remove_from_index(self, index_type: str, key: str, value: str) -> None:
        """Remove a value from an index."""
        index_path = self.base_path / "indexes" / index_type / f"{key}.json"
        values = self._get_index(index_type, key)
        if value in values:
            values.remove(value)
            with open(index_path, "w") as f:
                json.dump(values, f)

    # === UTILITY ===

    def get_stats(self) -> dict:
        """Get storage statistics."""
        goals = self.list_all_goals()
        total_tests = sum(len(self._get_index("by_goal", g)) for g in goals)
        pending = len(self._get_index("by_approval", "pending"))
        approved = len(self._get_index("by_approval", "approved"))
        modified = len(self._get_index("by_approval", "modified"))
        rejected = len(self._get_index("by_approval", "rejected"))

        return {
            "total_goals": len(goals),
            "total_tests": total_tests,
            "by_approval": {
                "pending": pending,
                "approved": approved,
                "modified": modified,
                "rejected": rejected,
            },
            "storage_path": str(self.base_path),
        }
