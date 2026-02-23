"""
Test the failure taxonomy module.
"""

from datetime import datetime

from framework.schemas.decision import Decision, Option, Outcome
from framework.schemas.failure_taxonomy import (
    ClassifiedFailure,
    FailureCategory,
    FailureDistribution,
    EvolutionStrategy,
    FAILURE_CATEGORY_TO_STRATEGY,
    CATEGORY_DESCRIPTIONS,
    STRATEGY_DESCRIPTIONS,
)
from framework.schemas.run import Problem, Run, RunStatus
from framework.builder.failure_classifier import FailureClassifier


class TestFailureCategory:
    """Test the FailureCategory enum."""

    def test_all_categories_exist(self):
        expected = [
            "goal_ambiguity",
            "tool_error",
            "routing_error",
            "output_quality",
            "cost_overrun",
            "timeout",
            "hallucination",
            "constraint_violation",
            "external_dependency",
            "unknown",
        ]
        for cat in expected:
            assert FailureCategory(cat)

    def test_category_values(self):
        assert FailureCategory.GOAL_AMBIGUITY.value == "goal_ambiguity"
        assert FailureCategory.TOOL_ERROR.value == "tool_error"
        assert FailureCategory.TIMEOUT.value == "timeout"


class TestEvolutionStrategy:
    """Test the EvolutionStrategy enum."""

    def test_all_strategies_exist(self):
        expected = [
            "refine_goal",
            "add_retry",
            "modify_edges",
            "refine_prompts",
            "reduce_cost",
            "parallelize",
            "add_grounding",
            "add_constraints",
            "investigate",
        ]
        for strat in expected:
            assert EvolutionStrategy(strat)


class TestCategoryToStrategyMapping:
    """Test the mapping between failure categories and evolution strategies."""

    def test_all_categories_have_strategies(self):
        for category in FailureCategory:
            assert category in FAILURE_CATEGORY_TO_STRATEGY

    def test_strategy_mapping_values(self):
        assert (
            FAILURE_CATEGORY_TO_STRATEGY[FailureCategory.GOAL_AMBIGUITY]
            == EvolutionStrategy.REFINE_GOAL
        )
        assert (
            FAILURE_CATEGORY_TO_STRATEGY[FailureCategory.TOOL_ERROR] == EvolutionStrategy.ADD_RETRY
        )
        assert (
            FAILURE_CATEGORY_TO_STRATEGY[FailureCategory.ROUTING_ERROR]
            == EvolutionStrategy.MODIFY_EDGES
        )
        assert (
            FAILURE_CATEGORY_TO_STRATEGY[FailureCategory.TIMEOUT] == EvolutionStrategy.PARALLELIZE
        )
        assert (
            FAILURE_CATEGORY_TO_STRATEGY[FailureCategory.HALLUCINATION]
            == EvolutionStrategy.ADD_GROUNDING
        )


class TestClassifiedFailure:
    """Test the ClassifiedFailure model."""

    def test_basic_creation(self):
        failure = ClassifiedFailure(
            category=FailureCategory.TOOL_ERROR,
            confidence=0.8,
            evidence=["Rate limit exceeded"],
        )
        assert failure.category == FailureCategory.TOOL_ERROR
        assert failure.confidence == 0.8
        assert failure.evidence == ["Rate limit exceeded"]
        assert failure.recommended_strategy == EvolutionStrategy.ADD_RETRY

    def test_auto_strategy_assignment(self):
        failure = ClassifiedFailure(
            category=FailureCategory.TIMEOUT,
            confidence=0.9,
            evidence=["Execution exceeded 60s limit"],
        )
        assert failure.recommended_strategy == EvolutionStrategy.PARALLELIZE

    def test_with_affected_nodes(self):
        failure = ClassifiedFailure(
            category=FailureCategory.ROUTING_ERROR,
            confidence=0.75,
            evidence=["Wrong branch taken"],
            affected_nodes=["router_node", "decision_node"],
        )
        assert failure.affected_nodes == ["router_node", "decision_node"]

    def test_to_dict(self):
        failure = ClassifiedFailure(
            category=FailureCategory.TOOL_ERROR,
            subcategory="rate_limit",
            confidence=0.85,
            evidence=["429 Too Many Requests"],
            affected_nodes=["api_caller"],
            raw_error="HTTP 429",
        )
        result = failure.to_dict()
        assert result["category"] == "tool_error"
        assert result["subcategory"] == "rate_limit"
        assert result["confidence"] == 0.85
        assert result["recommended_strategy"] == "add_retry"

    def test_str_output(self):
        failure = ClassifiedFailure(
            category=FailureCategory.TIMEOUT,
            confidence=0.9,
            evidence=["Timeout after 30s"],
        )
        output = str(failure)
        assert "timeout" in output
        assert "0.90" in output
        assert "parallelize" in output


class TestFailureDistribution:
    """Test the FailureDistribution class."""

    def test_empty_distribution(self):
        dist = FailureDistribution()
        assert dist.total_failures == 0
        assert dist.counts == {}

    def test_add_failures(self):
        dist = FailureDistribution()
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TIMEOUT)

        assert dist.total_failures == 3
        assert dist.counts["tool_error"] == 2
        assert dist.counts["timeout"] == 1

    def test_get_percentage(self):
        dist = FailureDistribution()
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TIMEOUT)
        dist.add_failure(FailureCategory.TIMEOUT)
        dist.add_failure(FailureCategory.ROUTING_ERROR)

        assert dist.get_percentage(FailureCategory.TOOL_ERROR) == 40.0
        assert dist.get_percentage(FailureCategory.TIMEOUT) == 40.0
        assert dist.get_percentage(FailureCategory.ROUTING_ERROR) == 20.0
        assert dist.get_percentage(FailureCategory.HALLUCINATION) == 0.0

    def test_get_top_categories(self):
        dist = FailureDistribution()
        for _ in range(5):
            dist.add_failure(FailureCategory.TOOL_ERROR)
        for _ in range(3):
            dist.add_failure(FailureCategory.TIMEOUT)
        dist.add_failure(FailureCategory.ROUTING_ERROR)

        top = dist.get_top_categories(limit=2)
        assert len(top) == 2
        assert top[0] == (FailureCategory.TOOL_ERROR, 5)
        assert top[1] == (FailureCategory.TIMEOUT, 3)

    def test_to_dict(self):
        dist = FailureDistribution()
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TIMEOUT)

        result = dist.to_dict()
        assert result["total_failures"] == 2
        assert result["counts"]["tool_error"] == 1
        assert result["counts"]["timeout"] == 1
        assert result["percentages"]["tool_error"] == 50.0

    def test_str_output(self):
        dist = FailureDistribution()
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TOOL_ERROR)
        dist.add_failure(FailureCategory.TIMEOUT)

        output = str(dist)
        assert "3 total" in output
        assert "tool_error" in output


class TestFailureClassifier:
    """Test the FailureClassifier class."""

    def test_classify_timeout_failure(self):
        classifier = FailureClassifier()
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            started_at=datetime.now(),
        )
        run.add_problem(
            severity="critical",
            description="Operation timed out after 60 seconds",
            root_cause="timeout exceeded",
        )

        result = classifier.classify(run)
        assert result is not None
        assert result.category == FailureCategory.TIMEOUT
        assert result.confidence >= 0.5

    def test_classify_tool_error(self):
        classifier = FailureClassifier()
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            started_at=datetime.now(),
        )
        run.add_problem(
            severity="critical",
            description="API call failed with 429 Too Many Requests",
            root_cause="Rate limit exceeded",
        )

        result = classifier.classify(run)
        assert result is not None
        assert result.category == FailureCategory.TOOL_ERROR

    def test_classify_cost_overrun(self):
        classifier = FailureClassifier()
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            started_at=datetime.now(),
        )
        run.add_problem(
            severity="critical",
            description="Budget exceeded for this operation",
            root_cause="Token cost limit reached",
        )

        result = classifier.classify(run)
        assert result is not None
        assert result.category == FailureCategory.COST_OVERRUN

    def test_classify_constraint_violation(self):
        classifier = FailureClassifier()
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            started_at=datetime.now(),
        )
        run.add_problem(
            severity="critical",
            description="Request forbidden - unauthorized access",
            root_cause="403 Forbidden",
        )

        result = classifier.classify(run)
        assert result is not None
        assert result.category == FailureCategory.CONSTRAINT_VIOLATION

    def test_classify_no_failure_returns_none(self):
        classifier = FailureClassifier()
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.COMPLETED,
            started_at=datetime.now(),
        )

        result = classifier.classify(run)
        assert result is None

    def test_classify_unknown_failure(self):
        classifier = FailureClassifier()
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            started_at=datetime.now(),
        )
        run.add_problem(
            severity="critical",
            description="Something unexpected happened",
            root_cause="Unknown",
        )

        result = classifier.classify(run)
        assert result is not None
        assert result.category == FailureCategory.UNKNOWN

    def test_classify_problem_directly(self):
        classifier = FailureClassifier()
        problem = Problem(
            id="prob_1",
            severity="critical",
            description="Connection timeout to external service",
            root_cause="timeout",
        )

        result = classifier.classify_problem(problem)
        assert result.category == FailureCategory.TIMEOUT

    def test_confidence_threshold(self):
        classifier = FailureClassifier(confidence_threshold=0.9)
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            started_at=datetime.now(),
        )
        run.add_problem(
            severity="warning",
            description="Something might be wrong",
            root_cause="Unclear",
        )

        result = classifier.classify(run)
        assert result is not None


class TestRunWithClassifiedFailure:
    """Test Run model with classified_failure field."""

    def test_run_with_classified_failure(self):
        classified = ClassifiedFailure(
            category=FailureCategory.TOOL_ERROR,
            confidence=0.85,
            evidence=["Rate limit exceeded"],
        )
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.FAILED,
            classified_failure=classified,
        )
        assert run.classified_failure is not None
        assert run.classified_failure.category == FailureCategory.TOOL_ERROR

    def test_run_without_classified_failure(self):
        run = Run(
            id="test_run",
            goal_id="test_goal",
            status=RunStatus.COMPLETED,
        )
        assert run.classified_failure is None
