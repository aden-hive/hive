"""Tests for the run post-mortem analyzer.

Builds runs on disk through the real ``RuntimeLogStore`` so the discovery and
loading paths are exercised against the format the runtime actually writes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from framework.postmortem import analyze, find_runs, load_run, render, resolve_run
from framework.postmortem.models import Severity, Thresholds
from framework.tracker.runtime_log_schemas import (
    NodeDetail,
    NodeStepLog,
    RunSummaryLog,
    ToolCallLog,
)
from framework.tracker.runtime_log_store import RuntimeLogStore

_SID = "session_20250101_000000_abcd"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _call(name: str, **kwargs) -> ToolCallLog:
    return ToolCallLog(
        tool_use_id=kwargs.pop("tool_use_id", f"tu_{name}"),
        tool_name=name,
        tool_input=kwargs.pop("tool_input", {"q": "x"}),
        result=kwargs.pop("result", "ok"),
        is_error=kwargs.pop("is_error", False),
        duration_s=kwargs.pop("duration_s", 0.1),
    )


def _step(node_id: str, index: int, **kwargs) -> NodeStepLog:
    return NodeStepLog(
        node_id=node_id,
        node_type="event_loop",
        step_index=index,
        llm_text=kwargs.pop("llm_text", f"turn {index}"),
        tool_calls=kwargs.pop("tool_calls", []),
        input_tokens=kwargs.pop("input_tokens", 100),
        output_tokens=kwargs.pop("output_tokens", 10),
        latency_ms=kwargs.pop("latency_ms", 500),
        **kwargs,
    )


def _write_run(
    root: Path,
    steps: list[NodeStepLog],
    nodes: list[NodeDetail],
    summary: RunSummaryLog | None = None,
    run_id: str = _SID,
) -> RuntimeLogStore:
    """Persist a run through the real store and return it."""
    store = RuntimeLogStore(root)
    store.ensure_session_run_dir(run_id)
    for step in steps:
        store.append_step(run_id, step)
    for node in nodes:
        store.append_node_detail(run_id, node)
    if summary is not None:
        path = root / "sessions" / run_id / "logs" / "summary.json"
        path.write_text(json.dumps(summary.model_dump()), encoding="utf-8")
    return store


def _codes(report) -> set[str]:
    return {f.code for f in report.findings}


def _analyze(root: Path, run_id: str = _SID, **kwargs):
    location = resolve_run(run_id, root)
    assert location is not None, f"run {run_id} not discovered under {root}"
    return analyze(load_run(location), **kwargs)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_finds_unified_session_run(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [])
    runs = find_runs(tmp_path)
    assert [r.run_id for r in runs] == [_SID]
    assert runs[0].logs_dir == tmp_path / "sessions" / _SID / "logs"


def test_finds_legacy_runs_layout(tmp_path: Path) -> None:
    legacy = tmp_path / "runs" / "20250101T120000_deadbeef"
    legacy.mkdir(parents=True)
    (legacy / "tool_logs.jsonl").write_text(json.dumps(_step("n1", 0).model_dump()) + "\n", encoding="utf-8")
    runs = find_runs(tmp_path)
    assert [r.run_id for r in runs] == ["20250101T120000_deadbeef"]
    loaded = load_run(runs[0])
    assert len(loaded.steps) == 1


def test_resolve_run_defaults_to_most_recent(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [], run_id="session_20250101_000000_old")
    _write_run(tmp_path, [_step("n1", 0)], [], run_id="session_20250101_000000_new")
    # Make the second run unambiguously newer than the first.
    newer = tmp_path / "sessions" / "session_20250101_000000_new" / "logs" / "tool_logs.jsonl"
    import os

    os.utime(newer, (2_000_000_000, 2_000_000_000))
    assert resolve_run(None, tmp_path).run_id == "session_20250101_000000_new"


def test_resolve_run_accepts_unique_substring(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [])
    assert resolve_run("abcd", tmp_path).run_id == _SID
    assert resolve_run("nope", tmp_path) is None


def test_find_runs_ignores_empty_directories(tmp_path: Path) -> None:
    (tmp_path / "sessions" / "session_empty" / "logs").mkdir(parents=True)
    assert find_runs(tmp_path) == []


# ---------------------------------------------------------------------------
# Vitals
# ---------------------------------------------------------------------------


def test_vitals_prefer_summary_and_derive_tool_stats(tmp_path: Path) -> None:
    steps = [
        _step("n1", 0, tool_calls=[_call("search"), _call("read", is_error=True)]),
        _step("n1", 1, tool_calls=[_call("search")]),
    ]
    summary = RunSummaryLog(
        run_id=_SID,
        agent_id="agent-x",
        status="success",
        total_nodes_executed=1,
        total_input_tokens=999,
        total_output_tokens=11,
        duration_ms=4200,
    )
    _write_run(tmp_path, steps, [NodeDetail(node_id="n1", success=True)], summary)

    v = _analyze(tmp_path).vitals
    assert v.agent_id == "agent-x"
    assert v.status == "success"
    assert (v.input_tokens, v.output_tokens) == (999, 11)  # L1 wins
    assert (v.tool_calls, v.tool_errors) == (3, 1)
    assert v.tool_error_rate == pytest.approx(1 / 3)
    assert v.duration_ms == 4200


def test_vitals_fall_back_to_steps_when_summary_missing(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0, input_tokens=40, output_tokens=5)], [])
    report = _analyze(tmp_path)
    assert report.vitals.status == "incomplete"
    assert (report.vitals.input_tokens, report.vitals.output_tokens) == (40, 5)
    assert any("never reached end_run" in w for w in report.warnings)


def test_resend_overhead_excludes_largest_send(tmp_path: Path) -> None:
    steps = [_step("n1", i, input_tokens=tok) for i, tok in enumerate([100, 200, 500])]
    _write_run(tmp_path, steps, [])
    # 800 total sent, 500 unavoidable -> 300 is re-sent prefix.
    assert _analyze(tmp_path).vitals.resend_overhead_tokens == 300


def test_cost_estimated_from_catalog_pricing(tmp_path: Path) -> None:
    summary = RunSummaryLog(run_id=_SID, total_input_tokens=1_000_000, total_output_tokens=0)
    _write_run(tmp_path, [_step("n1", 0)], [], summary)
    # gpt-5.5 is priced at $5.00/Mtok input in the curated catalog.
    v = _analyze(tmp_path, model="gpt-5.5").vitals
    assert v.cost_usd == pytest.approx(5.0)
    assert v.cost_source == "--model"


def test_cost_strips_provider_prefix_to_find_pricing(tmp_path: Path) -> None:
    summary = RunSummaryLog(run_id=_SID, total_input_tokens=1_000_000, total_output_tokens=1_000_000)
    _write_run(tmp_path, [_step("n1", 0)], [], summary)
    # "minimax/minimax-m2.7" is catalogued; the provider-prefixed form is not.
    v = _analyze(tmp_path, model="openrouter/minimax/minimax-m2.7").vitals
    assert v.cost_usd == pytest.approx(0.3 + 1.2)


def test_cost_is_none_for_unknown_model(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [])
    assert _analyze(tmp_path, model="not-a-real-model").vitals.cost_usd is None


# ---------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------


def test_clean_run_reports_no_findings(tmp_path: Path) -> None:
    steps = [_step("n1", i, tool_calls=[_call("search", tool_input={"q": i})]) for i in range(3)]
    nodes = [NodeDetail(node_id="n1", success=True, exit_status="success", accept_count=1)]
    _write_run(tmp_path, steps, nodes, RunSummaryLog(run_id=_SID, status="success"))
    assert _analyze(tmp_path).findings == []


def test_detects_tool_thrash(tmp_path: Path) -> None:
    steps = [_step("n1", i, tool_calls=[_call("search", tool_input={"q": "same"})]) for i in range(4)]
    _write_run(tmp_path, steps, [])
    report = _analyze(tmp_path)
    thrash = [f for f in report.findings if f.code == "tool_thrash"]
    assert len(thrash) == 1
    assert thrash[0].metrics["repeats"] == 4
    assert thrash[0].node_id == "n1"


def test_differing_arguments_are_not_thrash(tmp_path: Path) -> None:
    steps = [_step("n1", i, tool_calls=[_call("search", tool_input={"q": i})]) for i in range(6)]
    _write_run(tmp_path, steps, [])
    assert "tool_thrash" not in _codes(_analyze(tmp_path))


def test_detects_failing_tool(tmp_path: Path) -> None:
    steps = [
        _step("n1", i, tool_calls=[_call("crm", tool_input={"i": i}, is_error=i < 3, result="401 unauthorized")])
        for i in range(4)
    ]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "failing_tool")
    assert finding.metrics["errors"] == 3
    assert finding.metrics["calls"] == 4
    assert finding.metrics["rate"] == 0.75
    assert finding.severity is Severity.HIGH
    # The same failure three times collapses to one counted evidence line.
    assert finding.evidence == ["3x  401 unauthorized"]
    assert finding.metrics["distinct_errors"] == 1


def test_failing_tool_evidence_keeps_distinct_messages(tmp_path: Path) -> None:
    steps = [
        _step("n1", i, tool_calls=[_call("crm", tool_input={"i": i}, is_error=True, result=msg)])
        for i, msg in enumerate(["401 unauthorized", "401 unauthorized", "500 server error"])
    ]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "failing_tool")
    assert finding.metrics["distinct_errors"] == 2
    assert set(finding.evidence) == {"2x  401 unauthorized", "500 server error"}


def test_single_tool_error_is_below_threshold(tmp_path: Path) -> None:
    steps = [_step("n1", i, tool_calls=[_call("crm", tool_input={"i": i}, is_error=i == 0)]) for i in range(5)]
    _write_run(tmp_path, steps, [])
    assert "failing_tool" not in _codes(_analyze(tmp_path))


def test_detects_retry_storm_and_escalation(tmp_path: Path) -> None:
    nodes = [NodeDetail(node_id="n1", success=True, retry_count=7, escalate_count=3, accept_count=1)]
    _write_run(tmp_path, [], nodes)
    report = _analyze(tmp_path)
    retry = next(f for f in report.findings if f.code == "retry_storm")
    assert retry.severity is Severity.HIGH
    assert "escalation_loop" in _codes(report)


def test_detects_node_reexecution(tmp_path: Path) -> None:
    nodes = [
        NodeDetail(node_id="n1", success=False, error="boom", attempt=1),
        NodeDetail(node_id="n1", success=True, attempt=2),
    ]
    _write_run(tmp_path, [], nodes)
    report = _analyze(tmp_path)
    assert "node_reexecuted" in _codes(report)
    assert next(f for f in report.findings if f.code == "node_failed").severity is Severity.CRITICAL


def test_detects_bad_exit_status(tmp_path: Path) -> None:
    nodes = [NodeDetail(node_id="n1", success=True, exit_status="stalled", total_steps=25)]
    _write_run(tmp_path, [], nodes)
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "bad_exit_status")
    assert finding.severity is Severity.HIGH


def test_detects_step_errors_and_partials(tmp_path: Path) -> None:
    steps = [
        _step("n1", 0, error="context length exceeded"),
        _step("n1", 1, is_partial=True),
    ]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "step_errors")
    assert finding.metrics["broken_steps"] == 2
    assert any("context length exceeded" in line for line in finding.evidence)


def test_detects_context_growth(tmp_path: Path) -> None:
    steps = [_step("n1", i, input_tokens=tok) for i, tok in enumerate([5_000, 12_000, 24_000, 60_000])]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "context_growth")
    assert finding.metrics["first_step_input_tokens"] == 5_000
    assert finding.metrics["last_step_input_tokens"] == 60_000


def test_flat_context_is_not_growth(tmp_path: Path) -> None:
    steps = [_step("n1", i, input_tokens=30_000) for i in range(5)]
    _write_run(tmp_path, steps, [])
    assert "context_growth" not in _codes(_analyze(tmp_path))


def test_detects_resend_overhead(tmp_path: Path) -> None:
    steps = [_step("n1", i, input_tokens=30_000) for i in range(5)]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "resend_overhead")
    assert finding.metrics["resend_overhead_tokens"] == 120_000


def test_detects_slow_tools(tmp_path: Path) -> None:
    steps = [_step("n1", 0, tool_calls=[_call("scrape", duration_s=95.0), _call("fast", duration_s=0.2)])]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "slow_tools")
    assert finding.metrics["slow_calls"] == 1
    assert finding.severity is Severity.HIGH


def test_detects_oversized_tool_result(tmp_path: Path) -> None:
    steps = [_step("n1", 0, tool_calls=[_call("dump", result="x" * 50_000)])]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "oversized_tool_result")
    assert finding.metrics["oversized_results"] == 1


def test_detects_repeated_output(tmp_path: Path) -> None:
    steps = [_step("n1", i, llm_text="Let me try that again.") for i in range(4)]
    _write_run(tmp_path, steps, [])
    finding = next(f for f in _analyze(tmp_path).findings if f.code == "repeated_output")
    assert finding.metrics["repeats"] == 4
    assert finding.metrics["first_step"] == 0


def test_alternating_output_is_not_repetition(tmp_path: Path) -> None:
    steps = [_step("n1", i, llm_text="a" if i % 2 else "b") for i in range(8)]
    _write_run(tmp_path, steps, [])
    assert "repeated_output" not in _codes(_analyze(tmp_path))


def test_thresholds_are_configurable(tmp_path: Path) -> None:
    steps = [_step("n1", i, tool_calls=[_call("search", tool_input={"q": "same"})]) for i in range(4)]
    _write_run(tmp_path, steps, [])
    strict = Thresholds(thrash_min_repeats=10)
    assert "tool_thrash" not in _codes(_analyze(tmp_path, thresholds=strict))


# ---------------------------------------------------------------------------
# Report + rendering
# ---------------------------------------------------------------------------


def test_findings_sort_worst_first(tmp_path: Path) -> None:
    steps = [_step("n1", i, tool_calls=[_call("search", tool_input={"q": "same"})]) for i in range(4)]
    nodes = [NodeDetail(node_id="n1", success=False, error="boom")]
    _write_run(tmp_path, steps, nodes)
    report = _analyze(tmp_path)
    assert report.worst_severity is Severity.CRITICAL
    assert report.sorted_findings()[0].severity is Severity.CRITICAL


def test_renderers_produce_output_for_each_format(tmp_path: Path) -> None:
    nodes = [NodeDetail(node_id="n1", success=False, error="boom")]
    _write_run(tmp_path, [_step("n1", 0)], nodes, RunSummaryLog(run_id=_SID, status="failure"))
    report = _analyze(tmp_path)

    text = render(report, "text")
    assert "Run post-mortem" in text and "boom" in text
    assert "\033[" not in text  # not a tty under pytest

    markdown = render(report, "markdown")
    assert markdown.startswith("# Run post-mortem")
    assert "`critical`" in markdown

    payload = json.loads(render(report, "json"))
    assert payload["worst_severity"] == "critical"
    assert payload["vitals"]["run_id"] == _SID
    assert payload["findings"][0]["code"] == "node_failed"


def test_render_rejects_unknown_format(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [])
    with pytest.raises(ValueError, match="Unknown format"):
        render(_analyze(tmp_path), "yaml")


def test_clean_run_text_report_says_so(tmp_path: Path) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [NodeDetail(node_id="n1", success=True)], RunSummaryLog(run_id=_SID))
    assert "No anomalies detected." in render(_analyze(tmp_path), "text")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> int:
    import argparse

    from framework.postmortem.cli import register_postmortem_commands

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    register_postmortem_commands(sub)
    args = parser.parse_args(argv)
    return args.func(args)


def test_cli_reports_and_respects_fail_on(tmp_path: Path, capsys) -> None:
    nodes = [NodeDetail(node_id="n1", success=False, error="boom")]
    _write_run(tmp_path, [_step("n1", 0)], nodes)

    assert _run_cli(["postmortem", "--path", str(tmp_path)]) == 0
    assert "boom" in capsys.readouterr().out

    assert _run_cli(["postmortem", "--path", str(tmp_path), "--fail-on", "critical"]) == 1
    capsys.readouterr()


def test_cli_fail_on_passes_for_clean_run(tmp_path: Path, capsys) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [NodeDetail(node_id="n1", success=True)])
    assert _run_cli(["postmortem", "--path", str(tmp_path), "--fail-on", "low"]) == 0
    capsys.readouterr()


def test_cli_list_and_missing_run(tmp_path: Path, capsys) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [])
    assert _run_cli(["postmortem", "--path", str(tmp_path), "--list"]) == 0
    assert _SID in capsys.readouterr().out

    empty = tmp_path / "empty"
    empty.mkdir()
    assert _run_cli(["postmortem", "--path", str(empty)]) == 2
    assert "No runs found" in capsys.readouterr().out


def test_cli_writes_output_file(tmp_path: Path, capsys) -> None:
    _write_run(tmp_path, [_step("n1", 0)], [])
    out = tmp_path / "reports" / "run.json"
    assert _run_cli(["postmortem", "--path", str(tmp_path), "--format", "json", "-o", str(out)]) == 0
    capsys.readouterr()
    assert json.loads(out.read_text())["vitals"]["run_id"] == _SID
