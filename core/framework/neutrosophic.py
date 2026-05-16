from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class NeutrosophicDecision(str, Enum):
    """Possible decisions derived from a neutrosophic score."""
    ACCEPT = "accept"
    CLARIFY = "clarify"
    RETRY = "retry"
    ESCALATE = "escalate"
    CAVEAT = "caveat"


@dataclass(frozen=True)
class NeutrosophicScore:
    """Immutable T/I/F triplet with clamping between 0.0 and 1.0.
    
    T: Truth / support / success
    I: Indeterminacy / uncertainty / missing data
    F: Falsity / contradiction / error
    """
    t: float
    i: float
    f: float

    def __post_init__(self):
        # Clamp values to [0.0, 1.0]
        object.__setattr__(self, "t", max(0.0, min(1.0, self.t)))
        object.__setattr__(self, "i", max(0.0, min(1.0, self.i)))
        object.__setattr__(self, "f", max(0.0, min(1.0, self.f)))

    def get_decision(
        self,
        t_thresh: float = 0.7,
        i_thresh: float = 0.5,
        f_thresh: float = 0.5
    ) -> NeutrosophicDecision:
        """Derive a decision from the score based on thresholds."""
        if self.f >= f_thresh:
            if self.i >= i_thresh:
                return NeutrosophicDecision.ESCALATE
            return NeutrosophicDecision.RETRY
            
        if self.i >= i_thresh:
            return NeutrosophicDecision.CLARIFY
            
        if self.t >= t_thresh:
            return NeutrosophicDecision.ACCEPT
            
        return NeutrosophicDecision.CAVEAT


def score_worker_report(
    status: str,
    summary: str,
    data: dict[str, Any] | None,
    error: str | None = None
) -> NeutrosophicScore:
    """Derive T/I/F from worker report signals.
    
    This is a heuristic implementation for Phase 1 to demonstrate
    deriving multidimensional confidence from flat worker results.
    """
    t, i, f = 0.0, 0.0, 0.0

    # Status baseline
    if status == "success":
        t += 0.8
    elif status == "partial":
        t += 0.4
        i += 0.4
    elif status == "failed":
        f += 0.8

    # Error signal
    if error:
        f += 0.5

    # Data completeness signal
    if data is None or len(data) == 0:
        i += 0.4

    # Summary analysis (basic heuristic)
    lower_summary = (summary or "").lower()
    if "missing" in lower_summary or "unclear" in lower_summary or "unknown" in lower_summary:
        i += 0.3
    if "conflict" in lower_summary or "contradict" in lower_summary or "error" in lower_summary:
        f += 0.3
    if "confirm" in lower_summary or "verified" in lower_summary or "found" in lower_summary:
        t += 0.2

    return NeutrosophicScore(t=t, i=i, f=f)


def aggregate_scores(scores: list[NeutrosophicScore]) -> NeutrosophicScore:
    """Combine multiple worker scores into a single swarm consensus score."""
    if not scores:
        return NeutrosophicScore(t=0.0, i=1.0, f=0.0)

    avg_t = sum(s.t for s in scores) / len(scores)
    avg_i = sum(s.i for s in scores) / len(scores)
    avg_f = sum(s.f for s in scores) / len(scores)
    
    return NeutrosophicScore(t=avg_t, i=avg_i, f=avg_f)
