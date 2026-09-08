"""Rendering a post-mortem ``Report`` for terminals, files, and machines."""

from __future__ import annotations

import json
import os
import sys

from framework.postmortem.models import Report, Severity

_SEVERITY_COLOR = {
    Severity.CRITICAL: "\033[1;31m",
    Severity.HIGH: "\033[31m",
    Severity.MEDIUM: "\033[33m",
    Severity.LOW: "\033[36m",
    Severity.INFO: "\033[90m",
}
_BOLD = "\033[1m"
_DIM = "\033[90m"
_RESET = "\033[0m"

_SEVERITY_MARK = {
    Severity.CRITICAL: "!!",
    Severity.HIGH: " !",
    Severity.MEDIUM: " ~",
    Severity.LOW: " -",
    Severity.INFO: " .",
}


def use_color(stream=None) -> bool:
    """Colour only for real terminals, and never when NO_COLOR is set."""
    if os.environ.get("NO_COLOR"):
        return False
    target = stream if stream is not None else sys.stdout
    return bool(getattr(target, "isatty", lambda: False)())


def _fmt_duration(ms: int) -> str:
    if ms <= 0:
        return "—"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {seconds:04.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes:02d}m"


def _vitals_rows(report: Report) -> list[tuple[str, str]]:
    v = report.vitals
    rows = [
        ("Run", v.run_id),
        ("Agent", v.agent_id or "—"),
        ("Status", v.status or "—"),
        ("Started", v.started_at or "—"),
        ("Duration", _fmt_duration(v.duration_ms)),
        ("Nodes / steps", f"{v.nodes_executed} / {v.steps}"),
        (
            "Tool calls",
            f"{v.tool_calls} ({v.tool_errors} failed, {v.tool_error_rate:.0%})" if v.tool_calls else "0",
        ),
        (
            "Tokens",
            f"{v.total_tokens:,} ({v.input_tokens:,} in / {v.output_tokens:,} out)",
        ),
    ]
    if v.resend_overhead_tokens:
        share = v.resend_overhead_tokens / v.input_tokens if v.input_tokens else 0.0
        rows.append(("Re-sent context", f"{v.resend_overhead_tokens:,} tokens ({share:.0%} of input)"))
    if v.cost_usd is not None:
        rows.append(("Est. cost", f"${v.cost_usd:,.4f}  ({v.model}, via {v.cost_source})"))
    elif v.model:
        rows.append(("Est. cost", f"unpriced — no catalog entry for '{v.model}'"))
    return rows


def render_text(report: Report, color: bool | None = None) -> str:
    """Human-readable terminal report."""
    tint = use_color() if color is None else color

    def c(text: str, code: str) -> str:
        return f"{code}{text}{_RESET}" if tint else text

    out: list[str] = []
    out.append(c("Run post-mortem", _BOLD))
    out.append("─" * 62)

    rows = _vitals_rows(report)
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        out.append(f"  {c(label.ljust(width), _DIM)}  {value}")

    for warning in report.warnings:
        out.append(f"  {c('note', _DIM)}  {warning}")

    findings = report.sorted_findings()
    out.append("")
    if not findings:
        out.append(c("  No anomalies detected.", _SEVERITY_COLOR[Severity.LOW]))
        out.append("")
        return "\n".join(out)

    counts: dict[Severity, int] = {}
    for finding in findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1
    tally = ", ".join(f"{n} {sev.value}" for sev, n in sorted(counts.items(), key=lambda kv: kv[0].value))
    out.append(c(f"Findings ({len(findings)}: {tally})", _BOLD))
    out.append("─" * 62)

    for finding in findings:
        mark = c(_SEVERITY_MARK[finding.severity], _SEVERITY_COLOR[finding.severity])
        out.append(f"{mark} {c(finding.title, _BOLD)}  {c('[' + finding.code + ']', _DIM)}")
        out.append(f"     {finding.detail}")
        for line in finding.evidence:
            out.append(f"     {c('│', _DIM)} {line}")
        if finding.suggestion:
            out.append(f"     {c('→ ' + finding.suggestion, _DIM)}")
        out.append("")
    return "\n".join(out)


def render_markdown(report: Report) -> str:
    """Markdown report, for pasting into an issue or a PR comment."""
    v = report.vitals
    out = [f"# Run post-mortem — `{v.run_id}`", ""]
    for label, value in _vitals_rows(report):
        out.append(f"- **{label}:** {value}")
    if report.warnings:
        out.append("")
        for warning in report.warnings:
            out.append(f"> {warning}")

    findings = report.sorted_findings()
    out.append("")
    if not findings:
        out.append("No anomalies detected.")
        return "\n".join(out) + "\n"

    out.append(f"## Findings ({len(findings)})")
    for finding in findings:
        out.append("")
        out.append(f"### `{finding.severity.value}` {finding.title}")
        out.append("")
        out.append(finding.detail)
        if finding.evidence:
            out.append("")
            out.append("```")
            out.extend(finding.evidence)
            out.append("```")
        if finding.suggestion:
            out.append("")
            out.append(f"**Suggested fix:** {finding.suggestion}")
    return "\n".join(out) + "\n"


def render_json(report: Report) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)


RENDERERS = {"text": render_text, "markdown": render_markdown, "json": render_json}


def render(report: Report, fmt: str = "text") -> str:
    renderer = RENDERERS.get(fmt)
    if renderer is None:
        raise ValueError(f"Unknown format '{fmt}'. Choose one of: {', '.join(RENDERERS)}")
    return renderer(report)
