from framework.neutrosophic import NeutrosophicDecision, NeutrosophicScore, aggregate_scores, score_worker_report


def test_score_clamps_values() -> None:
    score = NeutrosophicScore(2.0, -1.0, 0.5)

    assert score.truth == 1.0
    assert score.indeterminacy == 0.0
    assert score.falsity == 0.5


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
