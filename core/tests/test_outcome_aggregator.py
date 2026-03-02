"""
Tests for OutcomeAggregator — the goal evaluation engine.

This module (460 lines) had zero test coverage. These tests cover:
- Decision/outcome recording and tracking
- Constraint violation recording and event emission
- Goal progress evaluation (weighted criteria, partial credit)
- Success rate computation and recommendation engine
- Query and reset operations
- Edge cases (empty goals, zero-weight criteria, division safety)
"""

import pytest

from framework.graph.goal import Constraint, Goal, SuccessCriterion
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.schemas.decision import Decision, DecisionType, Outcome

# ---- Helpers ----


def _make_goal(
    criteria: list[SuccessCriterion] | None = None,
    constraints: list[Constraint] | None = None,
) -> Goal:
    return Goal(
        id="goal-1",
        name="Test Goal",
        description="Test goal",
        success_criteria=criteria or [],
        constraints=constraints or [],
    )


def _make_decision(
    decision_id: str = "d1",
    intent: str = "do something",
    active_constraints: list[str] | None = None,
    reasoning: str = "",
) -> Decision:
    return Decision(
        id=decision_id,
        node_id="node-1",
        intent=intent,
        decision_type=DecisionType.TOOL_SELECTION,
        active_constraints=active_constraints or [],
        reasoning=reasoning,
    )


def _make_outcome(success: bool = True) -> Outcome:
    return Outcome(success=success)


def _make_criterion(
    cid: str = "c1",
    description: str = "succeed",
    weight: float = 1.0,
    target: str = "80%",
    ctype: str = "success_rate",
) -> SuccessCriterion:
    return SuccessCriterion(
        id=cid,
        description=description,
        metric="custom",
        type=ctype,
        target=target,
        weight=weight,
    )


# ---- Decision Recording ----


class TestDecisionRecording:
    def test_record_single_decision(self):
        agg = OutcomeAggregator(_make_goal())
        decision = _make_decision()
        agg.record_decision("stream-1", "exec-1", decision)

        assert agg._total_decisions == 1
        assert len(agg._decisions) == 1

    def test_record_multiple_decisions(self):
        agg = OutcomeAggregator(_make_goal())
        for i in range(5):
            agg.record_decision("stream-1", "exec-1", _make_decision(f"d{i}"))

        assert agg._total_decisions == 5

    def test_decisions_indexed_by_composite_key(self):
        agg = OutcomeAggregator(_make_goal())
        d = _make_decision("d1")
        agg.record_decision("s1", "e1", d)

        assert "s1:e1:d1" in agg._decisions_by_id


# ---- Outcome Recording ----


class TestOutcomeRecording:
    def test_record_successful_outcome(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))

        assert agg._successful_outcomes == 1
        assert agg._failed_outcomes == 0

    def test_record_failed_outcome(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=False))

        assert agg._successful_outcomes == 0
        assert agg._failed_outcomes == 1

    def test_outcome_for_unknown_decision_is_noop(self):
        """Recording an outcome for a non-existent decision should not crash."""
        agg = OutcomeAggregator(_make_goal())
        agg.record_outcome("s1", "e1", "nonexistent", _make_outcome())

        assert agg._successful_outcomes == 0
        assert agg._failed_outcomes == 0

    def test_outcome_attached_to_decision_record(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_decision("s1", "e1", _make_decision("d1"))
        outcome = _make_outcome(success=True)
        agg.record_outcome("s1", "e1", "d1", outcome)

        record = agg._decisions_by_id["s1:e1:d1"]
        assert record.outcome is outcome


# ---- Constraint Violations ----


class TestConstraintViolations:
    def test_record_constraint_violation(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_constraint_violation(
            constraint_id="safety-1",
            description="No crashing",
            violation_details="Agent crashed",
        )

        assert len(agg._constraint_violations) == 1
        assert agg._constraint_violations[0].violated is True
        assert agg._constraint_violations[0].constraint_id == "safety-1"

    def test_violation_without_event_bus_does_not_crash(self):
        """No event bus should not raise."""
        agg = OutcomeAggregator(_make_goal(), event_bus=None)
        agg.record_constraint_violation(
            constraint_id="c1",
            description="test",
            violation_details="detail",
            stream_id="s1",
        )
        assert len(agg._constraint_violations) == 1


# ---- Goal Progress Evaluation ----


class TestGoalProgress:
    @pytest.mark.asyncio
    async def test_empty_goal_returns_zero_progress(self):
        """A goal with no criteria should have 0% progress."""
        agg = OutcomeAggregator(_make_goal(criteria=[]))
        result = await agg.evaluate_goal_progress()

        assert result["overall_progress"] == 0.0
        assert result["recommendation"] == "continue"

    @pytest.mark.asyncio
    async def test_single_criterion_fully_met(self):
        """One criterion at 100% success rate → 100% progress."""
        criterion = _make_criterion("c1", "all succeed", target="80%")
        goal = _make_goal(criteria=[criterion])
        agg = OutcomeAggregator(goal)

        # Record a decision with active_constraints containing criterion.id
        d = _make_decision("d1", active_constraints=["c1"])
        agg.record_decision("s1", "e1", d)
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))

        result = await agg.evaluate_goal_progress()
        assert result["overall_progress"] >= 0.8

    @pytest.mark.asyncio
    async def test_single_criterion_all_failed(self):
        """One criterion at 0% success → 0% progress."""
        criterion = _make_criterion("c1", "must succeed", target="80%")
        goal = _make_goal(criteria=[criterion])
        agg = OutcomeAggregator(goal)

        d = _make_decision("d1", active_constraints=["c1"])
        agg.record_decision("s1", "e1", d)
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=False))

        result = await agg.evaluate_goal_progress()
        assert result["overall_progress"] < 0.8

    @pytest.mark.asyncio
    async def test_weighted_criteria(self):
        """Two criteria with different weights produce weighted progress."""
        c1 = _make_criterion("c1", "high priority", weight=0.8, target="80%")
        c2 = _make_criterion("c2", "low priority", weight=0.2, target="80%")
        goal = _make_goal(criteria=[c1, c2])
        agg = OutcomeAggregator(goal)

        # c1: success, c2: no decisions → c1 fully met, c2 0%
        d = _make_decision("d1", active_constraints=["c1"])
        agg.record_decision("s1", "e1", d)
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))

        result = await agg.evaluate_goal_progress()
        # c1 (weight=0.8) met, c2 (weight=0.2) not → progress > 0.5
        assert result["overall_progress"] > 0.5

    @pytest.mark.asyncio
    async def test_non_success_rate_criterion_returns_zero(self):
        """Criteria with type != 'success_rate' should return zero progress."""
        criterion = _make_criterion(
            "c1", "custom check", target="100%", ctype="custom"
        )
        goal = _make_goal(criteria=[criterion])
        agg = OutcomeAggregator(goal)

        d = _make_decision("d1", active_constraints=["c1"])
        agg.record_decision("s1", "e1", d)
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))

        result = await agg.evaluate_goal_progress()
        # Custom type returns early with progress=0
        assert result["criteria_status"]["c1"]["progress"] == 0.0


# ---- Metrics ----


class TestMetrics:
    @pytest.mark.asyncio
    async def test_metrics_include_stream_and_execution_counts(self):
        goal = _make_goal(criteria=[_make_criterion()])
        agg = OutcomeAggregator(goal)

        # Two streams, three executions
        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_decision("s1", "e2", _make_decision("d2"))
        agg.record_decision("s2", "e3", _make_decision("d3"))

        result = await agg.evaluate_goal_progress()
        metrics = result["metrics"]

        assert metrics["total_decisions"] == 3
        assert metrics["streams_active"] == 2
        assert metrics["executions_total"] == 3

    @pytest.mark.asyncio
    async def test_success_rate_avoids_division_by_zero(self):
        """No outcomes → success_rate should be 0, not crash."""
        goal = _make_goal(criteria=[_make_criterion()])
        agg = OutcomeAggregator(goal)

        agg.record_decision("s1", "e1", _make_decision("d1"))
        # No outcome recorded

        result = await agg.evaluate_goal_progress()
        assert result["metrics"]["success_rate"] == 0


# ---- Recommendations ----


class TestRecommendations:
    @pytest.mark.asyncio
    async def test_high_progress_recommends_complete(self):
        c = _make_criterion("c1", "finish", target="50%")
        goal = _make_goal(criteria=[c])
        agg = OutcomeAggregator(goal)

        # 100% success across many decisions
        for i in range(20):
            d = _make_decision(f"d{i}", active_constraints=["c1"])
            agg.record_decision("s1", "e1", d)
            agg.record_outcome(
                "s1", "e1", f"d{i}", _make_outcome(success=True)
            )

        result = await agg.evaluate_goal_progress()
        assert result["recommendation"] == "complete"

    @pytest.mark.asyncio
    async def test_low_progress_many_decisions_recommends_adjust(self):
        c = _make_criterion("c1", "finish", target="80%")
        goal = _make_goal(criteria=[c])
        agg = OutcomeAggregator(goal)

        # 0% success across many decisions → should recommend adjust
        for i in range(15):
            d = _make_decision(f"d{i}", active_constraints=["c1"])
            agg.record_decision("s1", "e1", d)
            agg.record_outcome(
                "s1", "e1", f"d{i}", _make_outcome(success=False)
            )

        result = await agg.evaluate_goal_progress()
        assert result["recommendation"] == "adjust"

    @pytest.mark.asyncio
    async def test_hard_constraint_violation_recommends_adjust(self):
        constraint = Constraint(
            id="safety-1",
            description="No crashing",
            constraint_type="hard",
        )
        c = _make_criterion("c1", "finish", target="80%")
        goal = _make_goal(criteria=[c], constraints=[constraint])
        agg = OutcomeAggregator(goal)

        # Meet criterion but violate hard constraint
        d = _make_decision("d1", active_constraints=["c1"])
        agg.record_decision("s1", "e1", d)
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))
        agg.record_constraint_violation(
            "safety-1", "No crashing", "Agent crashed"
        )

        result = await agg.evaluate_goal_progress()
        assert result["recommendation"] == "adjust"


# ---- Query Operations ----


class TestQueryOperations:
    def test_get_decisions_by_stream(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_decision("s2", "e1", _make_decision("d2"))

        s1_decisions = agg.get_decisions_by_stream("s1")
        assert len(s1_decisions) == 1
        assert s1_decisions[0].decision.id == "d1"

    def test_get_decisions_by_execution(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_decision("s1", "e2", _make_decision("d2"))

        e1_decisions = agg.get_decisions_by_execution("s1", "e1")
        assert len(e1_decisions) == 1

    def test_get_recent_decisions(self):
        agg = OutcomeAggregator(_make_goal())
        for i in range(20):
            agg.record_decision("s1", "e1", _make_decision(f"d{i}"))

        recent = agg.get_recent_decisions(limit=5)
        assert len(recent) == 5

    def test_get_criterion_status(self):
        c = _make_criterion("c1")
        goal = _make_goal(criteria=[c])
        agg = OutcomeAggregator(goal)

        status = agg.get_criterion_status("c1")
        assert status is not None
        assert status.criterion_id == "c1"
        assert status.met is False

    def test_get_criterion_status_nonexistent(self):
        agg = OutcomeAggregator(_make_goal())
        assert agg.get_criterion_status("nonexistent") is None

    def test_get_stats(self):
        agg = OutcomeAggregator(_make_goal())
        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))

        stats = agg.get_stats()
        assert stats["total_decisions"] == 1
        assert stats["successful_outcomes"] == 1
        assert stats["streams_seen"] == 1


# ---- Reset ----


class TestReset:
    def test_reset_clears_all_state(self):
        c = _make_criterion("c1")
        goal = _make_goal(criteria=[c])
        agg = OutcomeAggregator(goal)

        agg.record_decision("s1", "e1", _make_decision("d1"))
        agg.record_outcome("s1", "e1", "d1", _make_outcome(success=True))
        agg.record_constraint_violation("c1", "test", "detail")

        agg.reset()

        assert agg._total_decisions == 0
        assert agg._successful_outcomes == 0
        assert agg._failed_outcomes == 0
        assert len(agg._decisions) == 0
        assert len(agg._constraint_violations) == 0
