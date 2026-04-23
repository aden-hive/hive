"""
Command-line interface for Aden Hive.

Usage:
    hive serve                       Start the HTTP API server
    hive open                        Start the server and open the dashboard
    hive queen list                  List queen profiles
    hive queen show <queen_id>       Inspect a queen profile
    hive queen sessions <queen_id>   List a queen's sessions
    hive colony list                 List colonies on disk
    hive colony info <name>          Inspect a colony
    hive colony delete <name>        Delete a colony
    hive session list                List live sessions (use --cold for on-disk)
    hive session stop <session_id>   Stop a live session
    hive chat <session_id> "msg"     Send a message to a live queen

Subsystems:
    hive skill ...                   Manage skills (~/.hive/skills/)
    hive mcp ...                     Manage MCP servers
    hive debugger                    LLM debug log viewer
"""

import argparse
import sys
from pathlib import Path


def _configure_paths() -> None:
    """Auto-configure sys.path so the framework is importable from any cwd.

    Walks up from this file to find the project root, then ensures
    `core/` is on sys.path so `framework.*` imports resolve when the
    package isn't installed via `pip install -e .`.
    """
    framework_dir = Path(__file__).resolve().parent  # core/framework/
    core_dir = framework_dir.parent  # core/
    project_root = core_dir.parent  # project root

    if not (project_root / "core").is_dir():
        project_root = Path.cwd()

    core_str = str(project_root / "core")
    if (project_root / "core").is_dir() and core_str not in sys.path:
        sys.path.insert(0, core_str)


def main() -> None:
    _configure_paths()

    parser = argparse.ArgumentParser(
        prog="hive",
        description="Aden Hive — Queens, colonies, and live agent sessions",
    )
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5-20251001",
        help="Default LLM model (Anthropic ID)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # Core commands: serve, open, queen, colony, session, chat
    from framework.loader.cli import register_commands

    register_commands(subparsers)

    # Skill management (~/.hive/skills/)
    from framework.skills.cli import register_skill_commands

    register_skill_commands(subparsers)

    # LLM debug log viewer
    from framework.debugger.cli import register_debugger_commands

    register_debugger_commands(subparsers)

    # MCP server registry
    from framework.loader.mcp_registry_cli import register_mcp_commands

    register_mcp_commands(subparsers)

    # Register credential management commands (creds list, show, add, delete, test, refresh)
    from framework.credentials.cli import register_commands as register_cred_commands

    register_cred_commands(subparsers)

    args = parser.parse_args()

    if hasattr(args, "func"):
        sys.exit(args.func(args))


if __name__ == "__main__":
    main()
