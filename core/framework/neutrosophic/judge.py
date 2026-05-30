"""Opt-in NeutrosophicJudge adapter for Hive's judge protocol.

Strictly opt-in: no instance is created by the core runtime. Callers that
want neutrosophic-quality gating can instantiate NeutrosophicJudge and pass
it where Hive expects a judge (anywhere JudgeProtocol is accepted).
"""

from __future__ import annotations

from typing import Any

from framework.agent_loop.internals.types import JudgeVerdict

from .scoring import NeutrosophicDecision, NeutrosophicScore

# ── Judge-specific scoring constants ─────────────────────────────────────────
_JUDGE_BASE_T = 0.38
_JUDGE_BASE_I = 0.55
_JUDGE_BASE_F = 0.18
_HAS_TEXT_TRUTH_INC = 0.15
_HAS_TEXT_INDET_DEC = 0.15
_MISSING_KEY_INDET_INC = 0.10
_MISSING_KEY_FALSITY_INC = 0.08
_MISSING_KEY_CAP = 3  # max keys that contribute before cap
_TOOL_CALLS_INDET_INC = 0.08
# Must push falsity above _F_ESCALATE_MIN (0.65) when combined with base
_LATE_INCOMPLETE_FALSITY_INC = 0.60


def _remaining(max_iterations: int, iteration: int) -> int:
    """Iterations left after the current one finishes.

    Aligns with ``SubagentJudge`` in ``framework.agent_loop.internals.judge_pipeline``
    which uses ``max_iterations - iteration - 1`` (iteration is 0-based and the
    current turn is already consumed).
    """
    return max(0, max(1, max_iterations) - iteration - 1)


def _normalize_missing_keys(raw: Any) -> list[str]:
    """Coerce missing_keys into a list of non-None strings, defensively."""
    if not isinstance(raw, list):
        return []
    return [str(k) for k in raw if k is not None]


def score_judge_context(
    context: dict[str, Any],
    max_iterations: int = 10,
) -> NeutrosophicScore:
    """Derive a NeutrosophicScore from a judge evaluation context dict.

    Defensively normalises non-list/non-int fields so a malformed context
    does not raise. The late-incomplete escalation threshold is derived from
    the configured ``max_iterations`` rather than a hard-coded iteration
    number, so a judge with ``max_iterations=3`` and ``max_iterations=50``
    both escalate at a proportional point in the run.
    """
    rationale: list[str] = []
    truth = _JUDGE_BASE_T
    indeterminacy = _JUDGE_BASE_I
    falsity = _JUDGE_BASE_F

    assistant_text = context.get("assistant_text") or ""
    if isinstance(assistant_text, str) and assistant_text.strip():
        truth += _HAS_TEXT_TRUTH_INC
        indeterminacy -= _HAS_TEXT_INDET_DEC
        rationale.append("has_assistant_text")

    missing_keys = _normalize_missing_keys(context.get("missing_keys"))
    capped = min(len(missing_keys), _MISSING_KEY_CAP)
    if capped:
        indeterminacy += _MISSING_KEY_INDET_INC * capped
        falsity += _MISSING_KEY_FALSITY_INC * capped
        rationale.append(f"missing_keys={len(missing_keys)}")

    raw_tool_calls = context.get("tool_calls")
    if isinstance(raw_tool_calls, list) and raw_tool_calls:
        indeterminacy += _TOOL_CALLS_INDET_INC
        rationale.append("tool_calls_pending")

    raw_iter = context.get("iteration", 0)
    try:
        iteration = int(raw_iter)
    except (TypeError, ValueError):
        iteration = 0

    max_iter = max(1, max_iterations)
    remaining = _remaining(max_iter, iteration)
    late_threshold = max(2, int(max_iter * 0.3))
    if remaining <= late_threshold and missing_keys:
        falsity += _LATE_INCOMPLETE_FALSITY_INC
        rationale.append("late_iteration_incomplete")

    return NeutrosophicScore(
        truth=truth,
        indeterminacy=indeterminacy,
        falsity=falsity,
        rationale=tuple(rationale),
    )


class NeutrosophicJudge:
    """Opt-in judge adapter mapping T/I/F pressure to ACCEPT / RETRY / ESCALATE.

    NOT instantiated anywhere in the core runtime — supply it explicitly to
    AgentLoop or LoopConfig when neutrosophic quality gating is desired.

    Iteration semantics match ``SubagentJudge``: ``iteration`` is 0-based and
    ``remaining = max_iterations - iteration - 1``.
    """

    def __init__(self, task: str, max_iterations: int = 10) -> None:
        self._task = task
        self._max_iterations = max(1, max_iterations)

    def _remaining_iterations(self, context: dict[str, Any]) -> int:
        try:
            return _remaining(self._max_iterations, int(context.get("iteration", 0)))
        except (TypeError, ValueError):
            return max(0, self._max_iterations - 1)

    def _feedback(self, message: str, score: NeutrosophicScore) -> str:
        prefix = f"Task: {self._task} — " if self._task else ""
        return f"{prefix}{message} (T={score.truth:.3f}, I={score.indeterminacy:.3f}, F={score.falsity:.3f})"

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict:
        """Map judge context to ACCEPT, RETRY, or ESCALATE using T/I/F scores.

        All :class:`NeutrosophicDecision` states are handled explicitly:

        - ACCEPT    → ACCEPT (clean pass)
        - ESCALATE  → ESCALATE (high falsity / late incomplete)
        - missing_keys present → RETRY (regardless of CLARIFY/RETRY/CAVEAT)
        - CLARIFY   → RETRY (high indeterminacy — add evidence)
        - RETRY     → RETRY (contradictions / failure pressure)
        - CAVEAT    → ACCEPT, with the score embedded in feedback so the
                       caller can see this was a borderline accept rather
                       than a clean one.
        """
        score = score_judge_context(context, max_iterations=self._max_iterations)
        missing_keys = _normalize_missing_keys(context.get("missing_keys"))
        remaining = self._remaining_iterations(context)

        if score.decision == NeutrosophicDecision.ACCEPT:
            return JudgeVerdict(action="ACCEPT", feedback="")

        if score.decision == NeutrosophicDecision.ESCALATE:
            return JudgeVerdict(
                action="ESCALATE",
                feedback=self._feedback(
                    "Escalating: attempt is incomplete late in the run.",
                    score,
                ),
            )

        if missing_keys:
            return JudgeVerdict(
                action="RETRY",
                feedback=self._feedback(
                    f"Missing required outputs: {missing_keys}. Remaining iterations: {remaining}.",
                    score,
                ),
            )

        if score.decision == NeutrosophicDecision.CLARIFY:
            return JudgeVerdict(
                action="RETRY",
                feedback=self._feedback(
                    "Answer is too indeterminate — add evidence or clarify the result.",
                    score,
                ),
            )

        if score.decision == NeutrosophicDecision.RETRY:
            return JudgeVerdict(
                action="RETRY",
                feedback=self._feedback(
                    "Result contains contradictions or failure signals — retry required.",
                    score,
                ),
            )

        # NeutrosophicDecision.CAVEAT — borderline accept. Surface the score
        # in feedback so callers see this was not a clean pass.
        return JudgeVerdict(
            action="ACCEPT",
            feedback=self._feedback(
                "Accepted with caveat: signal is weak but not contradictory.",
                score,
            ),
        )
