"""
Scorecard Schema - Quantifying agent adaptation over time.

Scorecards transform internal runtime metrics (OutcomeAggregator progress,
BuilderQuery patterns, RunMetrics success rates) into a structured,
user-facing report that answers: "Is my agent getting better?"

This serves three product goals:
1. Enterprise POC-to-contract conversion (quantifiable proof of value)
2. Community benchmarking (template quality comparison)
3. Developer feedback (where to invest optimization effort)
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, computed_field


class CriterionScore(BaseModel):
    """
    Achievement score for a single success criterion across runs.

    Computed by tracking how often each SuccessCriterion.met == True
    across the analyzed run window, with trend detection.
    """

    criterion_id: str
    description: str
    achievement_rate: float = Field(
        ge=0.0, le=1.0, description="Fraction of runs where this criterion was met"
    )
    trend: str = Field(
        description="Direction of change: 'improving', 'stable', or 'declining'"
    )
    sample_size: int = Field(ge=0, description="Number of runs this score is based on")

    model_config = {"extra": "allow"}


class CostMetrics(BaseModel):
    """
    Cost tracking across runs.

    Derived from RunMetrics.total_tokens and configurable per-token pricing.
    Enables the question: "Is my agent getting cheaper to run?"
    """

    total_spend_tokens: int = Field(ge=0, description="Total tokens consumed across all runs")
    avg_tokens_per_run: float = Field(ge=0.0, description="Average tokens per run")
    cost_trend: str = Field(
        description="Direction of change: 'decreasing', 'stable', or 'increasing'"
    )
    cheapest_run_tokens: int = Field(ge=0, description="Tokens in most efficient run")
    most_expensive_run_tokens: int = Field(ge=0, description="Tokens in least efficient run")

    model_config = {"extra": "allow"}


class AdaptationMetrics(BaseModel):
    """
    Metrics about the self-improvement loop.

    Tracks how the agent evolves: how many graph evolutions occurred,
    how many distinct failure modes were resolved, and whether decision
    confidence is trending upward.
    """

    total_graph_versions: int = Field(
        ge=1, description="Number of distinct agent graph versions observed"
    )
    failure_modes_resolved: int = Field(
        ge=0, description="Distinct failure patterns that stopped recurring"
    )
    failure_modes_remaining: int = Field(
        ge=0, description="Distinct failure patterns still occurring"
    )
    avg_decision_confidence: float = Field(
        ge=0.0, le=1.0, description="Mean confidence across all decisions"
    )
    confidence_trend: str = Field(
        description="Direction of change: 'improving', 'stable', or 'declining'"
    )

    model_config = {"extra": "allow"}


class Scorecard(BaseModel):
    """
    Complete outcome scorecard for an agent.

    This is the user-facing artifact that quantifies the adaptation loop.
    It aggregates data from BuilderQuery (patterns, failures), RunMetrics
    (success rates, tokens), and OutcomeAggregator (criterion progress)
    into a single, exportable report.

    The overall_health score (0-100) is a weighted composite:
    - 40% goal achievement rate
    - 25% cost efficiency trend
    - 20% adaptation progress
    - 15% decision confidence
    """

    agent_name: str
    goal_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    time_window: str = Field(
        description="Analysis window: 'last_7_days', 'last_30_days', 'all_time'"
    )
    runs_analyzed: int = Field(ge=0)

    # Composite health
    overall_health: int = Field(ge=0, le=100, description="Weighted health score (0-100)")

    # Goal performance
    goal_achievement_rate: float = Field(
        ge=0.0, le=1.0, description="Fraction of runs that achieved the goal"
    )

    # Detailed breakdowns
    criteria_scores: list[CriterionScore] = Field(default_factory=list)
    cost_metrics: CostMetrics
    adaptation_metrics: AdaptationMetrics

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def health_label(self) -> str:
        """Human-readable health status."""
        if self.overall_health >= 80:
            return "healthy"
        elif self.overall_health >= 50:
            return "needs_attention"
        else:
            return "critical"

    def to_table_str(self) -> str:
        """Format scorecard as a readable table for terminal output."""
        lines = [
            f"{'=' * 60}",
            f"  AGENT SCORECARD: {self.agent_name}",
            f"  Goal: {self.goal_id}",
            f"  Window: {self.time_window} | Runs: {self.runs_analyzed}",
            f"  Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M')}",
            f"{'=' * 60}",
            "",
            f"  OVERALL HEALTH: {self.overall_health}/100 ({self.health_label.upper()})",
            f"  Goal Achievement: {self.goal_achievement_rate:.1%}",
            "",
            "  CRITERIA BREAKDOWN:",
        ]

        for cs in self.criteria_scores:
            trend_icon = {"improving": "+", "stable": "=", "declining": "-"}.get(
                cs.trend, "?"
            )
            lines.append(
                f"    [{trend_icon}] {cs.description}: "
                f"{cs.achievement_rate:.1%} (n={cs.sample_size})"
            )

        lines.extend(
            [
                "",
                "  COST:",
                f"    Avg tokens/run: {self.cost_metrics.avg_tokens_per_run:.0f}",
                f"    Total tokens: {self.cost_metrics.total_spend_tokens}",
                f"    Trend: {self.cost_metrics.cost_trend}",
                "",
                "  ADAPTATION:",
                f"    Graph versions: {self.adaptation_metrics.total_graph_versions}",
                f"    Failures resolved: {self.adaptation_metrics.failure_modes_resolved}",
                f"    Failures remaining: {self.adaptation_metrics.failure_modes_remaining}",
                f"    Avg confidence: {self.adaptation_metrics.avg_decision_confidence:.2f}",
                f"    Confidence trend: {self.adaptation_metrics.confidence_trend}",
                "",
                f"{'=' * 60}",
            ]
        )

        return "\n".join(lines)


class ScorecardDiff(BaseModel):
    """
    Comparison between two scorecards.

    Enables before/after analysis: "After evolution X, the agent improved
    goal achievement by 15% and reduced cost by 22%."
    """

    before: Scorecard
    after: Scorecard
    achievement_delta: float = Field(
        description="Change in goal achievement rate (positive = better)"
    )
    cost_delta: float = Field(
        description="Change in avg tokens per run (negative = cheaper)"
    )
    health_delta: int = Field(
        description="Change in overall health score (positive = better)"
    )
    improvements: list[str] = Field(
        default_factory=list, description="List of metrics that improved"
    )
    regressions: list[str] = Field(
        default_factory=list, description="List of metrics that regressed"
    )

    model_config = {"extra": "allow"}

    def to_table_str(self) -> str:
        """Format comparison as a readable diff table."""
        lines = [
            f"{'=' * 60}",
            f"  SCORECARD COMPARISON",
            f"  Before: {self.before.generated_at.strftime('%Y-%m-%d')} | "
            f"After: {self.after.generated_at.strftime('%Y-%m-%d')}",
            f"{'=' * 60}",
            "",
            f"  Health: {self.before.overall_health} -> {self.after.overall_health} "
            f"({'+'if self.health_delta >= 0 else ''}{self.health_delta})",
            f"  Achievement: {self.before.goal_achievement_rate:.1%} -> "
            f"{self.after.goal_achievement_rate:.1%} "
            f"({'+'if self.achievement_delta >= 0 else ''}{self.achievement_delta:.1%})",
            f"  Avg tokens: {self.before.cost_metrics.avg_tokens_per_run:.0f} -> "
            f"{self.after.cost_metrics.avg_tokens_per_run:.0f} "
            f"({'+'if self.cost_delta >= 0 else ''}{self.cost_delta:.0f})",
        ]

        if self.improvements:
            lines.append("")
            lines.append("  IMPROVEMENTS:")
            for imp in self.improvements:
                lines.append(f"    [+] {imp}")

        if self.regressions:
            lines.append("")
            lines.append("  REGRESSIONS:")
            for reg in self.regressions:
                lines.append(f"    [-] {reg}")

        lines.append(f"\n{'=' * 60}")

        return "\n".join(lines)
