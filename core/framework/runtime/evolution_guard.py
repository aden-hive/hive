"""EvolutionGuard skeleton for safe graph mutations.

This module provides a minimal, placeholder EvolutionGuard and
ValidationResult class. The real implementation (probation, snapshot,
rollback) will be provided in a follow-up PR (per the agreed split).

The guard API is intentionally small and synchronous/async where needed:
  - snapshot(graph) -> snapshot_id
  - probation_run(snapshot_id, candidate_graph, steps) -> ValidationResult (async)
  - approve(result) -> bool
  - rollback(snapshot_id) -> None
  - audit_log(entry) -> None

Clients (AgentRuntime) should treat the guard as optional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class ValidationResult:
    """Result of probation/validation for a candidate graph.

    Attributes:
        passed: True if candidate passed probation checks
        violations: List of human-readable violation messages
        metrics: Arbitrary metrics (e.g., loop-detection score, tool-call rates)
    """

    passed: bool = True
    violations: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


class EvolutionGuard:
    """Minimal placeholder EvolutionGuard.

    Replace with a fuller implementation that snapshots runtime state,
    runs probation executions, validates, and can rollback.
    """

    def snapshot(self, graph: Any) -> str:
        """Create a lightweight snapshot of `graph` and return an id.

        Placeholder returns a simple textual id. Real impl should store
        snapshot content in durable storage (or memory with eviction).
        """
        return "snapshot:1"

    async def probation_run(
        self,
        snapshot_id: str,
        candidate_graph: Any,
        steps: int = 10,
    ) -> ValidationResult:
        """Run candidate graph in probation mode for `steps` iterations.

        Placeholder implementation always returns passed=True. Real
        implementation should run smoke tests and collect violations.
        """
        return ValidationResult(passed=True, violations=[], metrics={})

    def approve(self, result: ValidationResult) -> bool:
        """Decide whether the candidate passes based on ValidationResult."""
        return bool(result.passed)

    def rollback(self, snapshot_id: str) -> None:
        """Rollback to a previously taken snapshot.

        Placeholder is a no-op. Real impl should restore the runtime state.
        """
        return None

    def audit_log(self, entry: dict[str, Any]) -> None:
        """Record audit information about the evolution attempt."""
        # Placeholder: no-op
        return None
