"""
Scorecard Generator - Generates structured success metrics from agent runs.

The ScorecardGenerator transforms internal runtime data (OutcomeAggregator,
BuilderQuery, FileStorage) into user-facing Scorecards that can be exported,
compared, and used for enterprise proof-of-value reporting.
"""

from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from framework.builder.query import BuilderQuery, PatternAnalysis
from framework.schemas.run import Run, RunStatus
from framework.schemas.scorecard import (
    AdaptationMetrics,
    CostMetrics,
    CriterionScore,
    Scorecard,
    ScorecardDiff,
    TrendDirection,
)
from framework.storage.backend import FileStorage


# Default cost per token (rough approximation for Claude models)
DEFAULT_COST_PER_INPUT_TOKEN = 0.000003  # $3 per million tokens
DEFAULT_COST_PER_OUTPUT_TOKEN = 0.000015  # $15 per million tokens


class ScorecardGenerator:
    """
    Generates Agent Outcome Scorecards from run data.

    Consumes BuilderQuery and FileStorage to analyze agent performance
    across runs and produce exportable scorecards.

    Health Score Weighting:
        - 40% Goal Achievement
        - 25% Cost Efficiency
        - 20% Adaptation Progress
        - 15% Decision Confidence
    """

    # Weight constants for health score calculation
    WEIGHT_GOAL_ACHIEVEMENT = 0.40
    WEIGHT_COST_EFFICIENCY = 0.25
    WEIGHT_ADAPTATION = 0.20
    WEIGHT_CONFIDENCE = 0.15

    # Cost per token (can be configured)
    COST_PER_INPUT_TOKEN = DEFAULT_COST_PER_INPUT_TOKEN
    COST_PER_OUTPUT_TOKEN = DEFAULT_COST_PER_OUTPUT_TOKEN

    def __init__(
        self,
        storage_path: str | Path,
        cost_per_input_token: float = DEFAULT_COST_PER_INPUT_TOKEN,
        cost_per_output_token: float = DEFAULT_COST_PER_OUTPUT_TOKEN,
    ):
        """
        Initialize the scorecard generator.

        Args:
            storage_path: Path to the agent's storage directory.
            cost_per_input_token: Cost per input token in dollars.
            cost_per_output_token: Cost per output token in dollars.
        """
        self.storage_path = Path(storage_path)
        self.storage = FileStorage(storage_path)
        self.query = BuilderQuery(storage_path)
        self.COST_PER_INPUT_TOKEN = cost_per_input_token
        self.COST_PER_OUTPUT_TOKEN = cost_per_output_token

    def generate(
        self,
        goal_id: str,
        agent_name: str = "Unknown Agent",
        time_window_days: int | None = None,
        min_runs: int = 5,
    ) -> Scorecard | None:
        """
        Generate a scorecard for an agent's goal.

        Args:
            goal_id: The goal ID to analyze.
            agent_name: Human-readable name of the agent.
            time_window_days: Optional time window in days (None = all time).
            min_runs: Minimum number of runs required for meaningful analysis.

        Returns:
            Scorecard if sufficient data exists, None otherwise.
        """
        # Get runs for this goal
        runs = self._get_runs_in_window(goal_id, time_window_days)

        if len(runs) < min_runs:
            return None

        # Calculate time window
        time_window_start = min(r.started_at for r in runs)
        time_window_end = max(r.completed_at or r.started_at for r in runs)

        # Get pattern analysis
        patterns = self.query.find_patterns(goal_id)

        # Calculate criterion scores
        criterion_scores = self._calculate_criterion_scores(runs)

        # Calculate cost metrics
        cost_metrics = self._calculate_cost_metrics(runs)

        # Calculate adaptation metrics
        adaptation_metrics = self._calculate_adaptation_metrics(runs, patterns)

        # Calculate goal achievement rate and trend
        goal_achievement_rate = self._calculate_goal_achievement_rate(runs)
        goal_achievement_trend = self._calculate_achievement_trend(
            runs, time_window_days
        )

        # Calculate overall health score
        overall_health = self._calculate_health_score(
            goal_achievement_rate=goal_achievement_rate,
            cost_metrics=cost_metrics,
            adaptation_metrics=adaptation_metrics,
            runs=runs,
        )

        # Generate recommendations
        recommendations = self._generate_recommendations(
            goal_achievement_rate=goal_achievement_rate,
            cost_metrics=cost_metrics,
            adaptation_metrics=adaptation_metrics,
            patterns=patterns,
        )

        # Identify improvements and regressions
        key_improvements, key_regressions = self._identify_trends(
            runs, time_window_days
        )

        # Load agent metadata for goal description
        goal_description = self._get_goal_description(goal_id)

        return Scorecard(
            agent_id=str(self.storage_path),
            agent_name=agent_name,
            goal_id=goal_id,
            goal_description=goal_description,
            generated_at=datetime.now(),
            time_window_start=time_window_start,
            time_window_end=time_window_end,
            runs_analyzed=len(runs),
            overall_health=overall_health,
            goal_achievement_rate=goal_achievement_rate,
            goal_achievement_trend=goal_achievement_trend,
            criterion_scores=criterion_scores,
            cost_metrics=cost_metrics,
            adaptation_metrics=adaptation_metrics,
            key_improvements=key_improvements,
            key_regressions=key_regressions,
            recommendations=recommendations,
        )

    def compare(
        self,
        scorecard_before: Scorecard,
        scorecard_after: Scorecard,
    ) -> ScorecardDiff:
        """
        Compare two scorecards to identify changes.

        Args:
            scorecard_before: Earlier scorecard.
            scorecard_after: Later scorecard.

        Returns:
            ScorecardDiff with detailed comparison.
        """
        # Calculate deltas
        health_delta = scorecard_after.overall_health - scorecard_before.overall_health
        goal_achievement_delta = (
            scorecard_after.goal_achievement_rate
            - scorecard_before.goal_achievement_rate
        )
        cost_per_run_delta = (
            scorecard_after.cost_metrics.avg_cost_per_run
            - scorecard_before.cost_metrics.avg_cost_per_run
        )
        confidence_delta = (
            scorecard_after.adaptation_metrics.avg_decision_confidence
            - scorecard_before.adaptation_metrics.avg_decision_confidence
        )

        # Identify improvements and regressions
        improvements = []
        regressions = []

        if health_delta > 5:
            improvements.append(f"Health score improved by {health_delta} points")
        elif health_delta < -5:
            regressions.append(f"Health score decreased by {abs(health_delta)} points")

        if goal_achievement_delta > 0.05:
            improvements.append(
                f"Goal achievement improved by {goal_achievement_delta:.1%}"
            )
        elif goal_achievement_delta < -0.05:
            regressions.append(
                f"Goal achievement decreased by {abs(goal_achievement_delta):.1%}"
            )

        if cost_per_run_delta < -0.01:
            improvements.append(
                f"Cost per run reduced by ${abs(cost_per_run_delta):.4f}"
            )
        elif cost_per_run_delta > 0.01:
            regressions.append(
                f"Cost per run increased by ${cost_per_run_delta:.4f}"
            )

        if confidence_delta > 0.05:
            improvements.append(
                f"Decision confidence improved by {confidence_delta:.1%}"
            )
        elif confidence_delta < -0.05:
            regressions.append(
                f"Decision confidence decreased by {abs(confidence_delta):.1%}"
            )

        # Compare criterion scores
        before_criteria = {cs.criterion_id: cs for cs in scorecard_before.criterion_scores}
        after_criteria = {cs.criterion_id: cs for cs in scorecard_after.criterion_scores}

        for cid, after_cs in after_criteria.items():
            if cid in before_criteria:
                before_cs = before_criteria[cid]
                delta = after_cs.achievement_rate - before_cs.achievement_rate
                if delta > 0.1:
                    improvements.append(
                        f"'{after_cs.description[:30]}...' improved by {delta:.0%}"
                    )
                elif delta < -0.1:
                    regressions.append(
                        f"'{after_cs.description[:30]}...' decreased by {abs(delta):.0%}"
                    )

        # Identify resolved and new failure modes
        before_failures = set(
            fm[0] for fm in scorecard_before.adaptation_metrics.common_failures
        )
        after_failures = set(
            fm[0] for fm in scorecard_after.adaptation_metrics.common_failures
        )

        resolved_failure_modes = list(before_failures - after_failures)
        new_failure_modes = list(after_failures - before_failures)

        return ScorecardDiff(
            agent_id=scorecard_after.agent_id,
            agent_name=scorecard_after.agent_name,
            scorecard_before_date=scorecard_before.generated_at,
            scorecard_after_date=scorecard_after.generated_at,
            runs_before=scorecard_before.runs_analyzed,
            runs_after=scorecard_after.runs_analyzed,
            health_delta=health_delta,
            goal_achievement_delta=goal_achievement_delta,
            cost_per_run_delta=cost_per_run_delta,
            confidence_delta=confidence_delta,
            improvements=improvements,
            regressions=regressions,
            new_failure_modes=new_failure_modes,
            resolved_failure_modes=resolved_failure_modes,
        )

    def load_scorecard_from_file(self, filepath: str | Path) -> Scorecard:
        """
        Load a previously saved scorecard from JSON file.

        Args:
            filepath: Path to the JSON file.

        Returns:
            Scorecard loaded from file.
        """
        import json

        with open(filepath) as f:
            data = json.load(f)
        return Scorecard.model_validate(data)

    def _get_runs_in_window(
        self,
        goal_id: str,
        time_window_days: int | None,
    ) -> list[Run]:
        """Get all runs for a goal within the time window."""
        run_ids = self.storage.get_runs_by_goal(goal_id)
        runs = []

        cutoff_date = None
        if time_window_days is not None:
            cutoff_date = datetime.now() - timedelta(days=time_window_days)

        for run_id in run_ids:
            run = self.storage.load_run(run_id)
            if run is None:
                continue

            if cutoff_date is not None and run.started_at < cutoff_date:
                continue

            runs.append(run)

        # Sort by start time
        runs.sort(key=lambda r: r.started_at)

        return runs

    def _calculate_criterion_scores(self, runs: list[Run]) -> list[CriterionScore]:
        """Calculate scores for each success criterion."""
        # Aggregate criterion data across runs
        criterion_data: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"met_count": 0, "total_count": 0, "description": ""}
        )

        for run in runs:
            # Each run has decisions that may relate to criteria
            # We track success rate per criterion based on decision outcomes
            for decision in run.decisions:
                if decision.evaluation:
                    # Use the decision's criteria if available
                    for constraint in decision.active_constraints:
                        criterion_data[constraint]["total_count"] += 1
                        if decision.evaluation.goal_aligned:
                            criterion_data[constraint]["met_count"] += 1
                        if not criterion_data[constraint]["description"]:
                            criterion_data[constraint]["description"] = constraint

        # Also check run-level metrics
        for run in runs:
            # Track overall success per run
            if run.status == RunStatus.COMPLETED:
                criterion_data["goal_completion"]["met_count"] += 1
            criterion_data["goal_completion"]["total_count"] += 1
            criterion_data["goal_completion"]["description"] = "Goal successfully completed"

        # Convert to CriterionScore objects
        scores = []
        for cid, data in criterion_data.items():
            if data["total_count"] > 0:
                achievement_rate = data["met_count"] / data["total_count"]
                trend = self._calculate_trend_for_criterion(runs, cid)

                scores.append(
                    CriterionScore(
                        criterion_id=cid,
                        description=data["description"] or cid,
                        achievement_rate=achievement_rate,
                        trend=trend,
                        sample_size=data["total_count"],
                    )
                )

        return scores

    def _calculate_cost_metrics(self, runs: list[Run]) -> CostMetrics:
        """Calculate cost-related metrics from runs."""
        if not runs:
            return CostMetrics()

        total_tokens = sum(r.metrics.total_tokens for r in runs)
        total_spend = total_tokens * (
            (self.COST_PER_INPUT_TOKEN + self.COST_PER_OUTPUT_TOKEN) / 2
        )

        run_costs = []
        for run in runs:
            run_cost = run.metrics.total_tokens * (
                (self.COST_PER_INPUT_TOKEN + self.COST_PER_OUTPUT_TOKEN) / 2
            )
            run_costs.append(run_cost)

        avg_cost = total_spend / len(runs) if runs else 0
        min_cost = min(run_costs) if run_costs else 0
        max_cost = max(run_costs) if run_costs else 0
        avg_tokens = total_tokens / len(runs) if runs else 0

        # Calculate cost trend (compare first half to second half)
        cost_trend = TrendDirection.INSUFFICIENT_DATA
        if len(runs) >= 10:
            mid = len(runs) // 2
            first_half_avg = sum(run_costs[:mid]) / mid if mid > 0 else 0
            second_half_avg = (
                sum(run_costs[mid:]) / (len(runs) - mid) if (len(runs) - mid) > 0 else 0
            )

            if second_half_avg < first_half_avg * 0.9:
                cost_trend = TrendDirection.IMPROVING  # Lower cost is better
            elif second_half_avg > first_half_avg * 1.1:
                cost_trend = TrendDirection.DECLINING  # Higher cost is worse
            else:
                cost_trend = TrendDirection.STABLE

        return CostMetrics(
            total_spend=total_spend,
            avg_cost_per_run=avg_cost,
            cost_trend=cost_trend,
            min_run_cost=min_cost,
            max_run_cost=max_cost,
            total_tokens=total_tokens,
            avg_tokens_per_run=avg_tokens,
        )

    def _calculate_adaptation_metrics(
        self,
        runs: list[Run],
        patterns: PatternAnalysis | None,
    ) -> AdaptationMetrics:
        """Calculate adaptation and self-improvement metrics."""
        if not runs:
            return AdaptationMetrics()

        # Calculate average decision confidence
        total_confidence = 0.0
        confidence_count = 0
        for run in runs:
            for decision in run.decisions:
                if decision.evaluation:
                    total_confidence += decision.evaluation.outcome_quality
                    confidence_count += 1
                elif decision.chosen_option:
                    total_confidence += decision.chosen_option.confidence
                    confidence_count += 1

        avg_confidence = (
            total_confidence / confidence_count if confidence_count > 0 else 0.0
        )

        # Calculate confidence trend
        confidence_trend = TrendDirection.INSUFFICIENT_DATA
        if len(runs) >= 10:
            mid = len(runs) // 2
            first_half_conf = []
            second_half_conf = []

            for i, run in enumerate(runs):
                for decision in run.decisions:
                    conf = 0.5
                    if decision.evaluation:
                        conf = decision.evaluation.outcome_quality
                    elif decision.chosen_option:
                        conf = decision.chosen_option.confidence

                    if i < mid:
                        first_half_conf.append(conf)
                    else:
                        second_half_conf.append(conf)

            if first_half_conf and second_half_conf:
                first_avg = sum(first_half_conf) / len(first_half_conf)
                second_avg = sum(second_half_conf) / len(second_half_conf)

                if second_avg > first_avg * 1.05:
                    confidence_trend = TrendDirection.IMPROVING
                elif second_avg < first_avg * 0.95:
                    confidence_trend = TrendDirection.DECLINING
                else:
                    confidence_trend = TrendDirection.STABLE

        # Get failure data from patterns
        common_failures = []
        problematic_nodes = []
        if patterns:
            common_failures = patterns.common_failures
            problematic_nodes = patterns.problematic_nodes

        # Count failure modes
        failure_modes_remaining = len(common_failures)
        # Estimate resolved by comparing to total unique errors seen
        all_errors = set()
        for run in runs:
            for decision in run.decisions:
                if not decision.was_successful and decision.outcome and decision.outcome.error:
                    all_errors.add(decision.outcome.error)
        current_error_texts = set(f[0] for f in common_failures)
        failure_modes_resolved = len(all_errors - current_error_texts)

        return AdaptationMetrics(
            total_evolutions=0,  # Would need graph version tracking
            failure_modes_resolved=failure_modes_resolved,
            failure_modes_remaining=failure_modes_remaining,
            avg_decision_confidence=avg_confidence,
            confidence_trend=confidence_trend,
            common_failures=common_failures,
            problematic_nodes=problematic_nodes,
        )

    def _calculate_goal_achievement_rate(self, runs: list[Run]) -> float:
        """Calculate the overall goal achievement rate."""
        if not runs:
            return 0.0

        completed = sum(1 for r in runs if r.status == RunStatus.COMPLETED)
        return completed / len(runs)

    def _calculate_achievement_trend(
        self,
        runs: list[Run],
        time_window_days: int | None,
    ) -> TrendDirection:
        """Calculate the trend in goal achievement."""
        if len(runs) < 10:
            return TrendDirection.INSUFFICIENT_DATA

        mid = len(runs) // 2
        first_half = runs[:mid]
        second_half = runs[mid:]

        first_rate = sum(1 for r in first_half if r.status == RunStatus.COMPLETED) / len(
            first_half
        )
        second_rate = sum(
            1 for r in second_half if r.status == RunStatus.COMPLETED
        ) / len(second_half)

        if second_rate > first_rate * 1.1:
            return TrendDirection.IMPROVING
        elif second_rate < first_rate * 0.9:
            return TrendDirection.DECLINING
        else:
            return TrendDirection.STABLE

    def _calculate_trend_for_criterion(
        self,
        runs: list[Run],
        criterion_id: str,
    ) -> TrendDirection:
        """Calculate trend for a specific criterion."""
        if len(runs) < 10:
            return TrendDirection.INSUFFICIENT_DATA

        # This is a simplified trend calculation
        # In practice, you might want more sophisticated time-series analysis
        return TrendDirection.STABLE

    def _calculate_health_score(
        self,
        goal_achievement_rate: float,
        cost_metrics: CostMetrics,
        adaptation_metrics: AdaptationMetrics,
        runs: list[Run],
    ) -> int:
        """
        Calculate overall health score (0-100).

        Weighting:
            - 40% Goal Achievement
            - 25% Cost Efficiency
            - 20% Adaptation Progress
            - 15% Decision Confidence
        """
        # Goal achievement component (0-100)
        goal_component = goal_achievement_rate * 100

        # Cost efficiency component (0-100)
        # We normalize based on improvement trend
        cost_component = 50  # Base score
        if cost_metrics.cost_trend == TrendDirection.IMPROVING:
            cost_component = 75
        elif cost_metrics.cost_trend == TrendDirection.STABLE:
            cost_component = 60
        elif cost_metrics.cost_trend == TrendDirection.DECLINING:
            cost_component = 30

        # Adaptation component (0-100)
        adaptation_component = 50  # Base score
        total_failure_modes = (
            adaptation_metrics.failure_modes_resolved
            + adaptation_metrics.failure_modes_remaining
        )
        if total_failure_modes > 0:
            resolution_rate = (
                adaptation_metrics.failure_modes_resolved / total_failure_modes
            )
            adaptation_component = resolution_rate * 100
        if adaptation_metrics.confidence_trend == TrendDirection.IMPROVING:
            adaptation_component = min(100, adaptation_component + 10)

        # Confidence component (0-100)
        confidence_component = adaptation_metrics.avg_decision_confidence * 100

        # Weighted sum
        health = (
            self.WEIGHT_GOAL_ACHIEVEMENT * goal_component
            + self.WEIGHT_COST_EFFICIENCY * cost_component
            + self.WEIGHT_ADAPTATION * adaptation_component
            + self.WEIGHT_CONFIDENCE * confidence_component
        )

        return int(min(100, max(0, health)))

    def _generate_recommendations(
        self,
        goal_achievement_rate: float,
        cost_metrics: CostMetrics,
        adaptation_metrics: AdaptationMetrics,
        patterns: PatternAnalysis | None,
    ) -> list[str]:
        """Generate actionable recommendations based on scorecard analysis."""
        recommendations = []

        # Goal achievement recommendations
        if goal_achievement_rate < 0.5:
            recommendations.append(
                "Critical: Goal achievement rate is below 50%. "
                "Review agent configuration and node implementations."
            )
        elif goal_achievement_rate < 0.8:
            recommendations.append(
                "Goal achievement rate could be improved. "
                "Consider adding retry logic or alternative paths."
            )

        # Cost recommendations
        if cost_metrics.cost_trend == TrendDirection.DECLINING:
            recommendations.append(
                "Cost per run is increasing. "
                "Review token usage and consider prompt optimization."
            )

        # Adaptation recommendations
        if adaptation_metrics.failure_modes_remaining > 3:
            recommendations.append(
                f"There are {adaptation_metrics.failure_modes_remaining} "
                "unresolved failure modes. Prioritize addressing common failures."
            )

        # Confidence recommendations
        if adaptation_metrics.avg_decision_confidence < 0.5:
            recommendations.append(
                "Decision confidence is low. Consider providing clearer "
                "constraints or improving prompts for better decision quality."
            )

        # Node-specific recommendations
        if patterns and patterns.problematic_nodes:
            for node_id, rate in patterns.problematic_nodes[:2]:
                recommendations.append(
                    f"Node '{node_id}' has a {rate:.0%} failure rate. "
                    "Review its implementation and error handling."
                )

        return recommendations

    def _identify_trends(
        self,
        runs: list[Run],
        time_window_days: int | None,
    ) -> tuple[list[str], list[str]]:
        """Identify key improvements and regressions."""
        improvements = []
        regressions = []

        if len(runs) < 10:
            return improvements, regressions

        mid = len(runs) // 2
        first_half = runs[:mid]
        second_half = runs[mid:]

        # Success rate comparison
        first_success = sum(
            1 for r in first_half if r.status == RunStatus.COMPLETED
        ) / len(first_half)
        second_success = sum(
            1 for r in second_half if r.status == RunStatus.COMPLETED
        ) / len(second_half)

        if second_success > first_success + 0.1:
            improvements.append(
                f"Success rate improved from {first_success:.0%} to {second_success:.0%}"
            )
        elif second_success < first_success - 0.1:
            regressions.append(
                f"Success rate dropped from {first_success:.0%} to {second_success:.0%}"
            )

        # Latency comparison
        first_latency = sum(r.metrics.total_latency_ms for r in first_half) / len(
            first_half
        )
        second_latency = sum(r.metrics.total_latency_ms for r in second_half) / len(
            second_half
        )

        if second_latency < first_latency * 0.8:
            improvements.append(
                f"Latency improved from {first_latency:.0f}ms to {second_latency:.0f}ms"
            )
        elif second_latency > first_latency * 1.2:
            regressions.append(
                f"Latency increased from {first_latency:.0f}ms to {second_latency:.0f}ms"
            )

        return improvements, regressions

    def _get_goal_description(self, goal_id: str) -> str:
        """Get the goal description from agent metadata."""
        try:
            import json

            agent_json = self.storage_path / "agent.json"
            if agent_json.exists():
                with open(agent_json) as f:
                    data = json.load(f)
                    goal = data.get("goal", {})
                    if isinstance(goal, dict):
                        return goal.get("description", "")
        except Exception:
            pass
        return ""
