"""CLI commands for memory management."""

import argparse
import json
import sys
from pathlib import Path

from framework.storage.backend import FileStorage


def register_memory_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register memory management commands with the main CLI."""

    # Create 'memory' subcommand group
    memory_parser = subparsers.add_parser(
        "memory",
        help="Memory management commands",
        description="Inspect and manage agent run memory.",
    )
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    # memory list command
    list_parser = memory_subparsers.add_parser(
        "list",
        help="List stored agent runs",
        description="Display a list of all stored agent runs from memory.",
    )
    list_parser.add_argument(
        "agent_path",
        type=str,
        nargs="?",
        help="Path to agent (e.g., exports/my-agent) or agent name",
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
    inspect_parser = memory_subparsers.add_parser(
        "inspect",
        help="Inspect agent memory from runs",
        description="View memory state and details from an agent run.",
    )
    inspect_parser.add_argument(
        "agent_path",
        type=str,
        help="Path to agent (e.g., exports/my-agent) or agent name",
    )
    inspect_parser.add_argument(
        "--run-id",
        type=str,
        help="Specific run ID to inspect (defaults to last run)",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    inspect_parser.set_defaults(func=cmd_inspect)

    # memory stats command
    stats_parser = memory_subparsers.add_parser(
        "stats",
        help="Show memory statistics",
        description="Display statistics about stored agent runs.",
    )
    stats_parser.add_argument(
        "agent_path",
        type=str,
        nargs="?",
        help="Path to agent (e.g., exports/my-agent) or agent name",
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    stats_parser.set_defaults(func=cmd_stats)



def _get_storage_path(agent_path: str | None) -> Path:
    """
    Get the storage path for an agent.

    Args:
        agent_path: Agent path (e.g., 'exports/my-agent'), agent name, or None to infer

    Returns:
        Path to storage directory
    """
    if agent_path:
        # Handle paths like 'exports/my-agent' or just 'my-agent'
        path = Path(agent_path)
        agent_name = path.name  # Extract the agent name from path
        return Path.home() / ".hive" / "storage" / agent_name

    # Try to infer from current directory
    cwd = Path.cwd()
    exports_dir = cwd.parent if cwd.parent.name == "exports" else None
    if exports_dir and (exports_dir / cwd.name / "agent.json").exists():
        return Path.home() / ".hive" / "storage" / cwd.name

    # No agent specified and couldn't infer
    print("Error: Could not determine agent. Provide agent path as argument.", file=sys.stderr)
    sys.exit(1)


def cmd_list(args: argparse.Namespace) -> int:
    """List stored agent runs."""
    storage_path = _get_storage_path(args.agent_path)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)

    # Validate limit
    if args.limit < 1:
        print("Error: limit must be a positive number", file=sys.stderr)
        return 1

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
        print(json.dumps([s.model_dump(mode="json") for s in summaries], indent=2))
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
        }.get(s.status.value if hasattr(s.status, "value") else s.status, "?")
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
    storage_path = _get_storage_path(args.agent_path)

    if not storage_path.exists():
        print(f"No memory found at {storage_path}", file=sys.stderr)
        return 1

    storage = FileStorage(storage_path)

    # Determine run_id: use provided or get last run
    # Note: argparse converts --run-id to run_id attribute
    run_id = args.run_id if hasattr(args, "run_id") else None
    if not run_id:
        # Get the most recent run
        all_runs = storage.list_all_runs()
        if not all_runs:
            print("No runs found.", file=sys.stderr)
            return 1
        run_id = all_runs[-1]  # Assuming list is sorted, take last

    run = storage.load_run(run_id)

    if not run:
        print(f"Run {run_id} not found.", file=sys.stderr)
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

    # Display input data (what was passed to the agent)
    if run.input_data:
        print("\nInput Data:")
        for key, value in run.input_data.items():
            if isinstance(value, (list, dict)):
                if len(str(value)) < 100:
                    value_str = json.dumps(value, indent=2)
                else:
                    value_str = f"{type(value).__name__} with {len(value)} items"
            else:
                value_str = str(value)[:200]
            print(f"  {key}: {value_str}")

    print("\nMetrics:")
    print(f"  Decisions: {run.metrics.total_decisions}")
    print(f"  Successful: {run.metrics.successful_decisions}")
    print(f"  Failed: {run.metrics.failed_decisions}")
    print(f"  Nodes executed: {len(run.metrics.nodes_executed)}")

    # Display memory state (run.output_data = final SharedMemory state)
    if run.output_data:
        print("\nMemory State:")
        for key, value in run.output_data.items():
            # Format value for display
            if isinstance(value, (list, dict)):
                if len(str(value)) < 100:
                    value_str = json.dumps(value, indent=2)
                else:
                    value_str = f"{type(value).__name__} with {len(value)} items"
            else:
                value_str = str(value)[:200]  # Truncate long strings
            print(f"  {key}: {value_str}")
        print(f"\nTotal keys: {len(run.output_data)}")
    else:
        print("\nMemory State: (empty)")

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
    storage_path = _get_storage_path(args.agent_path)

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
    print("Memory Statistics")
    print(f"Storage: {stats['storage_path']}")
    print(f"\nTotal runs: {stats['total_runs']}")
    print(f"Total goals: {stats['total_goals']}")
    print("\nBy status:")
    print(f"  Completed: {status_counts['completed']}")
    print(f"  Failed: {status_counts['failed']}")
    print(f"  Running: {status_counts['running']}")
    print(f"  Stuck: {status_counts['stuck']}")
    print(f"  Cancelled: {status_counts['cancelled']}")

    return 0


