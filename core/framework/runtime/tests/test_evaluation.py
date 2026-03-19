"""Tests for the execution evaluation system."""

import tempfile
from pathlib import Path

import pytest

from framework.graph.executor import ExecutionResult
from framework.graph.goal import Goal, SuccessCriterion
from framework.runtime.evaluation import (
    EvaluationStore,
    ExecutionEvaluator,
)


@pytest.fixture
def tmp_store(tmp_path: Path) -> EvaluationStore:
    return EvaluationStore(base_path=tmp_path)


@pytest.fixture
def evaluator(tmp_store: EvaluationStore) -> ExecutionEvaluator:
    return ExecutionEvaluator(store=tmp_store)


@pytest.fixture
def sample_goal() -> Goal:
    return Goal(
        id="test-goal",
        name="Test Goal",
        description="A test goal for evaluation",
        success_criteria=[
            SuccessCriterion(
                id="accuracy",
                description="Output should contain expected result",
                metric="output_contains",
                target="hello",
                weight=0.7,
            ),
            SuccessCriterion(
                id="completeness",
                description="All output keys present",
                metric="output_equals",
                target="result",
                weight=0.3,
            ),
        ],
    )


def _make_result(success: bool, output: dict | None = None) -> ExecutionResult:
    return ExecutionResult(
        success=success,
        output=output or {},
        steps_executed=3,
        total_tokens=1500,
        total_latency_ms=5000,
    )


class TestExecutionEvaluator:
    def test_evaluate_successful_execution(
        self, evaluator: ExecutionEvaluator, sample_goal: Goal
    ):
        result = _make_result(True, {"result": "hello world"})
        ev = evaluator.evaluate(result, sample_goal, "stream-1", "exec-1")

        assert ev.success is True
        assert ev.overall_score > 0.7
        assert len(ev.criteria_results) == 2
        assert ev.criteria_results[0].met is True  # output_contains "hello"
        assert ev.criteria_results[1].met is True  # output_equals "result"

    def test_evaluate_failed_execution(
        self, evaluator: ExecutionEvaluator, sample_goal: Goal
    ):
        result = _make_result(False, {"error_detail": "something broke"})
        ev = evaluator.evaluate(result, sample_goal, "stream-1", "exec-2")

        assert ev.success is False
        assert ev.overall_score < 0.5

    def test_evaluate_partial_success(
        self, evaluator: ExecutionEvaluator, sample_goal: Goal
    ):
        """Output contains target but is missing the expected key."""
        result = _make_result(True, {"other_key": "hello"})
        ev = evaluator.evaluate(result, sample_goal, "stream-1", "exec-3")

        # "hello" found → accuracy met (0.7 weight)
        # "result" key missing → completeness not met (0.3 weight)
        assert ev.criteria_results[0].met is True
        assert ev.criteria_results[1].met is False
        assert 0.6 < ev.overall_score < 0.8

    def test_efficiency_metrics(
        self, evaluator: ExecutionEvaluator, sample_goal: Goal
    ):
        result = _make_result(True, {"result": "hello"})
        ev = evaluator.evaluate(result, sample_goal, "stream-1", "exec-4")

        assert ev.tokens_per_step == 500.0  # 1500 / 3
        assert ev.latency_per_step_ms == pytest.approx(1666.67, rel=0.01)


class TestEvaluationStore:
    def test_record_and_load(self, tmp_store: EvaluationStore):
        from framework.runtime.evaluation import EvaluationResult

        ev = EvaluationResult(
            execution_id="exec-1",
            stream_id="stream-1",
            success=True,
            overall_score=0.85,
        )
        tmp_store.record(ev)

        history = tmp_store.load_history("stream-1")
        assert len(history) == 1
        assert history[0]["execution_id"] == "exec-1"
        assert history[0]["overall_score"] == 0.85

    def test_load_empty_stream(self, tmp_store: EvaluationStore):
        assert tmp_store.load_history("nonexistent") == []

    def test_limit(self, tmp_store: EvaluationStore):
        from framework.runtime.evaluation import EvaluationResult

        for i in range(20):
            ev = EvaluationResult(
                execution_id=f"exec-{i}",
                stream_id="stream-1",
                success=i % 2 == 0,
                overall_score=0.5,
            )
            tmp_store.record(ev)

        history = tmp_store.load_history("stream-1", limit=5)
        assert len(history) == 5
        assert history[0]["execution_id"] == "exec-15"


class TestDiagnosis:
    def test_diagnose_with_history(
        self, evaluator: ExecutionEvaluator, sample_goal: Goal
    ):
        # Generate some history
        for i in range(8):
            result = _make_result(
                success=i >= 4,  # First 4 fail, last 4 succeed
                output={"result": "hello"} if i >= 4 else {},
            )
            evaluator.evaluate(result, sample_goal, "stream-diag", f"exec-{i}")

        plan = evaluator.diagnose("stream-diag", window=8)
        assert plan.recent_success_rate == 0.5
        assert plan.trend == "improving"  # Second half better than first
        assert len(plan.recommendations) > 0

    def test_diagnose_empty_history(self, evaluator: ExecutionEvaluator):
        plan = evaluator.diagnose("nonexistent")
        assert plan.recent_success_rate == 0.0
        assert plan.trend == "stable"

    def test_improvement_plan_prompt_context(
        self, evaluator: ExecutionEvaluator, sample_goal: Goal
    ):
        for i in range(5):
            result = _make_result(False, {})
            evaluator.evaluate(result, sample_goal, "stream-ctx", f"exec-{i}")

        plan = evaluator.diagnose("stream-ctx")
        ctx = plan.to_prompt_context()
        assert "Improvement Guidance" in ctx
        assert "Recommendations:" in ctx
