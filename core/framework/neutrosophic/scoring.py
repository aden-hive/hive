"""Core neutrosophic score primitives.

The score keeps three independent signals:
- truth: evidence that a result satisfies the task
- indeterminacy: missing, ambiguous, or incomplete evidence
- falsity: contradiction, failure, drift, or risk evidence
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NeutrosophicDecision(StrEnum):
    """Default action suggested by a neutrosophic score."""

    ACCEPT = "accept"
    CLARIFY = "clarify"
    RETRY = "retry"
    ESCALATE = "escalate"
    CAVEAT = "caveat"


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass(frozen=True)
class NeutrosophicScore:
    """Decision-quality triplet for one result or an aggregate."""

    truth: float
    indeterminacy: float
    falsity: float
    rationale: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object.__setattr__(self, "truth", _clamp(self.truth))
        object.__setattr__(self, "indeterminacy", _clamp(self.indeterminacy))
        object.__setattr__(self, "falsity", _clamp(self.falsity))

    @property
    def decision(self) -> NeutrosophicDecision:
        """Return the default decision policy for the score."""
        if self.falsity >= 0.65:
            return NeutrosophicDecision.ESCALATE
        if self.indeterminacy >= 0.65:
            return NeutrosophicDecision.CLARIFY
        if self.truth >= 0.72 and self.indeterminacy <= 0.35 and self.falsity <= 0.35:
            return NeutrosophicDecision.ACCEPT
        if self.falsity >= 0.45:
            return NeutrosophicDecision.RETRY
        return NeutrosophicDecision.CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "truth": round(self.truth, 3),
            "indeterminacy": round(self.indeterminacy, 3),
            "falsity": round(self.falsity, 3),
            "decision": self.decision.value,
            "rationale": list(self.rationale),
        }


def score_worker_report(
    *,
    status: str,
    summary: str = "",
    data: dict[str, Any] | None = None,
    error: str | None = None,
    signals: dict[str, Any] | None = None,
) -> NeutrosophicScore:
    """Score a Hive worker report without changing runtime behavior."""
    normalized_status = str(status or "").strip().lower()
    normalized_summary = str(summary or "").strip()
    payload = data if isinstance(data, dict) else {}
    evidence = signals if isinstance(signals, dict) else {}
    rationale: list[str] = []

    if normalized_status == "success":
        truth, indeterminacy, falsity = 0.78, 0.12, 0.08
        rationale.append("status=success")
    elif normalized_status == "partial":
        truth, indeterminacy, falsity = 0.38, 0.55, 0.18
        rationale.append("status=partial")
    elif normalized_status in {"failed", "timeout", "stopped"}:
        truth, indeterminacy, falsity = 0.12, 0.35, 0.68
        rationale.append(f"status={normalized_status}")
    else:
        truth, indeterminacy, falsity = 0.25, 0.62, 0.25
        rationale.append("status=unknown")

    if normalized_summary:
        truth += 0.07
        indeterminacy -= 0.05
        rationale.append("summary_present")
    else:
        indeterminacy += 0.18
        rationale.append("summary_missing")

    if payload:
        truth += 0.08
        indeterminacy -= 0.04
        rationale.append("data_present")
    else:
        indeterminacy += 0.05
        rationale.append("data_missing")

    if error:
        truth -= 0.12
        falsity += 0.2
        rationale.append("error_present")

    if evidence.get("stalled"):
        indeterminacy += 0.2
        falsity += 0.12
        rationale.append("stall_signal")

    if evidence.get("doom_loop"):
        indeterminacy += 0.15
        falsity += 0.22
        rationale.append("doom_loop_signal")

    if evidence.get("contradiction"):
        falsity += 0.25
        indeterminacy += 0.1
        rationale.append("contradiction_signal")

    return NeutrosophicScore(truth, indeterminacy, falsity, tuple(rationale))


def aggregate_scores(scores: list[NeutrosophicScore]) -> NeutrosophicScore:
    """Average a batch of scores into one swarm-level score."""
    if not scores:
        return NeutrosophicScore(0.0, 1.0, 0.0, ("no_scores",))

    count = len(scores)
    truth = sum(score.truth for score in scores) / count
    indeterminacy = sum(score.indeterminacy for score in scores) / count
    falsity = sum(score.falsity for score in scores) / count
    rationale = tuple(f"aggregate_count={count}" for _ in range(1))
    return NeutrosophicScore(truth, indeterminacy, falsity, rationale)
