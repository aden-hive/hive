"""
CLI commands for goal-based testing.

Provides commands:
- test-run: Run tests for an agent
- test-debug: Debug a failed test
- test-list: List tests for an agent
- test-stats: Show test statistics for an agent
"""

import argparse
import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def _check_pytest_available() -> bool:
    """Check if pytest is available as a runnable command.

    Returns True if pytest is found, otherwise prints an error message
    with install instructions and returns False.
    """
    if shutil.which("pytest") is None:
        print(
            "Error: pytest is not installed or not on PATH.\n"
            "Hive's testing commands require pytest at runtime.\n"
            "Install it with:\n"
            "\n"
            "  pip install 'framework[testing]'\n"
            "\n"
            "or if using uv:\n"
            "\n"
            "  uv pip install 'framework[testing]'",
            file=sys.stderr,
        )
        return False
    return True


def register_testing_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register testing CLI commands."""

    # test-run
    run_parser = subparsers.add_parser(
        "test-run",
        help="Run tests for an agent",
    )
    run_parser.add_argument(
        "agent_path",
        help="Path to agent export folder",
    )
    run_parser.add_argument(
        "--goal",
        "-g",
        required=True,
        help="Goal ID to run tests for",
    )
    run_parser.add_argument(
        "--parallel",
        "-p",
        type=int,
        default=-1,
        help="Number of parallel workers (-1 for auto, 0 for sequential)",
    )
    run_parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failure",
    )
    run_parser.add_argument(
        "--type",
        choices=["constraint", "success", "edge_case", "all"],
        default="all",
        help="Type of tests to run",
    )
    run_parser.add_argument(
        "--auto-evolve",
        action="store_true",
        help=(
            "If tests fail, load recent FailureReports from the agent's "
            "storage and dispatch them through EvolutionTrigger to a "
            "coding agent for proposed graph changes."
        ),
    )
    run_parser.add_argument(
        "--storage-path",
        default=None,
        help=(
            "Storage root containing failure_reports/ "
            "(defaults to <agent_path>/.runtime). Used with --auto-evolve."
        ),
    )
    run_parser.add_argument(
        "--max-reports",
        type=int,
        default=1,
        help="Max failure reports to evolve (newest first). Default: 1",
    )
    run_parser.add_argument(
        "--evolve-threshold",
        type=float,
        default=None,
        help=(
            "Failure-rate threshold (0.0-1.0). When set with --auto-evolve, "
            "evolution only fires if recent failure rate over --evolve-window "
            "meets or exceeds this value. Without it, --auto-evolve fires on "
            "any pytest failure."
        ),
    )
    run_parser.add_argument(
        "--evolve-window",
        type=int,
        default=4,
        help=(
            "Number of recent failure reports to consider when computing "
            "the failure rate for --evolve-threshold. Default: 4"
        ),
    )
    run_parser.set_defaults(func=cmd_test_run)

    # test-debug
    debug_parser = subparsers.add_parser(
        "test-debug",
        help="Debug a failed test by re-running with verbose output",
    )
    debug_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    debug_parser.add_argument(
        "test_name",
        help="Name of the test function (e.g., test_constraint_foo)",
    )
    debug_parser.add_argument(
        "--goal",
        "-g",
        default="",
        help="Goal ID (optional, for display only)",
    )
    debug_parser.set_defaults(func=cmd_test_debug)

    # test-list
    list_parser = subparsers.add_parser(
        "test-list",
        help="List tests for an agent by scanning test files",
    )
    list_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    list_parser.add_argument(
        "--type",
        choices=["constraint", "success", "edge_case", "all"],
        default="all",
        help="Filter by test type",
    )
    list_parser.set_defaults(func=cmd_test_list)

    # test-stats
    stats_parser = subparsers.add_parser(
        "test-stats",
        help="Show test statistics for an agent",
    )
    stats_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    stats_parser.set_defaults(func=cmd_test_stats)

    # eval-report
    eval_parser = subparsers.add_parser(
        "eval-report",
        help="Print formatted summary of the most recent FailureReport on disk",
    )
    eval_parser.add_argument(
        "agent_path",
        help="Path to agent export folder",
    )
    eval_parser.add_argument(
        "--storage-path",
        default=None,
        help="Storage root containing failure_reports/ (default: <agent_path>/.runtime)",
    )
    eval_parser.add_argument(
        "--goal",
        "-g",
        default=None,
        help="Filter to a specific goal_id (default: latest report regardless of goal)",
    )
    eval_parser.add_argument(
        "--all",
        action="store_true",
        help="Print all reports (newest first) instead of only the latest",
    )
    eval_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit raw JSON instead of formatted text",
    )
    eval_parser.set_defaults(func=cmd_eval_report)

    # evolve (manual trigger)
    evolve_parser = subparsers.add_parser(
        "evolve",
        help=(
            "Manually dispatch FailureReports to a coding agent and apply "
            "the resulting EvolutionPlan to the goal (Phase 3 trigger)."
        ),
    )
    evolve_parser.add_argument("agent_path", help="Path to agent export folder")
    evolve_parser.add_argument(
        "--storage-path",
        default=None,
        help="Storage root containing failure_reports/ (default: <agent_path>/.runtime)",
    )
    evolve_parser.add_argument(
        "--goal",
        "-g",
        default=None,
        help="Restrict to a specific goal_id",
    )
    evolve_parser.add_argument(
        "--max-reports",
        type=int,
        default=1,
        help="Max reports to dispatch (newest first). Default: 1",
    )
    evolve_parser.add_argument(
        "--goal-file",
        default=None,
        help=(
            "Path to a goal JSON file to mutate in-place (parent_version, "
            "version, evolution_reason). If omitted, the plan is printed only."
        ),
    )
    evolve_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the proposed plan without writing the goal file",
    )
    evolve_parser.add_argument(
        "--rerun-tests",
        action="store_true",
        help=(
            "After applying the evolution plan, re-run the agent's test "
            "suite to validate the change (Phase 4 feedback loop)."
        ),
    )
    evolve_parser.set_defaults(func=cmd_evolve)

    # eval-trends
    trends_parser = subparsers.add_parser(
        "eval-trends",
        help="Emit per-version evaluation trends from stored failure reports",
    )
    trends_parser.add_argument("agent_path", help="Path to agent export folder")
    trends_parser.add_argument(
        "--storage-path",
        default=None,
        help="Storage root containing failure_reports/ (default: <agent_path>/.runtime)",
    )
    trends_parser.add_argument(
        "--goal",
        "-g",
        default=None,
        help="Restrict to a specific goal_id",
    )
    trends_parser.add_argument(
        "--format",
        choices=["json", "table"],
        default="table",
        help="Output format. JSON is suitable for dashboard ingestion.",
    )
    trends_parser.set_defaults(func=cmd_eval_trends)


def cmd_test_run(args: argparse.Namespace) -> int:
    """Run tests for an agent using pytest subprocess."""
    if not _check_pytest_available():
        return 1

    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}")
        print(
            "Hint: Use generate_constraint_tests/generate_success_tests MCP tools, "
            "then write tests with Write tool"
        )
        return 1

    # Build pytest command
    cmd = ["pytest"]

    # Add test path(s) based on type filter
    if args.type == "all":
        cmd.append(str(tests_dir))
    else:
        type_to_file = {
            "constraint": "test_constraints.py",
            "success": "test_success_criteria.py",
            "edge_case": "test_edge_cases.py",
        }
        if args.type in type_to_file:
            test_file = tests_dir / type_to_file[args.type]
            if test_file.exists():
                cmd.append(str(test_file))
            else:
                print(f"Error: Test file not found: {test_file}")
                return 1

    # Add flags
    cmd.append("-v")  # Always verbose for CLI
    if args.fail_fast:
        cmd.append("-x")

    # Parallel execution
    if args.parallel > 0:
        cmd.extend(["-n", str(args.parallel)])
    elif args.parallel == -1:
        cmd.extend(["-n", "auto"])

    cmd.append("--tb=short")

    # Set PYTHONPATH to project root
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    # Find project root (parent of core/)
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

    print(f"Running: {' '.join(cmd)}\n")

    # Run pytest
    try:
        result = subprocess.run(
            cmd,
            encoding="utf-8",
            env=env,
            timeout=600,  # 10 minute timeout
        )
    except subprocess.TimeoutExpired:
        print("Error: Test execution timed out after 10 minutes")
        return 1
    except Exception as e:
        print(f"Error: Failed to run pytest: {e}")
        return 1

    # Goal-criteria evaluation alongside pytest pass/fail (AC #4 of #3900).
    # We load the agent's goal and report its current criterion.met status
    # plus any FailureReports generated during this run, so test-run is no
    # longer just pytest pass/fail.
    _print_goal_criteria_status(agent_path, args.storage_path)

    if result.returncode != 0 and getattr(args, "auto_evolve", False):
        # Optional failure-rate gating: only evolve when recent failure
        # pressure crosses --evolve-threshold over --evolve-window reports.
        threshold = getattr(args, "evolve_threshold", None)
        if threshold is not None:
            from framework.runtime.evolution_trigger import compute_failure_rate

            storage_root = (
                Path(args.storage_path)
                if args.storage_path
                else agent_path / ".runtime"
            )
            reports_dir = storage_root / "failure_reports"
            rate, count = compute_failure_rate(reports_dir, args.evolve_window)
            print(
                f"\n[auto-evolve] failure rate {rate:.2f} "
                f"({count}/{args.evolve_window} recent reports), "
                f"threshold={threshold:.2f}"
            )
            if rate < threshold:
                print("[auto-evolve] below threshold - skipping evolution")
                return result.returncode

        _run_auto_evolve(
            agent_path=agent_path,
            storage_path=args.storage_path,
            max_reports=args.max_reports,
        )

    return result.returncode


def _print_goal_criteria_status(
    agent_path: Path,
    storage_path: str | None,
) -> None:
    """Print goal success-criteria status after a pytest run.

    Loads the agent module to get its Goal, then reports each criterion's
    pass/fail. Criterion state is sourced from the most recent FailureReport
    on disk for the goal (which is generated by OutcomeAggregator during
    real agent execution). If no FailureReport exists, all criteria are
    assumed met.

    This makes ``hive test-run`` integrate with goal-criteria evaluation
    rather than reporting only pytest pass/fail (issue #3900 AC #4).
    """
    try:
        from framework.runner.runner import AgentRunner  # noqa: F401
    except Exception:
        pass

    # Load the goal directly from the agent module without bringing up the
    # full runner. We import agent.py / __init__.py and grab `goal`.
    goal = _load_agent_goal(agent_path)
    if goal is None:
        return

    storage_root = (
        Path(storage_path) if storage_path else agent_path / ".runtime"
    )
    reports_dir = storage_root / "failure_reports"

    latest_unmet_ids: set[str] = set()
    latest_report = None
    try:
        from framework.runtime.evolution_trigger import load_failure_reports

        reports = [r for r in load_failure_reports(reports_dir) if r.goal_id == goal.id]
        if reports:
            latest_report = reports[0]
            latest_unmet_ids = {c.criterion_id for c in latest_report.unmet_criteria}
    except Exception as e:
        print(f"\n[criteria] could not load failure reports: {e}")

    print("\n=== Goal Criteria Status ===")
    print(f"goal: {goal.name} ({goal.id})")
    if not goal.success_criteria:
        print("  (no success_criteria defined)")
        return

    met_count = 0
    for c in goal.success_criteria:
        met = c.id not in latest_unmet_ids
        if met:
            met_count += 1
        marker = "PASS" if met else "FAIL"
        print(f"  [{marker}] {c.id}: {c.description} (metric={c.metric})")

    total = len(goal.success_criteria)
    print(f"  -> {met_count}/{total} criteria met")
    if latest_report and latest_report.violated_constraints:
        print(
            f"  -> {len(latest_report.violated_constraints)} "
            "constraint violation(s)"
        )
    if latest_report and latest_report.error_category:
        print(f"  -> error_category: {latest_report.error_category}")


def _load_agent_goal(agent_path: Path) -> Any:
    """Best-effort import of an agent's Goal from agent.py / __init__.py.

    Real-world templates use relative imports (``from .config import ...``)
    so we must import the agent as a *package*, not as a standalone file.
    Strategy: add the agent's parent directory to sys.path and do a normal
    package import (e.g. ``import competitive_intel_agent``), then read
    ``agent.goal`` or ``package.goal``.
    """
    import importlib
    import sys

    if not agent_path.exists():
        return None

    # Project root must be importable for ``framework.*`` references inside
    # the agent module.
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    parent = str(agent_path.parent.resolve())
    if parent not in sys.path:
        sys.path.insert(0, parent)

    package_name = agent_path.name
    try:
        # Import the package itself first — this evaluates __init__.py and
        # establishes the package context required by relative imports.
        pkg = importlib.import_module(package_name)
        goal = getattr(pkg, "goal", None)
        if goal is not None:
            return goal

        # If __init__.py doesn't re-export goal, try the agent submodule.
        try:
            agent_mod = importlib.import_module(f"{package_name}.agent")
            return getattr(agent_mod, "goal", None)
        except ModuleNotFoundError:
            return None
    except Exception as e:
        print(f"\n[criteria] could not load agent goal for {agent_path.name}: {e}")
        return None


def _run_auto_evolve(
    agent_path: Path,
    storage_path: str | None,
    max_reports: int,
) -> None:
    """Load recent FailureReports and dispatch them via EvolutionTrigger.

    Best-effort: failures here never change the test exit code, they only
    print diagnostics.
    """
    import asyncio

    try:
        from framework.llm.litellm import LiteLLMProvider
        from framework.runtime.evolution_trigger import (
            EvolutionTrigger,
            load_failure_reports,
        )
    except Exception as e:
        print(f"\n[auto-evolve] import failed: {e}")
        return

    storage_root = Path(storage_path) if storage_path else agent_path / ".runtime"
    reports_dir = storage_root / "failure_reports"

    print(f"\n[auto-evolve] scanning {reports_dir}")
    reports = load_failure_reports(reports_dir)
    if not reports:
        print("[auto-evolve] no failure reports found - nothing to evolve")
        return

    reports = reports[: max(1, max_reports)]
    print(f"[auto-evolve] dispatching {len(reports)} failure report(s)")

    model = os.environ.get("HIVE_EVOLVE_MODEL") or os.environ.get(
        "HIVE_DEFAULT_MODEL", "gpt-4o-mini"
    )
    try:
        llm = LiteLLMProvider(model=model)
    except Exception as e:
        print(f"[auto-evolve] could not initialize LLM provider ({model}): {e}")
        return
    print(f"[auto-evolve] using model: {model}")

    trigger = EvolutionTrigger(llm_provider=llm)

    async def _run() -> None:
        for report in reports:
            print(f"\n[auto-evolve] goal={report.goal_name} ({report.goal_id})")
            plan = await trigger.trigger(report)
            print(f"  diagnosis: {plan.diagnosis}")
            print(f"  confidence: {plan.confidence}")
            print(f"  needs_human_review: {plan.needs_human_review}")
            if plan.proposed_changes:
                print(f"  proposed changes ({len(plan.proposed_changes)}):")
                for i, change in enumerate(plan.proposed_changes, 1):
                    print(
                        f"    {i}. [{change.change_type}] "
                        f"{change.target}={change.target_id}"
                    )
                    print(f"       rationale: {change.rationale}")
                    print(f"       details: {change.details}")
            else:
                print("  (no concrete changes proposed)")

    try:
        asyncio.run(_run())
    except Exception as e:
        print(f"[auto-evolve] dispatch failed: {e}")


def cmd_evolve(args: argparse.Namespace) -> int:
    """Manually dispatch failure reports through EvolutionTrigger and apply
    the resulting plan to a goal file (Phase 3 manual trigger).
    """
    import asyncio
    import json as _json

    try:
        from framework.graph.goal import Goal
        from framework.llm.litellm import LiteLLMProvider
        from framework.runtime.evolution_trigger import (
            EvolutionTrigger,
            apply_plan,
            load_failure_reports,
        )
    except Exception as e:
        print(f"[evolve] import failed: {e}")
        return 1

    agent_path = Path(args.agent_path)
    storage_root = (
        Path(args.storage_path) if args.storage_path else agent_path / ".runtime"
    )
    reports_dir = storage_root / "failure_reports"

    reports = load_failure_reports(reports_dir)
    if args.goal:
        reports = [r for r in reports if r.goal_id == args.goal]
    if not reports:
        print(f"[evolve] no failure reports found in {reports_dir}")
        return 1
    reports = reports[: max(1, args.max_reports)]

    model = os.environ.get("HIVE_EVOLVE_MODEL") or os.environ.get(
        "HIVE_DEFAULT_MODEL", "gpt-4o-mini"
    )
    try:
        llm = LiteLLMProvider(model=model)
    except Exception as e:
        print(f"[evolve] could not initialize LLM provider ({model}): {e}")
        return 1
    print(f"[evolve] using model: {model}")

    # Optionally load the goal to mutate
    goal: Goal | None = None
    goal_path: Path | None = None
    if args.goal_file:
        goal_path = Path(args.goal_file)
        try:
            goal = Goal(**_json.loads(goal_path.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[evolve] failed to load goal file {goal_path}: {e}")
            return 1

    trigger = EvolutionTrigger(llm_provider=llm)

    async def _run() -> int:
        nonlocal goal
        for report in reports:
            print(f"\n[evolve] dispatching goal={report.goal_name} ({report.goal_id})")
            plan = await trigger.trigger(report)
            print(f"  diagnosis: {plan.diagnosis}")
            print(f"  confidence: {plan.confidence}")
            if plan.proposed_changes:
                print(f"  proposed changes ({len(plan.proposed_changes)}):")
                for i, c in enumerate(plan.proposed_changes, 1):
                    print(f"    {i}. [{c.change_type}] {c.target}={c.target_id}")
                    print(f"       rationale: {c.rationale}")
                    print(f"       details: {c.details}")
            else:
                print("  (no concrete changes proposed)")

            if goal is not None and not args.dry_run:
                old_version = goal.version
                apply_plan(goal, plan, report)
                print(
                    f"  applied: {old_version} -> {goal.version} "
                    f"(parent={goal.parent_version})"
                )
        return 0

    try:
        rc = asyncio.run(_run())
    except Exception as e:
        print(f"[evolve] dispatch failed: {e}")
        return 1

    if goal is not None and goal_path is not None and not args.dry_run:
        try:
            goal_path.write_text(
                goal.model_dump_json(indent=2), encoding="utf-8"
            )
            print(f"\n[evolve] wrote updated goal to {goal_path}")
        except Exception as e:
            print(f"[evolve] failed to write goal file: {e}")
            return 1

    # Phase 4 feedback loop: re-run tests after the evolution applies, so
    # the developer immediately sees whether the change improved the suite.
    if getattr(args, "rerun_tests", False):
        print("\n[evolve] re-running tests to validate evolution...")
        rerun_args = argparse.Namespace(
            agent_path=str(agent_path),
            type="all",
            fail_fast=False,
            parallel=0,
            auto_evolve=False,
            storage_path=None,
            max_reports=1,
            evolve_threshold=None,
            evolve_window=4,
        )
        rerun_rc = cmd_test_run(rerun_args)
        print(
            f"[evolve] post-evolution test exit code: {rerun_rc} "
            f"({'PASS' if rerun_rc == 0 else 'FAIL'})"
        )
        # Surface the post-evolution status but don't override the dispatch rc
        if rc == 0 and rerun_rc != 0:
            return rerun_rc

    return rc


def cmd_eval_trends(args: argparse.Namespace) -> int:
    """Emit per-goal-version eval trends from stored failure reports.

    Bins reports by ``goal_id`` and report ``version`` and reports
    aggregate metrics suitable for dashboard time-series ingestion.
    """
    import json as _json

    from framework.runtime.evolution_trigger import load_failure_reports

    agent_path = Path(args.agent_path)
    storage_root = (
        Path(args.storage_path) if args.storage_path else agent_path / ".runtime"
    )
    reports_dir = storage_root / "failure_reports"

    reports = load_failure_reports(reports_dir)
    if args.goal:
        reports = [r for r in reports if r.goal_id == args.goal]

    if not reports:
        print(f"No failure reports found in {reports_dir}")
        return 0

    # Sort oldest -> newest so trend lines read left-to-right
    reports = list(reversed(reports))

    rows: list[dict[str, Any]] = []
    for r in reports:
        total_outcomes = r.successful_outcomes + r.failed_outcomes
        success_rate = (
            r.successful_outcomes / total_outcomes if total_outcomes else 0.0
        )
        rows.append(
            {
                "goal_id": r.goal_id,
                "goal_name": r.goal_name,
                "version": r.version,
                "timestamp": r.timestamp.isoformat(),
                "unmet_criteria": len(r.unmet_criteria),
                "violated_constraints": len(r.violated_constraints),
                "total_decisions": r.total_decisions,
                "successful_outcomes": r.successful_outcomes,
                "failed_outcomes": r.failed_outcomes,
                "success_rate": round(success_rate, 4),
                "node_ids": list(r.node_ids),
                "edge_ids": list(r.edge_ids),
            }
        )

    if args.format == "json":
        print(_json.dumps(rows, indent=2, default=str))
        return 0

    # Compact table view
    header = (
        f"{'goal_id':<20} {'v':<4} {'unmet':<6} {'viol':<5} "
        f"{'success':<8} {'timestamp':<25}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        print(
            f"{row['goal_id'][:20]:<20} "
            f"{row['version']:<4} "
            f"{row['unmet_criteria']:<6} "
            f"{row['violated_constraints']:<5} "
            f"{row['success_rate']:<8.2f} "
            f"{row['timestamp']:<25}"
        )
    return 0


def cmd_eval_report(args: argparse.Namespace) -> int:
    """Print a formatted summary of the most recent FailureReport(s) on disk."""
    from framework.runtime.evolution_trigger import load_failure_reports

    agent_path = Path(args.agent_path)
    storage_root = (
        Path(args.storage_path) if args.storage_path else agent_path / ".runtime"
    )
    reports_dir = storage_root / "failure_reports"

    reports = load_failure_reports(reports_dir)
    if args.goal:
        reports = [r for r in reports if r.goal_id == args.goal]

    if not reports:
        where = f" for goal '{args.goal}'" if args.goal else ""
        print(f"No failure reports found in {reports_dir}{where}")
        return 0

    if not args.all:
        reports = reports[:1]

    if args.json:
        import json as _json

        out = [r.model_dump(mode="json") for r in reports]
        print(_json.dumps(out, indent=2, default=str))
        return 0

    for i, report in enumerate(reports):
        if i > 0:
            print()
        _print_failure_report(report)

    return 0


def _print_failure_report(report: Any) -> None:  # type: ignore[valid-type]
    """Pretty-print a single FailureReport to stdout."""
    bar = "=" * 70
    print(bar)
    print(f"FAILURE REPORT  goal={report.goal_name} ({report.goal_id})")
    print(f"  timestamp:  {report.timestamp}")
    print(
        f"  decisions:  total={report.total_decisions} "
        f"successful={report.successful_outcomes} failed={report.failed_outcomes}"
    )
    print(bar)

    # Criteria status
    print("\nUNMET SUCCESS CRITERIA:")
    if not report.unmet_criteria:
        print("  (none)")
    else:
        for c in report.unmet_criteria:
            print(f"  [X] {c.criterion_id}  weight={c.weight}")
            print(f"      desc:   {c.description}")
            print(f"      metric: {c.metric}")
            print(f"      target: {c.target!r}")

    # Constraint violations
    print("\nVIOLATED CONSTRAINTS:")
    if not report.violated_constraints:
        print("  (none)")
    else:
        for v in report.violated_constraints:
            tag = v.constraint_type.upper()
            print(f"  [{tag}] {v.constraint_id}")
            print(f"      desc:    {v.description}")
            print(f"      details: {v.violation_details}")
            if getattr(v, "stream_id", None):
                print(f"      stream:  {v.stream_id}")
            if getattr(v, "execution_id", None):
                print(f"      exec:    {v.execution_id}")

    # Responsible nodes
    print("\nRESPONSIBLE NODES (from execution trace):")
    if not report.node_ids:
        print("  (none)")
    else:
        for node_id in report.node_ids:
            print(f"  - {node_id}")

    # Summary
    print("\nSUMMARY:")
    print(f"  {report.summary or '(no summary)'}")

    # Phase 4: lightweight, deterministic evolution recommendations derived
    # straight from the report so developers see actionable next steps
    # without needing to run an LLM. cmd_evolve still does the real work.
    print("\nEVOLUTION RECOMMENDATIONS:")
    recs: list[str] = []
    for c in report.unmet_criteria:
        recs.append(
            f"- Strengthen criterion '{c.criterion_id}' "
            f"(metric={c.metric}, target={c.target!r}): "
            f"adjust prompts or graph nodes that produce its output."
        )
    for v in report.violated_constraints:
        recs.append(
            f"- Add a guard for constraint '{v.constraint_id}' "
            f"({v.constraint_type}): {v.description}"
        )
    if getattr(report, "edge_ids", None):
        recs.append(
            f"- Inspect failing edges: {', '.join(report.edge_ids)}"
        )
    if not recs:
        print("  (no specific recommendations)")
    else:
        for line in recs:
            print(f"  {line}")
    print(bar)


def cmd_test_debug(args: argparse.Namespace) -> int:
    """Debug a failed test by re-running with verbose output."""
    if not _check_pytest_available():
        return 1

    agent_path = Path(args.agent_path)
    test_name = args.test_name
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"Error: Tests directory not found: {tests_dir}")
        return 1

    # Find which file contains the test
    test_file = None
    for py_file in tests_dir.glob("test_*.py"):
        content = py_file.read_text(encoding="utf-8")
        if f"def {test_name}" in content or f"async def {test_name}" in content:
            test_file = py_file
            break

    if not test_file:
        print(f"Error: Test '{test_name}' not found in {tests_dir}")
        print("Hint: Use test-list to see available tests")
        return 1

    # Run specific test with verbose output
    cmd = [
        "pytest",
        f"{test_file}::{test_name}",
        "-vvs",  # Very verbose with stdout
        "--tb=long",  # Full traceback
    ]

    # Set PYTHONPATH to project root
    env = os.environ.copy()
    pythonpath = env.get("PYTHONPATH", "")
    project_root = Path(__file__).parent.parent.parent.parent.resolve()
    env["PYTHONPATH"] = f"{project_root}:{pythonpath}"

    print(f"Running: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            encoding="utf-8",
            env=env,
            timeout=120,  # 2 minute timeout for single test
        )
    except subprocess.TimeoutExpired:
        print("Error: Test execution timed out after 2 minutes")
        return 1
    except Exception as e:
        print(f"Error: Failed to run pytest: {e}")
        return 1

    return result.returncode


def _scan_test_files(tests_dir: Path) -> list[dict]:
    """Scan test files and extract test functions using AST parsing."""
    tests = []

    for test_file in sorted(tests_dir.glob("test_*.py")):
        try:
            content = test_file.read_text(encoding="utf-8")
            tree = ast.parse(content)

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if node.name.startswith("test_"):
                        # Determine test type from filename
                        if "constraint" in test_file.name:
                            test_type = "constraint"
                        elif "success" in test_file.name:
                            test_type = "success"
                        elif "edge" in test_file.name:
                            test_type = "edge_case"
                        else:
                            test_type = "unknown"

                        docstring = ast.get_docstring(node) or ""

                        tests.append(
                            {
                                "test_name": node.name,
                                "file": test_file.name,
                                "line": node.lineno,
                                "test_type": test_type,
                                "is_async": isinstance(node, ast.AsyncFunctionDef),
                                "description": docstring[:100] if docstring else None,
                            }
                        )
        except SyntaxError as e:
            print(f"  Warning: Syntax error in {test_file.name}: {e}")
        except Exception as e:
            print(f"  Warning: Error parsing {test_file.name}: {e}")

    return tests


def cmd_test_list(args: argparse.Namespace) -> int:
    """List tests for an agent by scanning pytest files."""
    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"No tests directory found at: {tests_dir}")
        print(
            "Hint: Generate tests using the MCP generate_constraint_tests "
            "or generate_success_tests tools"
        )
        return 0

    tests = _scan_test_files(tests_dir)

    # Filter by type if specified
    if args.type != "all":
        tests = [t for t in tests if t["test_type"] == args.type]

    if not tests:
        print(f"No tests found in {tests_dir}")
        return 0

    print(f"Tests in {tests_dir}:\n")

    # Group by type
    by_type: dict[str, list] = {}
    for t in tests:
        ttype = t["test_type"]
        if ttype not in by_type:
            by_type[ttype] = []
        by_type[ttype].append(t)

    for test_type, type_tests in sorted(by_type.items()):
        print(f"  [{test_type.upper()}] ({len(type_tests)} tests)")
        for t in type_tests:
            async_marker = "async " if t["is_async"] else ""
            desc = f" - {t['description']}" if t.get("description") else ""
            print(f"    {async_marker}{t['test_name']}{desc}")
            print(f"        {t['file']}:{t['line']}")
        print()

    print(f"Total: {len(tests)} tests")
    print(f"\nRun with: pytest {tests_dir} -v")

    return 0


def cmd_test_stats(args: argparse.Namespace) -> int:
    """Show test statistics by scanning pytest files."""
    agent_path = Path(args.agent_path)
    tests_dir = agent_path / "tests"

    if not tests_dir.exists():
        print(f"No tests directory found at: {tests_dir}")
        return 0

    tests = _scan_test_files(tests_dir)

    if not tests:
        print(f"No tests found in {tests_dir}")
        return 0

    print(f"Test Statistics for {agent_path}:\n")
    print(f"  Total tests: {len(tests)}")

    # Count by type
    by_type: dict[str, int] = {}
    async_count = 0
    for t in tests:
        ttype = t["test_type"]
        by_type[ttype] = by_type.get(ttype, 0) + 1
        if t["is_async"]:
            async_count += 1

    print("\n  By type:")
    for test_type, count in sorted(by_type.items()):
        print(f"    {test_type}: {count}")

    print(f"\n  Async tests: {async_count}/{len(tests)}")

    # List test files
    test_files = list(tests_dir.glob("test_*.py"))
    print(f"\n  Test files ({len(test_files)}):")
    for f in sorted(test_files):
        count = sum(1 for t in tests if t["file"] == f.name)
        print(f"    {f.name} ({count} tests)")

    print(f"\nRun all tests: pytest {tests_dir} -v")

    return 0
