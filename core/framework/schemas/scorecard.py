"""
Scorecard Schema - Structured success metrics for enterprise proof-of-value.

Agent Outcome Scorecards provide user-facing metrics that answer:
"Is my agent actually getting better over time?"

These schemas turn internal runtime data into exportable, comparable artifacts
that close the enterprise proof-of-value gap.
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class TrendDirection(str, Enum):
    """Direction of a metric trend over time."""

    IMPROVING = "improving"
    STABLE = "stable"
    DECLINING = "declining"
    INSUFFICIENT_DATA = "insufficient_data"


class HealthLabel(str, Enum):
    """Overall health classification for an agent."""

    HEALTHY = "healthy"
    NEEDS_ATTENTION = "needs_attention"
    CRITICAL = "critical"


class CriterionScore(BaseModel):
    """
    Per-criterion achievement rate and trend.

    Tracks how well a specific success criterion is being met over time.
    """

    criterion_id: str
    description: str
    achievement_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Rate at which this criterion is met (0.0-1.0)",
    )
    trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA
    sample_size: int = Field(
        default=0,
        ge=0,
        description="Number of runs used to calculate this score",
    )
    last_updated: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}


class CostMetrics(BaseModel):
    """
    Cost-related metrics for agent execution.

    Helps enterprises understand and control agent spending.
    """

    total_spend: float = Field(
        default=0.0,
        ge=0.0,
        description="Total cost in dollars across all analyzed runs",
    )
    avg_cost_per_run: float = Field(
        default=0.0,
        ge=0.0,
        description="Average cost per run in dollars",
    )
    cost_trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA
    min_run_cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum cost of a single run",
    )
    max_run_cost: float = Field(
        default=0.0,
        ge=0.0,
        description="Maximum cost of a single run",
    )
    total_tokens: int = Field(
        default=0,
        ge=0,
        description="Total tokens used across all runs",
    )
    avg_tokens_per_run: float = Field(
        default=0.0,
        ge=0.0,
        description="Average tokens per run",
    )

    model_config = {"extra": "allow"}


class AdaptationMetrics(BaseModel):
    """
    Metrics tracking agent self-improvement and adaptation.

    Shows how the agent evolves to handle failures better.
    """

    total_evolutions: int = Field(
        default=0,
        ge=0,
        description="Number of graph evolutions/adaptations",
    )
    failure_modes_resolved: int = Field(
        default=0,
        ge=0,
        description="Number of failure modes that have been resolved",
    )
    failure_modes_remaining: int = Field(
        default=0,
        ge=0,
        description="Number of failure modes still unresolved",
    )
    avg_decision_confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Average confidence score across all decisions",
    )
    confidence_trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA
    common_failures: list[tuple[str, int]] = Field(
        default_factory=list,
        description="List of (error description, count) for most common failures",
    )
    problematic_nodes: list[tuple[str, float]] = Field(
        default_factory=list,
        description="List of (node_id, failure_rate) for nodes with issues",
    )

    model_config = {"extra": "allow"}


class Scorecard(BaseModel):
    """
    Complete agent outcome scorecard.

    Composite model aggregating all metrics with overall health assessment.
    Designed for enterprise stakeholder reporting.
    """

    # Identification
    agent_id: str
    agent_name: str
    goal_id: str
    goal_description: str = ""

    # Time window
    generated_at: datetime = Field(default_factory=datetime.now)
    time_window_start: datetime | None = None
    time_window_end: datetime | None = None
    runs_analyzed: int = Field(
        default=0,
        ge=0,
        description="Number of runs included in this scorecard",
    )

    # Overall metrics
    overall_health: int = Field(
        default=0,
        ge=0,
        le=100,
        description="Overall health score (0-100)",
    )
    goal_achievement_rate: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Rate at which the goal is successfully achieved",
    )
    goal_achievement_trend: TrendDirection = TrendDirection.INSUFFICIENT_DATA

    # Sub-metrics
    criterion_scores: list[CriterionScore] = Field(default_factory=list)
    cost_metrics: CostMetrics = Field(default_factory=CostMetrics)
    adaptation_metrics: AdaptationMetrics = Field(default_factory=AdaptationMetrics)

    # Computed summaries
    key_improvements: list[str] = Field(
        default_factory=list,
        description="List of notable improvements",
    )
    key_regressions: list[str] = Field(
        default_factory=list,
        description="List of notable regressions",
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Actionable recommendations based on scorecard analysis",
    )

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def health_label(self) -> HealthLabel:
        """Classify overall health based on score."""
        if self.overall_health >= 70:
            return HealthLabel.HEALTHY
        elif self.overall_health >= 40:
            return HealthLabel.NEEDS_ATTENTION
        else:
            return HealthLabel.CRITICAL

    @computed_field
    @property
    def summary(self) -> str:
        """Generate a one-line summary of the scorecard."""
        status_emoji = {
            HealthLabel.HEALTHY: "✓",
            HealthLabel.NEEDS_ATTENTION: "⚠",
            HealthLabel.CRITICAL: "✗",
        }
        emoji = status_emoji.get(self.health_label, "?")
        return (
            f"{emoji} {self.agent_name}: {self.overall_health}/100 health, "
            f"{self.goal_achievement_rate:.0%} goal achievement "
            f"({self.runs_analyzed} runs)"
        )

    def to_formatted_string(self) -> str:
        """Generate a detailed, human-readable scorecard."""
        lines = [
            "=" * 70,
            f"AGENT OUTCOME SCORECARD: {self.agent_name}",
            "=" * 70,
            "",
            f"Generated: {self.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Goal: {self.goal_description}" if self.goal_description else "",
            f"Runs Analyzed: {self.runs_analyzed}",
            "",
        ]

        # Time window
        if self.time_window_start and self.time_window_end:
            lines.append(
                f"Time Window: {self.time_window_start.strftime('%Y-%m-%d')} to "
                f"{self.time_window_end.strftime('%Y-%m-%d')}"
            )
            lines.append("")

        # Overall Health
        health_bar = self._generate_progress_bar(self.overall_health, 100)
        lines.extend([
            "-" * 40,
            "OVERALL HEALTH",
            "-" * 40,
            f"Score: {self.overall_health}/100 [{self.health_label.value.upper()}]",
            f"{health_bar}",
            "",
        ])

        # Goal Achievement
        achievement_bar = self._generate_progress_bar(
            int(self.goal_achievement_rate * 100), 100
        )
        lines.extend([
            "-" * 40,
            "GOAL ACHIEVEMENT",
            "-" * 40,
            f"Rate: {self.goal_achievement_rate:.1%} ({self.goal_achievement_trend.value})",
            f"{achievement_bar}",
            "",
        ])

        # Criterion Scores
        if self.criterion_scores:
            lines.extend([
                "-" * 40,
                "SUCCESS CRITERIA BREAKDOWN",
                "-" * 40,
            ])
            for cs in self.criterion_scores:
                trend_symbol = self._trend_symbol(cs.trend)
                lines.append(
                    f"  • {cs.description}: {cs.achievement_rate:.0%} "
                    f"[{trend_symbol}] (n={cs.sample_size})"
                )
            lines.append("")

        # Cost Metrics
        lines.extend([
            "-" * 40,
            "COST METRICS",
            "-" * 40,
            f"Total Spend: ${self.cost_metrics.total_spend:.4f}",
            f"Avg Cost/Run: ${self.cost_metrics.avg_cost_per_run:.4f} "
            f"({self._trend_symbol(self.cost_metrics.cost_trend)})",
            f"Cost Range: ${self.cost_metrics.min_run_cost:.4f} - "
            f"${self.cost_metrics.max_run_cost:.4f}",
            f"Total Tokens: {self.cost_metrics.total_tokens:,}",
            f"Avg Tokens/Run: {self.cost_metrics.avg_tokens_per_run:,.0f}",
            "",
        ])

        # Adaptation Metrics
        lines.extend([
            "-" * 40,
            "ADAPTATION & SELF-IMPROVEMENT",
            "-" * 40,
            f"Evolutions: {self.adaptation_metrics.total_evolutions}",
            f"Failure Modes: {self.adaptation_metrics.failure_modes_resolved} resolved, "
            f"{self.adaptation_metrics.failure_modes_remaining} remaining",
            f"Decision Confidence: {self.adaptation_metrics.avg_decision_confidence:.0%} "
            f"({self._trend_symbol(self.adaptation_metrics.confidence_trend)})",
        ])

        if self.adaptation_metrics.common_failures:
            lines.append("Common Failures:")
            for failure, count in self.adaptation_metrics.common_failures[:3]:
                failure_text = failure[:50] + "..." if len(failure) > 50 else failure
                lines.append(f"  - {failure_text} ({count}x)")

        if self.adaptation_metrics.problematic_nodes:
            lines.append("Problematic Nodes:")
            for node_id, rate in self.adaptation_metrics.problematic_nodes[:3]:
                lines.append(f"  - {node_id}: {rate:.0%} failure rate")

        lines.append("")

        # Key Findings
        if self.key_improvements or self.key_regressions:
            lines.extend([
                "-" * 40,
                "KEY FINDINGS",
                "-" * 40,
            ])
            if self.key_improvements:
                lines.append("Improvements:")
                for imp in self.key_improvements[:3]:
                    lines.append(f"  ✓ {imp}")
            if self.key_regressions:
                lines.append("Regressions:")
                for reg in self.key_regressions[:3]:
                    lines.append(f"  ✗ {reg}")
            lines.append("")

        # Recommendations
        if self.recommendations:
            lines.extend([
                "-" * 40,
                "RECOMMENDATIONS",
                "-" * 40,
            ])
            for i, rec in enumerate(self.recommendations[:5], 1):
                lines.append(f"  {i}. {rec}")
            lines.append("")

        lines.append("=" * 70)

        return "\n".join(line for line in lines if line is not None)

    @staticmethod
    def _generate_progress_bar(value: int, max_value: int, width: int = 30) -> str:
        """Generate a text-based progress bar."""
        filled = int(width * value / max_value) if max_value > 0 else 0
        bar = "█" * filled + "░" * (width - filled)
        return f"[{bar}] {value}%"

    @staticmethod
    def _trend_symbol(trend: TrendDirection) -> str:
        """Get a symbol for the trend direction."""
        symbols = {
            TrendDirection.IMPROVING: "↑",
            TrendDirection.STABLE: "→",
            TrendDirection.DECLINING: "↓",
            TrendDirection.INSUFFICIENT_DATA: "?",
        }
        return symbols.get(trend, "?")


class ScorecardDiff(BaseModel):
    """
    Comparison between two scorecards.

    Shows what changed between two points in time, highlighting
    improvements and regressions.
    """

    agent_id: str
    agent_name: str

    # Source scorecards metadata
    scorecard_before_date: datetime
    scorecard_after_date: datetime
    runs_before: int
    runs_after: int

    # Deltas
    health_delta: int = Field(
        default=0,
        description="Change in overall health score (positive = improvement)",
    )
    goal_achievement_delta: float = Field(
        default=0.0,
        description="Change in goal achievement rate (positive = improvement)",
    )
    cost_per_run_delta: float = Field(
        default=0.0,
        description="Change in average cost per run (negative = improvement)",
    )
    confidence_delta: float = Field(
        default=0.0,
        description="Change in decision confidence (positive = improvement)",
    )

    # Lists
    improvements: list[str] = Field(
        default_factory=list,
        description="List of metrics that improved",
    )
    regressions: list[str] = Field(
        default_factory=list,
        description="List of metrics that regressed",
    )
    new_failure_modes: list[str] = Field(
        default_factory=list,
        description="Failure modes that appeared in the newer scorecard",
    )
    resolved_failure_modes: list[str] = Field(
        default_factory=list,
        description="Failure modes that were resolved",
    )

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def overall_direction(self) -> TrendDirection:
        """Determine the overall trend direction of the comparison."""
        score = 0
        # Health improvement is positive
        if self.health_delta > 5:
            score += 1
        elif self.health_delta < -5:
            score -= 1

        # Goal achievement improvement is positive
        if self.goal_achievement_delta > 0.05:
            score += 1
        elif self.goal_achievement_delta < -0.05:
            score -= 1

        # Cost reduction is positive
        if self.cost_per_run_delta < -0.01:
            score += 1
        elif self.cost_per_run_delta > 0.01:
            score -= 1

        if score > 0:
            return TrendDirection.IMPROVING
        elif score < 0:
            return TrendDirection.DECLINING
        else:
            return TrendDirection.STABLE

    def to_formatted_string(self) -> str:
        """Generate a human-readable comparison report."""
        direction_emoji = {
            TrendDirection.IMPROVING: "📈",
            TrendDirection.DECLINING: "📉",
            TrendDirection.STABLE: "➡️",
        }

        lines = [
            "=" * 70,
            f"SCORECARD COMPARISON: {self.agent_name}",
            "=" * 70,
            "",
            f"Before: {self.scorecard_before_date.strftime('%Y-%m-%d')} "
            f"({self.runs_before} runs)",
            f"After:  {self.scorecard_after_date.strftime('%Y-%m-%d')} "
            f"({self.runs_after} runs)",
            f"Overall Trend: {direction_emoji.get(self.overall_direction, '?')} "
            f"{self.overall_direction.value.upper()}",
            "",
            "-" * 40,
            "METRIC CHANGES",
            "-" * 40,
        ]

        # Format deltas
        def format_delta(value: float, is_percentage: bool = False,
                        lower_is_better: bool = False) -> str:
            if is_percentage:
                formatted = f"{value:+.1%}"
            else:
                formatted = f"{value:+.2f}"
            
            if (value > 0 and not lower_is_better) or (value < 0 and lower_is_better):
                return f"{formatted} ✓"
            elif (value < 0 and not lower_is_better) or (value > 0 and lower_is_better):
                return f"{formatted} ✗"
            return formatted

        lines.extend([
            f"Health Score: {format_delta(self.health_delta)} points",
            f"Goal Achievement: {format_delta(self.goal_achievement_delta, True)}",
            f"Avg Cost/Run: {format_delta(self.cost_per_run_delta, lower_is_better=True)} $",
            f"Decision Confidence: {format_delta(self.confidence_delta, True)}",
            "",
        ])

        # Improvements
        if self.improvements:
            lines.extend([
                "-" * 40,
                "IMPROVEMENTS",
                "-" * 40,
            ])
            for imp in self.improvements:
                lines.append(f"  ✓ {imp}")
            lines.append("")

        # Regressions
        if self.regressions:
            lines.extend([
                "-" * 40,
                "REGRESSIONS",
                "-" * 40,
            ])
            for reg in self.regressions:
                lines.append(f"  ✗ {reg}")
            lines.append("")

        # Failure modes
        if self.resolved_failure_modes:
            lines.append("Resolved Failure Modes:")
            for fm in self.resolved_failure_modes[:5]:
                lines.append(f"  ✓ {fm}")

        if self.new_failure_modes:
            lines.append("New Failure Modes:")
            for fm in self.new_failure_modes[:5]:
                lines.append(f"  ✗ {fm}")

        lines.append("")
        lines.append("=" * 70)

        return "\n".join(lines)
