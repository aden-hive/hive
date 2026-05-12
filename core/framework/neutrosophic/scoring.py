"""Core neutrosophic score primitives.

The score keeps three independent signals:
- truth: evidence that a result satisfies the task
- indeterminacy: missing, ambiguous, or incomplete evidence
- falsity: contradiction, failure, drift, or risk evidence
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# ── Decision thresholds ──────────────────────────────────────────────────────
_T_ACCEPT_MIN = 0.72
_I_ACCEPT_MAX = 0.35
_F_ACCEPT_MAX = 0.35
_I_CLARIFY_MIN = 0.65
_F_ESCALATE_MIN = 0.65
_F_RETRY_MIN = 0.45

# ── Base score triplets by status (T, I, F) ──────────────────────────────────
_BASE_SUCCESS = (0.78, 0.12, 0.08)
_BASE_PARTIAL = (0.38, 0.55, 0.18)
_BASE_FAILURE = (0.12, 0.35, 0.68)
_BASE_UNKNOWN = (0.25, 0.62, 0.25)

# ── Per-signal adjustments ───────────────────────────────────────────────────
_SUMMARY_TRUTH_INC = 0.07
_SUMMARY_INDET_DEC = 0.05
_SUMMARY_MISSING_INDET_INC = 0.18
_DATA_TRUTH_INC = 0.08
_DATA_INDET_DEC = 0.04
_DATA_MISSING_INDET_INC = 0.05
_ERROR_TRUTH_DEC = 0.12
_ERROR_FALSITY_INC = 0.30  # large enough to block ACCEPT when error is present
_STALL_INDET_INC = 0.20
_STALL_FALSITY_INC = 0.12
_DOOM_LOOP_INDET_INC = 0.15
_DOOM_LOOP_FALSITY_INC = 0.22
_CONTRADICTION_FALSITY_INC = 0.25
_CONTRADICTION_INDET_INC = 0.10


class NeutrosophicDecision(StrEnum):
    ACCEPT = "accept"
    CLARIFY = "clarify"
    RETRY = "retry"
    ESCALATE = "escalate"
    CAVEAT = "caveat"


def _clamp(value: float) -> float:
    """Clamp to [0.0, 1.0], raising on non-finite input."""
    if not math.isfinite(value):
        raise ValueError(f"Non-finite neutrosophic component: {value!r}")
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class NeutrosophicScore:
    """Immutable (T, I, F) triplet representing a decision-quality signal."""

    truth: float
    indeterminacy: float
    falsity: float
    rationale: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "truth", _clamp(self.truth))
        object.__setattr__(self, "indeterminacy", _clamp(self.indeterminacy))
        object.__setattr__(self, "falsity", _clamp(self.falsity))

    @property
    def decision(self) -> NeutrosophicDecision:
        """RFC-aligned priority: ACCEPT > ESCALATE > CLARIFY > RETRY > CAVEAT."""
        if self.truth >= _T_ACCEPT_MIN and self.indeterminacy <= _I_ACCEPT_MAX and self.falsity <= _F_ACCEPT_MAX:
            return NeutrosophicDecision.ACCEPT
        if self.falsity >= _F_ESCALATE_MIN:
            return NeutrosophicDecision.ESCALATE
        if self.indeterminacy >= _I_CLARIFY_MIN:
            return NeutrosophicDecision.CLARIFY
        if self.falsity >= _F_RETRY_MIN:
            return NeutrosophicDecision.RETRY
        return NeutrosophicDecision.CAVEAT

    def to_dict(self) -> dict[str, Any]:
        return {
            "truth": self.truth,
            "indeterminacy": self.indeterminacy,
            "falsity": self.falsity,
            "decision": self.decision.value,
            "rationale": list(self.rationale),
        }


def score_worker_report(
    status: str,
    summary: str | None = None,
    data: dict[str, Any] | None = None,
    error: str | None = None,
    signals: dict[str, Any] | None = None,
) -> NeutrosophicScore:
    """Derive a conservative NeutrosophicScore from a worker report."""
    rationale: list[str] = []
    normalized_status = (status or "unknown").strip().lower()
    normalized_summary = (summary or "").strip()
    payload = data or {}
    evidence = signals or {}

    if normalized_status == "success":
        truth, indeterminacy, falsity = _BASE_SUCCESS
        rationale.append("status=success")
    elif normalized_status == "partial":
        truth, indeterminacy, falsity = _BASE_PARTIAL
        rationale.append("status=partial")
    elif normalized_status in {"failed", "timeout", "stopped"}:
        truth, indeterminacy, falsity = _BASE_FAILURE
        rationale.append(f"status={normalized_status}")
    else:
        truth, indeterminacy, falsity = _BASE_UNKNOWN
        rationale.append("status=unknown")

    if normalized_summary:
        truth += _SUMMARY_TRUTH_INC
        indeterminacy -= _SUMMARY_INDET_DEC
        rationale.append("summary_present")
    else:
        indeterminacy += _SUMMARY_MISSING_INDET_INC
        rationale.append("summary_missing")

    if payload:
        truth += _DATA_TRUTH_INC
        indeterminacy -= _DATA_INDET_DEC
        rationale.append("data_present")
    else:
        indeterminacy += _DATA_MISSING_INDET_INC
        rationale.append("data_missing")

    if error:
        truth -= _ERROR_TRUTH_DEC
        falsity += _ERROR_FALSITY_INC
        rationale.append("error_present")

    if evidence.get("stalled"):
        indeterminacy += _STALL_INDET_INC
        falsity += _STALL_FALSITY_INC
        rationale.append("stall_signal")

    if evidence.get("doom_loop"):
        indeterminacy += _DOOM_LOOP_INDET_INC
        falsity += _DOOM_LOOP_FALSITY_INC
        rationale.append("doom_loop_signal")

    if evidence.get("contradiction"):
        falsity += _CONTRADICTION_FALSITY_INC
        indeterminacy += _CONTRADICTION_INDET_INC
        rationale.append("contradiction_signal")

    return NeutrosophicScore(
        truth=truth,
        indeterminacy=indeterminacy,
        falsity=falsity,
        rationale=tuple(rationale),
    )


def aggregate_scores(scores: list[NeutrosophicScore]) -> NeutrosophicScore:
    """Average a list of NeutrosophicScore objects into one aggregate score."""
    if not scores:
        return NeutrosophicScore(0.0, 1.0, 0.0, ("empty_aggregate",))
    n = len(scores)
    avg_t = sum(s.truth for s in scores) / n
    avg_i = sum(s.indeterminacy for s in scores) / n
    avg_f = sum(s.falsity for s in scores) / n
    all_rationale = tuple(r for s in scores for r in s.rationale)
    return NeutrosophicScore(
        truth=avg_t,
        indeterminacy=avg_i,
        falsity=avg_f,
        rationale=all_rationale,
    )


def aggregate_worker_reports(reports: list[dict[str, Any]]) -> NeutrosophicScore:
    """Score and aggregate a list of raw worker report dicts."""
    scores = [
        score_worker_report(
            status=str(report.get("status", "unknown")),
            summary=report.get("summary") or "",
            data=report.get("data") if isinstance(report.get("data"), dict) else {},
            error=str(report.get("error")) if report.get("error") else None,
            signals=report.get("signals") if isinstance(report.get("signals"), dict) else {},
        )
        for report in reports
    ]
    return aggregate_scores(scores)
