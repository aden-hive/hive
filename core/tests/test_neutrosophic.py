import pytest

from framework.neutrosophic import (
    NeutrosophicDecision,
    NeutrosophicScore,
    aggregate_scores,
    score_worker_report,
)


def test_neutrosophic_score_clamping():
    """Test that T/I/F values are correctly clamped between 0.0 and 1.0."""
    score1 = NeutrosophicScore(t=1.5, i=-0.5, f=0.5)
    assert score1.t == 1.0
    assert score1.i == 0.0
    assert score1.f == 0.5

    score2 = NeutrosophicScore(t=-1.0, i=2.0, f=3.0)
    assert score2.t == 0.0
    assert score2.i == 1.0
    assert score2.f == 1.0


def test_neutrosophic_decision_logic():
    """Test the derivation of decisions based on T/I/F thresholds."""
    # High truth -> ACCEPT
    assert NeutrosophicScore(t=0.8, i=0.2, f=0.1).get_decision() == NeutrosophicDecision.ACCEPT
    
    # High indeterminacy -> CLARIFY
    assert NeutrosophicScore(t=0.4, i=0.8, f=0.2).get_decision() == NeutrosophicDecision.CLARIFY
    
    # High falsity -> RETRY
    assert NeutrosophicScore(t=0.1, i=0.1, f=0.8).get_decision() == NeutrosophicDecision.RETRY
    
    # High falsity + High indeterminacy -> ESCALATE
    assert NeutrosophicScore(t=0.1, i=0.8, f=0.9).get_decision() == NeutrosophicDecision.ESCALATE
    
    # Below all thresholds -> CAVEAT
    assert NeutrosophicScore(t=0.4, i=0.4, f=0.4).get_decision() == NeutrosophicDecision.CAVEAT


def test_score_worker_report_heuristics():
    """Test the heuristic scoring of worker reports."""
    # Perfect success
    score = score_worker_report(status="success", summary="Found the exact answer.", data={"key": "value"})
    assert score.t >= 0.8
    assert score.i == 0.0
    assert score.f == 0.0

    # Partial success with missing data
    score = score_worker_report(status="partial", summary="Missing some details.", data=None)
    assert score.t == 0.4
    assert score.i >= 0.7  # 0.4 from status + 0.4 from no data + 0.3 from 'missing' = 1.0 (clamped)
    assert score.f == 0.0

    # Failed with error and conflict
    score = score_worker_report(status="failed", summary="Conflict in records.", data=None, error="Connection timeout")
    assert score.t == 0.0
    assert score.i >= 0.4  # from no data
    assert score.f >= 1.0  # 0.8 status + 0.5 error + 0.3 conflict (clamped to 1.0)


def test_aggregate_scores():
    """Test the aggregation of multiple neutrosophic scores."""
    scores = [
        NeutrosophicScore(t=0.8, i=0.1, f=0.0),
        NeutrosophicScore(t=0.6, i=0.3, f=0.2),
        NeutrosophicScore(t=0.4, i=0.5, f=0.4),
    ]
    agg = aggregate_scores(scores)
    assert agg.t == pytest.approx(0.6)
    assert agg.i == pytest.approx(0.3)
    assert agg.f == pytest.approx(0.2)

    # Test empty list gives complete indeterminacy
    empty_agg = aggregate_scores([])
    assert empty_agg.t == 0.0
    assert empty_agg.i == 1.0
    assert empty_agg.f == 0.0
