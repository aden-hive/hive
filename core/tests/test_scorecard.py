"""
Tests for Agent Outcome Scorecards.

Tests cover:
1. Schema validation (Scorecard, CriterionScore, CostMetrics, etc.)
2. ScorecardGenerator logic with mock run data
3. Health score computation and weighting
4. Trend detection algorithm
5. ScorecardDiff comparison
6. Edge cases (zero runs, single run, all failures, all successes)
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from framework.schemas.scorecard import (
    AdaptationMetrics,
    CostMetrics,
    CriterionScore,
    Scorecard,
    ScorecardDiff,
)
from framework.builder.scorecard_generator import ScorecardGenerator


# === FIXTURES ===


def make_mock_run(
    run_id: str,
    goal_id: str = "goal_001",
    status: str = "completed",
    total_tokens: int = 1000,
    total_decisions: int = 5,
    successful_decisions: int = 4,
    failed_decisions: int = 1,
    nodes_executed: list[str] | None = None,
    problems: list | None = None,
    started_at: datetime | None = None,
    output_data: dict | None = None,
):
    """Create a mock Run object for testing."""
    run = MagicMock()
    run.id = run_id
    run.goal_id = goal_id
    run.status = MagicMock()
    run.status.value = status
    run.status.__eq__ = lambda self, other: self.value == (other.value if hasattr(other, 'value') else other)

    # Make status comparison work with RunStatus enum
    if status == "completed":
        from framework.schemas.run import RunStatus
        run.status = RunStatus.COMPLETED
    elif status == "failed":
        from framework.schemas.run import RunStatus
        run.status = RunStatus.FAILED

    run.started_at = started_at or datetime.now()
    run.completed_at = run.started_at + timedelta(seconds=30)

    # Metrics
    run.metrics = MagicMock()
    run.metrics.total_tokens = total_tokens
    run.metrics.total_decisions = total_decisions
    run.metrics.successful_decisions = successful_decisions
    run.metrics.failed_decisions = failed_decisions
    run.metrics.success_rate = (
        successful_decisions / total_decisions if total_decisions > 0 else 0.0
    )
    run.metrics.nodes_executed = nodes_executed or ["node_a", "node_b", "node_c"]

    # Problems
    run.problems = problems or []

    # Decisions (with confidence)
    run.decisions = []
    for i in range(total_decisions):
        dec = MagicMock()
        dec.evaluation = MagicMock()
        dec.evaluation.confidence = 0.8 + (i * 0.02)
        dec.was_successful = i < successful_decisions
        dec.outcome = MagicMock()
        dec.outcome.error = None if dec.was_successful else "test error"
        run.decisions.append(dec)

    # Output data
    run.output_data = output_data or {}

    return run


# === SCHEMA TESTS ===


class TestCriterionScore:
    def test_valid_creation(self):
        cs = CriterionScore(
            criterion_id="crit_001",
            description="Output contains required fields",
            achievement_rate=0.85,
            trend="improving",
            sample_size=10,
        )
        assert cs.achievement_rate == 0.85
        assert cs.trend == "improving"

    def test_achievement_rate_bounds(self):
        with pytest.raises(Exception):
            CriterionScore(
                criterion_id="crit_001",
                description="test",
                achievement_rate=1.5,  # > 1.0
                trend="stable",
                sample_size=5,
            )


class TestCostMetrics:
    def test_valid_creation(self):
        cm = CostMetrics(
            total_spend_tokens=5000,
            avg_tokens_per_run=1000.0,
            cost_trend="decreasing",
            cheapest_run_tokens=500,
            most_expensive_run_tokens=2000,
        )
        assert cm.total_spend_tokens == 5000
        assert cm.cost_trend == "decreasing"


class TestScorecard:
    def test_health_label_healthy(self):
        sc = Scorecard(
            agent_name="test_agent",
            goal_id="goal_001",
            time_window="all_time",
            runs_analyzed=10,
            overall_health=85,
            goal_achievement_rate=0.9,
            criteria_scores=[],
            cost_metrics=CostMetrics(
                total_spend_tokens=10000,
                avg_tokens_per_run=1000.0,
                cost_trend="stable",
                cheapest_run_tokens=500,
                most_expensive_run_tokens=1500,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=3,
                failure_modes_resolved=2,
                failure_modes_remaining=1,
                avg_decision_confidence=0.85,
                confidence_trend="improving",
            ),
        )
        assert sc.health_label == "healthy"

    def test_health_label_needs_attention(self):
        sc = Scorecard(
            agent_name="test_agent",
            goal_id="goal_001",
            time_window="all_time",
            runs_analyzed=10,
            overall_health=60,
            goal_achievement_rate=0.6,
            criteria_scores=[],
            cost_metrics=CostMetrics(
                total_spend_tokens=10000,
                avg_tokens_per_run=1000.0,
                cost_trend="stable",
                cheapest_run_tokens=500,
                most_expensive_run_tokens=1500,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=2,
                failure_modes_resolved=0,
                failure_modes_remaining=3,
                avg_decision_confidence=0.5,
                confidence_trend="declining",
            ),
        )
        assert sc.health_label == "needs_attention"

    def test_health_label_critical(self):
        sc = Scorecard(
            agent_name="test_agent",
            goal_id="goal_001",
            time_window="all_time",
            runs_analyzed=10,
            overall_health=30,
            goal_achievement_rate=0.2,
            criteria_scores=[],
            cost_metrics=CostMetrics(
                total_spend_tokens=50000,
                avg_tokens_per_run=5000.0,
                cost_trend="increasing",
                cheapest_run_tokens=3000,
                most_expensive_run_tokens=8000,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=1,
                failure_modes_resolved=0,
                failure_modes_remaining=5,
                avg_decision_confidence=0.3,
                confidence_trend="declining",
            ),
        )
        assert sc.health_label == "critical"

    def test_json_serialization(self):
        sc = Scorecard(
            agent_name="test_agent",
            goal_id="goal_001",
            time_window="all_time",
            runs_analyzed=5,
            overall_health=75,
            goal_achievement_rate=0.8,
            criteria_scores=[
                CriterionScore(
                    criterion_id="c1",
                    description="Test criterion",
                    achievement_rate=0.8,
                    trend="improving",
                    sample_size=5,
                )
            ],
            cost_metrics=CostMetrics(
                total_spend_tokens=5000,
                avg_tokens_per_run=1000.0,
                cost_trend="stable",
                cheapest_run_tokens=500,
                most_expensive_run_tokens=1500,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=2,
                failure_modes_resolved=1,
                failure_modes_remaining=1,
                avg_decision_confidence=0.75,
                confidence_trend="stable",
            ),
        )
        json_str = sc.model_dump_json(indent=2)
        parsed = json.loads(json_str)
        assert parsed["agent_name"] == "test_agent"
        assert parsed["health_label"] == "needs_attention"

    def test_table_output(self):
        sc = Scorecard(
            agent_name="test_agent",
            goal_id="goal_001",
            time_window="last_7_days",
            runs_analyzed=10,
            overall_health=85,
            goal_achievement_rate=0.9,
            criteria_scores=[],
            cost_metrics=CostMetrics(
                total_spend_tokens=10000,
                avg_tokens_per_run=1000.0,
                cost_trend="decreasing",
                cheapest_run_tokens=500,
                most_expensive_run_tokens=1500,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=3,
                failure_modes_resolved=2,
                failure_modes_remaining=0,
                avg_decision_confidence=0.85,
                confidence_trend="improving",
            ),
        )
        table = sc.to_table_str()
        assert "test_agent" in table
        assert "HEALTHY" in table
        assert "90.0%" in table


# === GENERATOR TESTS ===


class TestScorecardGenerator:
    @patch("framework.builder.scorecard_generator.FileStorage")
    @patch("framework.builder.scorecard_generator.BuilderQuery")
    def test_generate_basic(self, MockQuery, MockStorage):
        """Test basic scorecard generation with mock runs."""
        # Setup mocks
        mock_storage = MockStorage.return_value
        mock_query = MockQuery.return_value

        runs = [
            make_mock_run(f"run_{i}", status="completed" if i < 8 else "failed")
            for i in range(10)
        ]

        mock_storage.get_runs_by_goal.return_value = [r.id for r in runs]
        mock_storage.load_run.side_effect = lambda rid: next(
            (r for r in runs if r.id == rid), None
        )

        # Pattern analysis mock
        mock_patterns = MagicMock()
        mock_patterns.success_rate = 0.8
        mock_query.find_patterns.return_value = mock_patterns

        generator = ScorecardGenerator("/fake/path")
        generator.query = mock_query
        generator.storage = mock_storage

        scorecard = generator.generate("test_agent", "goal_001")

        assert scorecard.agent_name == "test_agent"
        assert scorecard.goal_id == "goal_001"
        assert scorecard.runs_analyzed == 10
        assert scorecard.goal_achievement_rate == 0.8

    @patch("framework.builder.scorecard_generator.FileStorage")
    @patch("framework.builder.scorecard_generator.BuilderQuery")
    def test_generate_no_runs_raises(self, MockQuery, MockStorage):
        """Test that generating with no runs raises ValueError."""
        mock_storage = MockStorage.return_value
        mock_storage.get_runs_by_goal.return_value = []

        generator = ScorecardGenerator("/fake/path")
        generator.storage = mock_storage

        with pytest.raises(ValueError, match="No runs found"):
            generator.generate("test_agent", "goal_001")


class TestTrendDetection:
    def test_improving_trend(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        values = [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9]
        assert generator._compute_trend(values) == "improving"

    def test_declining_trend(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        values = [0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
        assert generator._compute_trend(values) == "declining"

    def test_stable_trend(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        values = [0.7, 0.72, 0.68, 0.71, 0.69, 0.70, 0.71, 0.70]
        assert generator._compute_trend(values) == "stable"

    def test_too_few_values(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        values = [0.5, 0.9]
        assert generator._compute_trend(values) == "stable"

    def test_cost_trend_lower_is_better(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        values = [1000, 900, 800, 700, 600, 500, 400, 300]
        assert generator._compute_trend(values, lower_is_better=True) == "improving"


class TestHealthComputation:
    def test_perfect_health(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        health = generator._compute_health(
            achievement_rate=1.0,
            cost_metrics=CostMetrics(
                total_spend_tokens=1000,
                avg_tokens_per_run=100,
                cost_trend="decreasing",
                cheapest_run_tokens=50,
                most_expensive_run_tokens=200,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=3,
                failure_modes_resolved=5,
                failure_modes_remaining=0,
                avg_decision_confidence=1.0,
                confidence_trend="improving",
            ),
        )
        assert health == 100

    def test_worst_health(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)
        health = generator._compute_health(
            achievement_rate=0.0,
            cost_metrics=CostMetrics(
                total_spend_tokens=100000,
                avg_tokens_per_run=10000,
                cost_trend="increasing",
                cheapest_run_tokens=8000,
                most_expensive_run_tokens=15000,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=1,
                failure_modes_resolved=0,
                failure_modes_remaining=10,
                avg_decision_confidence=0.0,
                confidence_trend="declining",
            ),
        )
        assert health == 5  # Only gets 5 from cost_score (increasing)


class TestScorecardComparison:
    def test_improvement_detected(self):
        generator = ScorecardGenerator.__new__(ScorecardGenerator)

        before = Scorecard(
            agent_name="test",
            goal_id="g1",
            time_window="all_time",
            runs_analyzed=5,
            overall_health=50,
            goal_achievement_rate=0.5,
            criteria_scores=[],
            cost_metrics=CostMetrics(
                total_spend_tokens=5000,
                avg_tokens_per_run=1000,
                cost_trend="stable",
                cheapest_run_tokens=500,
                most_expensive_run_tokens=1500,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=1,
                failure_modes_resolved=0,
                failure_modes_remaining=3,
                avg_decision_confidence=0.6,
                confidence_trend="stable",
            ),
        )

        after = Scorecard(
            agent_name="test",
            goal_id="g1",
            time_window="all_time",
            runs_analyzed=10,
            overall_health=80,
            goal_achievement_rate=0.85,
            criteria_scores=[],
            cost_metrics=CostMetrics(
                total_spend_tokens=8000,
                avg_tokens_per_run=800,
                cost_trend="decreasing",
                cheapest_run_tokens=400,
                most_expensive_run_tokens=1200,
            ),
            adaptation_metrics=AdaptationMetrics(
                total_graph_versions=3,
                failure_modes_resolved=2,
                failure_modes_remaining=1,
                avg_decision_confidence=0.85,
                confidence_trend="improving",
            ),
        )

        diff = generator.compare(before, after)

        assert diff.health_delta == 30
        assert diff.achievement_delta == pytest.approx(0.35)
        assert diff.cost_delta == pytest.approx(-200)
        assert len(diff.improvements) > 0
        assert any("achievement" in imp.lower() for imp in diff.improvements)
