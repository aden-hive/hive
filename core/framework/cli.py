"""
Command-line interface for Aden Hive.

Usage:
    hive run exports/my-agent --input '{"key": "value"}'
    hive info exports/my-agent
    hive validate exports/my-agent
    hive list exports/
    hive dispatch exports/ --input '{"key": "value"}'
    hive shell exports/my-agent

Testing commands:
    hive test-run <agent_path> --goal <goal_id>
    hive test-debug <agent_path> <test_name>
    hive test-list <agent_path>
    hive test-stats <agent_path>
"""

import argparse
import sys
from pathlib import Path


def _configure_paths():
    """Auto-configure sys.path so agents in exports/ are discoverable.

    Resolves the project root by walking up from this file (framework/cli.py lives
    inside core/framework/) or from CWD, then adds the exports/ directory to sys.path
    if it exists. This eliminates the need for manual PYTHONPATH configuration.
    """
    # Strategy 1: resolve relative to this file (works when installed via pip install -e core/)
    framework_dir = Path(__file__).resolve().parent  # core/framework/
    core_dir = framework_dir.parent  # core/
    project_root = core_dir.parent  # project root

    # Strategy 2: if project_root doesn't look right, fall back to CWD
    if not (project_root / "exports").is_dir() and not (project_root / "core").is_dir():
        project_root = Path.cwd()

    # Add exports/ to sys.path so agents are importable as top-level packages
    exports_dir = project_root / "exports"
    if exports_dir.is_dir():
        exports_str = str(exports_dir)
        if exports_str not in sys.path:
            sys.path.insert(0, exports_str)

    # Add examples/templates/ to sys.path so template agents are importable
    templates_dir = project_root / "examples" / "templates"
    if templates_dir.is_dir():
        templates_str = str(templates_dir)
        if templates_str not in sys.path:
            sys.path.insert(0, templates_str)

    # Ensure core/ is also in sys.path (for non-editable-install scenarios)
    core_str = str(project_root / "core")
    if (project_root / "core").is_dir() and core_str not in sys.path:
        sys.path.insert(0, core_str)

    # Add core/framework/agents/ so framework agents are importable as top-level packages
    framework_agents_dir = project_root / "core" / "framework" / "agents"
    if framework_agents_dir.is_dir():
        fa_str = str(framework_agents_dir)
        if fa_str not in sys.path:
            sys.path.insert(0, fa_str)


def main():
    _configure_paths()

    parser = argparse.ArgumentParser(
        prog="hive",
        description="Aden Hive - Build and run goal-driven agents",
    )
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

    # doctor command
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run system health check",
        description="Diagnose environment and configuration issues.",
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    # export command
    export_parser = subparsers.add_parser(
        "export-analytics",
        help="Export agent session data to CSV",
        description="Generate a CSV report of agent execution history.",
    )
    export_parser.add_argument(
        "agent_name",
        type=str,
        help="Name of the agent (folder name in exports/)",
    )
    export_parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="sessions.csv",
        help="Output CSV file path (default: sessions.csv)",
    )
    export_parser.set_defaults(func=cmd_export)

    args = parser.parse_args()

    if hasattr(args, "func"):
        sys.exit(args.func(args))


def cmd_doctor(args: argparse.Namespace) -> int:
    from framework.doctor import run_doctor
    return run_doctor()


def cmd_export(args: argparse.Namespace) -> int:
    from framework.analytics import export_sessions_to_csv
    export_sessions_to_csv(args.agent_name, args.output)
    return 0



if __name__ == "__main__":
    main()
