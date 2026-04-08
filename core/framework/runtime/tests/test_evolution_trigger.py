"""Tests for EvolutionTrigger."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from framework.graph.goal import Goal
from framework.runtime.evolution_trigger import (
    EvolutionPlan,
    EvolutionTrigger,
    ProposedChange,
    apply_plan,
    compute_failure_rate,
    load_failure_reports,
)
from framework.schemas.failure_report import (
    FailureReport,
    UnmetCriterion,
    ViolatedConstraint,
)


def _make_report() -> FailureReport:
    return FailureReport(
        goal_id="g1",
        goal_name="Test Goal",
        unmet_criteria=[
            UnmetCriterion(
                criterion_id="c1",
                description="Output mentions widgets",
                metric="output_contains",
                target="widgets",
                weight=1.0,
            )
        ],
        violated_constraints=[
            ViolatedConstraint(
                constraint_id="x1",
                description="No PII",
                constraint_type="hard",
                violation_details="email leaked",
            )
        ],
        node_ids=["nodeA", "nodeB"],
        summary="Goal not achieved",
        total_decisions=3,
        successful_outcomes=1,
        failed_outcomes=2,
    )


class TestBuildPrompt:
    def test_prompt_includes_all_sections(self) -> None:
        llm = SimpleNamespace(acomplete=AsyncMock())
        trigger = EvolutionTrigger(llm_provider=llm)
        prompt = trigger.build_prompt(_make_report())

        assert "Test Goal" in prompt
        assert "g1" in prompt
        assert "c1" in prompt
        assert "widgets" in prompt
        assert "x1" in prompt
        assert "email leaked" in prompt
        assert "nodeA" in prompt
        assert "decisions: 3" in prompt

    def test_prompt_includes_error_category(self) -> None:
        llm = SimpleNamespace(acomplete=AsyncMock())
        trigger = EvolutionTrigger(llm_provider=llm)
        report = _make_report()
        report.error_category = "implementation_error"
        prompt = trigger.build_prompt(report)
        assert "ERROR CATEGORY: implementation_error" in prompt

    def test_prompt_handles_missing_error_category(self) -> None:
        llm = SimpleNamespace(acomplete=AsyncMock())
        trigger = EvolutionTrigger(llm_provider=llm)
        prompt = trigger.build_prompt(_make_report())
        assert "ERROR CATEGORY: (uncategorized)" in prompt


class TestRequiresBackend:
    def test_construction_requires_backend(self) -> None:
        with pytest.raises(ValueError):
            EvolutionTrigger()


class TestParseResponse:
    def test_parses_valid_json(self) -> None:
        payload = json.dumps(
            {
                "diagnosis": "missing prompt instruction",
                "proposed_changes": [
                    {
                        "target": "node_id",
                        "target_id": "nodeA",
                        "change_type": "modify",
                        "rationale": "add explicit mention",
                        "details": "append 'widgets' to prompt",
                    }
                ],
                "confidence": 0.7,
                "needs_human_review": False,
            }
        )
        plan = EvolutionTrigger._parse_response(payload)
        assert plan.diagnosis == "missing prompt instruction"
        assert plan.confidence == 0.7
        assert plan.needs_human_review is False
        assert len(plan.proposed_changes) == 1
        assert plan.proposed_changes[0].target_id == "nodeA"

    def test_parses_markdown_fenced_json(self) -> None:
        payload = (
            "```json\n"
            '{"diagnosis":"x","proposed_changes":[],'
            '"confidence":0.1,"needs_human_review":true}\n```'
        )
        plan = EvolutionTrigger._parse_response(payload)
        assert plan.diagnosis == "x"

    def test_invalid_json_returns_empty_plan_with_raw(self) -> None:
        plan = EvolutionTrigger._parse_response("not json at all")
        assert "Failed to parse" in plan.diagnosis
        assert plan.raw_response == "not json at all"


class TestDispatchToLLM:
    @pytest.mark.asyncio
    async def test_calls_llm_and_parses(self) -> None:
        response = SimpleNamespace(
            content=json.dumps(
                {
                    "diagnosis": "ok",
                    "proposed_changes": [],
                    "confidence": 0.5,
                    "needs_human_review": True,
                }
            )
        )
        llm = SimpleNamespace(acomplete=AsyncMock(return_value=response))
        trigger = EvolutionTrigger(llm_provider=llm)

        plan = await trigger.trigger(_make_report())

        assert plan.diagnosis == "ok"
        llm.acomplete.assert_awaited_once()
        kwargs = llm.acomplete.await_args.kwargs
        assert kwargs["json_mode"] is True

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error_plan(self) -> None:
        llm = SimpleNamespace(acomplete=AsyncMock(side_effect=RuntimeError("boom")))
        trigger = EvolutionTrigger(llm_provider=llm)
        plan = await trigger.trigger(_make_report())
        assert "boom" in plan.diagnosis


class TestDispatchToQueen:
    @pytest.mark.asyncio
    async def test_injects_trigger_event(self) -> None:
        queen_node = SimpleNamespace(inject_trigger=AsyncMock())
        trigger = EvolutionTrigger(queen_node=queen_node)

        plan = await trigger.trigger(_make_report())

        assert queen_node.inject_trigger.await_count == 1
        event = queen_node.inject_trigger.await_args.args[0]
        assert event.trigger_type == "evolution"
        assert event.payload["goal_id"] == "g1"
        assert event.payload["node_ids"] == ["nodeA", "nodeB"]
        assert "task" in event.payload
        assert plan.needs_human_review is False

    @pytest.mark.asyncio
    async def test_queen_takes_precedence_over_llm(self) -> None:
        queen_node = SimpleNamespace(inject_trigger=AsyncMock())
        llm = SimpleNamespace(acomplete=AsyncMock())
        trigger = EvolutionTrigger(llm_provider=llm, queen_node=queen_node)
        await trigger.trigger(_make_report())
        queen_node.inject_trigger.assert_awaited_once()
        llm.acomplete.assert_not_awaited()


class TestLoadFailureReports:
    def test_loads_and_sorts_newest_first(self, tmp_path: Path) -> None:
        d = tmp_path / "failure_reports"
        d.mkdir()

        r1 = _make_report()
        r1.goal_id = "older"
        r2 = _make_report()
        r2.goal_id = "newer"

        p1 = d / "older.json"
        p2 = d / "newer.json"
        p1.write_text(r1.model_dump_json())
        p2.write_text(r2.model_dump_json())

        # Force p2 to be newer
        import os
        import time

        old_time = time.time() - 100
        os.utime(p1, (old_time, old_time))

        loaded = load_failure_reports(d)
        assert [r.goal_id for r in loaded] == ["newer", "older"]

    def test_missing_dir_returns_empty(self, tmp_path: Path) -> None:
        assert load_failure_reports(tmp_path / "nope") == []


def test_proposed_change_from_dict_handles_missing_fields() -> None:
    c = ProposedChange.from_dict({})
    assert c.target == ""
    assert c.target_id is None


def test_evolution_plan_is_empty_default() -> None:
    plan = EvolutionPlan()
    assert plan.is_empty()


# ----------------------------------------------------------------------
# apply_plan: Phase 3 version-chain bookkeeping
# ----------------------------------------------------------------------


class TestApplyPlan:
    def test_version_bump_and_chain(self) -> None:
        goal = Goal(id="g", name="G", description="d", version="1.2.3")
        plan = EvolutionPlan(
            diagnosis="missing widget",
            proposed_changes=[
                ProposedChange(
                    target="node_id",
                    target_id="nA",
                    change_type="modify",
                    rationale="r",
                    details="dt",
                )
            ],
            confidence=0.6,
        )
        report = FailureReport(goal_id="g", goal_name="G", version=3)

        apply_plan(goal, plan, report)
        assert goal.parent_version == "1.2.3"
        assert goal.version == "1.2.4"
        assert goal.evolution_reason == "missing widget"

        log = goal.context["evolution_log"]
        assert len(log) == 1
        assert log[0]["from_version"] == "1.2.3"
        assert log[0]["to_version"] == "1.2.4"
        assert log[0]["failure_report_version"] == 3
        assert log[0]["changes"][0]["target_id"] == "nA"

    def test_empty_plan_skips_bump(self) -> None:
        goal = Goal(id="g", name="G", description="d", version="1.0.0")
        apply_plan(goal, EvolutionPlan(), FailureReport(goal_id="g", goal_name="G"))
        assert goal.version == "1.0.0"
        assert goal.parent_version is None
        assert "evolution_log" not in goal.context

    def test_non_semver_version_falls_back(self) -> None:
        goal = Goal(id="g", name="G", description="d", version="alpha")
        plan = EvolutionPlan(
            diagnosis="x",
            proposed_changes=[
                ProposedChange(
                    target="prompt",
                    target_id=None,
                    change_type="add",
                    rationale="r",
                    details="d",
                )
            ],
        )
        apply_plan(goal, plan, FailureReport(goal_id="g", goal_name="G"))
        assert goal.version == "alpha.1"


# ----------------------------------------------------------------------
# compute_failure_rate: Phase 3 automatic-trigger gate
# ----------------------------------------------------------------------


class TestComputeFailureRate:
    def test_empty_dir_returns_zero(self, tmp_path: Path) -> None:
        rate, count = compute_failure_rate(tmp_path / "missing", 4)
        assert rate == 0.0
        assert count == 0

    def test_zero_window(self, tmp_path: Path) -> None:
        assert compute_failure_rate(tmp_path, 0) == (0.0, 0)

    def test_full_window(self, tmp_path: Path) -> None:
        d = tmp_path / "failure_reports"
        d.mkdir()
        for i in range(4):
            (d / f"r{i}.json").write_text("{}")
        rate, count = compute_failure_rate(d, 4)
        assert rate == 1.0
        assert count == 4

    def test_partial_window(self, tmp_path: Path) -> None:
        d = tmp_path / "failure_reports"
        d.mkdir()
        (d / "r1.json").write_text("{}")
        rate, count = compute_failure_rate(d, 4)
        assert count == 1
        assert rate == 0.25
