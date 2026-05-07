import math

import pytest

from framework.neutrosophic import NeutrosophicDecision, NeutrosophicScore, aggregate_scores, score_worker_report


def test_score_clamps_values() -> None:
    score = NeutrosophicScore(2.0, -1.0, 0.5)

    assert score.truth == 1.0
    assert score.indeterminacy == 0.0
    assert score.falsity == 0.5


def test_score_rejects_non_finite_values() -> None:
    with pytest.raises(ValueError, match="finite numbers"):
        NeutrosophicScore(math.nan, 0.0, 0.0)

    with pytest.raises(ValueError, match="finite numbers"):
        NeutrosophicScore(0.0, math.inf, 0.0)


def test_success_worker_report_accepts_with_evidence() -> None:
    score = score_worker_report(status="success", summary="Completed task", data={"rows": 3})

    assert score.decision == NeutrosophicDecision.ACCEPT
    assert score.truth > score.indeterminacy
    assert score.truth > score.falsity
    assert "status=success" in score.rationale


def test_partial_worker_report_requests_clarification() -> None:
    score = score_worker_report(status="partial", summary="Found some data", data={})

    assert score.decision in {NeutrosophicDecision.CLARIFY, NeutrosophicDecision.CAVEAT}
    assert score.indeterminacy >= score.truth


def test_failed_worker_report_escalates() -> None:
    score = score_worker_report(status="failed", summary="Tool failed", error="missing credentials")

    assert score.decision == NeutrosophicDecision.ESCALATE
    assert score.falsity > score.truth


def test_loop_signals_increase_risk() -> None:
    baseline = score_worker_report(status="partial", summary="Still trying")
    risky = score_worker_report(
        status="partial",
        summary="Still trying",
        signals={"stalled": True, "doom_loop": True},
    )

    assert risky.indeterminacy > baseline.indeterminacy
    assert risky.falsity > baseline.falsity


def test_aggregate_scores_averages_triplets() -> None:
    aggregate = aggregate_scores(
        [
            NeutrosophicScore(1.0, 0.0, 0.0),
            NeutrosophicScore(0.0, 1.0, 0.0),
        ]
    )

    assert aggregate.truth == 0.5
    assert aggregate.indeterminacy == 0.5
    assert aggregate.falsity == 0.0
    assert aggregate.rationale == ("aggregate_count=2",)


def test_aggregate_scores_empty_returns_fully_indeterminate() -> None:
    # An empty batch has no evidence: indeterminacy=1.0 is the conservative default.
    aggregate = aggregate_scores([])

    assert aggregate.truth == 0.0
    assert aggregate.indeterminacy == 1.0
    assert aggregate.falsity == 0.0
    assert aggregate.rationale == ("no_scores",)
    assert aggregate.decision == NeutrosophicDecision.CLARIFY


def test_high_indeterminacy_takes_priority_over_high_falsity() -> None:
    # RFC specifies: I >= 0.65 → CLARIFY before F >= 0.65 → ESCALATE.
    # A score that crosses both thresholds should yield CLARIFY, not ESCALATE.
    score = NeutrosophicScore(truth=0.1, indeterminacy=0.8, falsity=0.7)

    assert score.decision == NeutrosophicDecision.CLARIFY


def test_moderate_falsity_retries_without_escalating() -> None:
    score = NeutrosophicScore(truth=0.5, indeterminacy=0.2, falsity=0.5)

    assert score.decision == NeutrosophicDecision.RETRY


def test_to_dict_contract() -> None:
    score = NeutrosophicScore(0.9, 0.05, 0.05, ("status=success",))
    result = score.to_dict()

    assert set(result.keys()) == {"truth", "indeterminacy", "falsity", "decision", "rationale"}
    assert isinstance(result["truth"], float)
    assert isinstance(result["rationale"], list)
    assert result["decision"] == "accept"


def test_unknown_status_scores_conservatively() -> None:
    score = score_worker_report(status="pending")

    assert "status=unknown" in score.rationale
    # Unknown status should not yield ACCEPT — too little evidence.
    assert score.decision != NeutrosophicDecision.ACCEPT


def test_success_report_with_error_does_not_clean_accept() -> None:
    score = score_worker_report(
        status="success",
        summary="Completed with warning",
        data={"rows": 3},
        error="post-processing failed",
    )

    assert "error_present" in score.rationale
    assert score.decision != NeutrosophicDecision.ACCEPT
