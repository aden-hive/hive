"""
Execution Evidence Model - Separates execution attempts from observed outcomes.

This module provides a lightweight model for classifying the quality of evidence
about execution outcomes. In distributed or external tool interactions, execution
does not imply confirmation - timeouts, retries, or partial failures may produce
effects outside the system's observation boundary.

The Execution Evidence model enables:
- Distinguishing "executed" from "confirmed"
- Future reconciliation for partial failures
- Evidence-based guardrails and retry policies
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EvidenceType(str, Enum):
    """Classification of execution evidence quality."""

    OBSERVED = "observed"  # Saw the result
    CONFIRMED = "confirmed"  # Verified the effect
    ASSUMED = "assumed"  # Inferred from context
    UNKNOWN = "unknown"  # No evidence


class ExecutionAttempt(BaseModel):
    """
    Records a single execution attempt with evidence classification.

    Separates execution (what we tried) from observation (what we saw)
    from confirmation (what we verified).

    This enables safer failure interpretation and future reconciliation.

    Example:
        attempt = ExecutionAttempt(
            attempt_id="node_1_attempt_2",
            node_id="api_caller",
        )

        # ... execute ...

        attempt.finished_at = datetime.now()
        attempt.observed_result = "Success"
        attempt.evidence_type = EvidenceType.CONFIRMED
    """

    attempt_id: str
    node_id: str
    step_index: int = 0  # For EventLoopNode iterations

    started_at: datetime = Field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None

    # What we observed
    observed_result: Optional[str] = None
    evidence_type: EvidenceType = EvidenceType.UNKNOWN

    # Error tracking
    error: Optional[str] = None
    is_partial: bool = False

    # Metadata
    retry_of: Optional[str] = None  # attempt_id of previous try

    @property
    def duration_ms(self) -> int:
        """Calculate execution duration in milliseconds."""
        if self.finished_at is None:
            return 0
        delta = self.finished_at - self.started_at
        return int(delta.total_seconds() * 1000)

    model_config = {"extra": "allow"}

