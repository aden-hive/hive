"""
Command-line interface for Goal Agent.

Usage:
    python -m core run exports/my-agent --input '{"key": "value"}'
    python -m core info exports/my-agent
    python -m core validate exports/my-agent
    python -m core list exports/
    python -m core dispatch exports/ --input '{"key": "value"}'
    python -m core shell exports/my-agent

Testing commands:
    python -m core test-run <agent_path> --goal <goal_id>
    python -m core test-debug <goal_id> <test_id>
    python -m core test-list <goal_id>
    python -m core test-stats <goal_id>

History/Analytics commands:
    python -m core history [--status completed|failed|running] [--goal-id <goal_id>] [--limit 10]
    python -m core show <run_id>
    python -m core stats [--goal-id <goal_id>]
"""

import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Goal Agent - Build and run goal-driven agents")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Anthropic model to use",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Register runner commands (run, info, validate, list, dispatch, shell)
    from framework.runner.cli import register_commands

    register_commands(subparsers)

    # Register testing commands (test-run, test-debug, test-list, test-stats)
    from framework.testing.cli import register_testing_commands

    register_testing_commands(subparsers)

    # Register history commands (history, show, stats)
    from framework.runner.history import register_history_commands

    register_history_commands(subparsers)

    args = parser.parse_args()

    if hasattr(args, "func"):
        sys.exit(args.func(args))


if __name__ == "__main__":
    main()
