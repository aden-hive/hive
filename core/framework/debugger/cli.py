"""CLI command for the LLM debug log viewer."""

import argparse
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "llm_debug_log_visualizer.py"


def register_debugger_commands(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``hive debugger`` command."""
    parser = subparsers.add_parser(
        "debugger",
        help="Open the LLM debug log viewer",
        description=(
            "Start a local server that lets you browse LLM debug sessions "
            "recorded in ~/.hive/llm_logs. Sessions are loaded on demand so "
            "the browser stays responsive."
        ),
    )
    parser.add_argument(
        "--session",
        help="Execution ID to select initially.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Port for the local server (0 = auto-pick a free port).",
    )
    parser.add_argument(
        "--logs-dir",
        help="Directory containing JSONL log files (default: ~/.hive/llm_logs).",
    )
    parser.add_argument(
        "--limit-files",
        type=int,
        default=None,
        help="Maximum number of newest log files to scan (default: 200).",
    )
    parser.add_argument(
        "--output",
        help="Write a static HTML file instead of starting a server.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Start the server but do not open a browser.",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Show test/mock sessions (hidden by default).",
    )
    parser.set_defaults(func=cmd_debugger)


def cmd_debugger(args: argparse.Namespace) -> int:
    """Launch the LLM debug log visualizer."""
    # Lazy import so a HIVE_HOME env override set after process start
    # (e.g. by the desktop shell) is respected.
    from framework.config import HIVE_HOME

    logs_dir = Path(args.logs_dir) if args.logs_dir else HIVE_HOME / "llm_logs"
    if not logs_dir.is_dir() or not any(logs_dir.glob("*.jsonl")):
        print(
            f"No LLM debug logs found in {logs_dir}.\n"
            "LLM turn logging is now server-side (LLM proxy datalog); "
            "set HIVE_ENABLE_LLM_LOGS=1 to capture local debug logs."
        )
        return 0

    if not _SCRIPT.is_file():
        print(
            f"Visualizer script missing: {_SCRIPT}\n"
            "It ships with the OSS hive repo (scripts/llm_debug_log_visualizer.py); "
            "for proxy traffic, use the server-side datalog "
            "(llm/scripts/datalog_replay.py in hive-backend) instead."
        )
        return 1

    cmd: list[str] = [sys.executable, str(_SCRIPT)]
    if args.session:
        cmd += ["--session", args.session]
    if args.port:
        cmd += ["--port", str(args.port)]
    if args.logs_dir:
        cmd += ["--logs-dir", args.logs_dir]
    if args.limit_files is not None:
        cmd += ["--limit-files", str(args.limit_files)]
    if args.output:
        cmd += ["--output", args.output]
    if args.no_open:
        cmd.append("--no-open")
    if args.include_tests:
        cmd.append("--include-tests")
    return subprocess.call(cmd)
