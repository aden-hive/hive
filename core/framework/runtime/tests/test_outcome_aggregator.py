"""Tests for OutcomeAggregator failure recording, history, and notifier integration.

Companion to ``test_evaluate_criterion.py`` (which covers metric dispatch).
This file focuses on the Phase 2/4 surfaces of OutcomeAggregator:

- ``evaluate_output`` populates ``Goal.failure_history`` with monotonic versions
- successful evaluations don't append to history
- failure reports are persisted to disk under ``storage_path``
- ``generate_failure_report`` derives ``edge_ids`` from consecutive decisions
- Phase 4 developer notifier is invoked on failure and isolated from exceptions
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from framework.graph.goal import Goal, SuccessCriterion
from framework.runtime.outcome_aggregator import OutcomeAggregator
from framework.schemas.decision import Decision, Outcome
from framework.schemas.failure_report import FailureReport


def _failing_goal() -> Goal:
    return Goal(
        id="g1",
        name="G",
        description="d",
        success_criteria=[
            SuccessCriterion(
                id="c1",
                description="must contain widgets",
                metric="output_contains",
                target="widgets",
            )
        ],
    )


class TestFailureHistory:
    @pytest.mark.asyncio
    async def test_evaluate_output_appends_history_with_versioning(
        self, tmp_path: Path
    ) -> None:
        goal = _failing_goal()
        agg = OutcomeAggregator(goal, storage_path=tmp_path)

        ok = await agg.evaluate_output("nothing relevant")
        assert ok is False
        assert len(goal.failure_history) == 1
        assert goal.failure_history[0].version == 1

        for c in goal.success_criteria:
            c.met = False
        ok = await agg.evaluate_output("still nothing")
        assert ok is False
        assert len(goal.failure_history) == 2
        assert goal.failure_history[1].version == 2

    @pytest.mark.asyncio
    async def test_successful_evaluation_does_not_append(self) -> None:
        goal = _failing_goal()
        agg = OutcomeAggregator(goal)
        ok = await agg.evaluate_output("we have widgets here")
        assert ok is True
        assert goal.failure_history == []

    @pytest.mark.asyncio
    async def test_failure_report_persisted_to_disk(self, tmp_path: Path) -> None:
        goal = _failing_goal()
        agg = OutcomeAggregator(goal, storage_path=tmp_path)
        await agg.evaluate_output("no match")
        files = list((tmp_path / "failure_reports").glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text())
        assert data["goal_id"] == "g1"
        assert data["version"] == 1


class TestGenerateFailureReportEdges:
    def test_edge_ids_field_default_empty(self) -> None:
        r = FailureReport(goal_id="g", goal_name="n")
        assert r.edge_ids == []

    def test_derives_edges_between_failed_nodes(self) -> None:
        goal = _failing_goal()
        agg = OutcomeAggregator(goal)

        d1 = Decision(
            id="d1", node_id="nodeA", intent="i", action="a", reasoning="r"
        )
        d2 = Decision(
            id="d2", node_id="nodeB", intent="i", action="a", reasoning="r"
        )
        agg.record_decision("s", "e", d1)
        agg.record_outcome("s", "e", "d1", Outcome(decision_id="d1", success=False))
        agg.record_decision("s", "e", d2)
        agg.record_outcome("s", "e", "d2", Outcome(decision_id="d2", success=False))

        report = agg.generate_failure_report()
        assert "nodeA" in report.node_ids
        assert "nodeB" in report.node_ids
        assert "nodeA->nodeB" in report.edge_ids


class TestErrorCategoryWiring:
    @pytest.mark.asyncio
    async def test_failure_report_has_error_category(self) -> None:
        goal = _failing_goal()
        agg = OutcomeAggregator(goal)
        await agg.evaluate_output("no match")
        assert goal.failure_history[0].error_category is not None


class TestNotifierIntegration:
    @pytest.mark.asyncio
    async def test_notifier_invoked_on_failure(self) -> None:
        calls: list = []
        notifier = SimpleNamespace(
            notify_failure=lambda r: calls.append(r),
            notify_progress=lambda p: None,
        )
        agg = OutcomeAggregator(_failing_goal(), notifier=notifier)
        await agg.evaluate_output("none")
        assert len(calls) == 1
        assert calls[0].goal_id == "g1"

    @pytest.mark.asyncio
    async def test_notifier_exception_does_not_break_eval(self) -> None:
        def boom(_r):
            raise RuntimeError("notifier down")

        notifier = SimpleNamespace(
            notify_failure=boom, notify_progress=lambda p: None
        )
        agg = OutcomeAggregator(_failing_goal(), notifier=notifier)
        # Best-effort: notifier failure must not propagate.
        result = await agg.evaluate_output("none")
        assert result is False
