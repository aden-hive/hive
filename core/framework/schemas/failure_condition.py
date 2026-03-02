"""
Failure Condition Schema - SDK for defining and evaluating failure conditions.

A FailureCondition defines when an agent execution should be considered failed.
This enables proactive failure detection rather than post-hoc exception handling.

Key Components:
- FailureSeverity: Enum for severity levels (CRITICAL, MAJOR, MINOR, WARNING)
- ExecutionContext: Context data for evaluating failure conditions
- FailureCondition: A condition that, when triggered, indicates failure
- FailureResult: The result of evaluating a failure condition
- FailureEvaluator: Evaluates multiple conditions against execution context
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class FailureSeverity(StrEnum):
    """Severity level of a failure condition."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"


@dataclass
class ExecutionContext:
    """
    Context data for evaluating failure conditions.

    This captures the runtime state that failure conditions check against.
    """

    elapsed_time: float = 0.0
    total_tokens: int = 0
    output: dict[str, Any] = field(default_factory=dict)
    last_outcome: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    decisions_count: int = 0
    successful_decisions: int = 0
    failed_decisions: int = 0
    budget: dict[str, Any] = field(default_factory=dict)
    goal_constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        """Calculate success rate of decisions."""
        total = self.successful_decisions + self.failed_decisions
        if total == 0:
            return 0.0
        return self.successful_decisions / total

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "elapsed_time": self.elapsed_time,
            "total_tokens": self.total_tokens,
            "output": self.output,
            "last_outcome": self.last_outcome,
            "errors": self.errors,
            "decisions_count": self.decisions_count,
            "successful_decisions": self.successful_decisions,
            "failed_decisions": self.failed_decisions,
            "budget": self.budget,
            "goal_constraints": self.goal_constraints,
            "metadata": self.metadata,
            "success_rate": self.success_rate,
        }


class FailureCondition(BaseModel):
    """
    A condition that, when triggered, indicates failure.

    FailureConditions enable proactive failure detection. They can be:
    - Pre-defined and reusable (built-in conditions)
    - Custom conditions for specific use cases
    - Combined with severity levels for prioritization

    Example:
        condition = FailureCondition(
            name="timeout_exceeded",
            description="Execution exceeded maximum allowed time",
            severity=FailureSeverity.MAJOR,
            check="elapsed_time > max_duration",
            recovery_hint="Consider optimizing the agent or increasing timeout"
        )
    """

    name: str = Field(description="Unique identifier for this condition")
    description: str = Field(description="Human-readable description of the failure")
    severity: FailureSeverity = Field(
        default=FailureSeverity.MAJOR, description="Severity level of this failure"
    )
    check: str = Field(
        description="Evaluation expression or Python callable string. "
        "Receives ExecutionContext as 'ctx'. Examples: "
        "'ctx.elapsed_time > 60', 'len(ctx.errors) > 0'"
    )
    recovery_hint: str | None = Field(
        default=None, description="Suggested action to recover from this failure"
    )
    enabled: bool = Field(default=True, description="Whether this condition is active")

    model_config = {"extra": "allow"}

    def evaluate(self, context: ExecutionContext) -> "FailureResult":
        """
        Evaluate this condition against the execution context.

        Args:
            context: The execution context to check against

        Returns:
            FailureResult indicating whether the condition was triggered
        """
        if not self.enabled:
            return FailureResult(
                condition=self,
                triggered=False,
                context=context.to_dict(),
                timestamp=datetime.now(),
                evaluation_error=None,
            )

        try:
            result = self._evaluate_check(context)
            return FailureResult(
                condition=self,
                triggered=bool(result),
                context=context.to_dict(),
                timestamp=datetime.now(),
                evaluation_error=None,
            )
        except Exception as e:
            return FailureResult(
                condition=self,
                triggered=False,
                context=context.to_dict(),
                timestamp=datetime.now(),
                evaluation_error=str(e),
            )

    def _evaluate_check(self, context: ExecutionContext) -> bool:
        """
        Internal method to evaluate the check expression.

        Supports:
        - Simple Python expressions with 'ctx' variable
        - Callable references (as string names to be resolved)
        """
        safe_builtins = {
            "len": len,
            "float": float,
            "int": int,
            "str": str,
            "bool": bool,
            "list": list,
            "dict": dict,
            "True": True,
            "False": False,
            "None": None,
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "any": any,
            "all": all,
            "isinstance": isinstance,
        }
        local_vars = {"ctx": context}

        if self.check.startswith("lambda ") or "lambda " in self.check:
            result = eval(self.check, {"__builtins__": safe_builtins}, local_vars)
            if callable(result):
                return result(context)
            return bool(result)

        try:
            return bool(eval(self.check, {"__builtins__": safe_builtins}, local_vars))
        except Exception:
            raise

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "description": self.description,
            "severity": self.severity.value,
            "check": self.check,
            "recovery_hint": self.recovery_hint,
            "enabled": self.enabled,
        }


class FailureResult(BaseModel):
    """
    The result of evaluating a failure condition.

    Captures whether a condition was triggered, along with context
    and timing information for debugging and logging.
    """

    condition: FailureCondition = Field(description="The condition that was evaluated")
    triggered: bool = Field(description="Whether the failure condition was met")
    context: dict[str, Any] = Field(description="Snapshot of execution context at evaluation time")
    timestamp: datetime = Field(
        default_factory=datetime.now, description="When the evaluation occurred"
    )
    evaluation_error: str | None = Field(
        default=None, description="Error that occurred during evaluation, if any"
    )

    model_config = {"extra": "allow"}

    @property
    def severity(self) -> FailureSeverity:
        """Get the severity of the associated condition."""
        return self.condition.severity

    @property
    def is_critical(self) -> bool:
        """Check if this is a critical failure."""
        return self.triggered and self.condition.severity == FailureSeverity.CRITICAL

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "condition_name": self.condition.name,
            "triggered": self.triggered,
            "severity": self.severity.value,
            "context": self.context,
            "timestamp": self.timestamp.isoformat(),
            "evaluation_error": self.evaluation_error,
            "recovery_hint": self.condition.recovery_hint,
        }


class FailureEvaluator(BaseModel):
    """
    Evaluates multiple failure conditions against an execution context.

    The FailureEvaluator is the main entry point for checking failure
    conditions during agent execution.

    Example:
        evaluator = FailureEvaluator(conditions=[
            TIMEOUT_EXCEEDED,
            TOKEN_BUDGET_EXCEEDED,
            custom_condition
        ])

        results = evaluator.check_all(context)
        if evaluator.has_critical_failure(results):
            # Handle critical failure
            pass
    """

    conditions: list[FailureCondition] = Field(
        default_factory=list, description="List of conditions to evaluate"
    )

    model_config = {"extra": "allow"}

    def check_all(self, context: ExecutionContext) -> list[FailureResult]:
        """
        Evaluate all conditions against the execution context.

        Args:
            context: The execution context to check against

        Returns:
            List of FailureResult objects, one for each condition
        """
        return [condition.evaluate(context) for condition in self.conditions]

    def has_critical_failure(self, results: list[FailureResult]) -> bool:
        """
        Check if any critical failure conditions were triggered.

        Args:
            results: List of failure results to check

        Returns:
            True if any critical condition was triggered
        """
        return any(r.is_critical for r in results)

    def get_triggered_failures(self, results: list[FailureResult]) -> list[FailureResult]:
        """
        Get only the failures that were triggered.

        Args:
            results: List of failure results to filter

        Returns:
            List of triggered failure results, sorted by severity
        """
        triggered = [r for r in results if r.triggered]
        severity_order = {
            FailureSeverity.CRITICAL: 0,
            FailureSeverity.MAJOR: 1,
            FailureSeverity.MINOR: 2,
            FailureSeverity.WARNING: 3,
        }
        return sorted(triggered, key=lambda r: severity_order.get(r.severity, 4))

    def get_failures_by_severity(
        self, results: list[FailureResult], severity: FailureSeverity
    ) -> list[FailureResult]:
        """
        Get failures of a specific severity level.

        Args:
            results: List of failure results to filter
            severity: Severity level to filter by

        Returns:
            List of failure results with the specified severity
        """
        return [r for r in results if r.triggered and r.severity == severity]

    def add_condition(self, condition: FailureCondition) -> None:
        """
        Add a condition to the evaluator.

        Args:
            condition: The condition to add
        """
        self.conditions.append(condition)

    def remove_condition(self, condition_name: str) -> bool:
        """
        Remove a condition by name.

        Args:
            condition_name: Name of the condition to remove

        Returns:
            True if the condition was found and removed
        """
        for i, c in enumerate(self.conditions):
            if c.name == condition_name:
                self.conditions.pop(i)
                return True
        return False

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "conditions": [c.to_dict() for c in self.conditions],
            "condition_count": len(self.conditions),
        }
