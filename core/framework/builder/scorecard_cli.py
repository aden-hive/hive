"""
CLI commands for Agent Outcome Scorecards.

Registers the `scorecard` subcommand with the main hive CLI.
Follows the same register_commands() pattern used by
framework.runner.cli and framework.testing.cli.

Usage:
    hive scorecard exports/my-agent
    hive scorecard exports/my-agent --time-window last_7_days
    hive scorecard exports/my-agent --format json
    hive scorecard exports/my-agent --compare previous_scorecard.json
"""

import json
import sys
from pathlib import Path

from framework.builder.scorecard_generator import ScorecardGenerator
from framework.schemas.scorecard import Scorecard


def register_scorecard_commands(subparsers) -> None:
    """Register scorecard commands with the CLI subparsers."""
    scorecard_parser = subparsers.add_parser(
        "scorecard",
        help="Generate an outcome scorecard for an agent",
        description=(
            "Analyzes agent run history and produces a structured scorecard "
            "showing goal achievement, cost trends, adaptation progress, "
            "and decision confidence."
        ),
    )

    scorecard_parser.add_argument(
        "agent_path",
        type=str,
        help="Path to agent export directory (e.g., exports/my-agent)",
    )

    scorecard_parser.add_argument(
        "--goal-id",
        type=str,
        default=None,
        help="Goal ID to analyze (auto-detected if only one goal exists)",
    )

    scorecard_parser.add_argument(
        "--time-window",
        type=str,
        default="all_time",
        choices=["last_7_days", "last_14_days", "last_30_days", "last_90_days", "all_time"],
        help="Time window for analysis (default: all_time)",
    )

    scorecard_parser.add_argument(
        "--format",
        type=str,
        default="table",
        choices=["table", "json", "markdown"],
        dest="output_format",
        help="Output format (default: table)",
    )

    scorecard_parser.add_argument(
        "--compare",
        type=str,
        default=None,
        metavar="SCORECARD_JSON",
        help="Path to a previous scorecard JSON file for before/after comparison",
    )

    scorecard_parser.add_argument(
        "--save",
        type=str,
        default=None,
        metavar="OUTPUT_PATH",
        help="Save scorecard JSON to this path (for later comparison)",
    )

    scorecard_parser.set_defaults(func=_handle_scorecard)


def _handle_scorecard(args) -> int:
    """Handle the scorecard subcommand."""
    agent_path = Path(args.agent_path)

    if not agent_path.is_dir():
        print(f"Error: Agent path '{agent_path}' does not exist or is not a directory.")
        return 1

    # Find storage path (convention: agent_path/runs/ or agent_path/storage/)
    storage_path = _find_storage_path(agent_path)
    if storage_path is None:
        print(f"Error: No run storage found in '{agent_path}'.")
        print("Expected a 'runs/' or 'storage/' directory with run data.")
        return 1

    # Detect agent name from path
    agent_name = agent_path.name

    # Create generator
    generator = ScorecardGenerator(storage_path)

    # Auto-detect goal ID if not specified
    goal_id = args.goal_id
    if goal_id is None:
        goal_id = _detect_goal_id(generator)
        if goal_id is None:
            print("Error: Could not auto-detect goal ID. Use --goal-id to specify.")
            return 1

    # Generate scorecard
    try:
        scorecard = generator.generate(agent_name, goal_id, args.time_window)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    # Handle comparison mode
    if args.compare:
        compare_path = Path(args.compare)
        if not compare_path.is_file():
            print(f"Error: Comparison file '{compare_path}' not found.")
            return 1

        try:
            with open(compare_path) as f:
                before_data = json.load(f)
            before = Scorecard.model_validate(before_data)
        except Exception as e:
            print(f"Error loading comparison scorecard: {e}")
            return 1

        diff = generator.compare(before, scorecard)
        _output_diff(diff, args.output_format)
    else:
        _output_scorecard(scorecard, args.output_format)

    # Save if requested
    if args.save:
        save_path = Path(args.save)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, "w") as f:
            f.write(scorecard.model_dump_json(indent=2))
        print(f"\nScorecard saved to: {save_path}")

    return 0


def _find_storage_path(agent_path: Path) -> Path | None:
    """Find the run storage directory within an agent export."""
    candidates = [
        agent_path / "runs",
        agent_path / "storage",
        agent_path / "data" / "runs",
        agent_path,  # Fall back to agent path itself
    ]
    for candidate in candidates:
        if candidate.is_dir():
            # Check if it contains run data
            json_files = list(candidate.glob("*.json"))
            subdirs = [d for d in candidate.iterdir() if d.is_dir()]
            if json_files or subdirs:
                return candidate
    return None


def _detect_goal_id(generator: ScorecardGenerator) -> str | None:
    """Auto-detect goal ID from storage."""
    try:
        goals = generator.storage.list_all_goals()
        if len(goals) == 1:
            return goals[0]
        elif len(goals) > 1:
            print(f"Multiple goals found: {', '.join(goals)}")
            print("Use --goal-id to specify which goal to analyze.")
            return None
    except Exception:
        pass
    return None


def _output_scorecard(scorecard: Scorecard, output_format: str) -> None:
    """Output scorecard in the requested format."""
    if output_format == "json":
        print(scorecard.model_dump_json(indent=2))
    elif output_format == "markdown":
        print(_scorecard_to_markdown(scorecard))
    else:
        print(scorecard.to_table_str())


def _output_diff(diff, output_format: str) -> None:
    """Output scorecard diff in the requested format."""
    if output_format == "json":
        print(diff.model_dump_json(indent=2))
    else:
        print(diff.to_table_str())


def _scorecard_to_markdown(scorecard: Scorecard) -> str:
    """Convert scorecard to Markdown format."""
    lines = [
        f"# Agent Scorecard: {scorecard.agent_name}",
        "",
        f"**Goal:** {scorecard.goal_id}  ",
        f"**Window:** {scorecard.time_window} | **Runs:** {scorecard.runs_analyzed}  ",
        f"**Generated:** {scorecard.generated_at.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"## Overall Health: {scorecard.overall_health}/100 ({scorecard.health_label})",
        "",
        f"- **Goal Achievement:** {scorecard.goal_achievement_rate:.1%}",
        "",
        "## Criteria Breakdown",
        "",
        "| Criterion | Achievement | Trend | Samples |",
        "|-----------|------------|-------|---------|",
    ]

    for cs in scorecard.criteria_scores:
        lines.append(
            f"| {cs.description} | {cs.achievement_rate:.1%} | {cs.trend} | {cs.sample_size} |"
        )

    lines.extend(
        [
            "",
            "## Cost",
            "",
            f"- **Avg tokens/run:** {scorecard.cost_metrics.avg_tokens_per_run:.0f}",
            f"- **Total tokens:** {scorecard.cost_metrics.total_spend_tokens}",
            f"- **Trend:** {scorecard.cost_metrics.cost_trend}",
            "",
            "## Adaptation",
            "",
            f"- **Graph versions:** {scorecard.adaptation_metrics.total_graph_versions}",
            f"- **Failures resolved:** {scorecard.adaptation_metrics.failure_modes_resolved}",
            f"- **Failures remaining:** {scorecard.adaptation_metrics.failure_modes_remaining}",
            f"- **Avg confidence:** {scorecard.adaptation_metrics.avg_decision_confidence:.2f}",
            f"- **Confidence trend:** {scorecard.adaptation_metrics.confidence_trend}",
        ]
    )

    return "\n".join(lines)
