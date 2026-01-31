"""CLI commands for memory management."""

import argparse
import json
import sys
from pathlib import Path

from framework.schemas.run import RunStatus
from framework.storage.backend import FileStorage


def register_memory_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register memory management commands with the main CLI."""

    # memory list command
    list_parser = subparsers.add_parser(
        "memory-list",
        help="List stored agent runs",
        description="Display a list of all stored agent runs from memory.",
    )
    list_parser.add_argument(
        "--agent",
        "-a",
        type=str,
        help="Agent name (folder in ~/.hive/storage/)",
    )
    list_parser.add_argument(
        "--status",
        "-s",
        type=str,
        choices=["completed", "failed", "running", "stuck", "cancelled"],
        help="Filter by run status",
    )
    list_parser.add_argument(
        "--goal",
        "-g",
        type=str,
        help="Filter by goal ID",
    )
    list_parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=20,
        help="Maximum number of runs to display (default: 20)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    list_parser.set_defaults(func=cmd_list)

    # memory inspect command
    inspect_parser = subparsers.add_parser(
        "memory-inspect",
        help="Inspect a specific run",
        description="Show detailed information about a specific agent run.",
    )
    inspect_parser.add_argument(
        "run_id",
        type=str,
        help="Run ID to inspect",
    )
    inspect_parser.add_argument(
        "--agent",
        "-a",
        type=str,
        help="Agent name (folder in ~/.hive/storage/)",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    inspect_parser.set_defaults(func=cmd_inspect)

    # memory stats command
    stats_parser = subparsers.add_parser(
        "memory-stats",
        help="Show memory statistics",
        description="Display statistics about stored agent runs.",
    )
    stats_parser.add_argument(
        "--agent",
        "-a",
        type=str,
        help="Agent name (folder in ~/.hive/storage/)",
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    stats_parser.set_defaults(func=cmd_stats)

    # memory delete command
    delete_parser = subparsers.add_parser(
        "memory-delete",
        help="Delete a specific run",
        description="Remove a specific agent run from memory.",
    )
    delete_parser.add_argument(
        "run_id",
        type=str,
        help="Run ID to delete",
    )
    delete_parser.add_argument(
        "--agent",
        "-a",
        type=str,
        help="Agent name (folder in ~/.hive/storage/)",
    )
    delete_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    delete_parser.set_defaults(func=cmd_delete)

    # memory clear command
    clear_parser = subparsers.add_parser(
        "memory-clear",
        help="Clear all runs",
        description="Remove all agent runs from memory (requires confirmation).",
    )
    clear_parser.add_argument(
        "--agent",
        "-a",
        type=str,
        help="Agent name (folder in ~/.hive/storage/)",
    )
    clear_parser.add_argument(
        "--status",
        "-s",
        type=str,
        choices=["completed", "failed", "running", "stuck", "cancelled"],
        help="Only clear runs with this status",
    )
    clear_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt",
    )
    clear_parser.set_defaults(func=cmd_clear)


def _get_storage_path(agent_name: str | None) -> Path:
    """
    Get the storage path for an agent.

    Args:
        agent_name: Agent name, or None to use current directory name

    Returns:
        Path to storage directory
    """
    if agent_name:
        return Path.home() / ".hive" / "storage" / agent_name

    # Try to infer from current directory
    cwd = Path.cwd()
    exports_dir = cwd.parent if cwd.parent.name == "exports" else None
    if exports_dir and (exports_dir / cwd.name / "agent.json").exists():
        return Path.home() / ".hive" / "storage" / cwd.name

    # No agent specified and couldn't infer
    print("Error: Could not determine agent. Use --agent or run from agent directory.", file=sys.stderr)
    sys.exit(1)


def cmd_list(args: argparse.Namespace) -> int:
    """List stored agent runs."""
    storage_path = _get_storage_path(args.agent)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)

    # Get run IDs
    if args.status:
        run_ids = storage.get_runs_by_status(args.status)
    elif args.goal:
        run_ids = storage.get_runs_by_goal(args.goal)
    else:
        run_ids = storage.list_all_runs()

    # Apply limit
    run_ids = run_ids[: args.limit]

    # Load summaries
    summaries = []
    for run_id in run_ids:
        summary = storage.load_summary(run_id)
        if summary:
            summaries.append(summary)

    if args.json:
        print(json.dumps([s.model_dump() for s in summaries], indent=2))
        return 0

    # Human-readable output
    if not summaries:
        print("No runs found.")
        return 0

    print(f"Found {len(summaries)} run(s):\n")
    for s in summaries:
        status_color = {
            "completed": "✓",
            "failed": "✗",
            "running": "→",
            "stuck": "⊗",
            "cancelled": "⊘",
        }.get(s.status.value if hasattr(s.status, 'value') else s.status, "?")
        print(f"{status_color} {s.run_id}")
        print(f"  Goal: {s.goal_id}")
        print(f"  Status: {s.status.value if hasattr(s.status, 'value') else s.status}")
        print(f"  Duration: {s.duration_ms}ms")
        print(f"  Decisions: {s.decision_count} (success rate: {s.success_rate:.1%})")
        if s.problem_count > 0:
            print(f"  Problems: {s.problem_count}")
        print()

    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    """Inspect a specific run."""
    storage_path = _get_storage_path(args.agent)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)
    run = storage.load_run(args.run_id)

    if not run:
        print(f"Run {args.run_id} not found.", file=sys.stderr)
        return 1

    if args.json:
        print(run.model_dump_json(indent=2))
        return 0

    # Human-readable output
    print(f"Run: {run.id}")
    print(f"Goal: {run.goal_id} - {run.goal_description}")
    print(f"Status: {run.status.value}")
    print(f"Started: {run.started_at}")
    print(f"Completed: {run.completed_at or 'N/A'}")
    print(f"Duration: {run.duration_ms}ms")
    print(f"\nMetrics:")
    print(f"  Decisions: {run.metrics.total_decisions}")
    print(f"  Successful: {run.metrics.successful_decisions}")
    print(f"  Failed: {run.metrics.failed_decisions}")
    print(f"  Nodes executed: {len(run.metrics.nodes_executed)}")

    if run.decisions:
        print(f"\nDecisions ({len(run.decisions)}):")
        for i, decision in enumerate(run.decisions[:5], 1):
            print(f"  {i}. [{decision.node_id}] {decision.intent}")
            print(f"     Chosen: {decision.chosen}")
            if decision.outcome:
                outcome_status = "✓" if decision.outcome.success else "✗"
                print(f"     Outcome: {outcome_status} {decision.outcome.summary}")

        if len(run.decisions) > 5:
            print(f"  ... and {len(run.decisions) - 5} more")

    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Show memory statistics."""
    storage_path = _get_storage_path(args.agent)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)
    stats = storage.get_stats()

    # Count by status
    status_counts = {}
    for status in ["completed", "failed", "running", "stuck", "cancelled"]:
        status_counts[status] = len(storage.get_runs_by_status(status))

    if args.json:
        output = {
            **stats,
            "by_status": status_counts,
        }
        print(json.dumps(output, indent=2))
        return 0

    # Human-readable output
    print(f"Memory Statistics")
    print(f"Storage: {stats['storage_path']}")
    print(f"\nTotal runs: {stats['total_runs']}")
    print(f"Total goals: {stats['total_goals']}")
    print(f"\nBy status:")
    print(f"  Completed: {status_counts['completed']}")
    print(f"  Failed: {status_counts['failed']}")
    print(f"  Running: {status_counts['running']}")
    print(f"  Stuck: {status_counts['stuck']}")
    print(f"  Cancelled: {status_counts['cancelled']}")

    return 0


def cmd_delete(args: argparse.Namespace) -> int:
    """Delete a specific run."""
    storage_path = _get_storage_path(args.agent)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)

    # Check if run exists
    run = storage.load_run(args.run_id)
    if not run:
        print(f"Run {args.run_id} not found.", file=sys.stderr)
        return 1

    # Confirm deletion
    if not args.yes:
        print(f"Delete run {args.run_id}?")
        print(f"  Goal: {run.goal_id}")
        print(f"  Status: {run.status.value}")
        response = input("Continue? [y/N] ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0

    # Delete
    storage.delete_run(args.run_id)
    print(f"Deleted run {args.run_id}")
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    """Clear all runs."""
    storage_path = _get_storage_path(args.agent)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)

    # Get runs to delete
    if args.status:
        run_ids = storage.get_runs_by_status(args.status)
    else:
        run_ids = storage.list_all_runs()

    if not run_ids:
        print("No runs to clear.")
        return 0

    # Confirm deletion
    if not args.yes:
        if args.status:
            print(f"Clear {len(run_ids)} run(s) with status '{args.status}'?")
        else:
            print(f"Clear ALL {len(run_ids)} run(s)?")
        print(f"Storage: {storage_path}")
        response = input("Continue? [y/N] ")
        if response.lower() != "y":
            print("Cancelled.")
            return 0

    # Delete all
    deleted = 0
    for run_id in run_ids:
        if storage.delete_run(run_id):
            deleted += 1

    print(f"Cleared {deleted} run(s)")
    return 0
