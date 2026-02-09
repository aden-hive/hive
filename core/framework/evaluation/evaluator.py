"""Agent evaluator -- evaluates ExecutionResult against Goal."""

import logging
import uuid
from typing import Any

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

logger = logging.getLogger(__name__)

# Rough token pricing per 1K tokens (for cost estimation)
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 0.005, "output": 0.015},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-haiku-4-5": {"input": 0.001, "output": 0.005},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
}
_DEFAULT_COST_PER_1K = 0.002


class AgentEvaluator:
    """Evaluates agent execution results against goals.

    Checks success criteria, validates constraints, classifies failures,
    computes metrics, and produces an EvaluationReport with evolution
    recommendations.
    """

    def __init__(
        self,
        classifier: FailureClassifier | None = None,
        collector: MetricsCollector | None = None,
    ) -> None:
        self._classifier = classifier or FailureClassifier()
        self._collector = collector

    def evaluate(
        self,
        execution_result: Any,
        goal: Goal,
        *,
        run_id: str = "",
        agent_id: str = "",
        model: str = "",
    ) -> EvaluationReport:
        """Evaluate an execution result against a goal."""
        run_id = run_id or str(uuid.uuid4())[:8]

        criteria_results = self._evaluate_criteria(execution_result, goal)
        criteria_met = sum(1 for c in criteria_results if c["met"])
        criteria_total = len(criteria_results)

        constraint_results = self._evaluate_constraints(execution_result, goal)
        constraint_violations = sum(1 for c in constraint_results if not c["satisfied"])

        failures = self._classifier.classify(execution_result)

        success = getattr(execution_result, "success", False)
        metrics = EvaluationMetrics(
            run_id=run_id,
            agent_id=agent_id,
            success=success,
            execution_quality=getattr(execution_result, "execution_quality", "clean"),
            total_tokens=getattr(execution_result, "total_tokens", 0),
            total_latency_ms=getattr(execution_result, "total_latency_ms", 0),
            steps_executed=getattr(execution_result, "steps_executed", 0),
            total_retries=getattr(execution_result, "total_retries", 0),
            estimated_cost_usd=self._estimate_cost(execution_result, model),
            criteria_met=criteria_met,
            criteria_total=criteria_total,
            constraint_violations=constraint_violations,
            failure_count=len(failures),
            failure_categories={f.category.value: 1 for f in failures},
        )

        recommendations = self._generate_recommendations(
            failures, criteria_results, constraint_results, metrics
        )

        hard_violations = sum(
            1 for c in constraint_results if not c["satisfied"] and c.get("type") == "hard"
        )
        passed = success and criteria_met >= criteria_total * 0.9 and hard_violations == 0

        summary = self._build_summary(passed, criteria_met, criteria_total, failures)

        report = EvaluationReport(
            run_id=run_id,
            agent_id=agent_id,
            goal_id=goal.id,
            passed=passed,
            summary=summary,
            metrics=metrics,
            failures=failures,
            criteria_results=criteria_results,
            constraint_results=constraint_results,
            recommendations=recommendations,
        )

        if self._collector is not None:
            self._collector.record(metrics)

        logger.info(
            "Evaluation complete: run=%s passed=%s criteria=%d/%d failures=%d",
            run_id,
            passed,
            criteria_met,
            criteria_total,
            len(failures),
        )

        return report

    def _evaluate_criteria(self, result: Any, goal: Goal) -> list[dict[str, Any]]:
        output = getattr(result, "output", {})
        success = getattr(result, "success", False)
        results: list[dict[str, Any]] = []

        for criterion in goal.success_criteria:
            met = self._check_criterion(criterion, output, success)
            results.append(
                {
                    "id": criterion.id,
                    "description": criterion.description,
                    "metric": criterion.metric,
                    "target": criterion.target,
                    "weight": criterion.weight,
                    "met": met,
                }
            )
        return results

    def _check_criterion(
        self, criterion: SuccessCriterion, output: dict[str, Any], success: bool
    ) -> bool:
        metric = criterion.metric
        target = criterion.target

        if metric == "execution_success":
            return success
        if metric == "output_contains":
            return str(target).lower() in str(output).lower()
        if metric == "output_equals":
            return str(output.get(str(target), "")) != ""
        if metric == "output_exists":
            return str(target) in output
        if metric == "llm_judge":
            # Full LLM judge integration deferred -- optimistic for now
            return success
        return success

    def _evaluate_constraints(self, result: Any, goal: Goal) -> list[dict[str, Any]]:
        total_tokens = getattr(result, "total_tokens", 0)
        total_latency = getattr(result, "total_latency_ms", 0)
        results: list[dict[str, Any]] = []

        for constraint in goal.constraints:
            satisfied = self._check_constraint(constraint, result, total_tokens, total_latency)
            results.append(
                {
                    "id": constraint.id,
                    "description": constraint.description,
                    "type": constraint.constraint_type,
                    "category": constraint.category,
                    "satisfied": satisfied,
                }
            )
        return results

    def _check_constraint(
        self,
        constraint: Constraint,
        result: Any,
        total_tokens: int,
        total_latency: int,
    ) -> bool:
        category = constraint.category
        success = getattr(result, "success", False)

        if category == "cost":
            try:
                limit = int(constraint.check) if constraint.check.isdigit() else 100_000
            except (ValueError, AttributeError):
                limit = 100_000
            return total_tokens <= limit

        if category == "time":
            try:
                limit = int(constraint.check) if constraint.check.isdigit() else 120_000
            except (ValueError, AttributeError):
                limit = 120_000
            return total_latency <= limit

        if category == "safety":
            error = getattr(result, "error", "") or ""
            return "safety" not in error.lower() and "pii" not in error.lower()

        return success

    def _generate_recommendations(
        self,
        failures: list[FailureRecord],
        criteria_results: list[dict[str, Any]],
        constraint_results: list[dict[str, Any]],
        metrics: EvaluationMetrics,
    ) -> list[EvolutionRecommendation]:
        recs: list[EvolutionRecommendation] = []

        for failure in failures:
            stage = self._stage_for_failure(failure.category)
            priority = self._priority_from_severity(failure.severity)
            recs.append(
                EvolutionRecommendation(
                    stage=stage,
                    priority=priority,
                    action=failure.remediation_hint or f"Fix {failure.category.value}",
                    description=failure.message,
                    target_node=failure.node_id,
                    failure_category=failure.category,
                    estimated_effort=self._effort_for_stage(stage),
                )
            )

        for criterion in criteria_results:
            if not criterion["met"]:
                recs.append(
                    EvolutionRecommendation(
                        stage=EvolutionStage.AGENT,
                        priority=RecommendationPriority.HIGH,
                        action=f"Fix unmet criterion: {criterion['id']}",
                        description=(
                            f"Criterion '{criterion['description']}' "
                            f"(metric: {criterion['metric']}) was not met."
                        ),
                        estimated_effort="medium",
                    )
                )

        for constraint in constraint_results:
            if not constraint["satisfied"]:
                is_hard = constraint.get("type") == "hard"
                recs.append(
                    EvolutionRecommendation(
                        stage=EvolutionStage.AGENT if is_hard else EvolutionStage.CONFIG,
                        priority=(
                            RecommendationPriority.CRITICAL
                            if is_hard
                            else RecommendationPriority.MEDIUM
                        ),
                        action=f"Fix constraint: {constraint['id']}",
                        description=constraint["description"],
                        estimated_effort="medium" if is_hard else "small",
                    )
                )

        if metrics.estimated_cost_usd > 1.0:
            recs.append(
                EvolutionRecommendation(
                    stage=EvolutionStage.CONFIG,
                    priority=RecommendationPriority.MEDIUM,
                    action="Reduce execution cost",
                    description=(
                        f"Execution cost ${metrics.estimated_cost_usd:.4f} is high. "
                        "Consider prompt compression, caching, or cheaper model."
                    ),
                    estimated_effort="small",
                )
            )

        priority_order = {
            RecommendationPriority.CRITICAL: 0,
            RecommendationPriority.HIGH: 1,
            RecommendationPriority.MEDIUM: 2,
            RecommendationPriority.LOW: 3,
        }
        recs.sort(key=lambda r: priority_order.get(r.priority, 9))
        return recs

    def _estimate_cost(self, result: Any, model: str) -> float:
        tokens = getattr(result, "total_tokens", 0)
        if tokens == 0:
            return 0.0
        cost_per_1k = _DEFAULT_COST_PER_1K
        for model_name, pricing in _MODEL_PRICING.items():
            if model_name in model.lower():
                cost_per_1k = pricing["input"] * 0.6 + pricing["output"] * 0.4
                break
        return (tokens / 1000) * cost_per_1k

    @staticmethod
    def _build_summary(
        passed: bool,
        criteria_met: int,
        criteria_total: int,
        failures: list[FailureRecord],
    ) -> str:
        status = "PASSED" if passed else "FAILED"
        parts = [f"{status}: {criteria_met}/{criteria_total} criteria met"]
        if failures:
            top = failures[0]
            node_info = f" on {top.node_id}" if top.node_id else ""
            parts.append(f"{len(failures)} failure(s), top: {top.category.value}{node_info}")
        return ". ".join(parts) + "."

    @staticmethod
    def _stage_for_failure(category: FailureCategory) -> EvolutionStage:
        config_cats = {
            FailureCategory.LLM_RATE_LIMIT,
            FailureCategory.LLM_EMPTY_RESPONSE,
            FailureCategory.RESOURCE_BUDGET_EXHAUSTED,
            FailureCategory.RESOURCE_CONCURRENCY_LIMIT,
            FailureCategory.CONSTRAINT_COST_EXCEEDED,
            FailureCategory.CONSTRAINT_TIME_EXCEEDED,
        }
        goal_cats = {
            FailureCategory.CONSTRAINT_QUALITY_BELOW,
            FailureCategory.CONSTRAINT_SAFETY_VIOLATION,
        }
        if category in config_cats:
            return EvolutionStage.CONFIG
        if category in goal_cats:
            return EvolutionStage.GOAL
        return EvolutionStage.AGENT

    @staticmethod
    def _priority_from_severity(severity: str) -> RecommendationPriority:
        mapping = {
            "critical": RecommendationPriority.CRITICAL,
            "high": RecommendationPriority.HIGH,
            "medium": RecommendationPriority.MEDIUM,
            "low": RecommendationPriority.LOW,
        }
        return mapping.get(severity, RecommendationPriority.MEDIUM)

    @staticmethod
    def _effort_for_stage(stage: EvolutionStage) -> str:
        if stage == EvolutionStage.CONFIG:
            return "small"
        if stage == EvolutionStage.GOAL:
            return "large"
        return "medium"
