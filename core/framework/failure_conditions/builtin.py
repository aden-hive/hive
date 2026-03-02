"""
Built-in Failure Conditions - Pre-defined conditions for common failure scenarios.

These conditions can be used directly or as templates for custom conditions.
"""

from framework.schemas.failure_condition import FailureCondition, FailureSeverity

TIMEOUT_EXCEEDED = FailureCondition(
    name="timeout_exceeded",
    description="Execution exceeded maximum allowed duration",
    severity=FailureSeverity.MAJOR,
    check="ctx.elapsed_time > ctx.goal_constraints.get('max_duration', float('inf'))",
    recovery_hint="Consider optimizing the agent or increasing the timeout constraint",
)


TOKEN_BUDGET_EXCEEDED = FailureCondition(
    name="token_budget_exceeded",
    description="Token usage exceeded the allocated budget",
    severity=FailureSeverity.CRITICAL,
    check="ctx.total_tokens > ctx.budget.get('max_tokens', float('inf'))",
    recovery_hint="Reduce output verbosity or increase token budget",
)


OUTPUT_VALIDATION_FAILED = FailureCondition(
    name="output_validation_failed",
    description="Output failed validation checks",
    severity=FailureSeverity.MAJOR,
    check="ctx.last_outcome.get('validation_errors') is not None",
    recovery_hint="Review output format and ensure it meets schema requirements",
)


NO_DATA_FOUND = FailureCondition(
    name="no_data_found",
    description="No data was found during execution",
    severity=FailureSeverity.MINOR,
    check="len(ctx.output.get('data', ctx.output.get('results', []))) == 0",
    recovery_hint="Try different search queries or data sources",
)


MAX_ERRORS_EXCEEDED = FailureCondition(
    name="max_errors_exceeded",
    description="Too many errors occurred during execution",
    severity=FailureSeverity.CRITICAL,
    check="len(ctx.errors) > ctx.goal_constraints.get('max_errors', 3)",
    recovery_hint="Review error logs and fix underlying issues",
)


SUCCESS_RATE_TOO_LOW = FailureCondition(
    name="success_rate_too_low",
    description="Decision success rate fell below acceptable threshold",
    severity=FailureSeverity.MAJOR,
    check=(
        "ctx.decisions_count > 0 and "
        "ctx.success_rate < ctx.goal_constraints.get('min_success_rate', 0.5)"
    ),
    recovery_hint="Review failed decisions and adjust agent strategy",
)


LOOP_DETECTED = FailureCondition(
    name="loop_detected",
    description="Agent appears to be stuck in a loop",
    severity=FailureSeverity.MAJOR,
    check="ctx.decisions_count > ctx.goal_constraints.get('max_decisions', 50)",
    recovery_hint="Review agent logic to prevent infinite loops",
)


BUILTIN_CONDITIONS = [
    TIMEOUT_EXCEEDED,
    TOKEN_BUDGET_EXCEEDED,
    OUTPUT_VALIDATION_FAILED,
    NO_DATA_FOUND,
    MAX_ERRORS_EXCEEDED,
    SUCCESS_RATE_TOO_LOW,
    LOOP_DETECTED,
]


def get_builtin_condition(name: str) -> FailureCondition | None:
    """
    Get a built-in condition by name.

    Args:
        name: Name of the condition to retrieve

    Returns:
        The condition if found, None otherwise
    """
    for condition in BUILTIN_CONDITIONS:
        if condition.name == name:
            return condition
    return None


def get_all_builtin_conditions() -> list[FailureCondition]:
    """
    Get all built-in conditions.

    Returns:
        List of all built-in failure conditions
    """
    return BUILTIN_CONDITIONS.copy()
