"""Agent execution compatibility contract for evolved agent graphs.

This module provides validation and compatibility checks to ensure that
evolved agent graphs can safely execute with existing runtime, tools, and
memory schemas. It prevents runtime failures by validating changes before
execution and provides actionable diagnostics.
"""

from .compatibility import (
    CompatibilityResult,
    CompatibilityValidator,
    EvolutionValidationResult,
    is_compatible,
    validate_agent_compatibility,
    validate_graph_evolution,
)

__all__ = [
    "CompatibilityResult",
    "CompatibilityValidator",
    "EvolutionValidationResult",
    "is_compatible",
    "validate_agent_compatibility",
    "validate_graph_evolution",
]
