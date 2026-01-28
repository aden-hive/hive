"""
Plan Data Structures for Flexible Execution.

Plans are created externally (by Claude Code or another LLM agent) and
executed internally by the FlexibleGraphExecutor with Worker-Judge loop.

The Plan is the contract between the external planner and the executor:
- Planner creates a Plan with PlanSteps
- Executor runs steps and judges results
- If replanning needed, returns feedback to external planner
"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Types of actions a PlanStep can perform."""

    LLM_CALL = "llm_call"  # Call LLM for generation
    TOOL_USE = "tool_use"  # Use a registered tool
    SUB_GRAPH = "sub_graph"  # Execute a sub-graph
    FUNCTION = "function"  # Call a Python function
    CODE_EXECUTION = "code_execution"  # Execute dynamic code (sandboxed)


class StepStatus(str, Enum):
    """Status of a plan step."""

    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"  # Waiting for human approval
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    REJECTED = "rejected"  # Human rejected execution


class ApprovalDecision(str, Enum):
    """Human decision on a step requiring approval."""

    APPROVE = "approve"  # Execute as planned
    REJECT = "reject"  # Skip this step
    MODIFY = "modify"  # Execute with modifications
    ABORT = "abort"  # Stop entire execution


class ApprovalRequest(BaseModel):
    """Request for human approval before executing a step."""

    step_id: str
    step_description: str
    action_type: str
    action_details: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    approval_message: str | None = None

    # Preview of what will happen
    preview: str | None = None

    model_config = {"extra": "allow"}


class ApprovalResult(BaseModel):
    """Result of human approval decision."""

    decision: ApprovalDecision
    reason: str | None = None
    modifications: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class JudgmentAction(str, Enum):
    """Actions the judge can take after evaluating a step."""

    ACCEPT = "accept"  # Step completed successfully, continue
    RETRY = "retry"  # Retry the step with feedback
    REPLAN = "replan"  # Return to external planner for new plan
    ESCALATE = "escalate"  # Request human intervention


class ActionSpec(BaseModel):
    """
    Specification for an action to be executed.

    This is the "what to do" part of a PlanStep.
    """

    action_type: ActionType

    # For LLM_CALL
    prompt: str | None = None
    system_prompt: str | None = None
    model: str | None = None

    # For TOOL_USE
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)

    # For SUB_GRAPH
    graph_id: str | None = None

    # For FUNCTION
    function_name: str | None = None
    function_args: dict[str, Any] = Field(default_factory=dict)

    # For CODE_EXECUTION
    code: str | None = None
    language: str = "python"

    model_config = {"extra": "allow"}


class PlanStep(BaseModel):
    """
    A single step in a plan.

    Created by external planner, executed by Worker, evaluated by Judge.
    """

    id: str
    description: str
    action: ActionSpec

    # Data flow
    inputs: dict[str, Any] = Field(
        default_factory=dict,
        description="Input data for this step (can reference previous step outputs)",
    )
    expected_outputs: list[str] = Field(
        default_factory=list, description="Keys this step should produce"
    )

    # Dependencies
    dependencies: list[str] = Field(
        default_factory=list, description="IDs of steps that must complete before this one"
    )

    # Human-in-the-loop (HITL)
    requires_approval: bool = Field(
        default=False, description="If True, requires human approval before execution"
    )
    approval_message: str | None = Field(
        default=None, description="Message to show human when requesting approval"
    )

    # Execution state
    status: StepStatus = StepStatus.PENDING
    result: Any | None = None
    error: str | None = None
    attempts: int = 0
    max_retries: int = 3

    # Metadata
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"extra": "allow"}

    def is_ready(self, completed_step_ids: set[str]) -> bool:
        """Check if this step is ready to execute (all dependencies met)."""
        if self.status != StepStatus.PENDING:
            return False
        return all(dep in completed_step_ids for dep in self.dependencies)


class Judgment(BaseModel):
    """
    Result of judging a step execution.

    The Judge evaluates step results and decides what to do next.
    """

    action: JudgmentAction
    reasoning: str
    feedback: str | None = None  # For retry/replan - what went wrong

    # For rule-based judgments
    rule_matched: str | None = None

    # For LLM-based judgments
    confidence: float = 1.0
    llm_used: bool = False

    # Context for replanning
    context: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class EvaluationRule(BaseModel):
    """
    A rule for the HybridJudge to evaluate step results.

    Rules are checked before falling back to LLM evaluation.
    """

    id: str
    description: str

    # Condition (Python expression evaluated with result, step, goal context)
    condition: str

    # What to do if condition matches
    action: JudgmentAction
    feedback_template: str = ""  # Can use {result}, {step}, etc.

    # Priority (higher = checked first)
    priority: int = 0

    model_config = {"extra": "allow"}


class Plan(BaseModel):
    """
    A complete execution plan.

    Created by external planner (Claude Code, etc).
    Executed by FlexibleGraphExecutor.
    """

    id: str
    goal_id: str
    description: str

    # Steps to execute
    steps: list[PlanStep] = Field(default_factory=list)

    # Execution state
    revision: int = 1  # Incremented on replan
    current_step_idx: int = 0

    # Accumulated context from execution
    context: dict[str, Any] = Field(default_factory=dict)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    created_by: str = "external"  # Who created this plan

    # Previous attempt info (for replanning)
    previous_feedback: str | None = None

    model_config = {"extra": "allow"}

    @classmethod
    def from_json(cls, data: str | dict) -> "Plan":
        """
        Load a Plan from exported JSON.

        This handles the output from export_graph() and properly converts
        action_type strings to ActionType enums.

        Args:
            data: JSON string or dict from export_graph()

        Returns:
            Plan object ready for FlexibleGraphExecutor

        Example:
            # Load from export_graph() output
            exported = export_graph()
            plan = Plan.from_json(exported)

            # Load from file
            with open("plan.json") as f:
                plan = Plan.from_json(json.load(f))
        """
        import json as json_module

        if isinstance(data, str):
            data = json_module.loads(data)

        # Handle nested "plan" key from export_graph output
        if "plan" in data:
            data = data["plan"]

        # Convert steps
        steps = []
        for step_data in data.get("steps", []):
            action_data = step_data.get("action", {})

            # Convert action_type string to enum
            action_type_str = action_data.get("action_type", "function")
            action_type = ActionType(action_type_str)

            action = ActionSpec(
                action_type=action_type,
                prompt=action_data.get("prompt"),
                system_prompt=action_data.get("system_prompt"),
                tool_name=action_data.get("tool_name"),
                tool_args=action_data.get("tool_args", {}),
                function_name=action_data.get("function_name"),
                function_args=action_data.get("function_args", {}),
                code=action_data.get("code"),
            )

            step = PlanStep(
                id=step_data["id"],
                description=step_data.get("description", ""),
                action=action,
                inputs=step_data.get("inputs", {}),
                expected_outputs=step_data.get("expected_outputs", []),
                dependencies=step_data.get("dependencies", []),
                requires_approval=step_data.get("requires_approval", False),
                approval_message=step_data.get("approval_message"),
            )
            steps.append(step)

        return cls(
            id=data.get("id", "plan"),
            goal_id=data.get("goal_id", ""),
            description=data.get("description", ""),
            steps=steps,
            context=data.get("context", {}),
            revision=data.get("revision", 1),
        )

    def get_step(self, step_id: str) -> PlanStep | None:
        """Get a step by ID."""
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def get_ready_steps(self) -> list[PlanStep]:
        """Get all steps that are ready to execute."""
        completed_ids = {s.id for s in self.steps if s.status == StepStatus.COMPLETED}
        return [s for s in self.steps if s.is_ready(completed_ids)]

    def get_completed_steps(self) -> list[PlanStep]:
        """Get all completed steps."""
        return [s for s in self.steps if s.status == StepStatus.COMPLETED]

    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        return all(s.status == StepStatus.COMPLETED for s in self.steps)

    def to_feedback_context(self) -> dict[str, Any]:
        """Create context for replanning."""
        return {
            "plan_id": self.id,
            "revision": self.revision,
            "completed_steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "result": s.result,
                }
                for s in self.get_completed_steps()
            ],
            "failed_steps": [
                {
                    "id": s.id,
                    "description": s.description,
                    "error": s.error,
                    "attempts": s.attempts,
                }
                for s in self.steps
                if s.status == StepStatus.FAILED
            ],
            "context": self.context,
        }


class ExecutionStatus(str, Enum):
    """Status of plan execution."""

    COMPLETED = "completed"
    AWAITING_APPROVAL = "awaiting_approval"  # Paused for human approval
    NEEDS_REPLAN = "needs_replan"
    NEEDS_ESCALATION = "needs_escalation"
    REJECTED = "rejected"  # Human rejected a step
    ABORTED = "aborted"  # Human aborted execution
    FAILED = "failed"


class PlanExecutionResult(BaseModel):
    """
    Result of executing a plan.

    Returned to external planner with status and feedback.
    """

    status: ExecutionStatus

    # Results from completed steps
    results: dict[str, Any] = Field(default_factory=dict)

    # For needs_replan - what to tell the planner
    feedback: str | None = None
    feedback_context: dict[str, Any] = Field(default_factory=dict)

    # Steps that completed before stopping
    completed_steps: list[str] = Field(default_factory=list)

    # Metrics
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0

    # Error info (for failed status)
    error: str | None = None

    model_config = {"extra": "allow"}


def load_export(data: str | dict) -> tuple["Plan", Any]:
    """
    Load both Plan and Goal from export_graph() output.

    The export_graph() MCP tool returns both the plan and the goal that was
    defined and approved during the agent building process. This function
    loads both so you can use them with FlexibleGraphExecutor.

    Args:
        data: JSON string or dict from export_graph()

    Returns:
        Tuple of (Plan, Goal) ready for FlexibleGraphExecutor

    Example:
        # Load from export_graph() output
        exported = export_graph()
        plan, goal = load_export(exported)

        result = await executor.execute_plan(plan, goal, context)
    """
    import json as json_module

    from framework.graph.goal import Goal

    if isinstance(data, str):
        data = json_module.loads(data)

    # Load plan
    plan = Plan.from_json(data)

    # Load goal
    goal_data = data.get("goal", {})
    if goal_data:
        goal = Goal.model_validate(goal_data)
    else:
        # Fallback: create minimal goal from plan metadata
        goal = Goal(
            id=plan.goal_id,
            name=plan.goal_id,
            description=plan.description,
            success_criteria=[],
            constraints=[],
        )

    return plan, goal
