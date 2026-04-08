"""Tests for framework.testing.cli — Phase 4 reporting/trends surfaces.

Covers:
- ``_print_failure_report`` includes the EVOLUTION RECOMMENDATIONS section
- ``cmd_eval_trends`` table + JSON output and the no-reports path
"""

from __future__ import annotations

import argparse
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from framework.schemas.failure_report import (
    FailureReport,
    UnmetCriterion,
    ViolatedConstraint,
)
from framework.testing.cli import (
    _load_agent_goal,
    _print_failure_report,
    _print_goal_criteria_status,
    cmd_eval_trends,
)


class TestPrintFailureReport:
    def test_includes_recommendations_section(self) -> None:
        report = FailureReport(
            goal_id="g1",
            goal_name="G",
            unmet_criteria=[
                UnmetCriterion(
                    criterion_id="c1",
                    description="must mention widgets",
                    metric="output_contains",
                    target="widgets",
                    weight=1.0,
                )
            ],
            violated_constraints=[
                ViolatedConstraint(
                    constraint_id="k1",
                    description="no PII",
                    constraint_type="hard",
                    violation_details="leaked",
                )
            ],
            edge_ids=["a->b"],
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_failure_report(report)
        out = buf.getvalue()
        assert "EVOLUTION RECOMMENDATIONS" in out
        assert "Strengthen criterion 'c1'" in out
        assert "guard for constraint 'k1'" in out
        assert "Inspect failing edges: a->b" in out


class TestEvalTrends:
    def test_outputs_table_for_stored_reports(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rd = tmp_path / ".runtime" / "failure_reports"
        rd.mkdir(parents=True)
        r = FailureReport(
            goal_id="g1",
            goal_name="G",
            version=1,
            unmet_criteria=[
                UnmetCriterion(
                    criterion_id="c1",
                    description="d",
                    metric="output_contains",
                    target="x",
                    weight=1.0,
                )
            ],
            total_decisions=4,
            successful_outcomes=1,
            failed_outcomes=3,
        )
        (rd / "g1.json").write_text(r.model_dump_json())

        rc = cmd_eval_trends(
            argparse.Namespace(
                agent_path=str(tmp_path),
                storage_path=None,
                goal=None,
                format="table",
            )
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "g1" in out
        assert "0.25" in out  # 1 / (1+3) success rate

    def test_json_output_shape(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rd = tmp_path / ".runtime" / "failure_reports"
        rd.mkdir(parents=True)
        (rd / "x.json").write_text(
            FailureReport(goal_id="g", goal_name="G", version=2).model_dump_json()
        )
        rc = cmd_eval_trends(
            argparse.Namespace(
                agent_path=str(tmp_path),
                storage_path=None,
                goal=None,
                format="json",
            )
        )
        assert rc == 0
        rows = json.loads(capsys.readouterr().out)
        assert isinstance(rows, list)
        assert rows[0]["goal_id"] == "g"
        assert rows[0]["version"] == 2

    def _make_agent_dir(self, tmp_path: Path) -> Path:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "agent.py").write_text(
            """
from framework.graph.goal import Goal, SuccessCriterion

goal = Goal(
    id="g1",
    name="Test Goal",
    description="d",
    success_criteria=[
        SuccessCriterion(
            id="c1",
            description="must contain widgets",
            metric="output_contains",
            target="widgets",
            weight=1.0,
        ),
        SuccessCriterion(
            id="c2",
            description="must equal answer",
            metric="output_equals",
            target="42",
            weight=1.0,
        ),
    ],
)
nodes = []
edges = []
"""
        )
        return agent_dir

    def test_missing_reports_returns_zero(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        rc = cmd_eval_trends(
            argparse.Namespace(
                agent_path=str(tmp_path),
                storage_path=None,
                goal=None,
                format="table",
            )
        )
        assert rc == 0
        assert "No failure reports" in capsys.readouterr().out


class TestGoalCriteriaStatus:
    """Tests for the AC #4 integration: hive test-run reports criteria status."""

    def _make_agent_dir(self, tmp_path: Path) -> Path:
        agent_dir = tmp_path / "agent"
        agent_dir.mkdir()
        (agent_dir / "agent.py").write_text(
            "from framework.graph.goal import Goal, SuccessCriterion\n"
            "goal = Goal(\n"
            "    id='g1', name='Test Goal', description='d',\n"
            "    success_criteria=[\n"
            "        SuccessCriterion(id='c1', description='must contain widgets',\n"
            "            metric='output_contains', target='widgets', weight=1.0),\n"
            "        SuccessCriterion(id='c2', description='answer is 42',\n"
            "            metric='output_equals', target='42', weight=1.0),\n"
            "    ],\n"
            ")\n"
            "nodes = []\n"
            "edges = []\n"
        )
        return agent_dir

    def test_load_agent_goal(self, tmp_path: Path) -> None:
        agent_dir = self._make_agent_dir(tmp_path)
        goal = _load_agent_goal(agent_dir)
        assert goal is not None
        assert goal.id == "g1"
        assert len(goal.success_criteria) == 2

    def test_no_failure_report_means_all_criteria_pass(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        agent_dir = self._make_agent_dir(tmp_path)
        _print_goal_criteria_status(agent_dir, storage_path=None)
        out = capsys.readouterr().out
        assert "Goal Criteria Status" in out
        assert "[PASS] c1" in out
        assert "[PASS] c2" in out
        assert "2/2 criteria met" in out

    def test_failure_report_marks_unmet_criteria_failing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        agent_dir = self._make_agent_dir(tmp_path)
        reports_dir = agent_dir / ".runtime" / "failure_reports"
        reports_dir.mkdir(parents=True)
        report = FailureReport(
            goal_id="g1",
            goal_name="Test Goal",
            unmet_criteria=[
                UnmetCriterion(
                    criterion_id="c1",
                    description="must contain widgets",
                    metric="output_contains",
                    target="widgets",
                    weight=1.0,
                )
            ],
            error_category="implementation_error",
        )
        (reports_dir / "g1_20260101_000000.json").write_text(
            report.model_dump_json()
        )

        _print_goal_criteria_status(agent_dir, storage_path=None)
        out = capsys.readouterr().out
        assert "[FAIL] c1" in out
        assert "[PASS] c2" in out
        assert "1/2 criteria met" in out
        assert "error_category: implementation_error" in out

    def test_missing_agent_module_is_silent(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        # No agent.py / __init__.py — helper should no-op without raising.
        _print_goal_criteria_status(tmp_path, storage_path=None)
        out = capsys.readouterr().out
        assert "Goal Criteria Status" not in out
