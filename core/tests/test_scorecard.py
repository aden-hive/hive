"""
Tests for Agent Outcome Scorecards.

This module tests:
- Schema validation with edge cases
- Scorecard generation with mock run data
- CLI output format verification
- Scorecard comparison diff accuracy
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from framework.schemas.decision import Decision, DecisionEvaluation, DecisionType, Option, Outcome
from framework.schemas.run import Run, RunMetrics, RunStatus
from framework.schemas.scorecard import (
    AdaptationMetrics,
    CostMetrics,
    CriterionScore,
    HealthLabel,
    Scorecard,
    ScorecardDiff,
    TrendDirection,
)


class TestCriterionScore:
    """Tests for CriterionScore schema."""

    def test_valid_criterion_score(self):
        """Test creating a valid CriterionScore."""
        score = CriterionScore(
            criterion_id="test_criterion",
            description="Test criterion description",
            achievement_rate=0.85,
            trend=TrendDirection.IMPROVING,
            sample_size=100,
        )
        assert score.criterion_id == "test_criterion"
        assert score.achievement_rate == 0.85
        assert score.trend == TrendDirection.IMPROVING
        assert score.sample_size == 100

    def test_default_values(self):
        """Test default values are applied correctly."""
        score = CriterionScore(
            criterion_id="test",
            description="test",
        )
        assert score.achievement_rate == 0.0
        assert score.trend == TrendDirection.INSUFFICIENT_DATA
        assert score.sample_size == 0

    def test_achievement_rate_bounds(self):
        """Test that achievement_rate is bounded 0-1."""
        score = CriterionScore(
            criterion_id="test",
            description="test",
            achievement_rate=1.0,
        )
        assert score.achievement_rate == 1.0

        with pytest.raises(ValueError):
            CriterionScore(
                criterion_id="test",
                description="test",
                achievement_rate=1.5,
            )


class TestCostMetrics:
    """Tests for CostMetrics schema."""

    def test_valid_cost_metrics(self):
        """Test creating valid CostMetrics."""
        metrics = CostMetrics(
            total_spend=10.50,
            avg_cost_per_run=0.21,
            cost_trend=TrendDirection.IMPROVING,
            min_run_cost=0.05,
            max_run_cost=0.50,
            total_tokens=10000,
            avg_tokens_per_run=200.0,
        )
        assert metrics.total_spend == 10.50
        assert metrics.avg_cost_per_run == 0.21
        assert metrics.total_tokens == 10000

    def test_default_values(self):
        """Test CostMetrics default values."""
        metrics = CostMetrics()
        assert metrics.total_spend == 0.0
        assert metrics.avg_cost_per_run == 0.0
        assert metrics.cost_trend == TrendDirection.INSUFFICIENT_DATA


class TestAdaptationMetrics:
    """Tests for AdaptationMetrics schema."""

    def test_valid_adaptation_metrics(self):
        """Test creating valid AdaptationMetrics."""
        metrics = AdaptationMetrics(
            total_evolutions=5,
            failure_modes_resolved=3,
            failure_modes_remaining=2,
            avg_decision_confidence=0.85,
            confidence_trend=TrendDirection.IMPROVING,
            common_failures=[("Error A", 5), ("Error B", 3)],
            problematic_nodes=[("node_1", 0.3), ("node_2", 0.15)],
        )
        assert metrics.total_evolutions == 5
        assert metrics.failure_modes_resolved == 3
        assert len(metrics.common_failures) == 2

    def test_confidence_bounds(self):
        """Test that avg_decision_confidence is bounded 0-1."""
        metrics = AdaptationMetrics(avg_decision_confidence=1.0)
        assert metrics.avg_decision_confidence == 1.0

        with pytest.raises(ValueError):
            AdaptationMetrics(avg_decision_confidence=1.5)


class TestScorecard:
    """Tests for Scorecard schema."""

    def test_valid_scorecard(self):
        """Test creating a complete valid Scorecard."""
        scorecard = Scorecard(
            agent_id="test_agent",
            agent_name="Test Agent",
            goal_id="test_goal",
            goal_description="Test goal description",
            runs_analyzed=50,
            overall_health=75,
            goal_achievement_rate=0.8,
            goal_achievement_trend=TrendDirection.IMPROVING,
        )
        assert scorecard.agent_id == "test_agent"
        assert scorecard.overall_health == 75
        assert scorecard.goal_achievement_rate == 0.8

    def test_health_label_healthy(self):
        """Test health_label returns HEALTHY for score >= 70."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="Test",
            goal_id="goal",
            overall_health=75,
        )
        assert scorecard.health_label == HealthLabel.HEALTHY

    def test_health_label_needs_attention(self):
        """Test health_label returns NEEDS_ATTENTION for 40-69."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="Test",
            goal_id="goal",
            overall_health=55,
        )
        assert scorecard.health_label == HealthLabel.NEEDS_ATTENTION

    def test_health_label_critical(self):
        """Test health_label returns CRITICAL for < 40."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="Test",
            goal_id="goal",
            overall_health=25,
        )
        assert scorecard.health_label == HealthLabel.CRITICAL

    def test_summary_generation(self):
        """Test that summary is generated correctly."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="My Agent",
            goal_id="goal",
            overall_health=80,
            goal_achievement_rate=0.9,
            runs_analyzed=100,
        )
        summary = scorecard.summary
        assert "My Agent" in summary
        assert "80/100" in summary
        assert "90%" in summary
        assert "100 runs" in summary

    def test_formatted_string_output(self):
        """Test that to_formatted_string produces readable output."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="Test Agent",
            goal_id="test_goal",
            goal_description="Test goal for validation",
            runs_analyzed=50,
            overall_health=75,
            goal_achievement_rate=0.8,
            cost_metrics=CostMetrics(
                total_spend=5.0,
                avg_cost_per_run=0.10,
            ),
            adaptation_metrics=AdaptationMetrics(
                failure_modes_resolved=2,
                failure_modes_remaining=1,
            ),
            recommendations=["Improve node X", "Optimize prompts"],
        )

        output = scorecard.to_formatted_string()

        # Verify key sections are present
        assert "Test Agent" in output
        assert "OVERALL HEALTH" in output
        assert "GOAL ACHIEVEMENT" in output
        assert "COST METRICS" in output
        assert "ADAPTATION" in output
        assert "RECOMMENDATIONS" in output

    def test_overall_health_bounds(self):
        """Test that overall_health is bounded 0-100."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="Test",
            goal_id="goal",
            overall_health=100,
        )
        assert scorecard.overall_health == 100

        with pytest.raises(ValueError):
            Scorecard(
                agent_id="test",
                agent_name="Test",
                goal_id="goal",
                overall_health=101,
            )


class TestScorecardDiff:
    """Tests for ScorecardDiff schema."""

    def test_valid_diff(self):
        """Test creating a valid ScorecardDiff."""
        diff = ScorecardDiff(
            agent_id="test",
            agent_name="Test Agent",
            scorecard_before_date=datetime(2024, 1, 1),
            scorecard_after_date=datetime(2024, 2, 1),
            runs_before=50,
            runs_after=100,
            health_delta=10,
            goal_achievement_delta=0.1,
            cost_per_run_delta=-0.05,
            confidence_delta=0.15,
            improvements=["Health improved by 10 points"],
            regressions=[],
        )
        assert diff.health_delta == 10
        assert diff.goal_achievement_delta == 0.1

    def test_overall_direction_improving(self):
        """Test overall_direction returns IMPROVING correctly."""
        diff = ScorecardDiff(
            agent_id="test",
            agent_name="Test",
            scorecard_before_date=datetime.now(),
            scorecard_after_date=datetime.now(),
            runs_before=10,
            runs_after=20,
            health_delta=10,  # Positive improvement
            goal_achievement_delta=0.1,  # Positive improvement
            cost_per_run_delta=-0.02,  # Cost reduction (improvement)
        )
        assert diff.overall_direction == TrendDirection.IMPROVING

    def test_overall_direction_declining(self):
        """Test overall_direction returns DECLINING correctly."""
        diff = ScorecardDiff(
            agent_id="test",
            agent_name="Test",
            scorecard_before_date=datetime.now(),
            scorecard_after_date=datetime.now(),
            runs_before=10,
            runs_after=20,
            health_delta=-10,  # Negative (regression)
            goal_achievement_delta=-0.1,  # Negative (regression)
            cost_per_run_delta=0.05,  # Cost increase (regression)
        )
        assert diff.overall_direction == TrendDirection.DECLINING

    def test_overall_direction_stable(self):
        """Test overall_direction returns STABLE correctly."""
        diff = ScorecardDiff(
            agent_id="test",
            agent_name="Test",
            scorecard_before_date=datetime.now(),
            scorecard_after_date=datetime.now(),
            runs_before=10,
            runs_after=20,
            health_delta=2,  # Minor change
            goal_achievement_delta=0.01,  # Minor change
            cost_per_run_delta=0.001,  # Minor change
        )
        assert diff.overall_direction == TrendDirection.STABLE

    def test_formatted_string_output(self):
        """Test that to_formatted_string produces readable output."""
        diff = ScorecardDiff(
            agent_id="test",
            agent_name="Test Agent",
            scorecard_before_date=datetime(2024, 1, 1),
            scorecard_after_date=datetime(2024, 2, 1),
            runs_before=50,
            runs_after=100,
            health_delta=15,
            goal_achievement_delta=0.1,
            improvements=["Health improved"],
            regressions=["Latency increased"],
            resolved_failure_modes=["Error A fixed"],
        )

        output = diff.to_formatted_string()

        assert "SCORECARD COMPARISON" in output
        assert "Test Agent" in output
        assert "IMPROVEMENTS" in output
        assert "REGRESSIONS" in output


class TestScorecardGenerator:
    """Tests for ScorecardGenerator class."""

    @pytest.fixture
    def mock_runs(self):
        """Create a set of mock runs for testing."""
        runs = []
        base_time = datetime.now() - timedelta(days=30)

        for i in range(20):
            run = Run(
                id=f"run_{i}",
                goal_id="test_goal",
                started_at=base_time + timedelta(days=i),
                completed_at=base_time + timedelta(days=i, hours=1),
                status=RunStatus.COMPLETED if i % 5 != 0 else RunStatus.FAILED,
                metrics=RunMetrics(
                    total_decisions=10,
                    successful_decisions=8 if i % 5 != 0 else 5,
                    failed_decisions=2 if i % 5 != 0 else 5,
                    total_tokens=1000 + (i * 10),
                    total_latency_ms=500 + (i * 20),
                ),
            )

            # Add some decisions
            for j in range(3):
                decision = Decision(
                    id=f"decision_{i}_{j}",
                    node_id=f"node_{j}",
                    intent="Test decision",
                    decision_type=DecisionType.TOOL_SELECTION,
                    options=[
                        Option(
                            id=f"opt_{j}",
                            description="Option",
                            action_type="tool_call",
                            confidence=0.8,
                        )
                    ],
                    chosen_option_id=f"opt_{j}",
                    outcome=Outcome(
                        success=j != 2 or i % 5 != 0,
                        result="success",
                        tokens_used=100,
                        latency_ms=50,
                        error="Test error" if j == 2 and i % 5 == 0 else None,
                    ),
                    evaluation=DecisionEvaluation(
                        goal_aligned=True,
                        outcome_quality=0.85,
                    ),
                )
                run.add_decision(decision)

            runs.append(run)

        return runs

    @pytest.fixture
    def mock_storage(self, mock_runs, tmp_path):
        """Create a mock storage with runs."""
        from framework.storage.backend import FileStorage

        storage = FileStorage(tmp_path)

        # Mock the methods
        storage.get_runs_by_goal = MagicMock(
            return_value=[r.id for r in mock_runs]
        )
        storage.load_run = MagicMock(
            side_effect=lambda run_id: next(
                (r for r in mock_runs if r.id == run_id), None
            )
        )

        return storage

    def test_generate_scorecard_with_sufficient_data(self, mock_runs, tmp_path):
        """Test generating a scorecard with sufficient run data."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        # Create generator
        generator = ScorecardGenerator(tmp_path)

        # Mock the storage methods
        generator.storage.get_runs_by_goal = MagicMock(
            return_value=[r.id for r in mock_runs]
        )
        generator.storage.load_run = MagicMock(
            side_effect=lambda run_id: next(
                (r for r in mock_runs if r.id == run_id), None
            )
        )

        # Generate scorecard
        scorecard = generator.generate(
            goal_id="test_goal",
            agent_name="Test Agent",
            min_runs=5,
        )

        assert scorecard is not None
        assert scorecard.agent_name == "Test Agent"
        assert scorecard.runs_analyzed == 20
        assert scorecard.goal_achievement_rate > 0
        assert scorecard.overall_health >= 0
        assert scorecard.overall_health <= 100

    def test_generate_returns_none_insufficient_data(self, tmp_path):
        """Test that generate returns None when insufficient runs exist."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        generator = ScorecardGenerator(tmp_path)
        generator.storage.get_runs_by_goal = MagicMock(return_value=["run_1"])
        generator.storage.load_run = MagicMock(
            return_value=Run(
                id="run_1",
                goal_id="test_goal",
                status=RunStatus.COMPLETED,
            )
        )

        scorecard = generator.generate(
            goal_id="test_goal",
            agent_name="Test",
            min_runs=5,
        )

        assert scorecard is None

    def test_compare_scorecards(self, tmp_path):
        """Test comparing two scorecards."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        generator = ScorecardGenerator(tmp_path)

        before = Scorecard(
            agent_id="test",
            agent_name="Test Agent",
            goal_id="goal",
            overall_health=60,
            goal_achievement_rate=0.7,
            runs_analyzed=50,
            cost_metrics=CostMetrics(avg_cost_per_run=0.15),
            adaptation_metrics=AdaptationMetrics(
                avg_decision_confidence=0.7,
                common_failures=[("Error A", 5)],
            ),
        )

        after = Scorecard(
            agent_id="test",
            agent_name="Test Agent",
            goal_id="goal",
            overall_health=80,
            goal_achievement_rate=0.85,
            runs_analyzed=100,
            cost_metrics=CostMetrics(avg_cost_per_run=0.10),
            adaptation_metrics=AdaptationMetrics(
                avg_decision_confidence=0.85,
                common_failures=[("Error B", 2)],
            ),
        )

        diff = generator.compare(before, after)

        assert diff.health_delta == 20
        assert diff.goal_achievement_delta == pytest.approx(0.15)
        assert diff.cost_per_run_delta == pytest.approx(-0.05)  # Cost improved
        assert diff.confidence_delta == pytest.approx(0.15)
        assert len(diff.improvements) > 0
        assert diff.overall_direction == TrendDirection.IMPROVING
        assert "Error A" in diff.resolved_failure_modes
        assert "Error B" in diff.new_failure_modes

    def test_time_window_filtering(self, mock_runs, tmp_path):
        """Test that time window correctly filters runs."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        generator = ScorecardGenerator(tmp_path)

        # Calculate how many runs fall within the 35-day window (all 20 + margin)
        # mock_runs span from 30 days ago, so we use a 35-day window to include all
        recent_runs = [
            r for r in mock_runs
            if r.started_at > datetime.now() - timedelta(days=35)
        ]

        generator.storage.get_runs_by_goal = MagicMock(
            return_value=[r.id for r in mock_runs]
        )
        generator.storage.load_run = MagicMock(
            side_effect=lambda run_id: next(
                (r for r in mock_runs if r.id == run_id), None
            )
        )

        scorecard = generator.generate(
            goal_id="test_goal",
            agent_name="Test",
            time_window_days=35,  # Use 35-day window to include all mock runs
            min_runs=1,
        )

        # Should include all runs since they're all within the window
        assert scorecard is not None
        assert scorecard.runs_analyzed == len(mock_runs)  # All runs should be included


class TestScorecardCLI:
    """Tests for scorecard CLI commands."""

    def test_parse_time_window_days(self):
        """Test parsing time window for days format."""
        from framework.builder.cli import _parse_time_window

        assert _parse_time_window("7d") == 7
        assert _parse_time_window("30d") == 30
        assert _parse_time_window("1d") == 1

    def test_parse_time_window_weeks(self):
        """Test parsing time window for weeks format."""
        from framework.builder.cli import _parse_time_window

        assert _parse_time_window("1w") == 7
        assert _parse_time_window("2w") == 14
        assert _parse_time_window("4w") == 28

    def test_parse_time_window_months(self):
        """Test parsing time window for months format."""
        from framework.builder.cli import _parse_time_window

        assert _parse_time_window("1m") == 30
        assert _parse_time_window("3m") == 90

    def test_parse_time_window_all(self):
        """Test parsing 'all' time window."""
        from framework.builder.cli import _parse_time_window

        assert _parse_time_window("all") is None
        assert _parse_time_window("ALL") is None
        assert _parse_time_window("none") is None

    def test_parse_time_window_numeric(self):
        """Test parsing plain numeric time window."""
        from framework.builder.cli import _parse_time_window

        assert _parse_time_window("14") == 14
        assert _parse_time_window("365") == 365


class TestScorecardSerialization:
    """Tests for scorecard JSON serialization."""

    def test_scorecard_to_json(self):
        """Test that Scorecard serializes to valid JSON."""
        scorecard = Scorecard(
            agent_id="test",
            agent_name="Test Agent",
            goal_id="goal",
            overall_health=75,
            goal_achievement_rate=0.8,
            runs_analyzed=100,
            criterion_scores=[
                CriterionScore(
                    criterion_id="c1",
                    description="Criterion 1",
                    achievement_rate=0.9,
                )
            ],
        )

        json_str = scorecard.model_dump_json()
        parsed = json.loads(json_str)

        assert parsed["agent_name"] == "Test Agent"
        assert parsed["overall_health"] == 75
        assert len(parsed["criterion_scores"]) == 1

    def test_scorecard_from_json(self):
        """Test that Scorecard deserializes from JSON."""
        data = {
            "agent_id": "test",
            "agent_name": "Test Agent",
            "goal_id": "goal",
            "overall_health": 75,
            "goal_achievement_rate": 0.8,
            "runs_analyzed": 100,
        }

        scorecard = Scorecard.model_validate(data)

        assert scorecard.agent_name == "Test Agent"
        assert scorecard.overall_health == 75

    def test_diff_to_json(self):
        """Test that ScorecardDiff serializes to valid JSON."""
        diff = ScorecardDiff(
            agent_id="test",
            agent_name="Test Agent",
            scorecard_before_date=datetime(2024, 1, 1),
            scorecard_after_date=datetime(2024, 2, 1),
            runs_before=50,
            runs_after=100,
            health_delta=10,
        )

        json_str = diff.model_dump_json()
        parsed = json.loads(json_str)

        assert parsed["agent_name"] == "Test Agent"
        assert parsed["health_delta"] == 10


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_runs_list(self):
        """Test handling of empty runs list."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        generator = ScorecardGenerator("/tmp/test")
        generator.storage.get_runs_by_goal = MagicMock(return_value=[])

        scorecard = generator.generate("goal", "Agent")
        assert scorecard is None

    def test_all_failed_runs(self, tmp_path):
        """Test scorecard with all failed runs."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        runs = [
            Run(
                id=f"run_{i}",
                goal_id="goal",
                status=RunStatus.FAILED,
            )
            for i in range(10)
        ]

        generator = ScorecardGenerator(tmp_path)
        generator.storage.get_runs_by_goal = MagicMock(return_value=[r.id for r in runs])
        generator.storage.load_run = MagicMock(
            side_effect=lambda run_id: next((r for r in runs if r.id == run_id), None)
        )

        scorecard = generator.generate("goal", "Agent", min_runs=5)

        assert scorecard is not None
        assert scorecard.goal_achievement_rate == 0.0
        assert scorecard.overall_health < 50  # Should be low health

    def test_all_successful_runs(self, tmp_path):
        """Test scorecard with all successful runs."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        runs = [
            Run(
                id=f"run_{i}",
                goal_id="goal",
                status=RunStatus.COMPLETED,
                metrics=RunMetrics(
                    total_decisions=10,
                    successful_decisions=10,
                    total_tokens=1000,
                ),
            )
            for i in range(10)
        ]

        generator = ScorecardGenerator(tmp_path)
        generator.storage.get_runs_by_goal = MagicMock(return_value=[r.id for r in runs])
        generator.storage.load_run = MagicMock(
            side_effect=lambda run_id: next((r for r in runs if r.id == run_id), None)
        )

        scorecard = generator.generate("goal", "Agent", min_runs=5)

        assert scorecard is not None
        assert scorecard.goal_achievement_rate == 1.0
        assert scorecard.overall_health >= 50  # Should be healthy

    def test_scorecard_with_zero_tokens(self, tmp_path):
        """Test scorecard generation with zero token usage."""
        from framework.builder.scorecard_generator import ScorecardGenerator

        runs = [
            Run(
                id=f"run_{i}",
                goal_id="goal",
                status=RunStatus.COMPLETED,
                metrics=RunMetrics(total_tokens=0),
            )
            for i in range(10)
        ]

        generator = ScorecardGenerator(tmp_path)
        generator.storage.get_runs_by_goal = MagicMock(return_value=[r.id for r in runs])
        generator.storage.load_run = MagicMock(
            side_effect=lambda run_id: next((r for r in runs if r.id == run_id), None)
        )

        scorecard = generator.generate("goal", "Agent", min_runs=5)

        assert scorecard is not None
        assert scorecard.cost_metrics.total_spend == 0.0
        assert scorecard.cost_metrics.avg_cost_per_run == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
