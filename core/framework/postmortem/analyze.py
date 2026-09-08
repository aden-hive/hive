"""Build a post-mortem ``Report`` from a loaded run."""

from __future__ import annotations

from framework.postmortem.cost import estimate_cost, resolve_model
from framework.postmortem.detectors import DETECTORS
from framework.postmortem.discovery import LoadedRun
from framework.postmortem.models import Report, RunVitals, Thresholds


def build_vitals(run: LoadedRun, model: str = "") -> RunVitals:
    """Roll the three log levels up into headline numbers.

    L1 values win where present, since ``end_run()`` aggregates them; a run
    that crashed has no L1, so everything falls back to L2/L3.
    """
    summary = run.summary
    steps = run.steps
    nodes = run.nodes

    step_input = sum(s.input_tokens for s in steps)
    step_output = sum(s.output_tokens for s in steps)
    tool_calls = sum(len(s.tool_calls) for s in steps)
    tool_errors = sum(1 for s in steps for c in s.tool_calls if c.is_error)

    # Pick one token source and use it for both directions: mixing an L1 input
    # total with an L3 output total would produce an incoherent pair. L1 wins
    # only when it actually recorded tokens.
    l1_tokens = bool(summary and (summary.total_input_tokens or summary.total_output_tokens))
    input_tokens = summary.total_input_tokens if l1_tokens else step_input
    output_tokens = summary.total_output_tokens if l1_tokens else step_output

    vitals = RunVitals(
        run_id=run.location.run_id,
        agent_id=summary.agent_id if summary else "",
        goal_id=summary.goal_id if summary else "",
        status=summary.status if summary else "incomplete",
        started_at=summary.started_at if summary else "",
        duration_ms=summary.duration_ms if summary else sum(n.latency_ms for n in nodes),
        nodes_executed=summary.total_nodes_executed if summary else len(nodes),
        steps=len(steps),
        tool_calls=tool_calls,
        tool_errors=tool_errors,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        resend_overhead_tokens=max(0, step_input - max((s.input_tokens for s in steps), default=0)),
    )

    model_id, source = resolve_model(model)
    vitals.model = model_id
    cost = estimate_cost(model_id, vitals.input_tokens, vitals.output_tokens)
    if cost is not None:
        vitals.cost_usd = cost
        vitals.cost_source = source
    return vitals


def analyze(run: LoadedRun, thresholds: Thresholds | None = None, model: str = "") -> Report:
    """Run every detector over *run* and return a ranked report."""
    t = thresholds or Thresholds()
    report = Report(vitals=build_vitals(run, model=model))

    if run.summary is None:
        report.warnings.append(
            "No summary.json for this run — it never reached end_run(). Totals are derived from step logs."
        )
    if not run.steps:
        report.warnings.append("No tool_logs.jsonl steps found; step-level detectors were skipped.")
    if not run.nodes:
        report.warnings.append("No details.jsonl entries found; node-level detectors were skipped.")

    for detector in DETECTORS:
        report.findings.extend(detector(run.nodes, run.steps, t))
    return report
