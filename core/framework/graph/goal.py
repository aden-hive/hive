"""
Goal Schema - The source of truth for agent behavior.

A Goal defines WHAT the agent should achieve, not HOW. The graph structure
(nodes and edges) is derived from the goal, not hardcoded.

Goals are:
- Declarative: Define success criteria, not implementation
- Measurable: Success criteria are checkable
- Constrained: Boundaries the agent must respect
- Versionable: Can evolve based on runtime feedback
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class GoalStatus(StrEnum):
    """Lifecycle status of a goal."""

    DRAFT = "draft"  # Being defined
    READY = "ready"  # Ready for agent creation
    ACTIVE = "active"  # Has an agent graph, can execute
    COMPLETED = "completed"  # Achieved
    FAILED = "failed"  # Could not be achieved
    SUSPENDED = "suspended"  # Paused for revision


class SuccessCriterion(BaseModel):
    """
    A measurable condition that defines success.

    Each criterion should be:
    - Specific: Clear what it means
    - Measurable: Can be evaluated programmatically or by LLM
    - Achievable: Within the agent's capabilities
    """

    id: str
    description: str = Field(description="Human-readable description of what success looks like")
    metric: str = Field(
        description="How to measure: 'output_contains', 'output_equals', 'llm_judge', 'custom'"
    )
    # NEW: runtime evaluation type (separate from metric)
    type: str = Field(
        default="success_rate", description="Runtime evaluation type, e.g. 'success_rate'"
    )

    target: Any = Field(description="The target value or condition")
    weight: float = Field(default=1.0, ge=0.0, le=1.0, description="Relative importance (0-1)")
    met: bool = False

    model_config = {"extra": "allow"}


class Constraint(BaseModel):
    """
    A boundary the agent must respect.

    Constraints are either:
    - Hard: Violation means failure
    - Soft: Violation is discouraged but allowed
    """

    id: str
    description: str
    constraint_type: str = Field(
        description="Type: 'hard' (must not violate) or 'soft' (prefer not to violate)"
    )
    category: str = Field(
        default="general", description="Category: 'time', 'cost', 'safety', 'scope', 'quality'"
    )
    check: str = Field(
        default="", description="How to check: expression, function name, or 'llm_judge'"
    )

    model_config = {"extra": "allow"}


class Goal(BaseModel):
    """
    The source of truth for agent behavior.

    A Goal defines:
    - WHAT to achieve (success criteria)
    - WHAT NOT to do (constraints)
    - CONTEXT for decision-making

    The agent graph (nodes, edges) is derived from this goal.

    Example:
        goal = Goal(
            id="calc-001",
            name="Calculator",
            description="Perform mathematical calculations accurately",
            success_criteria=[
                SuccessCriterion(
                    id="accuracy",
                    description="Result matches expected mathematical answer",
                    metric="output_equals",
                    target="expected_result",
                    weight=1.0
                )
            ],
            constraints=[
                Constraint(
                    id="no-crash",
                    description="Handle invalid inputs gracefully, return 'Error'",
                    constraint_type="hard",
                    category="safety",
                    check="output != exception"
                )
            ]
        )
    """

    id: str
    name: str
    description: str
    status: GoalStatus = GoalStatus.DRAFT

    # What defines success
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)

    # What the agent must respect
    constraints: list[Constraint] = Field(default_factory=list)

    # Context for the agent
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context: domain knowledge, user preferences, etc.",
    )

    # Capabilities required
    required_capabilities: list[str] = Field(
        default_factory=list,
        description="What the agent needs: 'llm', 'web_search', 'code_execution', etc.",
    )

    # Input/output schema
    input_schema: dict[str, Any] = Field(default_factory=dict, description="Expected input format")
    output_schema: dict[str, Any] = Field(
        default_factory=dict, description="Expected output format"
    )

    # Versioning for evolution
    version: str = "1.0.0"
    parent_version: str | None = None
    evolution_reason: str | None = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    def is_success(self) -> bool:
        """Check if all weighted success criteria are met."""
        if not self.success_criteria:
            return False

        total_weight = sum(c.weight for c in self.success_criteria)
        met_weight = sum(c.weight for c in self.success_criteria if c.met)

        return met_weight >= total_weight * 0.9  # 90% threshold

    def check_constraint(self, constraint_id: str, value: Any) -> bool:
        """Check if a specific constraint is satisfied."""
        for c in self.constraints:
            if c.id == constraint_id:
                # This would be expanded with actual evaluation logic
                return True
        return True

    def to_prompt_context(self) -> str:
        """Generate context string for LLM prompts."""
        lines = [
            f"# Goal: {self.name}",
            f"{self.description}",
            "",
            "## Success Criteria:",
        ]

        for sc in self.success_criteria:
            lines.append(f"- {sc.description}")

        if self.constraints:
            lines.append("")
            lines.append("## Constraints:")
            for c in self.constraints:
                severity = "MUST" if c.constraint_type == "hard" else "SHOULD"
                lines.append(f"- [{severity}] {c.description}")

        if self.context:
            lines.append("")
            lines.append("## Context:")
            for key, value in self.context.items():
                lines.append(f"- {key}: {value}")

        return "\n".join(lines)
