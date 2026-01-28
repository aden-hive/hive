"""
Decision Schema - The atomic unit of agent behavior that Builder cares about.

A Decision captures a moment where the agent chose between options.
This is MORE important than actions because:
1. It shows the agent's reasoning
2. It shows what alternatives existed
3. It can be correlated with outcomes
4. It's what we need to improve
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class DecisionType(str, Enum):
    """Types of decisions an agent can make."""

    TOOL_SELECTION = "tool_selection"  # Which tool to use
    PARAMETER_CHOICE = "parameter_choice"  # What parameters to pass
    PATH_CHOICE = "path_choice"  # Which branch to take
    OUTPUT_FORMAT = "output_format"  # How to format output
    RETRY_STRATEGY = "retry_strategy"  # How to handle failure
    DELEGATION = "delegation"  # Whether to delegate to another node
    TERMINATION = "termination"  # Whether to stop or continue
    CUSTOM = "custom"  # User-defined decision type


class Option(BaseModel):
    """
    One possible choice the agent could make.

    Capturing options is crucial - it shows what the agent considered
    and enables us to evaluate whether the right choice was made.
    """

    id: str
    description: str  # Human-readable: "Call search API"
    action_type: str  # "tool_call", "generate", "delegate"
    action_params: dict[str, Any] = Field(default_factory=dict)

    # Why might this be good or bad?
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)

    # Agent's confidence in this option (0-1)
    confidence: float = 0.5

    model_config = {"extra": "allow"}


class Outcome(BaseModel):
    """
    What actually happened when a decision was executed.

    This is filled in AFTER the action completes, allowing us to
    correlate decisions with their results.
    """

    success: bool
    result: Any = None  # The actual output
    error: str | None = None  # Error message if failed

    # Side effects
    state_changes: dict[str, Any] = Field(default_factory=dict)
    tokens_used: int = 0
    latency_ms: int = 0

    # Natural language summary (crucial for Builder)
    summary: str = ""  # "Found 3 contacts matching query"

    timestamp: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}


class DecisionEvaluation(BaseModel):
    """
    Post-hoc evaluation of whether a decision was good.

    This is computed AFTER the run completes, allowing us to
    judge decisions in light of their eventual outcomes.
    """

    # Did it move toward the goal?
    goal_aligned: bool = True
    alignment_score: float = Field(default=1.0, ge=0.0, le=1.0)

    # Was there a better option?
    better_option_existed: bool = False
    better_option_id: str | None = None
    why_better: str | None = None

    # Outcome quality
    outcome_quality: float = Field(default=1.0, ge=0.0, le=1.0)

    # Did this contribute to final success/failure?
    contributed_to_success: bool | None = None

    # Explanation for Builder
    explanation: str = ""

    model_config = {"extra": "allow"}


class Decision(BaseModel):
    """
    The atomic unit of agent behavior that Builder analyzes.

    Every significant choice the agent makes is captured here.
    This is the core data structure for understanding and improving agents.
    """

    id: str
    timestamp: datetime = Field(default_factory=datetime.now)
    node_id: str

    # WHAT was the agent trying to accomplish?
    intent: str = Field(description="What the agent was trying to do")

    # WHAT type of decision is this?
    decision_type: DecisionType = DecisionType.CUSTOM

    # WHAT options did it consider?
    options: list[Option] = Field(default_factory=list)

    # WHAT did it choose?
    chosen_option_id: str = ""

    # WHY? (The agent's stated reasoning)
    reasoning: str = ""

    # WHAT constraints were active?
    active_constraints: list[str] = Field(default_factory=list)

    # WHAT input context was available?
    input_context: dict[str, Any] = Field(default_factory=dict)

    # WHAT happened? (Filled in after execution)
    outcome: Outcome | None = None

    # Was this a GOOD decision? (Evaluated later)
    evaluation: DecisionEvaluation | None = None

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def chosen_option(self) -> Option | None:
        """Get the option that was chosen."""
        for opt in self.options:
            if opt.id == self.chosen_option_id:
                return opt
        return None

    @computed_field
    @property
    def was_successful(self) -> bool:
        """Did this decision's execution succeed?"""
        return self.outcome is not None and self.outcome.success

    @computed_field
    @property
    def was_good_decision(self) -> bool:
        """Was this evaluated as a good decision?"""
        if self.evaluation is None:
            return self.was_successful
        return self.evaluation.goal_aligned and self.evaluation.outcome_quality > 0.5

    def summary_for_builder(self) -> str:
        """Generate a one-line summary for Builder to quickly understand."""
        status = "✓" if self.was_successful else "✗"
        quality = ""
        if self.evaluation:
            quality = f" [quality: {self.evaluation.outcome_quality:.1f}]"
        chosen = self.chosen_option
        action = chosen.description if chosen else "unknown action"
        return f"{status} [{self.node_id}] {self.intent} → {action}{quality}"
