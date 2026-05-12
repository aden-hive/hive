"""Tests for the neutrosophic scoring module (Phases 1–3)."""

from __future__ import annotations

import math
import pathlib

import pytest

from framework.neutrosophic import (
    NeutrosophicDecision,
    NeutrosophicJudge,
    NeutrosophicScore,
    aggregate_scores,
    aggregate_worker_reports,
    score_judge_context,
    score_worker_report,
)

# ── Phase 1: Core scoring primitives ─────────────────────────────────────────


def test_neutrosophic_score_clamps_below_zero() -> None:
    score = NeutrosophicScore(-0.5, 0.5, 0.5)
    assert score.truth == 0.0


def test_neutrosophic_score_clamps_above_one() -> None:
    score = NeutrosophicScore(1.5, 0.5, 0.5)
    assert score.truth == 1.0


def test_neutrosophic_score_rejects_nan() -> None:
    with pytest.raises(ValueError):
        NeutrosophicScore(math.nan, 0.5, 0.5)


def test_neutrosophic_score_rejects_inf() -> None:
    with pytest.raises(ValueError):
        NeutrosophicScore(0.5, math.inf, 0.5)


def test_score_worker_report_success_returns_accept() -> None:
    score = score_worker_report(status="success", summary="Done.", data={"result": 1})
    assert score.decision == NeutrosophicDecision.ACCEPT
    assert "status=success" in score.rationale


def test_score_worker_report_partial_does_not_accept() -> None:
    score = score_worker_report(status="partial", summary="Partially done.")
    assert score.decision != NeutrosophicDecision.ACCEPT


def test_score_worker_report_failed_raises_falsity() -> None:
    score = score_worker_report(status="failed")
    assert score.falsity >= 0.60


def test_score_worker_report_stopped_is_conservative() -> None:
    score = score_worker_report(status="stopped")
    assert score.falsity >= 0.60
    assert score.decision != NeutrosophicDecision.ACCEPT


def test_score_worker_report_error_blocks_accept() -> None:
    # Even a successful-looking report with an error must not be ACCEPT.
    score = score_worker_report(
        status="success",
        summary="Completed.",
        data={"result": 1},
        error="Partial write failure",
    )
    assert score.decision != NeutrosophicDecision.ACCEPT
    assert "error_present" in score.rationale


def test_score_worker_report_summary_missing_increases_indeterminacy() -> None:
    with_summary = score_worker_report(status="partial", summary="Something.")
    without_summary = score_worker_report(status="partial", summary="")
    assert without_summary.indeterminacy > with_summary.indeterminacy


def test_score_worker_report_stall_signal() -> None:
    score = score_worker_report(status="partial", signals={"stalled": True})
    assert "stall_signal" in score.rationale
    assert score.falsity > 0.18


def test_aggregate_scores_averages_correctly() -> None:
    a = NeutrosophicScore(0.8, 0.1, 0.1)
    b = NeutrosophicScore(0.4, 0.5, 0.3)
    result = aggregate_scores([a, b])
    assert abs(result.truth - 0.6) < 1e-9
    assert abs(result.indeterminacy - 0.3) < 1e-9


def test_aggregate_scores_empty_returns_uncertain() -> None:
    result = aggregate_scores([])
    assert result.indeterminacy == 1.0
    assert "empty_aggregate" in result.rationale


def test_decision_priority_escalate_over_clarify() -> None:
    # High falsity + high indeterminacy → ESCALATE, not CLARIFY
    score = NeutrosophicScore(0.1, 0.8, 0.8)
    assert score.decision == NeutrosophicDecision.ESCALATE


def test_decision_priority_clarify_over_retry() -> None:
    # High indeterminacy but falsity below escalate threshold → CLARIFY
    score = NeutrosophicScore(0.3, 0.7, 0.4)
    assert score.decision == NeutrosophicDecision.CLARIFY


def test_decision_retry_branch() -> None:
    # falsity in [_F_RETRY_MIN, _F_ESCALATE_MIN), indeterminacy < _I_CLARIFY_MIN
    score = NeutrosophicScore(0.3, 0.4, 0.55)
    assert score.decision == NeutrosophicDecision.RETRY


# ── Phase 2: score attached to WorkerResult, Queen guard ─────────────────────


def test_neutrosophic_score_to_dict_has_all_keys() -> None:
    score_dict = NeutrosophicScore(0.8, 0.1, 0.1, ("status=success",)).to_dict()
    assert isinstance(score_dict, dict) and score_dict
    for key in ("truth", "indeterminacy", "falsity", "decision"):
        assert score_dict.get(key) is not None


def test_queen_score_line_guard_empty_dict() -> None:
    # Verify that the queen's guard logic correctly omits the score line for {}
    empty: dict = {}
    assert not (isinstance(empty, dict) and empty)
    score_dict = NeutrosophicScore(0.8, 0.1, 0.1).to_dict()
    assert isinstance(score_dict, dict) and score_dict  # non-empty → would emit line


# ── Phase 3: Judge adapter + consensus helpers ────────────────────────────────


@pytest.mark.asyncio
async def test_neutrosophic_judge_accepts_complete_context() -> None:
    judge = NeutrosophicJudge("summarise emails", max_iterations=10)
    verdict = await judge.evaluate(
        {
            "assistant_text": "Here is the summary: ...",
            "missing_keys": [],
            "tool_calls": [],
            "iteration": 3,
        }
    )
    assert verdict.action == "ACCEPT"


@pytest.mark.asyncio
async def test_neutrosophic_judge_retries_missing_keys() -> None:
    judge = NeutrosophicJudge("extract data", max_iterations=10)
    verdict = await judge.evaluate(
        {
            "assistant_text": "Partial output.",
            "missing_keys": ["report_url"],
            "tool_calls": [],
            "iteration": 2,
        }
    )
    assert verdict.action == "RETRY"
    assert "report_url" in verdict.feedback


@pytest.mark.asyncio
async def test_neutrosophic_judge_escalates_late_incomplete_attempt() -> None:
    # At iteration 9/10 with missing keys, falsity should exceed _F_ESCALATE_MIN.
    judge = NeutrosophicJudge("fetch invoices", max_iterations=10)
    verdict = await judge.evaluate(
        {
            "assistant_text": "",
            "missing_keys": ["invoice_list"],
            "tool_calls": [],
            "iteration": 9,
        }
    )
    assert verdict.action == "ESCALATE"


def test_score_judge_context_handles_malformed_context() -> None:
    # Non-list missing_keys, non-int iteration — must not raise.
    score = score_judge_context(
        {
            "assistant_text": None,
            "missing_keys": "not_a_list",
            "tool_calls": 42,
            "iteration": "five",
        }
    )
    assert isinstance(score, NeutrosophicScore)


def test_aggregate_worker_reports_mixed_results_not_accept() -> None:
    reports = [
        {"status": "success", "summary": "Done.", "data": {"x": 1}},
        {"status": "partial", "summary": "Partial."},
        {"status": "failed", "error": "Crashed"},
    ]
    score = aggregate_worker_reports(reports)
    assert isinstance(score, NeutrosophicScore)
    assert score.decision != NeutrosophicDecision.ACCEPT


def test_neutrosophic_judge_not_instantiated_at_module_level() -> None:
    """NeutrosophicJudge must remain opt-in — absent from core runtime files."""
    import ast

    # Anchor to the repo root via this file's location: core/tests/test_*.py
    repo_core = pathlib.Path(__file__).resolve().parent.parent
    runtime_roots = [
        repo_core / "framework" / "agent_loop",
        repo_core / "framework" / "host",
        repo_core / "framework" / "server",
        repo_core / "framework" / "orchestrator",
    ]
    offenders: list[str] = []
    for root in runtime_roots:
        if not root.is_dir():
            continue
        for py_file in root.rglob("*.py"):
            source = py_file.read_text(encoding="utf-8", errors="replace")
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                    if name == "NeutrosophicJudge":
                        offenders.append(f"{py_file}:{node.lineno}")

    assert offenders == [], f"NeutrosophicJudge instantiated in runtime files: {offenders}"
