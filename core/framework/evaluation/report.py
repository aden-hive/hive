"""Evaluation reports and evolution recommendations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from framework.evaluation.failure_classifier import FailureCategory, FailureRecord
from framework.evaluation.metrics import EvaluationMetrics


class EvolutionStage(StrEnum):
    """Which stage of the Goal > Agent > Eval loop to revisit."""

    GOAL = "goal"
    AGENT = "agent"
    EVAL = "eval"
    CONFIG = "config"
    NONE = "none"


class RecommendationPriority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvolutionRecommendation(BaseModel):
    """A single actionable recommendation for improving the agent."""

    stage: EvolutionStage
    priority: RecommendationPriority
    action: str
    description: str
    target_node: str | None = None
    failure_category: FailureCategory | None = None
    estimated_effort: str = "small"

    model_config = {"extra": "allow"}


class EvaluationReport(BaseModel):
    """Complete evaluation report for a single agent execution."""

    run_id: str = ""
    agent_id: str = ""
    goal_id: str = ""

    passed: bool = False
    summary: str = ""

    metrics: EvaluationMetrics = Field(default_factory=EvaluationMetrics)
    failures: list[FailureRecord] = Field(default_factory=list)
    criteria_results: list[dict[str, Any]] = Field(default_factory=list)
    constraint_results: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[EvolutionRecommendation] = Field(default_factory=list)

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    @property
    def has_critical_failures(self) -> bool:
        return any(f.severity == "critical" for f in self.failures)

    @property
    def requires_graph_evolution(self) -> bool:
        return any(f.requires_graph_change for f in self.failures)

    @property
    def top_recommendation(self) -> EvolutionRecommendation | None:
        if not self.recommendations:
            return None
        return self.recommendations[0]

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "passed": self.passed,
            "summary": self.summary,
            "criteria": f"{self.metrics.criteria_met}/{self.metrics.criteria_total}",
            "failures": len(self.failures),
            "recommendations": len(self.recommendations),
            "top_action": self.top_recommendation.action if self.top_recommendation else None,
            "metrics": self.metrics.to_summary_dict(),
        }

    def to_coding_agent_prompt(self) -> str:
        """Format as a prompt the Coding Agent can consume to evolve the graph."""
        lines = [
            "# Agent Evaluation Report",
            "",
            f"Result: {'PASSED' if self.passed else 'FAILED'}",
            f"Summary: {self.summary}",
            "",
            "## Metrics",
            f"- Tokens: {self.metrics.total_tokens:,}",
            f"- Latency: {self.metrics.total_latency_ms:,}ms",
            f"- Cost: ${self.metrics.estimated_cost_usd:.4f}",
            f"- Criteria: {self.metrics.criteria_met}/{self.metrics.criteria_total}",
            f"- Retries: {self.metrics.total_retries}",
            "",
        ]

        if self.failures:
            lines.append("## Failures")
            for f in self.failures:
                node_info = f" (node: {f.node_id})" if f.node_id else ""
                lines.append(f"- [{f.severity.upper()}] {f.category.value}{node_info}: {f.message}")
            lines.append("")

        if self.criteria_results:
            lines.append("## Success Criteria")
            for cr in self.criteria_results:
                status = "PASS" if cr.get("met") else "FAIL"
                lines.append(f"- [{status}] {cr.get('description', cr.get('id', '?'))}")
            lines.append("")

        if self.recommendations:
            lines.append("## Recommended Actions")
            for i, rec in enumerate(self.recommendations, 1):
                lines.append(f"{i}. [{rec.priority.value.upper()}] {rec.action}")
                target = rec.target_node or "general"
                lines.append(f"   Stage: {rec.stage.value} | Target: {target}")
                lines.append(f"   {rec.description}")
            lines.append("")

        return "\n".join(lines)
