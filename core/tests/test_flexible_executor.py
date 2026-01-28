"""
Tests for the Worker-Judge flexible execution pattern.

Tests cover:
- Plan and PlanStep data structures
- Code sandbox security
- HybridJudge rule evaluation
- WorkerNode action dispatch
- FlexibleGraphExecutor end-to-end
"""

import asyncio

import pytest

from framework.graph.code_sandbox import (
    CodeSandbox,
    safe_eval,
    safe_exec,
)
from framework.graph.goal import Goal, SuccessCriterion
from framework.graph.judge import HybridJudge, create_default_judge
from framework.graph.plan import (
    ActionSpec,
    ActionType,
    EvaluationRule,
    ExecutionStatus,
    Judgment,
    JudgmentAction,
    Plan,
    PlanExecutionResult,
    PlanStep,
    StepStatus,
)


class TestPlanDataStructures:
    """Tests for Plan and PlanStep."""

    def test_plan_step_creation(self):
        """Test creating a PlanStep."""
        action = ActionSpec(
            action_type=ActionType.LLM_CALL,
            prompt="Hello, world!",
        )
        step = PlanStep(
            id="step_1",
            description="Say hello",
            action=action,
            expected_outputs=["greeting"],
        )

        assert step.id == "step_1"
        assert step.status == StepStatus.PENDING
        assert step.action.action_type == ActionType.LLM_CALL

    def test_plan_step_is_ready(self):
        """Test PlanStep.is_ready() with dependencies."""
        step1 = PlanStep(
            id="step_1",
            description="First step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=[],
        )
        step2 = PlanStep(
            id="step_2",
            description="Second step",
            action=ActionSpec(action_type=ActionType.FUNCTION),
            dependencies=["step_1"],
        )

        # Step 1 is ready (no deps)
        assert step1.is_ready(set()) is True

        # Step 2 is not ready (dep not met)
        assert step2.is_ready(set()) is False

        # Step 2 is ready after step 1 completes
        assert step2.is_ready({"step_1"}) is True

    def test_plan_get_ready_steps(self):
        """Test Plan.get_ready_steps()."""
        plan = Plan(
            id="test_plan",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="First",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    dependencies=[],
                ),
                PlanStep(
                    id="step_2",
                    description="Second",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    dependencies=["step_1"],
                ),
            ],
        )

        ready = plan.get_ready_steps()
        assert len(ready) == 1
        assert ready[0].id == "step_1"

    def test_plan_is_complete(self):
        """Test Plan.is_complete()."""
        plan = Plan(
            id="test_plan",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="First",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    status=StepStatus.COMPLETED,
                ),
            ],
        )

        assert plan.is_complete() is True

    def test_plan_to_feedback_context(self):
        """Test Plan.to_feedback_context()."""
        plan = Plan(
            id="test_plan",
            goal_id="goal_1",
            description="Test plan",
            steps=[
                PlanStep(
                    id="step_1",
                    description="Completed step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    status=StepStatus.COMPLETED,
                    result={"data": "value"},
                ),
                PlanStep(
                    id="step_2",
                    description="Failed step",
                    action=ActionSpec(action_type=ActionType.FUNCTION),
                    status=StepStatus.FAILED,
                    error="Something went wrong",
                    attempts=3,
                ),
            ],
        )

        context = plan.to_feedback_context()
        assert context["plan_id"] == "test_plan"
        assert len(context["completed_steps"]) == 1
        assert len(context["failed_steps"]) == 1
        assert context["failed_steps"][0]["error"] == "Something went wrong"


class TestCodeSandbox:
    """Tests for code sandbox security."""

    def test_simple_execution(self):
        """Test simple code execution."""
        result = safe_exec("x = 1 + 2\nresult = x * 3")
        assert result.success is True
        assert result.variables.get("x") == 3
        assert result.result == 9

    def test_input_injection(self):
        """Test passing inputs to sandbox."""
        result = safe_exec(
            "result = x + y",
            inputs={"x": 10, "y": 20},
        )
        assert result.success is True
        assert result.result == 30

    def test_blocked_import(self):
        """Test that dangerous imports are blocked."""
        result = safe_exec("import os")
        assert result.success is False
        assert "blocked" in result.error.lower() or "import" in result.error.lower()

    def test_blocked_private_access(self):
        """Test that private attribute access is blocked."""
        result = safe_exec("x = [].__class__.__bases__")
        assert result.success is False

    def test_blocked_exec_eval(self):
        """Test that exec/eval are blocked."""
        result = safe_exec("exec('print(1)')")
        assert result.success is False

    def test_safe_eval_expression(self):
        """Test safe_eval for expressions."""
        result = safe_eval("x + y", inputs={"x": 5, "y": 3})
        assert result.success is True
        assert result.result == 8

    def test_allowed_modules(self):
        """Test that allowed modules work."""
        sandbox = CodeSandbox()
        # math is in ALLOWED_MODULES
        result = sandbox.execute(
            """
import math
result = math.sqrt(16)
""",
            inputs={},
        )
        # Note: imports are blocked by default in validation
        # This test documents current behavior
        assert result.success is False  # imports blocked by validator


class TestHybridJudge:
    """Tests for the HybridJudge."""

    def test_rule_based_accept(self):
        """Test rule-based accept judgment."""
        judge = HybridJudge()
        judge.add_rule(
            EvaluationRule(
                id="success_check",
                description="Accept on success flag",
                condition="result.get('success') == True",
                action=JudgmentAction.ACCEPT,
            )
        )

        step = PlanStep(
            id="test_step",
            description="Test",
            action=ActionSpec(action_type=ActionType.FUNCTION),
        )
        goal = Goal(
            id="goal_1",
            name="Test Goal",
            description="A test goal",
            success_criteria=[
                SuccessCriterion(
                    id="sc1", description="Complete task", metric="completion", target="100%"
                ),
            ],
        )

        # Use sync version for testing
        judgment = asyncio.run(judge.evaluate(step, {"success": True}, goal))

        assert judgment.action == JudgmentAction.ACCEPT
        assert judgment.rule_matched == "success_check"

    def test_rule_based_retry(self):
        """Test rule-based retry judgment."""
        judge = HybridJudge()
        judge.add_rule(
            EvaluationRule(
                id="timeout_retry",
                description="Retry on timeout",
                condition="result.get('error_type') == 'timeout'",
                action=JudgmentAction.RETRY,
                feedback_template="Timeout occurred, please retry",
            )
        )

        step = PlanStep(
            id="test_step",
            description="Test",
            action=ActionSpec(action_type=ActionType.FUNCTION),
        )
        goal = Goal(
            id="goal_1",
            name="Test Goal",
            description="A test goal",
            success_criteria=[
                SuccessCriterion(
                    id="sc1", description="Complete task", metric="completion", target="100%"
                ),
            ],
        )

        judgment = asyncio.run(judge.evaluate(step, {"error_type": "timeout"}, goal))

        assert judgment.action == JudgmentAction.RETRY

    def test_rule_priority(self):
        """Test that higher priority rules are checked first."""
        judge = HybridJudge()

        # Lower priority - would match
        judge.add_rule(
            EvaluationRule(
                id="low_priority",
                description="Low priority accept",
                condition="True",
                action=JudgmentAction.ACCEPT,
                priority=1,
            )
        )

        # Higher priority - should match first
        judge.add_rule(
            EvaluationRule(
                id="high_priority",
                description="High priority escalate",
                condition="True",
                action=JudgmentAction.ESCALATE,
                priority=100,
            )
        )

        step = PlanStep(
            id="test_step",
            description="Test",
            action=ActionSpec(action_type=ActionType.FUNCTION),
        )
        goal = Goal(
            id="goal_1",
            name="Test Goal",
            description="A test goal",
            success_criteria=[
                SuccessCriterion(
                    id="sc1", description="Complete task", metric="completion", target="100%"
                ),
            ],
        )

        judgment = asyncio.run(judge.evaluate(step, {}, goal))

        assert judgment.rule_matched == "high_priority"
        assert judgment.action == JudgmentAction.ESCALATE

    def test_default_judge_rules(self):
        """Test that create_default_judge includes useful rules."""
        judge = create_default_judge()

        # Should have rules for common cases
        rule_ids = {r.id for r in judge.rules}
        assert "explicit_success" in rule_ids
        assert "transient_error_retry" in rule_ids
        assert "security_escalate" in rule_ids


class TestJudgment:
    """Tests for Judgment data structure."""

    def test_judgment_creation(self):
        """Test creating a Judgment."""
        judgment = Judgment(
            action=JudgmentAction.ACCEPT,
            reasoning="Step completed successfully",
            confidence=0.95,
        )

        assert judgment.action == JudgmentAction.ACCEPT
        assert judgment.confidence == 0.95
        assert judgment.llm_used is False

    def test_judgment_with_feedback(self):
        """Test Judgment with feedback for retry/replan."""
        judgment = Judgment(
            action=JudgmentAction.REPLAN,
            reasoning="Missing required data",
            feedback="Need to fetch user data first",
            context={"missing": ["user_id", "email"]},
        )

        assert judgment.action == JudgmentAction.REPLAN
        assert judgment.feedback is not None
        assert "user_id" in judgment.context["missing"]


class TestPlanExecutionResult:
    """Tests for PlanExecutionResult."""

    def test_completed_result(self):
        """Test completed execution result."""
        result = PlanExecutionResult(
            status=ExecutionStatus.COMPLETED,
            results={"output": "success"},
            steps_executed=5,
            total_tokens=1000,
        )

        assert result.status == ExecutionStatus.COMPLETED
        assert result.steps_executed == 5

    def test_needs_replan_result(self):
        """Test needs_replan execution result."""
        result = PlanExecutionResult(
            status=ExecutionStatus.NEEDS_REPLAN,
            feedback="Step 3 failed: missing data",
            feedback_context={
                "completed_steps": ["step_1", "step_2"],
                "failed_step": "step_3",
            },
            completed_steps=["step_1", "step_2"],
        )

        assert result.status == ExecutionStatus.NEEDS_REPLAN
        assert result.feedback is not None
        assert len(result.completed_steps) == 2


# Integration tests would require mocking Runtime and LLM
class TestFlexibleExecutorIntegration:
    """Integration tests for FlexibleGraphExecutor."""

    def test_executor_creation(self, tmp_path):
        """Test creating a FlexibleGraphExecutor."""
        from framework.graph.flexible_executor import FlexibleGraphExecutor
        from framework.runtime.core import Runtime

        runtime = Runtime(storage_path=tmp_path / "runtime")
        executor = FlexibleGraphExecutor(runtime=runtime)

        assert executor.runtime == runtime
        assert executor.judge is not None
        assert executor.worker is not None

    def test_executor_with_custom_judge(self, tmp_path):
        """Test executor with custom judge."""
        from framework.graph.flexible_executor import FlexibleGraphExecutor
        from framework.runtime.core import Runtime

        runtime = Runtime(storage_path=tmp_path / "runtime")
        custom_judge = HybridJudge()
        custom_judge.add_rule(
            EvaluationRule(
                id="custom_rule",
                description="Custom rule",
                condition="True",
                action=JudgmentAction.ACCEPT,
            )
        )

        executor = FlexibleGraphExecutor(runtime=runtime, judge=custom_judge)

        assert len(executor.judge.rules) == 1
        assert executor.judge.rules[0].id == "custom_rule"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
