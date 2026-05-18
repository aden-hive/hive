"""Core neutrosophic score primitives.

The score keeps three independent signals:
- truth: evidence that a result satisfies the task
- indeterminacy: missing, ambiguous, or incomplete evidence
- falsity: contradiction, failure, drift, or risk evidence
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final

# Decision thresholds — named here so reviewers can audit them without
# tracing magic numbers through the decision property.
_I_CLARIFY_MIN: Final = 0.65  # indeterminacy above this → CLARIFY
_F_ESCALATE_MIN: Final = 0.65  # falsity above this → ESCALATE
_T_ACCEPT_MIN: Final = 0.72  # truth must reach this for a clean ACCEPT
_I_ACCEPT_MAX: Final = 0.35  # indeterminacy must stay below this for ACCEPT
_F_ACCEPT_MAX: Final = 0.35  # falsity must stay below this for ACCEPT
_F_RETRY_MIN: Final = 0.45  # moderate falsity (below escalate) → RETRY

_SUCCESS_BASE: Final = (0.78, 0.12, 0.08)
_PARTIAL_BASE: Final = (0.38, 0.55, 0.18)
_TERMINAL_FAILURE_BASE: Final = (0.12, 0.35, 0.68)
_UNKNOWN_STATUS_BASE: Final = (0.25, 0.62, 0.25)

_SUMMARY_TRUTH_INC: Final = 0.07
_SUMMARY_INDETERMINACY_DEC: Final = 0.05
_SUMMARY_MISSING_INDETERMINACY_INC: Final = 0.18

_DATA_TRUTH_INC: Final = 0.08
_DATA_INDETERMINACY_DEC: Final = 0.04
_DATA_MISSING_INDETERMINACY_INC: Final = 0.05

_ERROR_TRUTH_DEC: Final = 0.12
_ERROR_FALSITY_INC: Final = 0.38

_STALL_INDETERMINACY_INC: Final = 0.2
_STALL_FALSITY_INC: Final = 0.12
_DOOM_LOOP_INDETERMINACY_INC: Final = 0.15
_DOOM_LOOP_FALSITY_INC: Final = 0.22
_CONTRADICTION_FALSITY_INC: Final = 0.25
_CONTRADICTION_INDETERMINACY_INC: Final = 0.1


class NeutrosophicDecision(StrEnum):
    """Default action suggested by a neutrosophic score."""

    ACCEPT = "accept"
    CLARIFY = "clarify"
    RETRY = "retry"
    ESCALATE = "escalate"
    CAVEAT = "caveat"


def _clamp(value: float) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("Neutrosophic score components must be finite numbers.")
    return max(0.0, min(1.0, parsed))


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
        """Return the default decision policy for the score.

        Priority order follows the RFC: high indeterminacy triggers CLARIFY
        before high falsity triggers ESCALATE.  A score that is simultaneously
        high-I and high-F is ambiguous enough to clarify first rather than
        immediately escalate.
        """
        if self.indeterminacy >= _I_CLARIFY_MIN:
            return NeutrosophicDecision.CLARIFY
        if self.falsity >= _F_ESCALATE_MIN:
            return NeutrosophicDecision.ESCALATE
        if self.truth >= _T_ACCEPT_MIN and self.indeterminacy <= _I_ACCEPT_MAX and self.falsity <= _F_ACCEPT_MAX:
            return NeutrosophicDecision.ACCEPT
        if self.falsity >= _F_RETRY_MIN:
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
    normalized_error = str(error or "").strip()
    payload = data if isinstance(data, dict) else {}
    evidence = signals if isinstance(signals, dict) else {}
    rationale: list[str] = []

    if normalized_status == "success":
        truth, indeterminacy, falsity = _SUCCESS_BASE
        rationale.append("status=success")
    elif normalized_status == "partial":
        truth, indeterminacy, falsity = _PARTIAL_BASE
        rationale.append("status=partial")
    elif normalized_status in {"failed", "timeout", "stopped"}:
        truth, indeterminacy, falsity = _TERMINAL_FAILURE_BASE
        rationale.append(f"status={normalized_status}")
    else:
        truth, indeterminacy, falsity = _UNKNOWN_STATUS_BASE
        rationale.append("status=unknown")

    if normalized_summary:
        truth += _SUMMARY_TRUTH_INC
        indeterminacy -= _SUMMARY_INDETERMINACY_DEC
        rationale.append("summary_present")
    else:
        indeterminacy += _SUMMARY_MISSING_INDETERMINACY_INC
        rationale.append("summary_missing")

    if payload:
        truth += _DATA_TRUTH_INC
        indeterminacy -= _DATA_INDETERMINACY_DEC
        rationale.append("data_present")
    else:
        indeterminacy += _DATA_MISSING_INDETERMINACY_INC
        rationale.append("data_missing")

    if normalized_error:
        truth -= _ERROR_TRUTH_DEC
        falsity += _ERROR_FALSITY_INC
        rationale.append("error_present")

    if evidence.get("stalled") is True:
        indeterminacy += _STALL_INDETERMINACY_INC
        falsity += _STALL_FALSITY_INC
        rationale.append("stall_signal")

    if evidence.get("doom_loop") is True:
        indeterminacy += _DOOM_LOOP_INDETERMINACY_INC
        falsity += _DOOM_LOOP_FALSITY_INC
        rationale.append("doom_loop_signal")

    if evidence.get("contradiction") is True:
        falsity += _CONTRADICTION_FALSITY_INC
        indeterminacy += _CONTRADICTION_INDETERMINACY_INC
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
    rationale = (f"aggregate_count={count}",)
    return NeutrosophicScore(truth, indeterminacy, falsity, rationale)
