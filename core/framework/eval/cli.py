"""
CLI commands for the eval system.
Registers: hive eval run, hive eval report
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path


def register_eval_commands(subparsers) -> None:
    """Register eval subcommands onto the main hive CLI."""

    eval_parser = subparsers.add_parser("eval", help="Run eval suites against agents")
    eval_sub = eval_parser.add_subparsers(dest="eval_command", required=True)

    # hive eval run
    run_parser = eval_sub.add_parser("run", help="Run an eval suite")
    run_parser.add_argument("--suite", required=True, help="Path to eval suite YAML")
    run_parser.add_argument("--agent", required=True, help="Path to agent directory")
    run_parser.add_argument("--concurrency", type=int, default=1, help="Parallel cases (default: 1)")
    run_parser.add_argument("--output-json", help="Save JSON report to this path")
    run_parser.add_argument("--output-md", help="Save Markdown report to this path")
    run_parser.add_argument("--fail-under", type=float, default=0.0,
                            help="Exit code 1 if pass rate below this threshold (0-1)")
    run_parser.add_argument("--tags", nargs="*", help="Only run cases with these tags")
    run_parser.add_argument("--verbose", action="store_true", help="Print case-by-case output")
    run_parser.set_defaults(func=_cmd_eval_run)

    # hive eval report
    report_parser = eval_sub.add_parser("report", help="Print a saved JSON report")
    report_parser.add_argument("report_path", help="Path to JSON report file")
    report_parser.set_defaults(func=_cmd_eval_report)


def _cmd_eval_run(args) -> int:
    from framework.eval.case import EvalSuite
    from framework.eval.runner import EvalRunner
    from framework.eval.scorer import ScorerConfig

    suite = EvalSuite.from_yaml(args.suite)
    suite = suite.model_copy(update={"agent_path": args.agent})

    if args.tags:
        suite = suite.filter_by_tags(args.tags)
        if len(suite) == 0:
            print(f"No cases matched tags: {args.tags}")
            return 1

    runner = EvalRunner(
        agent_path=args.agent,
        scorer_config=ScorerConfig(),
        concurrency=args.concurrency,
        verbose=args.verbose,
    )

    report = asyncio.run(runner.run(suite))
    report.print_summary()

    if args.output_json:
        report.to_json(args.output_json)
        print(f"JSON report saved: {args.output_json}")

    if args.output_md:
        report.to_markdown(args.output_md)
        print(f"Markdown report saved: {args.output_md}")

    if args.fail_under > 0 and report.pass_rate < args.fail_under:
        print(f"FAIL: pass rate {report.pass_rate:.1%} below threshold {args.fail_under:.1%}")
        return 1

    return 0 if report.all_passed else 1


def _cmd_eval_report(args) -> int:
    import json
    from framework.eval.report import EvalReport

    path = Path(args.report_path)
    if not path.exists():
        print(f"Report not found: {path}")
        return 1

    data = json.loads(path.read_text())
    report = EvalReport.model_validate(data)
    report.print_summary()
    return 0
