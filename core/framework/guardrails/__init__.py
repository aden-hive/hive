"""
Central guardrails interfaces for the Aden Hive Framework.

This package defines a small, composable API for system-level guardrails
that can be wired into the runtime, runner, and tools over time.

The initial implementation focuses on:
- Tool allow/deny lists
- Simple budget tracking hooks
- Pre/post content filtering hooks

Concrete enforcement (code sandbox, filesystem sandbox, etc.) already
exists elsewhere in the codebase; this package provides a single place
to orchestrate and extend those protections.
"""

from .manager import GuardrailsConfig, GuardrailsManager, GuardrailViolation
from .policy import DEFAULT_GUARDRAIL_PROMPT

__all__ = [
    "GuardrailsConfig",
    "GuardrailsManager",
    "GuardrailViolation",
    "DEFAULT_GUARDRAIL_PROMPT",
]

