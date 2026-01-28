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
    hive test-debug <goal_id> <test_id>
    hive test-list <goal_id>
    hive test-stats <goal_id>
"""

import argparse
import sys
import traceback
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

    # Ensure core/ is also in sys.path (for non-editable-install scenarios)
    core_str = str(project_root / "core")
    if (project_root / "core").is_dir() and core_str not in sys.path:
        sys.path.insert(0, core_str)


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
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show full tracebacks on error",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Register runner commands (run, info, validate, list, dispatch, shell)
    from framework.runner.cli import register_commands

    register_commands(subparsers)

    # Register testing commands (test-run, test-debug, test-list, test-stats)
    from framework.testing.cli import register_testing_commands

    register_testing_commands(subparsers)

    args = parser.parse_args()

    if hasattr(args, "func"):
        try:
            sys.exit(args.func(args))
        except KeyboardInterrupt:
            print("\nInterrupted.", file=sys.stderr)
            sys.exit(130)
        except Exception as exc:
            # Last-resort handler for anything that escapes command-level handling
            from framework.errors import _resolve_error, format_error

            verbose = getattr(args, "verbose", False)
            cli_err = _resolve_error(exc)
            cli_err.__cause__ = exc
            print(format_error(cli_err, verbose=verbose), file=sys.stderr)
            if verbose:
                traceback.print_exc(file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
