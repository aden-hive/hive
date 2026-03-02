"""
Failure Conditions Package - Built-in and custom failure conditions.

This package provides pre-defined failure conditions that can be used
with the FailureEvaluator and Goal system.
"""

from framework.failure_conditions.builtin import (
    LOOP_DETECTED,
    MAX_ERRORS_EXCEEDED,
    NO_DATA_FOUND,
    OUTPUT_VALIDATION_FAILED,
    SUCCESS_RATE_TOO_LOW,
    TIMEOUT_EXCEEDED,
    TOKEN_BUDGET_EXCEEDED,
)
from framework.schemas.failure_condition import (
    ExecutionContext,
    FailureCondition,
    FailureEvaluator,
    FailureResult,
    FailureSeverity,
)

__all__ = [
    "ExecutionContext",
    "FailureCondition",
    "FailureEvaluator",
    "FailureResult",
    "FailureSeverity",
    "TIMEOUT_EXCEEDED",
    "TOKEN_BUDGET_EXCEEDED",
    "OUTPUT_VALIDATION_FAILED",
    "NO_DATA_FOUND",
    "MAX_ERRORS_EXCEEDED",
    "SUCCESS_RATE_TOO_LOW",
    "LOOP_DETECTED",
]
