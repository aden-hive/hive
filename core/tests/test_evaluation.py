"""Tests for the evaluation framework."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from framework.evaluation.evaluator import AgentEvaluator
from framework.evaluation.failure_classifier import (
    FailureCategory,
    FailureClassifier,
    FailureRecord,
)
from framework.evaluation.metrics import EvaluationMetrics, MetricsCollector
from framework.evaluation.report import (
    EvaluationReport,
    EvolutionRecommendation,
    EvolutionStage,
    RecommendationPriority,
)
from framework.graph.goal import Constraint, Goal, SuccessCriterion


@dataclass
class FakeExecutionResult:
    success: bool = True
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    steps_executed: int = 3
    total_tokens: int = 1000
    total_latency_ms: int = 2000
    path: list[str] = field(default_factory=lambda: ["node-a", "node-b", "node-c"])
    total_retries: int = 0
    nodes_with_failures: list[str] = field(default_factory=list)
    retry_details: dict[str, int] = field(default_factory=dict)
    had_partial_failures: bool = False
    execution_quality: str = "clean"
    node_visit_counts: dict[str, int] = field(default_factory=dict)


def _make_goal(**overrides: Any) -> Goal:
    defaults: dict[str, Any] = {
        "id": "test-goal",
        "name": "Test Goal",
        "description": "A goal for testing.",
        "success_criteria": [
            SuccessCriterion(
                id="sc-1",
                description="Execution must succeed",
                metric="execution_success",
                target=True,
                weight=1.0,
            ),
        ],
        "constraints": [],
    }
    defaults.update(overrides)
    return Goal(**defaults)


class TestFailureClassifier:
    def setup_method(self) -> None:
        self.classifier = FailureClassifier()

    def test_classify_rate_limit(self) -> None:
        result = FakeExecutionResult(success=False, error="429 Too Many Requests")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.LLM_RATE_LIMIT in categories

    def test_classify_timeout(self) -> None:
        result = FakeExecutionResult(success=False, error="Request timed out after 30s")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.TOOL_TIMEOUT in categories

    def test_classify_auth_failure(self) -> None:
        result = FakeExecutionResult(success=False, error="401 Unauthorized - invalid API key")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.TOOL_AUTH_FAILURE in categories

    def test_classify_content_filter(self) -> None:
        result = FakeExecutionResult(success=False, error="Content filter triggered: safety block")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.LLM_CONTENT_FILTER in categories

    def test_classify_empty_response(self) -> None:
        result = FakeExecutionResult(success=False, error="Empty response from model")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.LLM_EMPTY_RESPONSE in categories

    def test_classify_context_overflow(self) -> None:
        result = FakeExecutionResult(
            success=False, error="Context window overflow: too many tokens"
        )
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.LLM_CONTEXT_OVERFLOW in categories

    def test_classify_hallucination(self) -> None:
        result = FakeExecutionResult(success=False, error="Output not grounded in source data")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.LLM_HALLUCINATION in categories

    def test_classify_budget_exceeded(self) -> None:
        result = FakeExecutionResult(
            success=False, error="Budget exhausted: spending limit reached"
        )
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.CONSTRAINT_COST_EXCEEDED in categories

    def test_classify_dead_end(self) -> None:
        result = FakeExecutionResult(success=False, error="Dead end: no next node for output")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.GRAPH_DEAD_END in categories

    def test_classify_infinite_loop(self) -> None:
        result = FakeExecutionResult(success=False, error="Max visits exceeded, cycle detected")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.GRAPH_INFINITE_LOOP in categories

    def test_classify_safety_violation(self) -> None:
        result = FakeExecutionResult(success=False, error="PII detected: sensitive data in output")
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.CONSTRAINT_SAFETY_VIOLATION in categories

    def test_structural_high_tokens(self) -> None:
        result = FakeExecutionResult(success=True, total_tokens=200_000)
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.CONSTRAINT_COST_EXCEEDED in categories

    def test_structural_high_latency(self) -> None:
        result = FakeExecutionResult(success=True, total_latency_ms=150_000)
        records = self.classifier.classify(result)
        categories = {r.category for r in records}
        assert FailureCategory.CONSTRAINT_TIME_EXCEEDED in categories

    def test_structural_failed_nodes(self) -> None:
        result = FakeExecutionResult(
            success=False,
            execution_quality="failed",
            nodes_with_failures=["node-x"],
            retry_details={"node-x": 3},
            error="node-x failed",
        )
        records = self.classifier.classify(result)
        node_ids = {r.node_id for r in records if r.node_id}
        assert "node-x" in node_ids

    def test_clean_success_returns_empty(self) -> None:
        result = FakeExecutionResult(success=True)
        records = self.classifier.classify(result)
        assert records == []

    def test_unknown_failure(self) -> None:
        result = FakeExecutionResult(success=False, error="Something weird happened")
        records = self.classifier.classify(result)
        assert len(records) >= 1
        assert records[-1].category == FailureCategory.UNKNOWN

    def test_classify_error_string(self) -> None:
        record = self.classifier.classify_error("Rate limit exceeded", node_id="n1")
        assert record.category == FailureCategory.LLM_RATE_LIMIT
        assert record.node_id == "n1"

    def test_deduplication(self) -> None:
        result = FakeExecutionResult(
            success=False,
            error="rate limit rate limit rate limit",
        )
        records = self.classifier.classify(result)
        cats = [r.category for r in records]
        assert cats.count(FailureCategory.LLM_RATE_LIMIT) <= 1


class TestFailureRecord:
    def test_retriable(self) -> None:
        r = FailureRecord(
            category=FailureCategory.LLM_RATE_LIMIT,
            severity="low",
            message="rate limited",
        )
        assert r.is_retriable is True

    def test_not_retriable(self) -> None:
        r = FailureRecord(
            category=FailureCategory.LLM_HALLUCINATION,
            severity="high",
            message="hallucinated",
        )
        assert r.is_retriable is False

    def test_requires_graph_change(self) -> None:
        r = FailureRecord(
            category=FailureCategory.GRAPH_DEAD_END,
            severity="high",
            message="dead end",
        )
        assert r.requires_graph_change is True

    def test_no_graph_change_needed(self) -> None:
        r = FailureRecord(
            category=FailureCategory.TOOL_TIMEOUT,
            severity="low",
            message="timeout",
        )
        assert r.requires_graph_change is False


class TestMetricsCollector:
    def test_record_and_count(self) -> None:
        collector = MetricsCollector(agent_id="test")
        collector.record(EvaluationMetrics(success=True, total_tokens=100))
        collector.record(EvaluationMetrics(success=False, total_tokens=200))
        assert collector.count == 2

    def test_aggregate_success_rate(self) -> None:
        collector = MetricsCollector()
        for success in [True, True, False, True]:
            collector.record(EvaluationMetrics(success=success))
        agg = collector.aggregate()
        assert agg["success_rate"] == 0.75

    def test_aggregate_empty(self) -> None:
        collector = MetricsCollector()
        agg = collector.aggregate()
        assert agg["total_runs"] == 0

    def test_aggregate_tokens_and_cost(self) -> None:
        collector = MetricsCollector()
        collector.record(EvaluationMetrics(total_tokens=1000, estimated_cost_usd=0.01))
        collector.record(EvaluationMetrics(total_tokens=2000, estimated_cost_usd=0.02))
        agg = collector.aggregate()
        assert agg["total_tokens"] == 3000
        assert agg["total_cost_usd"] == pytest.approx(0.03)

    def test_trend_improving(self) -> None:
        collector = MetricsCollector()
        for _ in range(5):
            collector.record(EvaluationMetrics(success=False))
        for _ in range(5):
            collector.record(EvaluationMetrics(success=True))
        agg = collector.aggregate()
        assert agg["trend"] == "improving"

    def test_trend_degrading(self) -> None:
        collector = MetricsCollector()
        for _ in range(5):
            collector.record(EvaluationMetrics(success=True))
        for _ in range(5):
            collector.record(EvaluationMetrics(success=False))
        agg = collector.aggregate()
        assert agg["trend"] == "degrading"

    def test_trend_stable(self) -> None:
        collector = MetricsCollector()
        for _ in range(10):
            collector.record(EvaluationMetrics(success=True))
        agg = collector.aggregate()
        assert agg["trend"] == "stable"

    def test_trend_insufficient_data(self) -> None:
        collector = MetricsCollector()
        collector.record(EvaluationMetrics(success=True))
        agg = collector.aggregate()
        assert agg["trend"] == "insufficient_data"

    def test_get_recent(self) -> None:
        collector = MetricsCollector()
        for i in range(20):
            collector.record(EvaluationMetrics(run_id=str(i)))
        recent = collector.get_recent(5)
        assert len(recent) == 5
        assert recent[0].run_id == "15"

    def test_clear(self) -> None:
        collector = MetricsCollector()
        collector.record(EvaluationMetrics())
        collector.clear()
        assert collector.count == 0


class TestEvaluationMetrics:
    def test_criteria_pass_rate(self) -> None:
        m = EvaluationMetrics(criteria_met=3, criteria_total=4)
        assert m.criteria_pass_rate == 0.75

    def test_criteria_pass_rate_zero(self) -> None:
        m = EvaluationMetrics(criteria_met=0, criteria_total=0)
        assert m.criteria_pass_rate == 0.0

    def test_avg_latency_per_step(self) -> None:
        m = EvaluationMetrics(total_latency_ms=6000, steps_executed=3)
        assert m.avg_latency_per_step_ms == 2000.0

    def test_tokens_per_step(self) -> None:
        m = EvaluationMetrics(total_tokens=3000, steps_executed=3)
        assert m.tokens_per_step == 1000.0

    def test_to_summary_dict(self) -> None:
        m = EvaluationMetrics(run_id="r1", success=True, total_tokens=500)
        d = m.to_summary_dict()
        assert d["run_id"] == "r1"
        assert d["success"] is True


class TestAgentEvaluator:
    def setup_method(self) -> None:
        self.evaluator = AgentEvaluator()

    def test_passing_evaluation(self) -> None:
        result = FakeExecutionResult(success=True)
        goal = _make_goal()
        report = self.evaluator.evaluate(result, goal)
        assert report.passed is True
        assert report.metrics.criteria_met == 1
        assert len(report.failures) == 0

    def test_failing_evaluation(self) -> None:
        result = FakeExecutionResult(
            success=False, error="Rate limit exceeded", execution_quality="failed"
        )
        goal = _make_goal()
        report = self.evaluator.evaluate(result, goal)
        assert report.passed is False
        assert len(report.failures) > 0
        assert len(report.recommendations) > 0

    def test_criteria_output_contains(self) -> None:
        result = FakeExecutionResult(
            success=True,
            output={"report": "The weather in San Francisco is sunny"},
        )
        goal = _make_goal(
            success_criteria=[
                SuccessCriterion(
                    id="has-weather",
                    description="Output contains weather info",
                    metric="output_contains",
                    target="weather",
                    weight=1.0,
                ),
            ]
        )
        report = self.evaluator.evaluate(result, goal)
        assert report.passed is True
        assert report.metrics.criteria_met == 1

    def test_criteria_output_contains_fail(self) -> None:
        result = FakeExecutionResult(
            success=True,
            output={"report": "No relevant data found"},
        )
        goal = _make_goal(
            success_criteria=[
                SuccessCriterion(
                    id="has-weather",
                    description="Must mention weather",
                    metric="output_contains",
                    target="weather",
                    weight=1.0,
                ),
            ]
        )
        report = self.evaluator.evaluate(result, goal)
        assert report.metrics.criteria_met == 0

    def test_criteria_output_exists(self) -> None:
        result = FakeExecutionResult(
            success=True,
            output={"summary": "Some summary text"},
        )
        goal = _make_goal(
            success_criteria=[
                SuccessCriterion(
                    id="has-summary",
                    description="Output has summary key",
                    metric="output_exists",
                    target="summary",
                    weight=1.0,
                ),
            ]
        )
        report = self.evaluator.evaluate(result, goal)
        assert report.metrics.criteria_met == 1

    def test_hard_constraint_violation_fails(self) -> None:
        result = FakeExecutionResult(
            success=True,
            error="PII detected in output: safety violation",
        )
        goal = _make_goal(
            constraints=[
                Constraint(
                    id="no-pii",
                    description="Must not expose PII",
                    constraint_type="hard",
                    category="safety",
                ),
            ]
        )
        report = self.evaluator.evaluate(result, goal)
        assert report.passed is False

    def test_soft_constraint_violation_can_pass(self) -> None:
        result = FakeExecutionResult(success=True, total_tokens=200_000)
        goal = _make_goal(
            constraints=[
                Constraint(
                    id="token-budget",
                    description="Prefer under 50k tokens",
                    constraint_type="soft",
                    category="cost",
                    check="50000",
                ),
            ]
        )
        report = self.evaluator.evaluate(result, goal)
        assert report.passed is True
        violated = [c for c in report.constraint_results if not c["satisfied"]]
        assert len(violated) == 1

    def test_recommendations_sorted_by_priority(self) -> None:
        result = FakeExecutionResult(
            success=False,
            error="Rate limit and dead end no next node",
            execution_quality="failed",
        )
        goal = _make_goal()
        report = self.evaluator.evaluate(result, goal)
        if len(report.recommendations) >= 2:
            priorities = [r.priority for r in report.recommendations]
            priority_order = {
                RecommendationPriority.CRITICAL: 0,
                RecommendationPriority.HIGH: 1,
                RecommendationPriority.MEDIUM: 2,
                RecommendationPriority.LOW: 3,
            }
            values = [priority_order[p] for p in priorities]
            assert values == sorted(values)

    def test_metrics_collector_integration(self) -> None:
        collector = MetricsCollector(agent_id="test")
        evaluator = AgentEvaluator(collector=collector)
        for success in [True, True, False]:
            result = FakeExecutionResult(success=success)
            goal = _make_goal()
            evaluator.evaluate(result, goal, agent_id="test")
        assert collector.count == 3
        agg = collector.aggregate()
        assert agg["total_runs"] == 3

    def test_cost_estimation(self) -> None:
        result = FakeExecutionResult(success=True, total_tokens=10_000)
        goal = _make_goal()
        report = self.evaluator.evaluate(result, goal, model="gpt-4o")
        assert report.metrics.estimated_cost_usd > 0

    def test_run_id_auto_generated(self) -> None:
        result = FakeExecutionResult(success=True)
        goal = _make_goal()
        report = self.evaluator.evaluate(result, goal)
        assert report.run_id != ""
        assert len(report.run_id) == 8


class TestEvaluationReport:
    def test_has_critical_failures(self) -> None:
        report = EvaluationReport(
            failures=[
                FailureRecord(
                    category=FailureCategory.CONSTRAINT_SAFETY_VIOLATION,
                    severity="critical",
                    message="PII exposed",
                )
            ]
        )
        assert report.has_critical_failures is True

    def test_no_critical_failures(self) -> None:
        report = EvaluationReport(
            failures=[
                FailureRecord(
                    category=FailureCategory.TOOL_TIMEOUT,
                    severity="low",
                    message="timeout",
                )
            ]
        )
        assert report.has_critical_failures is False

    def test_requires_graph_evolution(self) -> None:
        report = EvaluationReport(
            failures=[
                FailureRecord(
                    category=FailureCategory.GRAPH_DEAD_END,
                    severity="high",
                    message="dead end",
                )
            ]
        )
        assert report.requires_graph_evolution is True

    def test_top_recommendation(self) -> None:
        report = EvaluationReport(
            recommendations=[
                EvolutionRecommendation(
                    stage=EvolutionStage.AGENT,
                    priority=RecommendationPriority.HIGH,
                    action="Fix dead end",
                    description="Add fallback edge",
                ),
            ]
        )
        assert report.top_recommendation is not None
        assert report.top_recommendation.action == "Fix dead end"

    def test_to_summary_dict(self) -> None:
        report = EvaluationReport(run_id="r1", passed=True, summary="All good")
        d = report.to_summary_dict()
        assert d["passed"] is True
        assert d["run_id"] == "r1"

    def test_to_coding_agent_prompt(self) -> None:
        report = EvaluationReport(
            passed=False,
            summary="1/2 criteria met",
            metrics=EvaluationMetrics(
                total_tokens=5000,
                total_latency_ms=3000,
                criteria_met=1,
                criteria_total=2,
            ),
            failures=[
                FailureRecord(
                    category=FailureCategory.LLM_HALLUCINATION,
                    severity="high",
                    message="Output not grounded",
                )
            ],
            recommendations=[
                EvolutionRecommendation(
                    stage=EvolutionStage.AGENT,
                    priority=RecommendationPriority.HIGH,
                    action="Add grounding check",
                    description="Validate LLM output against sources",
                ),
            ],
        )
        prompt = report.to_coding_agent_prompt()
        assert "FAILED" in prompt
        assert "hallucination" in prompt.lower()
        assert "Add grounding check" in prompt
        assert "## Recommended Actions" in prompt


class TestEvolutionRecommendation:
    def test_fields(self) -> None:
        rec = EvolutionRecommendation(
            stage=EvolutionStage.AGENT,
            priority=RecommendationPriority.HIGH,
            action="Add validator",
            description="Add output validation node",
            target_node="research-node",
            failure_category=FailureCategory.LLM_INVALID_OUTPUT,
        )
        assert rec.stage == EvolutionStage.AGENT
        assert rec.target_node == "research-node"
        assert rec.estimated_effort == "small"
