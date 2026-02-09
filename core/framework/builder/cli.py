"""
CLI commands for Agent Outcome Scorecards.

Provides commands for generating, viewing, and comparing agent scorecards.

Usage:
    python -m core scorecard exports/my-agent
    python -m core scorecard exports/my-agent --time-window 7d
    python -m core scorecard exports/my-agent --format json
    python -m core scorecard exports/my-agent --compare old_scorecard.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def register_scorecard_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register scorecard commands with the main CLI."""

    # scorecard command
    scorecard_parser = subparsers.add_parser(
        "scorecard",
        help="Generate agent outcome scorecard",
        description="Generate structured success metrics for an agent.",
    )
    scorecard_parser.add_argument(
        "agent_path",
        type=str,
        help="Path to agent folder (containing agent.json)",
    )
    scorecard_parser.add_argument(
        "--time-window",
        "-t",
        type=str,
        help="Time window for analysis (e.g., 7d, 30d, all)",
        default="all",
    )
    scorecard_parser.add_argument(
        "--format",
        "-f",
        type=str,
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    scorecard_parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Write scorecard to file instead of stdout",
    )
    scorecard_parser.add_argument(
        "--compare",
        "-c",
        type=str,
        help="Compare with a previous scorecard JSON file",
    )
    scorecard_parser.add_argument(
        "--min-runs",
        type=int,
        default=5,
        help="Minimum number of runs required (default: 5)",
    )
    scorecard_parser.add_argument(
        "--goal",
        "-g",
        type=str,
        help="Specific goal ID to analyze (default: auto-detect from agent.json)",
    )
    scorecard_parser.set_defaults(func=cmd_scorecard)


def cmd_scorecard(args: argparse.Namespace) -> int:
    """Generate or compare agent scorecards."""
    from framework.builder.scorecard_generator import ScorecardGenerator
    from framework.schemas.scorecard import Scorecard

    agent_path = Path(args.agent_path)
    if not agent_path.exists():
        print(f"Error: Agent path not found: {agent_path}", file=sys.stderr)
        return 1

    agent_json = agent_path / "agent.json"
    if not agent_json.exists():
        print(f"Error: No agent.json found in {agent_path}", file=sys.stderr)
        return 1

    # Load agent metadata
    try:
        with open(agent_json) as f:
            agent_data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing agent.json: {e}", file=sys.stderr)
        return 1

    # Extract agent info
    agent_name = agent_data.get("name", agent_path.name)
    goal = agent_data.get("goal", {})
    goal_id = args.goal or goal.get("id", goal.get("name", "default"))

    # Parse time window
    time_window_days = _parse_time_window(args.time_window)

    # Create generator
    storage_path = agent_path / ".runs"
    if not storage_path.exists():
        # Try alternative paths
        storage_path = agent_path / "runs"
        if not storage_path.exists():
            # Create a minimal storage directory for the generator
            storage_path = agent_path / ".runs"
            storage_path.mkdir(exist_ok=True)

    generator = ScorecardGenerator(storage_path)

    # If comparing, load previous scorecard
    if args.compare:
        return _handle_comparison(args, generator, agent_name, goal_id, time_window_days)

    # Generate scorecard
    scorecard = generator.generate(
        goal_id=goal_id,
        agent_name=agent_name,
        time_window_days=time_window_days,
        min_runs=args.min_runs,
    )

    if scorecard is None:
        print(
            f"Insufficient data: Need at least {args.min_runs} runs to generate scorecard.",
            file=sys.stderr,
        )
        print("Run your agent more times and try again.", file=sys.stderr)
        return 1

    # Output based on format
    if args.format == "json":
        output = scorecard.model_dump_json(indent=2)
    else:
        output = scorecard.to_formatted_string()

    # Write to file or stdout
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Scorecard written to {args.output}")
    else:
        print(output)

    return 0


def _handle_comparison(
    args: argparse.Namespace,
    generator: Any,
    agent_name: str,
    goal_id: str,
    time_window_days: int | None,
) -> int:
    """Handle scorecard comparison."""
    compare_path = Path(args.compare)
    if not compare_path.exists():
        print(f"Error: Comparison file not found: {compare_path}", file=sys.stderr)
        return 1

    # Load the previous scorecard
    try:
        scorecard_before = generator.load_scorecard_from_file(compare_path)
    except Exception as e:
        print(f"Error loading comparison scorecard: {e}", file=sys.stderr)
        return 1

    # Generate current scorecard
    scorecard_after = generator.generate(
        goal_id=goal_id,
        agent_name=agent_name,
        time_window_days=time_window_days,
        min_runs=args.min_runs,
    )

    if scorecard_after is None:
        print(
            f"Insufficient data: Need at least {args.min_runs} runs to generate scorecard.",
            file=sys.stderr,
        )
        return 1

    # Compare
    diff = generator.compare(scorecard_before, scorecard_after)

    # Output based on format
    if args.format == "json":
        output = diff.model_dump_json(indent=2)
    else:
        output = diff.to_formatted_string()

    # Write to file or stdout
    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"Comparison written to {args.output}")
    else:
        print(output)

    return 0


def _parse_time_window(window_str: str) -> int | None:
    """
    Parse time window string into days.

    Args:
        window_str: Time window like '7d', '30d', '1w', '1m', or 'all'.

    Returns:
        Number of days, or None for 'all'.
    """
    if window_str.lower() in ("all", "none", ""):
        return None

    window_str = window_str.lower().strip()

    # Handle days
    if window_str.endswith("d"):
        try:
            return int(window_str[:-1])
        except ValueError:
            pass

    # Handle weeks
    if window_str.endswith("w"):
        try:
            return int(window_str[:-1]) * 7
        except ValueError:
            pass

    # Handle months (approximate)
    if window_str.endswith("m"):
        try:
            return int(window_str[:-1]) * 30
        except ValueError:
            pass

    # Try parsing as plain number (assumed days)
    try:
        return int(window_str)
    except ValueError:
        pass

    # Default to all time
    return None
