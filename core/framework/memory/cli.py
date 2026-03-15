"""
Memory Management CLI - Interactive memory inspection and cleanup utilities.

Usage:
    hive memory list-sessions [--agent <agent_name>] [--limit <limit>]
    hive memory inspect <session_id> [--type <memory_type>]
    hive memory cleanup <session_id> [--dry-run]
    hive memory analyze <session_id> [--summary]
    hive memory export <session_id> [--format <format>]
    hive memory search <session_id> <query> [--type <memory_type>]
"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from framework.storage.session_store import SessionStore


def register_memory_commands(subparsers):
    """Register memory management commands with the main CLI."""
    memory_parser = subparsers.add_parser(
        "memory",
        help="Memory management and inspection tools",
        description="Interactive memory inspection, cleanup, and analysis utilities",
    )

    memory_subparsers = memory_parser.add_subparsers(
        dest="memory_command",
        required=True,
        help="Available memory commands",
    )

    # List sessions command
    list_parser = memory_subparsers.add_parser(
        "list-sessions",
        help="List all agent sessions",
        description="List all available agent sessions with basic metadata",
    )
    list_parser.add_argument(
        "--agent",
        help="Filter by agent name",
    )
    list_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of sessions to show (default: 20)",
    )
    list_parser.set_defaults(func=cmd_list_sessions)

    # Inspect session command
    inspect_parser = memory_subparsers.add_parser(
        "inspect",
        help="Inspect session memory",
        description="Detailed inspection of session memory and state",
    )
    inspect_parser.add_argument(
        "session_id",
        help="Session ID to inspect",
    )
    inspect_parser.add_argument(
        "--type",
        choices=["state", "conversations", "logs", "artifacts", "all"],
        default="all",
        help="Type of memory to inspect (default: all)",
    )
    inspect_parser.set_defaults(func=cmd_inspect_session)

    # Cleanup command
    cleanup_parser = memory_subparsers.add_parser(
        "cleanup",
        help="Clean up session memory",
        description="Remove old or unnecessary session data",
    )
    cleanup_parser.add_argument(
        "session_id",
        help="Session ID to clean up",
    )
    cleanup_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    cleanup_parser.set_defaults(func=cmd_cleanup_session)

    # Analyze command
    analyze_parser = memory_subparsers.add_parser(
        "analyze",
        help="Analyze session memory usage",
        description="Analyze memory usage patterns and statistics",
    )
    analyze_parser.add_argument(
        "session_id",
        help="Session ID to analyze",
    )
    analyze_parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary statistics only",
    )
    analyze_parser.set_defaults(func=cmd_analyze_session)

    # Export command
    export_parser = memory_subparsers.add_parser(
        "export",
        help="Export session memory",
        description="Export session data to various formats",
    )
    export_parser.add_argument(
        "session_id",
        help="Session ID to export",
    )
    export_parser.add_argument(
        "--format",
        choices=["json", "csv", "markdown"],
        default="json",
        help="Export format (default: json)",
    )
    export_parser.set_defaults(func=cmd_export_session)

    # Search command
    search_parser = memory_subparsers.add_parser(
        "search",
        help="Search session memory",
        description="Search through session memory for specific content",
    )
    search_parser.add_argument(
        "session_id",
        help="Session ID to search",
    )
    search_parser.add_argument(
        "query",
        help="Search query string",
    )
    search_parser.add_argument(
        "--type",
        choices=["state", "conversations", "logs", "all"],
        default="all",
        help="Type of memory to search (default: all)",
    )
    search_parser.set_defaults(func=cmd_search_session)


def get_session_store() -> SessionStore:
    """Get the session store instance."""
    # Default to ~/.hive/agents directory
    hive_dir = Path.home() / ".hive" / "agents"
    return SessionStore(hive_dir)


def format_size(size_bytes: int) -> str:
    """Format bytes in human-readable format."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} TB"


def cmd_list_sessions(args):
    """List all available sessions."""

    async def _list_sessions():
        try:
            store = get_session_store()

            # Get session directories directly since list_sessions is async
            sessions_dir = store.sessions_dir
            if not sessions_dir.exists():
                print("No sessions found.")
                return

            session_dirs = [d for d in sessions_dir.iterdir() if d.is_dir()]

            # Filter by agent if specified
            if args.agent:
                session_dirs = [s for s in session_dirs if args.agent in str(s)]

            # Limit results
            session_dirs = session_dirs[: args.limit]

            if not session_dirs:
                print("No sessions found.")
                return

            print(f"\n{'Session ID':<40} {'Created':<20} {'Size':<10}")
            print("-" * 75)

            for session_path in session_dirs:
                try:
                    session_id = session_path.name
                    state_file = session_path / "state.json"

                    if state_file.exists():
                        with open(state_file) as f:
                            state = json.load(f)
                        created = state.get("created_at", "Unknown")
                        created_str = created[:19] if len(created) > 19 else created

                        # Calculate session size
                        total_size = sum(
                            f.stat().st_size for f in session_path.rglob("*") if f.is_file()
                        )
                        size_str = format_size(total_size)
                    else:
                        created_str = "Unknown"
                        size_str = "Unknown"

                    print(f"{session_id:<40} {created_str:<20} {size_str:<10}")

                except Exception as e:
                    print(f"{session_path.name:<40} Error: {str(e)}")

            print(f"\nShowing {len(session_dirs)} sessions")

        except Exception as e:
            print(f"Error listing sessions: {e}", file=sys.stderr)
            sys.exit(1)

    asyncio.run(_list_sessions())


def cmd_inspect_session(args):
    """Inspect a specific session."""
    try:
        store = get_session_store()
        session_path = store.base_path / args.session_id

        if not session_path.exists():
            print(f"Session {args.session_id} not found.")
            return

        print(f"\n=== Session Inspection: {args.session_id} ===\n")

        # Inspect state
        if args.type in ["state", "all"]:
            state_file = session_path / "state.json"
            if state_file.exists():
                print("📋 Session State:")
                with open(state_file) as f:
                    state = json.load(f)

                print(f"  Created: {state.get('created_at', 'Unknown')}")
                print(f"  Updated: {state.get('updated_at', 'Unknown')}")
                print(f"  Status: {state.get('status', 'Unknown')}")
                print(f"  Agent: {state.get('agent_id', 'Unknown')}")
                print()
            else:
                print("❌ No state.json found\n")

        # Inspect conversations
        if args.type in ["conversations", "all"]:
            conv_dir = session_path / "conversations"
            if conv_dir.exists():
                print("💬 Conversations:")
                conv_files = list(conv_dir.glob("*.json"))
                print(f"  Found {len(conv_files)} conversation files")
                for conv_file in conv_files[:5]:  # Show first 5
                    print(f"    - {conv_file.name}")
                if len(conv_files) > 5:
                    print(f"    ... and {len(conv_files) - 5} more")
                print()
            else:
                print("❌ No conversations directory\n")

        # Inspect logs
        if args.type in ["logs", "all"]:
            logs_dir = session_path / "logs"
            if logs_dir.exists():
                print("📊 Logs:")
                log_files = list(logs_dir.glob("*"))
                for log_file in log_files:
                    size = log_file.stat().st_size if log_file.is_file() else 0
                    print(f"    - {log_file.name} ({format_size(size)})")
                print()
            else:
                print("❌ No logs directory\n")

        # Inspect artifacts
        if args.type in ["artifacts", "all"]:
            artifacts_dir = session_path / "artifacts"
            if artifacts_dir.exists():
                print("🎁 Artifacts:")
                artifact_files = list(artifacts_dir.rglob("*"))
                artifact_files = [f for f in artifact_files if f.is_file()]
                print(f"  Found {len(artifact_files)} artifact files")
                for artifact_file in artifact_files[:5]:  # Show first 5
                    rel_path = artifact_file.relative_to(artifacts_dir)
                    size = artifact_file.stat().st_size
                    print(f"    - {rel_path} ({format_size(size)})")
                if len(artifact_files) > 5:
                    print(f"    ... and {len(artifact_files) - 5} more")
                print()
            else:
                print("❌ No artifacts directory\n")

    except Exception as e:
        print(f"Error inspecting session: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_cleanup_session(args):
    """Clean up a session."""
    try:
        store = get_session_store()
        session_path = store.base_path / args.session_id

        if not session_path.exists():
            print(f"Session {args.session_id} not found.")
            return

        if args.dry_run:
            print(f"🔍 Dry run - would clean up session: {args.session_id}")

            # Show what would be deleted
            files = list(session_path.rglob("*"))
            files = [f for f in files if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)

            print(f"  Files to delete: {len(files)}")
            print(f"  Space to free: {format_size(total_size)}")

            for file_path in files[:10]:  # Show first 10
                rel_path = file_path.relative_to(session_path)
                print(f"    - {rel_path}")

            if len(files) > 10:
                print(f"    ... and {len(files) - 10} more files")
        else:
            print(f"🧹 Cleaning up session: {args.session_id}")

            # Calculate size before deletion
            files = list(session_path.rglob("*"))
            files = [f for f in files if f.is_file()]
            total_size = sum(f.stat().st_size for f in files)

            # Delete the session directory
            import shutil

            shutil.rmtree(session_path)

            print(f"  ✅ Deleted {len(files)} files")
            print(f"  ✅ Freed {format_size(total_size)}")
            print(f"  ✅ Session {args.session_id} cleaned up successfully")

    except Exception as e:
        print(f"Error cleaning up session: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_analyze_session(args):
    """Analyze session memory usage."""
    try:
        store = get_session_store()
        session_path = store.base_path / args.session_id

        if not session_path.exists():
            print(f"Session {args.session_id} not found.")
            return

        print(f"\n📊 Memory Analysis: {args.session_id}\n")

        # Collect statistics
        stats = {"total_files": 0, "total_size": 0, "by_type": {}, "largest_files": []}

        for file_path in session_path.rglob("*"):
            if file_path.is_file():
                size = file_path.stat().st_size
                stats["total_files"] += 1
                stats["total_size"] += size

                # Categorize by directory
                category = file_path.parent.name
                if category not in stats["by_type"]:
                    stats["by_type"][category] = {"count": 0, "size": 0}
                stats["by_type"][category]["count"] += 1
                stats["by_type"][category]["size"] += size

                # Track largest files
                stats["largest_files"].append(
                    {"path": str(file_path.relative_to(session_path)), "size": size}
                )

        # Sort largest files
        stats["largest_files"].sort(key=lambda x: x["size"], reverse=True)

        if args.summary:
            print(f"Total Files: {stats['total_files']}")
            print(f"Total Size: {format_size(stats['total_size'])}")
            avg_size = stats["total_size"] // max(stats["total_files"], 1)
            print(f"Average File Size: {format_size(avg_size)}")
        else:
            print("📈 Overall Statistics:")
            print(f"  Total Files: {stats['total_files']}")
            print(f"  Total Size: {format_size(stats['total_size'])}")
            avg_size = stats["total_size"] // max(stats["total_files"], 1)
            print(f"  Average File Size: {format_size(avg_size)}")
            print()

            print("📂 By Type:")
            for category, data in sorted(stats["by_type"].items()):
                if stats["total_size"] > 0:
                    percentage = (data["size"] / stats["total_size"]) * 100
                else:
                    percentage = 0
                print(f"  {category}:")
                print(f"    Files: {data['count']}")
                print(f"    Size: {format_size(data['size'])} ({percentage:.1f}%)")
            print()

            print("🔝 Largest Files:")
            for file_info in stats["largest_files"][:10]:
                print(f"  {file_info['path']}: {format_size(file_info['size'])}")

    except Exception as e:
        print(f"Error analyzing session: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_export_session(args):
    """Export session data."""
    try:
        store = get_session_store()
        session_path = store.base_path / args.session_id

        if not session_path.exists():
            print(f"Session {args.session_id} not found.")
            return

        # Collect all session data
        export_data = {
            "session_id": args.session_id,
            "exported_at": datetime.now().isoformat(),
            "format": args.format,
            "data": {},
        }

        # Load state
        state_file = session_path / "state.json"
        if state_file.exists():
            with open(state_file) as f:
                export_data["data"]["state"] = json.load(f)

        # Load conversations
        conv_dir = session_path / "conversations"
        if conv_dir.exists():
            export_data["data"]["conversations"] = {}
            for conv_file in conv_dir.glob("*.json"):
                with open(conv_file) as f:
                    export_data["data"]["conversations"][conv_file.stem] = json.load(f)

        # Load logs
        logs_dir = session_path / "logs"
        if logs_dir.exists():
            export_data["data"]["logs"] = {}
            for log_file in logs_dir.glob("*"):
                if log_file.is_file():
                    with open(log_file) as f:
                        content = f.read()
                        if log_file.suffix == ".jsonl":
                            # Parse JSONL
                            content_lines = content.strip().split("\n")
                            lines = [json.loads(line) for line in content_lines if line.strip()]
                            export_data["data"]["logs"][log_file.name] = lines
                        else:
                            export_data["data"]["logs"][log_file.name] = content

        # Export based on format
        if args.format == "json":
            output_file = f"{args.session_id}_export.json"
            with open(output_file, "w") as f:
                json.dump(export_data, f, indent=2)
            print(f"✅ Exported to {output_file}")

        elif args.format == "markdown":
            output_file = f"{args.session_id}_export.md"
            with open(output_file, "w") as f:
                f.write(f"# Session Export: {args.session_id}\n\n")
                f.write(f"Exported at: {export_data['exported_at']}\n\n")

                if "state" in export_data["data"]:
                    f.write("## Session State\n\n")
                    f.write("```json\n")
                    f.write(json.dumps(export_data["data"]["state"], indent=2))
                    f.write("\n```\n\n")

                if "conversations" in export_data["data"]:
                    f.write("## Conversations\n\n")
                    for conv_name, conv_data in export_data["data"]["conversations"].items():
                        f.write(f"### {conv_name}\n\n")
                        f.write("```json\n")
                        f.write(json.dumps(conv_data, indent=2))
                        f.write("\n```\n\n")

            print(f"✅ Exported to {output_file}")

        elif args.format == "csv":
            # Create CSV summary
            import csv

            output_file = f"{args.session_id}_export.csv"
            with open(output_file, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["Type", "Name", "Size", "Created"])

                for file_path in session_path.rglob("*"):
                    if file_path.is_file():
                        size = file_path.stat().st_size
                        category = file_path.parent.name
                        writer.writerow([category, file_path.name, size, ""])

            print(f"✅ Exported to {output_file}")

    except Exception as e:
        print(f"Error exporting session: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_search_session(args):
    """Search through session memory."""
    try:
        store = get_session_store()
        session_path = store.base_path / args.session_id

        if not session_path.exists():
            print(f"Session {args.session_id} not found.")
            return

        print(f"\n🔍 Searching in session: {args.session_id}")
        print(f"Query: '{args.query}'\n")

        matches = []
        query_lower = args.query.lower()

        # Search in state
        if args.type in ["state", "all"]:
            state_file = session_path / "state.json"
            if state_file.exists():
                with open(state_file) as f:
                    state_content = f.read().lower()
                    if query_lower in state_content:
                        matches.append(("state.json", "Session state"))

        # Search in conversations
        if args.type in ["conversations", "all"]:
            conv_dir = session_path / "conversations"
            if conv_dir.exists():
                for conv_file in conv_dir.glob("*.json"):
                    with open(conv_file) as f:
                        conv_content = f.read().lower()
                        if query_lower in conv_content:
                            matches.append((f"conversations/{conv_file.name}", "Conversation"))

        # Search in logs
        if args.type in ["logs", "all"]:
            logs_dir = session_path / "logs"
            if logs_dir.exists():
                for log_file in logs_dir.glob("*"):
                    if log_file.is_file():
                        with open(log_file, encoding="utf-8", errors="ignore") as f:
                            log_content = f.read().lower()
                            if query_lower in log_content:
                                matches.append((f"logs/{log_file.name}", "Log file"))

        # Display results
        if matches:
            print(f"Found {len(matches)} matches:\n")
            for file_path, file_type in matches:
                print(f"📄 {file_type}: {file_path}")
        else:
            print("No matches found.")

    except Exception as e:
        print(f"Error searching session: {e}", file=sys.stderr)
        sys.exit(1)
