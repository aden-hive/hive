"""
Tests for Plan dependency resolution with failed steps.

These tests verify that plan execution correctly handles failed dependencies
instead of hanging indefinitely.
"""

import pytest

from framework.graph.plan import (
    ActionSpec,
    ActionType,
    Plan,
    PlanStep,
    StepStatus,
)


class TestStepStatusTerminal:
    """Tests for StepStatus.is_terminal() method."""

    def test_completed_is_terminal(self):
        """COMPLETED status should be terminal."""
        assert StepStatus.COMPLETED.is_terminal() is True

    def test_failed_is_terminal(self):
        """FAILED status should be terminal."""
        assert StepStatus.FAILED.is_terminal() is True

    def test_skipped_is_terminal(self):
        """SKIPPED status should be terminal."""
        assert StepStatus.SKIPPED.is_terminal() is True

    def test_rejected_is_terminal(self):
        """REJECTED status should be terminal."""
        assert StepStatus.REJECTED.is_terminal() is True

    def test_pending_is_not_terminal(self):
        """PENDING status should not be terminal."""
        assert StepStatus.PENDING.is_terminal() is False

    def test_in_progress_is_not_terminal(self):
        """IN_PROGRESS status should not be terminal."""
        assert StepStatus.IN_PROGRESS.is_terminal() is False

    def test_awaiting_approval_is_not_terminal(self):
        """AWAITING_APPROVAL status should not be terminal."""
        assert StepStatus.AWAITING_APPROVAL.is_terminal() is False

    def test_completed_is_successful(self):
        """Only COMPLETED should be successful."""
        assert StepStatus.COMPLETED.is_successful() is True
        assert StepStatus.FAILED.is_successful() is False
        assert StepStatus.SKIPPED.is_successful() is False


class TestPlanStepIsReady:
    """Tests for PlanStep.is_ready() with terminal states."""

    def _make_step(self, id: str, deps: list[str] = None, status: StepStatus = StepStatus.PENDING):
        """Helper to create a step."""
        return PlanStep(
            id=id,
            description=f"Step {id}",
            action=ActionSpec(action_type=ActionType.FUNCTION, function_name="test"),
            dependencies=deps or [],
            status=status,
        )

    def test_step_ready_when_no_dependencies(self):
        """Step with no dependencies should be ready."""
        step = self._make_step("step1")
        assert step.is_ready(set()) is True

    def test_step_ready_when_dependency_completed(self):
        """Step should be ready when dependency is completed."""
        step = self._make_step("step2", deps=["step1"])
        assert step.is_ready({"step1"}) is True

    def test_step_ready_when_dependency_failed(self):
        """Step should be ready when dependency failed (terminal state)."""
        step = self._make_step("step2", deps=["step1"])
        # step1 is in terminal_step_ids because it failed
        assert step.is_ready({"step1"}) is True

    def test_step_not_ready_when_dependency_pending(self):
        """Step should not be ready when dependency is still pending."""
        step = self._make_step("step2", deps=["step1"])
        assert step.is_ready(set()) is False

    def test_step_not_ready_when_already_completed(self):
        """Completed step should not be ready."""
        step = self._make_step("step1", status=StepStatus.COMPLETED)
        assert step.is_ready(set()) is False

    def test_step_not_ready_when_in_progress(self):
        """In-progress step should not be ready."""
        step = self._make_step("step1", status=StepStatus.IN_PROGRESS)
        assert step.is_ready(set()) is False

    def test_step_ready_with_multiple_dependencies_all_terminal(self):
        """Step should be ready when all dependencies are terminal."""
        step = self._make_step("step3", deps=["step1", "step2"])
        assert step.is_ready({"step1", "step2"}) is True

    def test_step_not_ready_with_partial_dependencies(self):
        """Step should not be ready when only some dependencies are terminal."""
        step = self._make_step("step3", deps=["step1", "step2"])
        assert step.is_ready({"step1"}) is False


class TestPlanGetReadySteps:
    """Tests for Plan.get_ready_steps() with failed dependencies."""

    def _make_plan(self, steps: list[PlanStep]) -> Plan:
        """Helper to create a plan."""
        return Plan(
            id="test_plan",
            goal_id="test_goal",
            description="Test plan",
            steps=steps,
        )

    def _make_step(self, id: str, deps: list[str] = None, status: StepStatus = StepStatus.PENDING):
        """Helper to create a step."""
        return PlanStep(
            id=id,
            description=f"Step {id}",
            action=ActionSpec(action_type=ActionType.FUNCTION, function_name="test"),
            dependencies=deps or [],
            status=status,
        )

    def test_ready_steps_with_no_dependencies(self):
        """Steps with no dependencies should be ready."""
        plan = self._make_plan(
            [
                self._make_step("step1"),
                self._make_step("step2"),
            ]
        )
        ready = plan.get_ready_steps()
        assert len(ready) == 2
        assert {s.id for s in ready} == {"step1", "step2"}

    def test_ready_steps_with_completed_dependency(self):
        """Dependent step should be ready when dependency is completed."""
        plan = self._make_plan(
            [
                self._make_step("step1", status=StepStatus.COMPLETED),
                self._make_step("step2", deps=["step1"]),
            ]
        )
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step2"

    def test_ready_steps_with_failed_dependency(self):
        """Dependent step should be ready when dependency failed."""
        plan = self._make_plan(
            [
                self._make_step("step1", status=StepStatus.FAILED),
                self._make_step("step2", deps=["step1"]),
            ]
        )
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step2"

    def test_ready_steps_with_skipped_dependency(self):
        """Dependent step should be ready when dependency was skipped."""
        plan = self._make_plan(
            [
                self._make_step("step1", status=StepStatus.SKIPPED),
                self._make_step("step2", deps=["step1"]),
            ]
        )
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step2"

    def test_ready_steps_with_rejected_dependency(self):
        """Dependent step should be ready when dependency was rejected."""
        plan = self._make_plan(
            [
                self._make_step("step1", status=StepStatus.REJECTED),
                self._make_step("step2", deps=["step1"]),
            ]
        )
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step2"

    def test_no_ready_steps_when_dependency_in_progress(self):
        """Dependent step should not be ready when dependency is in progress."""
        plan = self._make_plan(
            [
                self._make_step("step1", status=StepStatus.IN_PROGRESS),
                self._make_step("step2", deps=["step1"]),
            ]
        )
        ready = plan.get_ready_steps()
        assert len(ready) == 0


class TestPlanCompletion:
    """Tests for Plan completion status methods."""

    def _make_plan(self, steps: list[PlanStep]) -> Plan:
        """Helper to create a plan."""
        return Plan(
            id="test_plan",
            goal_id="test_goal",
            description="Test plan",
            steps=steps,
        )

    def _make_step(self, id: str, status: StepStatus = StepStatus.PENDING):
        """Helper to create a step."""
        return PlanStep(
            id=id,
            description=f"Step {id}",
            action=ActionSpec(action_type=ActionType.FUNCTION, function_name="test"),
            status=status,
        )

    def test_is_complete_when_all_completed(self):
        """Plan should be complete when all steps are completed."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.COMPLETED),
            ]
        )
        assert plan.is_complete() is True

    def test_is_complete_when_all_terminal_mixed(self):
        """Plan should be complete when all steps are in terminal states (mixed)."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.FAILED),
                self._make_step("step3", StepStatus.SKIPPED),
            ]
        )
        assert plan.is_complete() is True

    def test_is_not_complete_when_pending(self):
        """Plan should not be complete when steps are pending."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.PENDING),
            ]
        )
        assert plan.is_complete() is False

    def test_is_not_complete_when_in_progress(self):
        """Plan should not be complete when steps are in progress."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.IN_PROGRESS),
            ]
        )
        assert plan.is_complete() is False

    def test_is_successful_when_all_completed(self):
        """Plan should be successful only when all steps completed."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.COMPLETED),
            ]
        )
        assert plan.is_successful() is True

    def test_is_not_successful_when_failed(self):
        """Plan should not be successful when any step failed."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.FAILED),
            ]
        )
        assert plan.is_successful() is False

    def test_has_failed_steps(self):
        """has_failed_steps should detect failed steps."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.FAILED),
            ]
        )
        assert plan.has_failed_steps() is True

    def test_has_no_failed_steps(self):
        """has_failed_steps should return False when all succeeded."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.COMPLETED),
            ]
        )
        assert plan.has_failed_steps() is False

    def test_get_failed_steps(self):
        """get_failed_steps should return all failed/skipped/rejected steps."""
        plan = self._make_plan(
            [
                self._make_step("step1", StepStatus.COMPLETED),
                self._make_step("step2", StepStatus.FAILED),
                self._make_step("step3", StepStatus.SKIPPED),
                self._make_step("step4", StepStatus.REJECTED),
            ]
        )
        failed = plan.get_failed_steps()
        assert len(failed) == 3
        assert {s.id for s in failed} == {"step2", "step3", "step4"}


class TestBugScenario:
    """Test the specific bug scenario that was fixed."""

    def _make_step(self, id: str, deps: list[str] = None, status: StepStatus = StepStatus.PENDING):
        """Helper to create a step."""
        return PlanStep(
            id=id,
            description=f"Step {id}",
            action=ActionSpec(action_type=ActionType.FUNCTION, function_name="test"),
            dependencies=deps or [],
            status=status,
        )

    def test_dependent_step_becomes_ready_after_dependency_fails(self):
        """
        BUG SCENARIO: When step1 fails, step2 (which depends on step1) should
        become ready, allowing the executor to handle it appropriately.

        Before fix: step2 would never become ready, causing infinite hang.
        After fix: step2 becomes ready and executor can decide how to handle it.
        """
        plan = Plan(
            id="test_plan",
            goal_id="test_goal",
            description="Test plan with dependency",
            steps=[
                self._make_step("step1", status=StepStatus.PENDING),
                self._make_step("step2", deps=["step1"], status=StepStatus.PENDING),
            ],
        )

        # Initially, only step1 is ready
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step1"

        # Simulate step1 failing
        plan.steps[0].status = StepStatus.FAILED

        # Now step2 should be ready (dependency is in terminal state)
        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step2"

        # Plan should not be complete yet (step2 is still pending)
        assert plan.is_complete() is False

        # Simulate step2 also failing (or being skipped due to failed dependency)
        plan.steps[1].status = StepStatus.SKIPPED

        # Now plan should be complete (all steps in terminal states)
        assert plan.is_complete() is True

        # But not successful
        assert plan.is_successful() is False

        # And should have failed steps
        assert plan.has_failed_steps() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
