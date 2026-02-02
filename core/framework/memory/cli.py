"""CLI commands for memory inspection."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from framework.schemas.run import RunStatus
from framework.storage.backend import FileStorage


def register_memory_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register memory CLI commands."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Inspect stored agent memory",
    )
    memory_subparsers = memory_parser.add_subparsers(dest="memory_command", required=True)

    inspect_parser = memory_subparsers.add_parser(
        "inspect",
        help="Inspect output memory for a run",
    )
    inspect_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    inspect_parser.add_argument(
        "run_id",
        help="Run ID to inspect",
    )
    inspect_parser.add_argument(
        "--storage-path",
        type=str,
        help="Override storage path (defaults to ~/.hive/storage/<agent_name>)",
    )
    inspect_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    inspect_parser.set_defaults(func=cmd_memory_inspect)

    list_parser = memory_subparsers.add_parser(
        "list",
        help="List stored runs for an agent",
    )
    list_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    list_parser.add_argument(
        "--storage-path",
        type=str,
        help="Override storage path (defaults to ~/.hive/storage/<agent_name>)",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Maximum number of runs to display",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    list_parser.set_defaults(func=cmd_memory_list)

    stats_parser = memory_subparsers.add_parser(
        "stats",
        help="Show storage statistics for an agent",
    )
    stats_parser.add_argument(
        "agent_path",
        help="Path to agent export folder (e.g., exports/my_agent)",
    )
    stats_parser.add_argument(
        "--storage-path",
        type=str,
        help="Override storage path (defaults to ~/.hive/storage/<agent_name>)",
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )
    stats_parser.set_defaults(func=cmd_memory_stats)


def _resolve_storage_path(agent_path: str, override: str | None) -> Path:
    if override:
        return Path(override)
    return Path.home() / ".hive" / "storage" / Path(agent_path).name


def _ensure_storage(storage_path: Path) -> bool:
    runs_dir = storage_path / "runs"
    if not storage_path.exists() or not runs_dir.exists():
        print(f"Error: Storage not found at {storage_path}")
        return False
    return True


def cmd_memory_inspect(args: argparse.Namespace) -> int:
    """Inspect memory output for a specific run."""
    storage_path = _resolve_storage_path(args.agent_path, args.storage_path)
    if not _ensure_storage(storage_path):
        return 1

    storage = FileStorage(storage_path)
    run = storage.load_run(args.run_id)
    if not run:
        print(f"Error: Run not found: {args.run_id}")
        return 1

    payload = {
        "run_id": run.id,
        "goal_id": run.goal_id,
        "status": run.status.value,
        "output_data": run.output_data,
    }

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"Run: {run.id}")
        print(f"Goal: {run.goal_id}")
        print(f"Status: {run.status.value}")
        print("Output memory:")
        print(json.dumps(run.output_data, indent=2, default=str))

    return 0


def cmd_memory_list(args: argparse.Namespace) -> int:
    """List stored runs for an agent."""
    storage_path = _resolve_storage_path(args.agent_path, args.storage_path)
    if not _ensure_storage(storage_path):
        return 1

    storage = FileStorage(storage_path)
    run_ids = storage.list_all_runs()
    if not run_ids:
        print("No runs found.")
        return 0

    summaries = []
    for run_id in run_ids:
        summary = storage.load_summary(run_id)
        if summary:
            summaries.append(summary)

    summaries.sort(key=lambda s: s.run_id, reverse=True)
    summaries = summaries[: args.limit]

    if args.json:
        print(json.dumps([s.model_dump() for s in summaries], indent=2, default=str))
    else:
        print(f"Runs in {storage_path}:")
        for summary in summaries:
            print(
                f"- {summary.run_id} [{summary.status.value}] goal={summary.goal_id} "
                f"decisions={summary.decision_count} duration={summary.duration_ms}ms"
            )

    return 0


def cmd_memory_stats(args: argparse.Namespace) -> int:
    """Show storage statistics for an agent."""
    storage_path = _resolve_storage_path(args.agent_path, args.storage_path)
    if not _ensure_storage(storage_path):
        return 1

    storage = FileStorage(storage_path)
    stats = storage.get_stats()

    status_counts = {status.value: 0 for status in RunStatus}
    for run_id in storage.list_all_runs():
        summary = storage.load_summary(run_id)
        if summary:
            status_counts[summary.status.value] += 1

    payload = {**stats, "by_status": status_counts}

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"Storage: {stats['storage_path']}")
        print(f"Total runs: {stats['total_runs']}")
        print(f"Total goals: {stats['total_goals']}")
        print("By status:")
        for status, count in status_counts.items():
            print(f"  - {status}: {count}")

    return 0
