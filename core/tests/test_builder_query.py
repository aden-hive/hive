"""Tests for BuilderQuery compatibility with unified session storage."""

from pathlib import Path

from framework import BuilderQuery, Runtime


def _run_once(
    storage_path: Path,
    *,
    goal_id: str,
    node_id: str,
    success: bool,
) -> str:
    runtime = Runtime(storage_path)
    run_id = runtime.start_run(goal_id=goal_id, goal_description="Test goal")
    runtime.set_node(node_id)
    decision_id = runtime.decide(
        intent="Process input",
        options=[{"id": "process", "description": "Process"}],
        chosen="process",
        reasoning="Test decision",
    )
    runtime.record_outcome(
        decision_id=decision_id,
        success=success,
        result={"ok": success},
        error=None if success else "Synthetic failure",
        summary="Done" if success else "Failed",
        tokens_used=10,
        latency_ms=15,
    )
    runtime.end_run(success=success)
    return run_id


def test_builder_query_lists_goal_runs_from_unified_sessions(tmp_path: Path):
    run_1 = _run_once(tmp_path, goal_id="goal-a", node_id="node-a", success=True)
    run_2 = _run_once(tmp_path, goal_id="goal-a", node_id="node-a", success=False)
    _run_once(tmp_path, goal_id="goal-b", node_id="node-b", success=True)

    query = BuilderQuery(tmp_path)
    goal_a_summaries = query.list_runs_for_goal("goal-a")
    run_ids = {s.run_id for s in goal_a_summaries}

    assert run_ids == {run_1, run_2}


def test_builder_query_recent_failures_from_unified_sessions(tmp_path: Path):
    _run_once(tmp_path, goal_id="goal-a", node_id="node-a", success=True)
    failed_run = _run_once(tmp_path, goal_id="goal-a", node_id="node-a", success=False)

    query = BuilderQuery(tmp_path)
    failures = query.get_recent_failures(limit=5)

    assert any(summary.run_id == failed_run for summary in failures)


def test_builder_query_node_performance_from_unified_sessions(tmp_path: Path):
    _run_once(tmp_path, goal_id="goal-a", node_id="intake", success=True)
    _run_once(tmp_path, goal_id="goal-a", node_id="intake", success=False)
    _run_once(tmp_path, goal_id="goal-a", node_id="other", success=True)

    query = BuilderQuery(tmp_path)
    perf = query.get_node_performance("intake")

    assert perf["node_id"] == "intake"
    assert perf["total_decisions"] == 2
    assert perf["total_tokens"] == 20
    assert 0.0 <= perf["success_rate"] <= 1.0
