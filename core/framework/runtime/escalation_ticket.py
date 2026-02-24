"""EscalationTicket — structured schema for worker health judge escalations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class EscalationTicket(BaseModel):
    """Structured escalation report emitted by the Worker Health Judge.

    The judge must fill every field before calling emit_escalation_ticket.
    Pydantic validation rejects partial tickets, preventing impulsive escalation.
    """

    ticket_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # Worker identification
    worker_agent_id: str
    worker_session_id: str
    worker_node_id: str
    worker_graph_id: str

    # Problem characterization (filled by judge via LLM deliberation)
    severity: Literal["low", "medium", "high", "critical"]
    cause: str            # Human-readable: "Node has produced 18 RETRY verdicts..."
    judge_reasoning: str  # Judge's own deliberation chain
    suggested_action: str # "Restart node", "Human review", "Kill session", etc.

    # Evidence
    recent_verdicts: list[str]   # e.g. ["RETRY", "RETRY", "CONTINUE", "RETRY"]
    total_steps_checked: int     # How many steps the judge saw
    steps_since_last_accept: int # Steps with no ACCEPT verdict
    stall_minutes: float | None  # Wall-clock minutes since last new log step (None if active)
    evidence_snippet: str        # Brief excerpt from recent LLM output or error
