"""Post-mortem analysis of agent runs recorded by the runtime logger.

Reads the three levels of runtime logs written during a run and reports what
went wrong — stuck loops, failing tools, retry storms, context blow-up — as a
ranked set of findings. Read-only: nothing here changes runtime behaviour.

    from framework.postmortem import analyze, load_run, resolve_run

    location = resolve_run(None)          # most recent run under ~/.hive
    report = analyze(load_run(location))
    print(report.worst_severity)
"""

from framework.postmortem.analyze import analyze, build_vitals
from framework.postmortem.discovery import LoadedRun, RunLocation, find_runs, load_run, resolve_run
from framework.postmortem.models import Finding, Report, RunVitals, Severity, Thresholds
from framework.postmortem.render import render, render_json, render_markdown, render_text

__all__ = [
    "Finding",
    "LoadedRun",
    "Report",
    "RunLocation",
    "RunVitals",
    "Severity",
    "Thresholds",
    "analyze",
    "build_vitals",
    "find_runs",
    "load_run",
    "render",
    "render_json",
    "render_markdown",
    "render_text",
    "resolve_run",
]
