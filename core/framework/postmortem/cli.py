"""``hive postmortem`` — diagnose a finished (or crashed) agent run."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from framework.postmortem.analyze import analyze
from framework.postmortem.discovery import find_runs, load_run, resolve_run
from framework.postmortem.models import RANK, Severity, Thresholds
from framework.postmortem.render import render

# Exit codes: 0 clean, 1 findings at/above --fail-on, 2 could not read a run.
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_NO_RUN = 2

_SEVERITY_CHOICES = [s.value for s in Severity]


def register_postmortem_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``hive postmortem`` command."""
    parser = subparsers.add_parser(
        "postmortem",
        help="Diagnose an agent run from its runtime logs",
        description=(
            "Analyse the runtime logs of a run and report what went wrong: stuck "
            "loops, failing tools, retry storms, context blow-up, and slow calls. "
            "With no RUN_ID, the most recent run is analysed."
        ),
    )
    parser.add_argument("run_id", nargs="?", help="Run/session ID (a unique prefix or substring is enough).")
    parser.add_argument("--list", action="store_true", help="List recent runs instead of analysing one.")
    parser.add_argument(
        "--path",
        type=Path,
        help="Search root for runs (default: ~/.hive). Point at an agent's storage dir to narrow the scan.",
    )
    parser.add_argument(
        "--format",
        "-f",
        choices=["text", "markdown", "json"],
        default="text",
        help="Output format (default: text).",
    )
    parser.add_argument("--output", "-o", type=Path, help="Write the report to a file instead of stdout.")
    parser.add_argument(
        "--model",
        default="",
        help="Model ID to price tokens against (default: the configured worker/default model).",
    )
    parser.add_argument(
        "--fail-on",
        choices=_SEVERITY_CHOICES,
        default="",
        help="Exit non-zero when a finding at this severity or worse is present (for CI).",
    )
    parser.add_argument("--limit", type=int, default=20, help="How many runs --list shows (default: 20).")
    parser.set_defaults(func=cmd_postmortem)


def _fmt_mtime(mtime: float) -> str:
    if not mtime:
        return "—"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")


def _list_runs(args: argparse.Namespace) -> int:
    runs = find_runs(args.path, limit=max(1, args.limit))
    if not runs:
        print(f"No runs found under {args.path or '~/.hive'}.")
        return EXIT_NO_RUN
    width = max(len(loc.run_id) for loc in runs)
    print(f"{'RUN ID'.ljust(width)}  {'LAST WRITE':16}  LOCATION")
    for loc in runs:
        print(f"{loc.run_id.ljust(width)}  {_fmt_mtime(loc.mtime):16}  {loc.logs_dir}")
    return EXIT_OK


def cmd_postmortem(args: argparse.Namespace) -> int:
    if args.list:
        return _list_runs(args)

    location = resolve_run(args.run_id, args.path)
    if location is None:
        where = args.path or "~/.hive"
        if args.run_id:
            print(f"No unique run matching '{args.run_id}' under {where}. Try 'hive postmortem --list'.")
        else:
            print(f"No runs found under {where}. Run an agent first, or pass --path.")
        return EXIT_NO_RUN

    report = analyze(load_run(location), thresholds=Thresholds(), model=args.model)
    text = render(report, args.format)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.format} post-mortem for {location.run_id} to {args.output}")
    else:
        print(text)

    if args.fail_on:
        worst = report.worst_severity
        if worst is not None and RANK[worst] >= RANK[Severity(args.fail_on)]:
            return EXIT_FINDINGS
    return EXIT_OK
