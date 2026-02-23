"""
Failure Taxonomy - Structured classification system for agent failures.

This module provides a taxonomy of failure categories with mapped evolution
strategies, enabling faster and more targeted self-improvement cycles.

The taxonomy transforms raw failure data into actionable evolution signals,
allowing the builder to make targeted decisions instead of guessing what
changes to make.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FailureCategory(StrEnum):
    """Categories of failures that can occur during agent execution."""

    GOAL_AMBIGUITY = "goal_ambiguity"
    TOOL_ERROR = "tool_error"
    ROUTING_ERROR = "routing_error"
    OUTPUT_QUALITY = "output_quality"
    COST_OVERRUN = "cost_overrun"
    TIMEOUT = "timeout"
    HALLUCINATION = "hallucination"
    CONSTRAINT_VIOLATION = "constraint_violation"
    EXTERNAL_DEPENDENCY = "external_dependency"
    UNKNOWN = "unknown"


class EvolutionStrategy(StrEnum):
    """Strategies for evolving an agent to address failures."""

    REFINE_GOAL = "refine_goal"
    ADD_RETRY = "add_retry"
    MODIFY_EDGES = "modify_edges"
    REFINE_PROMPTS = "refine_prompts"
    REDUCE_COST = "reduce_cost"
    PARALLELIZE = "parallelize"
    ADD_GROUNDING = "add_grounding"
    ADD_CONSTRAINTS = "add_constraints"
    INVESTIGATE = "investigate"


FAILURE_CATEGORY_TO_STRATEGY: dict[FailureCategory, EvolutionStrategy] = {
    FailureCategory.GOAL_AMBIGUITY: EvolutionStrategy.REFINE_GOAL,
    FailureCategory.TOOL_ERROR: EvolutionStrategy.ADD_RETRY,
    FailureCategory.ROUTING_ERROR: EvolutionStrategy.MODIFY_EDGES,
    FailureCategory.OUTPUT_QUALITY: EvolutionStrategy.REFINE_PROMPTS,
    FailureCategory.COST_OVERRUN: EvolutionStrategy.REDUCE_COST,
    FailureCategory.TIMEOUT: EvolutionStrategy.PARALLELIZE,
    FailureCategory.HALLUCINATION: EvolutionStrategy.ADD_GROUNDING,
    FailureCategory.CONSTRAINT_VIOLATION: EvolutionStrategy.ADD_CONSTRAINTS,
    FailureCategory.EXTERNAL_DEPENDENCY: EvolutionStrategy.ADD_RETRY,
    FailureCategory.UNKNOWN: EvolutionStrategy.INVESTIGATE,
}

CATEGORY_DESCRIPTIONS: dict[FailureCategory, str] = {
    FailureCategory.GOAL_AMBIGUITY: "Goal is unclear or lacks necessary specificity",
    FailureCategory.TOOL_ERROR: "Tool invocation failed (API error, rate limit, etc.)",
    FailureCategory.ROUTING_ERROR: "Agent sent data to wrong node or branch",
    FailureCategory.OUTPUT_QUALITY: "Output doesn't meet quality standards",
    FailureCategory.COST_OVERRUN: "Execution exceeded token or cost budget",
    FailureCategory.TIMEOUT: "Execution exceeded time limit",
    FailureCategory.HALLUCINATION: "Agent generated fabricated or incorrect data",
    FailureCategory.CONSTRAINT_VIOLATION: "Agent bypassed required constraints",
    FailureCategory.EXTERNAL_DEPENDENCY: "External service or resource unavailable",
    FailureCategory.UNKNOWN: "Failure type could not be determined",
}

STRATEGY_DESCRIPTIONS: dict[EvolutionStrategy, str] = {
    EvolutionStrategy.REFINE_GOAL: "Clarify or add specificity to the goal description",
    EvolutionStrategy.ADD_RETRY: "Add retry/fallback logic for tool calls",
    EvolutionStrategy.MODIFY_EDGES: "Modify edge conditions or routing logic",
    EvolutionStrategy.REFINE_PROMPTS: "Improve node prompts for better outputs",
    EvolutionStrategy.REDUCE_COST: "Switch to cheaper model or optimize token usage",
    EvolutionStrategy.PARALLELIZE: "Parallelize independent nodes",
    EvolutionStrategy.ADD_GROUNDING: "Add validation/verification step",
    EvolutionStrategy.ADD_CONSTRAINTS: "Enforce constraints at edge level",
    EvolutionStrategy.INVESTIGATE: "Manual investigation required",
}


class ClassifiedFailure(BaseModel):
    """A failure that has been classified according to the taxonomy."""

    category: FailureCategory
    subcategory: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    recommended_strategy: EvolutionStrategy = EvolutionStrategy.INVESTIGATE
    affected_nodes: list[str] = Field(default_factory=list)
    affected_edges: list[str] = Field(default_factory=list)
    raw_error: str | None = None

    model_config = {"extra": "allow"}

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.recommended_strategy == EvolutionStrategy.INVESTIGATE:
            self.recommended_strategy = FAILURE_CATEGORY_TO_STRATEGY.get(
                self.category, EvolutionStrategy.INVESTIGATE
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "subcategory": self.subcategory,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "recommended_strategy": self.recommended_strategy.value,
            "affected_nodes": self.affected_nodes,
            "affected_edges": self.affected_edges,
            "raw_error": self.raw_error,
        }

    def __str__(self) -> str:
        lines = [
            f"=== Classified Failure ===",
            f"Category: {self.category.value}",
            f"Confidence: {self.confidence:.2f}",
            f"Recommended Strategy: {self.recommended_strategy.value}",
        ]
        if self.subcategory:
            lines.append(f"Subcategory: {self.subcategory}")
        if self.evidence:
            lines.append("Evidence:")
            for e in self.evidence:
                lines.append(f"  - {e}")
        if self.affected_nodes:
            lines.append(f"Affected Nodes: {', '.join(self.affected_nodes)}")
        if self.affected_edges:
            lines.append(f"Affected Edges: {', '.join(self.affected_edges)}")
        return "\n".join(lines)


class FailureDistribution(BaseModel):
    """Distribution of failure categories across runs."""

    counts: dict[str, int] = Field(default_factory=dict)
    total_failures: int = 0

    def add_failure(self, category: FailureCategory) -> None:
        key = category.value
        self.counts[key] = self.counts.get(key, 0) + 1
        self.total_failures += 1

    def get_percentage(self, category: FailureCategory) -> float:
        if self.total_failures == 0:
            return 0.0
        return (self.counts.get(category.value, 0) / self.total_failures) * 100

    def get_top_categories(self, limit: int = 5) -> list[tuple[FailureCategory, int]]:
        sorted_categories = sorted(self.counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [(FailureCategory(cat), count) for cat, count in sorted_categories]

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": self.counts,
            "total_failures": self.total_failures,
            "percentages": {cat: self.get_percentage(FailureCategory(cat)) for cat in self.counts},
        }

    def __str__(self) -> str:
        lines = [f"=== Failure Distribution ({self.total_failures} total) ==="]
        for category, count in self.get_top_categories():
            pct = self.get_percentage(category)
            lines.append(f"  {category.value}: {count} ({pct:.1f}%)")
        return "\n".join(lines)
