"""
Failure Report - Synthesized diagnosis when goal.is_success() returns False.

Generated automatically by OutcomeAggregator after evaluate_output detects
that the goal was not achieved. Captures unmet criteria, violated constraints,
relevant node IDs from the execution trace, and a human-readable summary.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class UnmetCriterion(BaseModel):
    """A success criterion that was not met."""

    criterion_id: str
    description: str
    metric: str
    target: Any
    weight: float

    model_config = {"extra": "allow"}


class ViolatedConstraint(BaseModel):
    """A constraint that was violated during execution."""

    constraint_id: str
    description: str
    constraint_type: str  # "hard" or "soft"
    violation_details: str
    stream_id: str | None = None
    execution_id: str | None = None

    model_config = {"extra": "allow"}


class FailureReport(BaseModel):
    """Synthesized report when goal evaluation fails.

    Combines unmet criteria, violated constraints, and execution trace
    data into a single artifact for debugging and iteration guidance.
    """

    goal_id: str
    goal_name: str

    # What failed
    unmet_criteria: list[UnmetCriterion] = Field(default_factory=list)
    violated_constraints: list[ViolatedConstraint] = Field(default_factory=list)

    # Execution context
    node_ids: list[str] = Field(
        default_factory=list,
        description="Node IDs from the execution trace relevant to the failure",
    )
    edge_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Edge IDs ('src->dst') derived from consecutive decisions in the "
            "failed execution trace, used for targeted evolution"
        ),
    )

    # Versioning: monotonically increasing sequence per goal
    version: int = Field(
        default=1,
        description="Sequence number within the goal's failure history",
    )

    # Categorization (Phase 3): category derived from the failure summary
    # via ErrorCategorizer, used by EvolutionTrigger to scope its prompt.
    # Stored as a plain string to keep this schema decoupled from the
    # testing module's ErrorCategory enum.
    error_category: str | None = Field(
        default=None,
        description="logic_error | implementation_error | edge_case",
    )

    # Summary
    summary: str = Field(
        default="",
        description="Human-readable summary of why the goal was not achieved",
    )

    # Metrics snapshot
    total_decisions: int = 0
    successful_outcomes: int = 0
    failed_outcomes: int = 0

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}
