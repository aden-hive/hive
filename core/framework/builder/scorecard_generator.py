"""
Scorecard Generator - Transforms raw run data into structured outcome scorecards.

Uses BuilderQuery (patterns, failures) and FileStorage (run data) to compute
rolling metrics across configurable time windows.

Health score weighting:
    40% goal achievement rate
    25% cost efficiency trend
    20% adaptation progress (failure resolution)
    15% decision confidence
"""

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from framework.builder.query import BuilderQuery
from framework.schemas.run import Run, RunStatus
from framework.schemas.scorecard import (
    AdaptationMetrics,
    CostMetrics,
    CriterionScore,
    Scorecard,
    ScorecardDiff,
)
from framework.storage.backend import FileStorage


# Time window parsing
_WINDOW_DELTAS = {
    "last_7_days": timedelta(days=7),
    "last_14_days": timedelta(days=14),
    "last_30_days": timedelta(days=30),
    "last_90_days": timedelta(days=90),
    "all_time": None,  # No cutoff
}


class ScorecardGenerator:
    """
    Generates outcome scorecards from agent run history.

    Wraps BuilderQuery and FileStorage to produce Scorecard instances
    that can be serialized to JSON, rendered as tables, or compared
    to previous scorecards for before/after analysis.

    Usage:
        generator = ScorecardGenerator("/path/to/storage")
        scorecard = generator.generate("my_agent", "goal_001", "last_7_days")
        print(scorecard.to_table_str())
        print(scorecard.model_dump_json(indent=2))
    """

    def __init__(self, storage_path: str | Path):
        self.query = BuilderQuery(str(storage_path))
        self.storage = FileStorage(str(storage_path))

    def generate(
        self,
        agent_name: str,
        goal_id: str,
        time_window: str = "all_time",
    ) -> Scorecard:
        """
        Generate a scorecard from run data.

        Args:
            agent_name: Human-readable agent identifier.
            goal_id: The goal ID to analyze runs for.
            time_window: Analysis window (e.g., 'last_7_days', 'all_time').

        Returns:
            A Scorecard instance with computed metrics.

        Raises:
            ValueError: If no runs found for the given goal and window.
        """
        runs = self._get_runs_in_window(goal_id, time_window)
        if not runs:
            raise ValueError(
                f"No runs found for goal '{goal_id}' in window '{time_window}'"
            )

        patterns = self.query.find_patterns(goal_id)

        criteria_scores = self._score_criteria(runs)
        cost_metrics = self._compute_cost_metrics(runs)
        adaptation_metrics = self._compute_adaptation_metrics(runs, goal_id)

        # Use pattern analysis for goal achievement rate if available
        goal_achievement_rate = (
            patterns.success_rate if patterns else self._compute_achievement_rate(runs)
        )

        overall_health = self._compute_health(
            goal_achievement_rate, cost_metrics, adaptation_metrics
        )

        return Scorecard(
            agent_name=agent_name,
            goal_id=goal_id,
            generated_at=datetime.now(),
            time_window=time_window,
            runs_analyzed=len(runs),
            overall_health=overall_health,
            goal_achievement_rate=goal_achievement_rate,
            criteria_scores=criteria_scores,
            cost_metrics=cost_metrics,
            adaptation_metrics=adaptation_metrics,
        )

    def compare(self, before: Scorecard, after: Scorecard) -> ScorecardDiff:
        """
        Compare two scorecards to show improvement or regression.

        Args:
            before: The earlier scorecard.
            after: The later scorecard.

        Returns:
            A ScorecardDiff with deltas, improvements, and regressions.
        """
        achievement_delta = after.goal_achievement_rate - before.goal_achievement_rate
        cost_delta = (
            after.cost_metrics.avg_tokens_per_run - before.cost_metrics.avg_tokens_per_run
        )
        health_delta = after.overall_health - before.overall_health

        improvements = []
        regressions = []

        # Achievement
        if achievement_delta > 0.01:
            improvements.append(
                f"Goal achievement improved by {achievement_delta:.1%}"
            )
        elif achievement_delta < -0.01:
            regressions.append(
                f"Goal achievement declined by {abs(achievement_delta):.1%}"
            )

        # Cost
        if cost_delta < -10:
            improvements.append(
                f"Avg tokens per run decreased by {abs(cost_delta):.0f}"
            )
        elif cost_delta > 10:
            regressions.append(
                f"Avg tokens per run increased by {cost_delta:.0f}"
            )

        # Confidence
        conf_delta = (
            after.adaptation_metrics.avg_decision_confidence
            - before.adaptation_metrics.avg_decision_confidence
        )
        if conf_delta > 0.02:
            improvements.append(
                f"Decision confidence improved by {conf_delta:.2f}"
            )
        elif conf_delta < -0.02:
            regressions.append(
                f"Decision confidence declined by {abs(conf_delta):.2f}"
            )

        # Failure resolution
        resolved_delta = (
            after.adaptation_metrics.failure_modes_resolved
            - before.adaptation_metrics.failure_modes_resolved
        )
        if resolved_delta > 0:
            improvements.append(
                f"{resolved_delta} additional failure mode(s) resolved"
            )

        # Per-criterion comparison
        before_criteria = {cs.criterion_id: cs for cs in before.criteria_scores}
        for cs_after in after.criteria_scores:
            cs_before = before_criteria.get(cs_after.criterion_id)
            if cs_before:
                delta = cs_after.achievement_rate - cs_before.achievement_rate
                if delta > 0.05:
                    improvements.append(
                        f"Criterion '{cs_after.description}' improved by {delta:.1%}"
                    )
                elif delta < -0.05:
                    regressions.append(
                        f"Criterion '{cs_after.description}' declined by {abs(delta):.1%}"
                    )

        return ScorecardDiff(
            before=before,
            after=after,
            achievement_delta=achievement_delta,
            cost_delta=cost_delta,
            health_delta=health_delta,
            improvements=improvements,
            regressions=regressions,
        )

    # === PRIVATE METHODS ===

    def _get_runs_in_window(
        self, goal_id: str, time_window: str
    ) -> list[Run]:
        """Retrieve runs within the specified time window."""
        run_ids = self.storage.get_runs_by_goal(goal_id)
        runs = []
        cutoff = self._get_cutoff(time_window)

        for run_id in run_ids:
            run = self.storage.load_run(run_id)
            if run is None:
                continue
            # Filter by time window
            if cutoff and run.started_at < cutoff:
                continue
            runs.append(run)

        # Sort chronologically
        runs.sort(key=lambda r: r.started_at)
        return runs

    def _get_cutoff(self, time_window: str) -> datetime | None:
        """Convert time window string to a cutoff datetime."""
        delta = _WINDOW_DELTAS.get(time_window)
        if delta is None:
            return None
        return datetime.now() - delta

    def _compute_achievement_rate(self, runs: list[Run]) -> float:
        """Compute goal achievement rate from run statuses."""
        if not runs:
            return 0.0
        completed = sum(1 for r in runs if r.status == RunStatus.COMPLETED)
        return completed / len(runs)

    def _score_criteria(self, runs: list[Run]) -> list[CriterionScore]:
        """
        Score each success criterion across runs.

        Examines each run's decisions and outcomes to determine
        which criteria were met, then computes achievement rates
        and trends.
        """
        if not runs:
            return []

        # Collect all unique criterion IDs from the goals
        # Since we're analyzing runs for a single goal, criteria should be consistent
        criterion_results: dict[str, list[bool]] = defaultdict(list)
        criterion_descriptions: dict[str, str] = {}

        for run in runs:
            # Check if the run's output_data contains criterion results
            criteria_met = run.output_data.get("criteria_met", {})
            for crit_id, was_met in criteria_met.items():
                criterion_results[crit_id].append(bool(was_met))

            # Also check if goal success criteria descriptions are available
            criteria_desc = run.output_data.get("criteria_descriptions", {})
            criterion_descriptions.update(criteria_desc)

        scores = []
        for crit_id, results in criterion_results.items():
            if not results:
                continue

            achievement_rate = sum(results) / len(results)
            trend = self._compute_trend(results)
            description = criterion_descriptions.get(crit_id, crit_id)

            scores.append(
                CriterionScore(
                    criterion_id=crit_id,
                    description=description,
                    achievement_rate=achievement_rate,
                    trend=trend,
                    sample_size=len(results),
                )
            )

        return scores

    def _compute_cost_metrics(self, runs: list[Run]) -> CostMetrics:
        """Aggregate cost (token usage) data from runs."""
        if not runs:
            return CostMetrics(
                total_spend_tokens=0,
                avg_tokens_per_run=0.0,
                cost_trend="stable",
                cheapest_run_tokens=0,
                most_expensive_run_tokens=0,
            )

        token_counts = [r.metrics.total_tokens for r in runs]
        total = sum(token_counts)
        avg = total / len(token_counts)

        # Compute cost trend from first half vs second half
        cost_trend = self._compute_trend(token_counts, lower_is_better=True)

        return CostMetrics(
            total_spend_tokens=total,
            avg_tokens_per_run=avg,
            cost_trend=cost_trend,
            cheapest_run_tokens=min(token_counts) if token_counts else 0,
            most_expensive_run_tokens=max(token_counts) if token_counts else 0,
        )

    def _compute_adaptation_metrics(
        self, runs: list[Run], goal_id: str
    ) -> AdaptationMetrics:
        """
        Track evolution and improvement signals.

        Counts distinct graph versions, resolved vs remaining failure modes,
        and tracks decision confidence trends.
        """
        if not runs:
            return AdaptationMetrics(
                total_graph_versions=1,
                failure_modes_resolved=0,
                failure_modes_remaining=0,
                avg_decision_confidence=0.0,
                confidence_trend="stable",
            )

        # Track unique graph versions (approximated by distinct node sets)
        node_sets: set[frozenset[str]] = set()
        for run in runs:
            node_set = frozenset(run.metrics.nodes_executed)
            if node_set:
                node_sets.add(node_set)
        total_graph_versions = max(len(node_sets), 1)

        # Track failure modes: errors that appeared early but stopped later
        midpoint = len(runs) // 2
        if midpoint > 0:
            early_runs = runs[:midpoint]
            late_runs = runs[midpoint:]

            early_errors: set[str] = set()
            for run in early_runs:
                for problem in run.problems:
                    if problem.root_cause:
                        early_errors.add(problem.root_cause)

            late_errors: set[str] = set()
            for run in late_runs:
                for problem in run.problems:
                    if problem.root_cause:
                        late_errors.add(problem.root_cause)

            resolved = early_errors - late_errors
            remaining = late_errors
        else:
            resolved = set()
            remaining = set()
            for run in runs:
                for problem in run.problems:
                    if problem.root_cause:
                        remaining.add(problem.root_cause)

        # Decision confidence
        all_confidences: list[float] = []
        for run in runs:
            for decision in run.decisions:
                if decision.evaluation and decision.evaluation.confidence is not None:
                    all_confidences.append(decision.evaluation.confidence)

        avg_confidence = (
            sum(all_confidences) / len(all_confidences)
            if all_confidences
            else 0.0
        )
        confidence_trend = (
            self._compute_trend(all_confidences)
            if len(all_confidences) >= 4
            else "stable"
        )

        return AdaptationMetrics(
            total_graph_versions=total_graph_versions,
            failure_modes_resolved=len(resolved),
            failure_modes_remaining=len(remaining),
            avg_decision_confidence=min(avg_confidence, 1.0),
            confidence_trend=confidence_trend,
        )

    def _compute_health(
        self,
        achievement_rate: float,
        cost_metrics: CostMetrics,
        adaptation_metrics: AdaptationMetrics,
    ) -> int:
        """
        Compute composite health score (0-100).

        Weighting:
            40% goal achievement rate
            25% cost efficiency (trend-based)
            20% adaptation progress (resolved / total failure modes)
            15% decision confidence
        """
        # Achievement component (0-40)
        achievement_score = achievement_rate * 40

        # Cost component (0-25): based on trend direction
        cost_trend_scores = {"decreasing": 25, "stable": 15, "increasing": 5}
        cost_score = cost_trend_scores.get(cost_metrics.cost_trend, 15)

        # Adaptation component (0-20): ratio of resolved failure modes
        total_failures = (
            adaptation_metrics.failure_modes_resolved
            + adaptation_metrics.failure_modes_remaining
        )
        if total_failures > 0:
            resolution_rate = adaptation_metrics.failure_modes_resolved / total_failures
            adaptation_score = resolution_rate * 20
        else:
            # No failures at all = healthy
            adaptation_score = 20

        # Confidence component (0-15)
        confidence_score = adaptation_metrics.avg_decision_confidence * 15

        total = achievement_score + cost_score + adaptation_score + confidence_score
        return max(0, min(100, int(round(total))))

    def _compute_trend(
        self,
        values: list[float | bool | int],
        lower_is_better: bool = False,
    ) -> str:
        """
        Compute trend direction from a sequence of values.

        Splits into first half vs second half and compares means.
        A 5% threshold is used to distinguish 'improving' from 'stable'.
        """
        if len(values) < 4:
            return "stable"

        # Convert bools to floats
        float_values = [float(v) for v in values]

        midpoint = len(float_values) // 2
        first_half_mean = sum(float_values[:midpoint]) / midpoint
        second_half_mean = sum(float_values[midpoint:]) / (len(float_values) - midpoint)

        if first_half_mean == 0:
            return "stable"

        change_pct = (second_half_mean - first_half_mean) / abs(first_half_mean)

        threshold = 0.05  # 5% change required to register as a trend

        if lower_is_better:
            if change_pct < -threshold:
                return "improving"
            elif change_pct > threshold:
                return "declining"
        else:
            if change_pct > threshold:
                return "improving"
            elif change_pct < -threshold:
                return "declining"

        return "stable"
