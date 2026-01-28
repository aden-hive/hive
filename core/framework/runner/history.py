"""
CLI commands for viewing past run history and statistics.

Provides commands:
- history: List past runs with filtering and pagination
- show: Display full details of a specific run
- stats: Show aggregate statistics across all runs
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from framework.schemas.run import Run, RunStatus, RunSummary
from framework.storage.backend import FileStorage


def register_history_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register history-related CLI commands."""

    # history command
    history_parser = subparsers.add_parser(
        "history",
        help="List past runs with filtering and pagination",
        description="View a list of past agent runs with status, goal, and timestamp.",
    )
    history_parser.add_argument(
        "--status",
        choices=["completed", "failed", "running", "stuck", "cancelled"],
        help="Filter runs by status",
    )
    history_parser.add_argument(
        "--goal-id",
        type=str,
        help="Filter runs by goal ID",
    )
    history_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of runs to display (default: 10)",
    )
    history_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of table format",
    )
    history_parser.add_argument(
        "--storage-path",
        type=str,
        default=None,
        help="Path to storage directory (default: ~/.hive/runs)",
    )
    history_parser.set_defaults(func=cmd_history)

    # show command
    show_parser = subparsers.add_parser(
        "show",
        help="Display full details of a specific run",
        description="Show detailed information about a run including decisions, problems, and metrics.",
    )
    show_parser.add_argument(
        "run_id",
        type=str,
        help="ID of the run to display",
    )
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )
    show_parser.add_argument(
        "--storage-path",
        type=str,
        default=None,
        help="Path to storage directory (default: ~/.hive/runs)",
    )
    show_parser.set_defaults(func=cmd_show)

    # stats command
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show aggregate statistics across all runs",
        description="Display overall metrics including success rate, token usage, and failure analysis.",
    )
    stats_parser.add_argument(
        "--goal-id",
        type=str,
        help="Filter statistics by goal ID",
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON instead of formatted text",
    )
    stats_parser.add_argument(
        "--storage-path",
        type=str,
        default=None,
        help="Path to storage directory (default: ~/.hive/runs)",
    )
    stats_parser.set_defaults(func=cmd_stats)


def _get_storage(storage_path: str | None) -> FileStorage:
    """Get or create storage instance."""
    if not storage_path:
        storage_path = str(Path.home() / ".hive" / "runs")
    return FileStorage(storage_path)


def cmd_history(args: argparse.Namespace) -> int:
    """Display list of past runs with filtering."""
    try:
        storage = _get_storage(args.storage_path)

        # Get all run IDs
        all_run_ids = storage.list_all_runs()

        if not all_run_ids:
            print("No runs found in storage.")
            return 0

        # Load summaries for filtering and sorting
        runs_data = []
        for run_id in all_run_ids:
            summary = storage.load_summary(run_id)
            if summary:
                runs_data.append(summary)

        # Apply filters
        if args.goal_id:
            runs_data = [r for r in runs_data if r.goal_id == args.goal_id]

        if args.status:
            runs_data = [r for r in runs_data if r.status.value == args.status]

        # Sort by timestamp (newest first)
        runs_data.sort(
            key=lambda r: r.run_id, reverse=True
        )  # Run IDs are timestamped

        # Apply limit
        runs_data = runs_data[: args.limit]

        if not runs_data:
            print("No runs match the given filters.")
            return 0

        if args.json:
            # JSON output
            output = [
                {
                    "run_id": r.run_id,
                    "goal_id": r.goal_id,
                    "status": r.status.value,
                    "duration_ms": r.duration_ms,
                    "decision_count": r.decision_count,
                    "success_rate": round(r.success_rate, 2),
                    "problem_count": r.problem_count,
                }
                for r in runs_data
            ]
            print(json.dumps(output, indent=2))
        else:
            # Table output
            _print_history_table(runs_data)

        return 0

    except FileNotFoundError as e:
        print(f"Error: Storage directory not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_show(args: argparse.Namespace) -> int:
    """Display full details of a specific run."""
    try:
        storage = _get_storage(args.storage_path)

        run = storage.load_run(args.run_id)
        if not run:
            print(f"Run not found: {args.run_id}", file=sys.stderr)
            return 1

        if args.json:
            # JSON output - use Pydantic's serialization
            output = json.loads(run.model_dump_json())
            print(json.dumps(output, indent=2))
        else:
            # Formatted text output
            _print_run_details(run)

        return 0

    except FileNotFoundError as e:
        print(f"Error: Storage directory not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_stats(args: argparse.Namespace) -> int:
    """Display aggregate statistics across runs."""
    try:
        storage = _get_storage(args.storage_path)

        # Get all run IDs
        all_run_ids = storage.list_all_runs()

        if not all_run_ids:
            print("No runs found in storage.")
            return 0

        # Load all runs
        runs = []
        for run_id in all_run_ids:
            run = storage.load_run(run_id)
            if run:
                runs.append(run)

        # Filter by goal_id if specified
        if args.goal_id:
            runs = [r for r in runs if r.goal_id == args.goal_id]

        if not runs:
            print("No runs match the given filters.")
            return 0

        # Calculate stats
        stats = _calculate_stats(runs)

        if args.json:
            print(json.dumps(stats, indent=2, default=str))
        else:
            _print_stats_table(stats)

        return 0

    except FileNotFoundError as e:
        print(f"Error: Storage directory not found: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# ===== FORMATTING FUNCTIONS =====


def _print_history_table(runs_data: list[RunSummary]) -> None:
    """Print runs in a formatted table."""
    if not runs_data:
        return

    # Headers
    print(f"{'Run ID':<40} {'Status':<12} {'Goal ID':<20} {'Success Rate':<15} {'Duration':<12}")
    print("-" * 100)

    # Rows
    for run in runs_data:
        duration_str = _format_duration(run.duration_ms)
        success_str = f"{run.success_rate * 100:.1f}%"
        status_str = run.status.value

        print(
            f"{run.run_id:<40} {status_str:<12} {run.goal_id:<20} {success_str:<15} {duration_str:<12}"
        )


def _print_run_details(run: Run) -> None:
    """Print full run details in formatted text."""
    print("=" * 80)
    print(f"Run ID: {run.id}")
    print(f"Goal ID: {run.goal_id}")
    print(f"Status: {run.status.value}")
    print(f"Started at: {run.started_at.isoformat()}")
    if run.completed_at:
        print(f"Completed at: {run.completed_at.isoformat()}")
        print(f"Duration: {_format_duration(run.duration_ms)}")
    print("=" * 80)

    # Goal and input
    if run.goal_description:
        print(f"\nGoal: {run.goal_description}")
    if run.input_data:
        print(f"\nInput Data:")
        print(f"  {json.dumps(run.input_data, indent=2, default=str)}")

    # Metrics
    print(f"\n--- METRICS ---")
    print(f"Total Decisions: {run.metrics.total_decisions}")
    print(f"Successful: {run.metrics.successful_decisions}")
    print(f"Failed: {run.metrics.failed_decisions}")
    if run.metrics.total_decisions > 0:
        success_rate = (
            run.metrics.successful_decisions / run.metrics.total_decisions * 100
        )
        print(f"Success Rate: {success_rate:.1f}%")
    print(f"Total Tokens: {run.metrics.total_tokens}")
    print(f"Total Latency: {_format_duration(run.metrics.total_latency_ms)}")
    print(f"Nodes Executed: {', '.join(run.metrics.nodes_executed) or 'None'}")

    # Problems
    if run.problems:
        print(f"\n--- PROBLEMS ({len(run.problems)}) ---")
        for problem in run.problems:
            severity_indicator = {
                "critical": "🔴",
                "warning": "🟡",
                "minor": "🟢",
            }.get(problem.severity, "⚪")
            print(f"\n{severity_indicator} [{problem.severity}] {problem.description}")
            if problem.root_cause:
                print(f"   Root Cause: {problem.root_cause}")
            if problem.suggested_fix:
                print(f"   Suggested Fix: {problem.suggested_fix}")

    # Decisions
    if run.decisions:
        print(f"\n--- DECISIONS ({len(run.decisions)}) ---")
        for i, decision in enumerate(run.decisions, 1):
            status = "✓" if decision.was_successful else "✗"
            print(f"\n{i}. {status} {decision.intent}")
            print(f"   Node: {decision.node_id}")
            if decision.outcome:
                print(f"   Result: {decision.outcome.summary or 'No summary'}")

    # Narrative
    if run.narrative:
        print(f"\n--- NARRATIVE ---")
        print(run.narrative)

    # Output
    if run.output_data:
        print(f"\n--- OUTPUT ---")
        print(json.dumps(run.output_data, indent=2, default=str))

    print("\n" + "=" * 80)


def _print_stats_table(stats: dict[str, Any]) -> None:
    """Print statistics in formatted text."""
    print("=" * 80)
    print("RUN STATISTICS")
    print("=" * 80)

    print(f"\nTotal Runs: {stats['total_runs']}")
    print(f"  Completed: {stats['by_status']['completed']}")
    print(f"  Failed: {stats['by_status']['failed']}")
    print(f"  Running: {stats['by_status']['running']}")
    print(f"  Stuck: {stats['by_status']['stuck']}")
    print(f"  Cancelled: {stats['by_status']['cancelled']}")

    print(f"\nSuccess Rate: {stats['success_rate']:.1f}%")
    print(f"Average Duration: {_format_duration(int(stats['avg_duration_ms']))}")

    print(f"\nToken Usage:")
    print(f"  Total: {stats['total_tokens']}")
    print(f"  Average per run: {stats['avg_tokens_per_run']:.0f}")

    print(f"\nDecision Analysis:")
    print(f"  Total Decisions: {stats['total_decisions']}")
    print(f"  Successful: {stats['total_successful_decisions']}")
    print(f"  Failed: {stats['total_failed_decisions']}")

    if stats["most_common_failure_nodes"]:
        print(f"\nMost Common Failure Nodes:")
        for node_id, count in stats["most_common_failure_nodes"][:5]:
            print(f"  - {node_id}: {count} failures")

    if stats["most_executed_nodes"]:
        print(f"\nMost Executed Nodes:")
        for node_id, count in stats["most_executed_nodes"][:5]:
            print(f"  - {node_id}: {count} times")

    print("\n" + "=" * 80)


def _calculate_stats(runs: list[Run]) -> dict[str, Any]:
    """Calculate aggregate statistics from runs."""
    if not runs:
        return {}

    # Status counts
    status_counts = {
        "completed": 0,
        "failed": 0,
        "running": 0,
        "stuck": 0,
        "cancelled": 0,
    }

    total_tokens = 0
    total_duration_ms = 0
    total_decisions = 0
    total_successful_decisions = 0
    total_failed_decisions = 0
    node_failure_counts = {}
    node_execution_counts = {}

    for run in runs:
        # Count status
        status_counts[run.status.value] += 1

        # Accumulate metrics
        total_tokens += run.metrics.total_tokens
        total_duration_ms += run.duration_ms
        total_decisions += run.metrics.total_decisions
        total_successful_decisions += run.metrics.successful_decisions
        total_failed_decisions += run.metrics.failed_decisions

        # Track node failures
        for decision in run.decisions:
            node_id = decision.node_id
            if node_id not in node_execution_counts:
                node_execution_counts[node_id] = 0
            node_execution_counts[node_id] += 1

            if not decision.was_successful:
                if node_id not in node_failure_counts:
                    node_failure_counts[node_id] = 0
                node_failure_counts[node_id] += 1

    # Calculate rates and averages
    success_rate = (
        (total_successful_decisions / total_decisions * 100)
        if total_decisions > 0
        else 0
    )
    avg_duration_ms = total_duration_ms / len(runs) if runs else 0
    avg_tokens_per_run = total_tokens / len(runs) if runs else 0

    # Sort failure nodes
    most_common_failures = sorted(
        node_failure_counts.items(), key=lambda x: x[1], reverse=True
    )
    most_executed = sorted(
        node_execution_counts.items(), key=lambda x: x[1], reverse=True
    )

    return {
        "total_runs": len(runs),
        "by_status": status_counts,
        "success_rate": success_rate,
        "avg_duration_ms": avg_duration_ms,
        "total_tokens": total_tokens,
        "avg_tokens_per_run": avg_tokens_per_run,
        "total_decisions": total_decisions,
        "total_successful_decisions": total_successful_decisions,
        "total_failed_decisions": total_failed_decisions,
        "most_common_failure_nodes": most_common_failures,
        "most_executed_nodes": most_executed,
    }


def _format_duration(ms: int) -> str:
    """Format milliseconds as human-readable duration."""
    if ms < 1000:
        return f"{ms}ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}m"
    hours = minutes / 60
    return f"{hours:.1f}h"
