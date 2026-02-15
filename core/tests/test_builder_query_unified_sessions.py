from __future__ import annotations

from datetime import datetime

from framework.builder.query import BuilderQuery
from framework.schemas.decision import Decision, DecisionType, Option, Outcome
from framework.schemas.run import Problem, Run, RunMetrics, RunStatus
from framework.schemas.session_state import (
    SessionMetrics,
    SessionProgress,
    SessionResult,
    SessionState,
    SessionStatus,
    SessionTimestamps,
)


def _write_session_state(tmp_path, state: SessionState) -> None:
    session_dir = tmp_path / "sessions" / state.session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "state.json").write_text(state.model_dump_json(indent=2), encoding="utf-8")


def test_builder_query_reads_unified_session_state(tmp_path) -> None:
    session_id = "session_20260214_120000_abc12345"
    now = datetime.now().isoformat()

    decision = Decision(
        id="dec_0",
        node_id="node_a",
        intent="Try something",
        decision_type=DecisionType.CUSTOM,
        options=[
            Option(id="ok", description="Succeed", action_type="execute"),
            Option(id="bad", description="Fail", action_type="execute"),
        ],
        chosen_option_id="bad",
        reasoning="Testing failure path",
        outcome=Outcome(
            success=False, error="boom", summary="failed", tokens_used=3, latency_ms=10
        ),
    )

    problem = Problem(id="prob_0", severity="critical", description="boom", decision_id="dec_0")

    state = SessionState(
        session_id=session_id,
        goal_id="goal_1",
        status=SessionStatus.FAILED,
        timestamps=SessionTimestamps(started_at=now, updated_at=now, completed_at=now),
        progress=SessionProgress(paused_at=None, steps_executed=1, total_latency_ms=10),
        result=SessionResult(success=False, error="boom", output={"ok": False}),
        metrics=SessionMetrics(decision_count=1, problem_count=1),
        decisions=[decision.model_dump()],
        problems=[problem.model_dump()],
        input_data={"x": 1},
    )
    _write_session_state(tmp_path, state)

    q = BuilderQuery(tmp_path)

    summary = q.get_run_summary(session_id)
    assert summary is not None
    assert summary.run_id == session_id
    assert summary.goal_id == "goal_1"
    assert summary.status == RunStatus.FAILED
    assert summary.decision_count == 1
    assert summary.problem_count == 1

    trace = q.get_decision_trace(session_id)
    assert len(trace) == 1

    analysis = q.analyze_failure(session_id)
    assert analysis is not None
    assert analysis.run_id == session_id
    assert "boom" in analysis.root_cause

    runs = q.list_runs_for_goal("goal_1")
    assert any(r.run_id == session_id for r in runs)

    failures = q.get_recent_failures(limit=10)
    assert any(r.run_id == session_id for r in failures)


def test_session_state_attach_run_populates_decisions_and_problems() -> None:
    now_dt = datetime.now()

    decision = Decision(
        id="dec_0",
        node_id="node_a",
        intent="Succeed",
        options=[Option(id="ok", description="Ok", action_type="execute")],
        chosen_option_id="ok",
        reasoning="",
        outcome=Outcome(success=True, summary="ok", tokens_used=2, latency_ms=5),
    )
    problem = Problem(id="prob_0", severity="warning", description="minor issue")

    run = Run(
        id="run_1",
        goal_id="goal_1",
        started_at=now_dt,
        status=RunStatus.COMPLETED,
        completed_at=now_dt,
        decisions=[decision],
        problems=[problem],
        metrics=RunMetrics(
            total_decisions=1,
            successful_decisions=1,
            failed_decisions=0,
            total_tokens=2,
            total_latency_ms=5,
            nodes_executed=["node_a"],
            edges_traversed=[],
        ),
        narrative="done",
    )

    state = SessionState(
        session_id="session_20260214_120100_def67890",
        goal_id="goal_1",
        status=SessionStatus.COMPLETED,
        timestamps=SessionTimestamps(
            started_at=now_dt.isoformat(),
            updated_at=now_dt.isoformat(),
            completed_at=now_dt.isoformat(),
        ),
        progress=SessionProgress(),
        result=SessionResult(success=True, output={}),
        metrics=SessionMetrics(),
    )

    state.attach_run(run)
    assert state.metrics.decision_count == 1
    assert state.metrics.problem_count == 1
    assert len(state.decisions) == 1
    assert len(state.problems) == 1
