"""
Unit tests for FailureCondition SDK.

Tests cover:
- FailureSeverity enum
- ExecutionContext dataclass
- FailureCondition evaluation
- FailureResult
- FailureEvaluator
- Integration with Goal
"""

import pytest
from datetime import datetime

from framework.schemas.failure_condition import (
    ExecutionContext,
    FailureCondition,
    FailureEvaluator,
    FailureResult,
    FailureSeverity,
)
from framework.failure_conditions.builtin import (
    TIMEOUT_EXCEEDED,
    TOKEN_BUDGET_EXCEEDED,
    OUTPUT_VALIDATION_FAILED,
    NO_DATA_FOUND,
    MAX_ERRORS_EXCEEDED,
    SUCCESS_RATE_TOO_LOW,
    LOOP_DETECTED,
    get_builtin_condition,
    get_all_builtin_conditions,
)
from framework.graph.goal import Goal


class TestFailureSeverity:
    """Test the FailureSeverity enum."""

    def test_severity_values(self):
        assert FailureSeverity.CRITICAL.value == "critical"
        assert FailureSeverity.MAJOR.value == "major"
        assert FailureSeverity.MINOR.value == "minor"
        assert FailureSeverity.WARNING.value == "warning"

    def test_severity_string_comparison(self):
        assert FailureSeverity.CRITICAL == "critical"
        assert FailureSeverity.MAJOR == "major"


class TestExecutionContext:
    """Test the ExecutionContext dataclass."""

    def test_default_values(self):
        ctx = ExecutionContext()
        assert ctx.elapsed_time == 0.0
        assert ctx.total_tokens == 0
        assert ctx.output == {}
        assert ctx.last_outcome == {}
        assert ctx.errors == []
        assert ctx.decisions_count == 0
        assert ctx.successful_decisions == 0
        assert ctx.failed_decisions == 0
        assert ctx.budget == {}
        assert ctx.goal_constraints == {}
        assert ctx.metadata == {}

    def test_custom_values(self):
        ctx = ExecutionContext(
            elapsed_time=10.5,
            total_tokens=1000,
            output={"result": "success"},
            errors=["error1"],
        )
        assert ctx.elapsed_time == 10.5
        assert ctx.total_tokens == 1000
        assert ctx.output == {"result": "success"}
        assert ctx.errors == ["error1"]

    def test_success_rate_no_decisions(self):
        ctx = ExecutionContext()
        assert ctx.success_rate == 0.0

    def test_success_rate_with_decisions(self):
        ctx = ExecutionContext(successful_decisions=8, failed_decisions=2)
        assert ctx.success_rate == 0.8

    def test_to_dict(self):
        ctx = ExecutionContext(
            elapsed_time=5.0,
            total_tokens=500,
            successful_decisions=5,
            failed_decisions=2,
        )
        d = ctx.to_dict()
        assert d["elapsed_time"] == 5.0
        assert d["total_tokens"] == 500
        assert d["success_rate"] == 5 / 7


class TestFailureCondition:
    """Test the FailureCondition class."""

    def test_create_condition(self):
        condition = FailureCondition(
            name="test_condition",
            description="Test condition description",
            severity=FailureSeverity.MAJOR,
            check="ctx.elapsed_time > 10",
        )
        assert condition.name == "test_condition"
        assert condition.description == "Test condition description"
        assert condition.severity == FailureSeverity.MAJOR
        assert condition.enabled is True

    def test_evaluate_not_triggered(self):
        condition = FailureCondition(
            name="timeout",
            description="Timeout exceeded",
            severity=FailureSeverity.MAJOR,
            check="ctx.elapsed_time > 60",
        )
        ctx = ExecutionContext(elapsed_time=30.0)
        result = condition.evaluate(ctx)

        assert result.triggered is False
        assert result.condition == condition
        assert result.evaluation_error is None

    def test_evaluate_triggered(self):
        condition = FailureCondition(
            name="timeout",
            description="Timeout exceeded",
            severity=FailureSeverity.MAJOR,
            check="ctx.elapsed_time > 60",
        )
        ctx = ExecutionContext(elapsed_time=90.0)
        result = condition.evaluate(ctx)

        assert result.triggered is True
        assert result.condition == condition
        assert result.severity == FailureSeverity.MAJOR

    def test_evaluate_disabled_condition(self):
        condition = FailureCondition(
            name="timeout",
            description="Timeout exceeded",
            severity=FailureSeverity.MAJOR,
            check="ctx.elapsed_time > 60",
            enabled=False,
        )
        ctx = ExecutionContext(elapsed_time=90.0)
        result = condition.evaluate(ctx)

        assert result.triggered is False

    def test_evaluate_with_error(self):
        condition = FailureCondition(
            name="bad_condition",
            description="Bad condition",
            severity=FailureSeverity.MAJOR,
            check="ctx.nonexistent_attr > 10",
        )
        ctx = ExecutionContext()
        result = condition.evaluate(ctx)

        assert result.triggered is False
        assert result.evaluation_error is not None

    def test_evaluate_lambda_expression(self):
        condition = FailureCondition(
            name="lambda_check",
            description="Lambda check",
            severity=FailureSeverity.MINOR,
            check="lambda ctx: len(ctx.errors) > 0",
        )
        ctx = ExecutionContext(errors=["error1"])
        result = condition.evaluate(ctx)

        assert result.triggered is True

    def test_to_dict(self):
        condition = FailureCondition(
            name="test",
            description="Test",
            severity=FailureSeverity.CRITICAL,
            check="True",
            recovery_hint="Fix it",
        )
        d = condition.to_dict()

        assert d["name"] == "test"
        assert d["severity"] == "critical"
        assert d["recovery_hint"] == "Fix it"


class TestFailureResult:
    """Test the FailureResult class."""

    def test_create_result(self):
        condition = FailureCondition(
            name="test",
            description="Test",
            severity=FailureSeverity.MAJOR,
            check="True",
        )
        result = FailureResult(
            condition=condition,
            triggered=True,
            context={"elapsed_time": 10},
        )

        assert result.triggered is True
        assert result.condition == condition
        assert result.context == {"elapsed_time": 10}

    def test_is_critical(self):
        critical_condition = FailureCondition(
            name="critical",
            description="Critical",
            severity=FailureSeverity.CRITICAL,
            check="True",
        )
        major_condition = FailureCondition(
            name="major",
            description="Major",
            severity=FailureSeverity.MAJOR,
            check="True",
        )

        critical_result = FailureResult(condition=critical_condition, triggered=True, context={})
        major_result = FailureResult(condition=major_condition, triggered=True, context={})
        not_triggered_result = FailureResult(
            condition=critical_condition, triggered=False, context={}
        )

        assert critical_result.is_critical is True
        assert major_result.is_critical is False
        assert not_triggered_result.is_critical is False

    def test_to_dict(self):
        condition = FailureCondition(
            name="test",
            description="Test",
            severity=FailureSeverity.WARNING,
            check="True",
            recovery_hint="Hint",
        )
        result = FailureResult(
            condition=condition,
            triggered=True,
            context={"key": "value"},
        )
        d = result.to_dict()

        assert d["condition_name"] == "test"
        assert d["triggered"] is True
        assert d["severity"] == "warning"
        assert d["recovery_hint"] == "Hint"


class TestFailureEvaluator:
    """Test the FailureEvaluator class."""

    def test_empty_evaluator(self):
        evaluator = FailureEvaluator()
        ctx = ExecutionContext()
        results = evaluator.check_all(ctx)

        assert results == []

    def test_check_all(self):
        conditions = [
            FailureCondition(
                name="cond1",
                description="Condition 1",
                severity=FailureSeverity.MAJOR,
                check="ctx.elapsed_time > 10",
            ),
            FailureCondition(
                name="cond2",
                description="Condition 2",
                severity=FailureSeverity.MINOR,
                check="len(ctx.errors) > 0",
            ),
        ]
        evaluator = FailureEvaluator(conditions=conditions)
        ctx = ExecutionContext(elapsed_time=15.0, errors=["error"])
        results = evaluator.check_all(ctx)

        assert len(results) == 2
        assert all(r.triggered for r in results)

    def test_has_critical_failure(self):
        conditions = [
            FailureCondition(
                name="critical",
                description="Critical",
                severity=FailureSeverity.CRITICAL,
                check="True",
            ),
        ]
        evaluator = FailureEvaluator(conditions=conditions)
        ctx = ExecutionContext()
        results = evaluator.check_all(ctx)

        assert evaluator.has_critical_failure(results) is True

    def test_no_critical_failure(self):
        conditions = [
            FailureCondition(
                name="major",
                description="Major",
                severity=FailureSeverity.MAJOR,
                check="True",
            ),
        ]
        evaluator = FailureEvaluator(conditions=conditions)
        ctx = ExecutionContext()
        results = evaluator.check_all(ctx)

        assert evaluator.has_critical_failure(results) is False

    def test_get_triggered_failures(self):
        conditions = [
            FailureCondition(
                name="triggered",
                description="Triggered",
                severity=FailureSeverity.MAJOR,
                check="True",
            ),
            FailureCondition(
                name="not_triggered",
                description="Not triggered",
                severity=FailureSeverity.MINOR,
                check="False",
            ),
        ]
        evaluator = FailureEvaluator(conditions=conditions)
        ctx = ExecutionContext()
        results = evaluator.check_all(ctx)
        triggered = evaluator.get_triggered_failures(results)

        assert len(triggered) == 1
        assert triggered[0].condition.name == "triggered"

    def test_get_triggered_failures_sorted_by_severity(self):
        conditions = [
            FailureCondition(
                name="warning",
                description="Warning",
                severity=FailureSeverity.WARNING,
                check="True",
            ),
            FailureCondition(
                name="critical",
                description="Critical",
                severity=FailureSeverity.CRITICAL,
                check="True",
            ),
            FailureCondition(
                name="major",
                description="Major",
                severity=FailureSeverity.MAJOR,
                check="True",
            ),
        ]
        evaluator = FailureEvaluator(conditions=conditions)
        ctx = ExecutionContext()
        results = evaluator.check_all(ctx)
        triggered = evaluator.get_triggered_failures(results)

        assert triggered[0].severity == FailureSeverity.CRITICAL
        assert triggered[1].severity == FailureSeverity.MAJOR
        assert triggered[2].severity == FailureSeverity.WARNING

    def test_get_failures_by_severity(self):
        conditions = [
            FailureCondition(
                name="critical1",
                description="Critical 1",
                severity=FailureSeverity.CRITICAL,
                check="True",
            ),
            FailureCondition(
                name="major1",
                description="Major 1",
                severity=FailureSeverity.MAJOR,
                check="True",
            ),
            FailureCondition(
                name="critical2",
                description="Critical 2",
                severity=FailureSeverity.CRITICAL,
                check="True",
            ),
        ]
        evaluator = FailureEvaluator(conditions=conditions)
        ctx = ExecutionContext()
        results = evaluator.check_all(ctx)
        critical = evaluator.get_failures_by_severity(results, FailureSeverity.CRITICAL)

        assert len(critical) == 2

    def test_add_condition(self):
        evaluator = FailureEvaluator()
        condition = FailureCondition(
            name="new",
            description="New",
            severity=FailureSeverity.MINOR,
            check="True",
        )
        evaluator.add_condition(condition)

        assert len(evaluator.conditions) == 1

    def test_remove_condition(self):
        condition = FailureCondition(
            name="remove_me",
            description="Remove me",
            severity=FailureSeverity.MINOR,
            check="True",
        )
        evaluator = FailureEvaluator(conditions=[condition])

        assert evaluator.remove_condition("remove_me") is True
        assert evaluator.remove_condition("nonexistent") is False
        assert len(evaluator.conditions) == 0


class TestBuiltinConditions:
    """Test built-in failure conditions."""

    def test_get_builtin_condition(self):
        timeout = get_builtin_condition("timeout_exceeded")
        assert timeout is not None
        assert timeout.name == "timeout_exceeded"

    def test_get_nonexistent_builtin(self):
        nonexistent = get_builtin_condition("nonexistent")
        assert nonexistent is None

    def test_get_all_builtins(self):
        all_builtins = get_all_builtin_conditions()
        assert len(all_builtins) >= 7
        names = [c.name for c in all_builtins]
        assert "timeout_exceeded" in names
        assert "token_budget_exceeded" in names

    def test_timeout_exceeded_triggered(self):
        ctx = ExecutionContext(
            elapsed_time=120.0,
            goal_constraints={"max_duration": 60.0},
        )
        result = TIMEOUT_EXCEEDED.evaluate(ctx)
        assert result.triggered is True

    def test_timeout_exceeded_not_triggered(self):
        ctx = ExecutionContext(
            elapsed_time=30.0,
            goal_constraints={"max_duration": 60.0},
        )
        result = TIMEOUT_EXCEEDED.evaluate(ctx)
        assert result.triggered is False

    def test_token_budget_exceeded_triggered(self):
        ctx = ExecutionContext(
            total_tokens=2000,
            budget={"max_tokens": 1000},
        )
        result = TOKEN_BUDGET_EXCEEDED.evaluate(ctx)
        assert result.triggered is True
        assert result.severity == FailureSeverity.CRITICAL

    def test_output_validation_failed_triggered(self):
        ctx = ExecutionContext(last_outcome={"validation_errors": ["Missing field"]})
        result = OUTPUT_VALIDATION_FAILED.evaluate(ctx)
        assert result.triggered is True

    def test_max_errors_exceeded_triggered(self):
        ctx = ExecutionContext(
            errors=["e1", "e2", "e3", "e4"],
            goal_constraints={"max_errors": 3},
        )
        result = MAX_ERRORS_EXCEEDED.evaluate(ctx)
        assert result.triggered is True

    def test_success_rate_too_low_triggered(self):
        ctx = ExecutionContext(
            decisions_count=10,
            successful_decisions=3,
            failed_decisions=7,
            goal_constraints={"min_success_rate": 0.5},
        )
        result = SUCCESS_RATE_TOO_LOW.evaluate(ctx)
        assert result.triggered is True

    def test_loop_detected_triggered(self):
        ctx = ExecutionContext(
            decisions_count=100,
            goal_constraints={"max_decisions": 50},
        )
        result = LOOP_DETECTED.evaluate(ctx)
        assert result.triggered is True


class TestGoalIntegration:
    """Test FailureCondition integration with Goal."""

    def test_goal_with_failure_conditions(self):
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="A test goal",
            failure_conditions=[
                FailureCondition(
                    name="custom_failure",
                    description="Custom failure condition",
                    severity=FailureSeverity.MAJOR,
                    check="ctx.elapsed_time > 100",
                )
            ],
        )

        assert len(goal.failure_conditions) == 1
        assert goal.failure_conditions[0].name == "custom_failure"

    def test_goal_evaluate_failures(self):
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="A test goal",
            failure_conditions=[
                FailureCondition(
                    name="timeout",
                    description="Timeout",
                    severity=FailureSeverity.MAJOR,
                    check="ctx.elapsed_time > 60",
                )
            ],
        )

        ctx = ExecutionContext(elapsed_time=90.0)
        results = goal.evaluate_failures(ctx)

        assert len(results) == 1
        assert results[0].triggered is True

    def test_goal_has_critical_failure(self):
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="A test goal",
            failure_conditions=[
                FailureCondition(
                    name="critical",
                    description="Critical",
                    severity=FailureSeverity.CRITICAL,
                    check="True",
                )
            ],
        )

        ctx = ExecutionContext()
        assert goal.has_critical_failure(ctx) is True

    def test_goal_get_failure_evaluator(self):
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="A test goal",
            failure_conditions=[
                FailureCondition(
                    name="cond1",
                    description="Condition 1",
                    severity=FailureSeverity.MINOR,
                    check="True",
                )
            ],
        )

        evaluator = goal.get_failure_evaluator()
        assert isinstance(evaluator, FailureEvaluator)
        assert len(evaluator.conditions) == 1

    def test_goal_empty_failure_conditions(self):
        goal = Goal(
            id="test-goal",
            name="Test Goal",
            description="A test goal",
        )

        ctx = ExecutionContext()
        results = goal.evaluate_failures(ctx)

        assert results == []
        assert goal.has_critical_failure(ctx) is False
