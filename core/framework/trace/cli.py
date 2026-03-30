"""CLI commands for viewing agent execution traces."""

from __future__ import annotations

import json
import logging
from argparse import Namespace
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_agent_dir(agent_name: str) -> Path:
    """Get the agent directory."""
    return Path.home() / ".hive" / "agents" / agent_name


def _parse_timestamp(ts_str: str) -> str:
    """Parse timestamp from various formats."""
    if not ts_str:
        return ""
    try:
        # Try ISO format with Z
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        try:
            # Try ISO format without timezone
            dt = datetime.fromisoformat(ts_str)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, TypeError):
            try:
                # Try timestamp as float
                dt = datetime.fromtimestamp(float(ts_str))
                return dt.strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError) as e:
                logger.debug(f"Failed to parse timestamp '{ts_str}': {e}")
                return ts_str[:19] if len(ts_str) > 19 else ts_str


def _list_sessions(agent_name: str) -> list[dict]:
    """List all sessions for an agent."""
    agent_dir = _get_agent_dir(agent_name)
    sessions_dir = agent_dir / "sessions"

    if not sessions_dir.exists():
        return []

    sessions = []
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue

        state_file = session_dir / "state.json"
        if not state_file.exists():
            continue

        try:
            with open(state_file, encoding="utf-8") as f:
                state = json.load(f)

            session_id = session_dir.name
            timestamps = state.get("timestamps", {})
            started_at = timestamps.get("started_at", "")
            status = state.get("status", "unknown")
            progress = state.get("progress", {})
            steps = progress.get("steps_executed", 0)
            error = state.get("result", {}).get("error", None)

            sessions.append({
                "id": session_id,
                "timestamp": started_at,
                "status": status,
                "steps": steps,
                "error": error,
                "state_file": state_file,
                "state": state,
                "started_at": started_at,  # For sorting
            })
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Could not read {state_file}: {e}")

    # Sort by actual start timestamp, most recent first
    return sorted(sessions, key=lambda s: s.get("started_at", ""), reverse=True)


def _get_conversation_messages(agent_dir: Path, session_id: str) -> list:
    """Get conversation messages from a session."""
    conv_dir = agent_dir / "sessions" / session_id / "conversations"
    if not conv_dir.exists():
        return []

    messages = []
    parts_dir = conv_dir / "parts"
    if parts_dir.exists():
        for part_file in sorted(parts_dir.glob("*.json")):
            try:
                with open(part_file, encoding="utf-8") as f:
                    data = json.load(f)
                    messages.append(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.debug(f"Could not read {part_file}: {e}")
                continue

    return messages


def _display_session_timeline(session: dict) -> None:
    """Display session timeline in human-readable format."""
    session_id = session.get("id", "unknown")
    state = session.get("state", {})
    timestamps = state.get("timestamps", {})
    started_at = timestamps.get("started_at", "")
    paused_at = timestamps.get("paused_at_time", "")
    status = state.get("status", "unknown")
    progress = state.get("progress", {})
    steps = progress.get("steps_executed", 0)
    path = progress.get("path", [])
    memory = state.get("memory", {})
    result = state.get("result", {})
    error = result.get("error", None)

    print("\n" + "═" * 70)
    print(f"Session: {session_id}")
    if started_at:
        print(f"Started: {_parse_timestamp(started_at)}")
    if paused_at:
        print(f"Paused: {_parse_timestamp(paused_at)}")
    print(f"Status: {status}")
    print(f"Steps: {steps}")
    if error:
        print(f"Error: {error}")
    print("═" * 70)

    # Execution Path
    if path:
        print(f"\n🔗 Execution Path: {' → '.join(path)}")

    # Memory
    if memory:
        print(f"\n💾 Memory: {', '.join(list(memory.keys())[:10])}")
        if len(memory) > 10:
            print(f"   ... and {len(memory)-10} more")

    # Conversation
    agent_name = session.get("agent_name", "")
    if agent_name:
        agent_dir = _get_agent_dir(agent_name)
        messages = _get_conversation_messages(agent_dir, session_id)

        if messages:
            print("\n📝 Conversation:")
            for msg in messages[:15]:
                role = msg.get("role", "unknown").upper()
                content = msg.get("content", "")
                if content:
                    # Truncate long content
                    if len(content) > 200:
                        content = content[:200] + "..."
                    print(f"\n[{role}]:")
                    for line in content.split("\n")[:3]:
                        if line.strip():
                            print(f"    {line}")
        else:
            print("\n⚠️ No conversation messages found")

    # Final output
    output = result.get("output", {})
    if output:
        output_json = json.dumps(output, indent=2)
        print(f"\n📤 Output: {output_json[:300]}")
        if len(output_json) > 300:
            print("    ...")

    print("\n" + "═" * 70)


def _display_session_summary(sessions: list) -> None:
    """Display session summary."""
    print(f"\nRecent sessions:")
    print("-" * 80)

    for sess in sessions[:20]:
        session_id = sess["id"]
        short_id = session_id[:20] if len(session_id) > 20 else session_id
        timestamp = _parse_timestamp(sess["timestamp"])

        # Multi-line conditional to avoid long line
        if sess["status"] == "completed":
            status_icon = "✅"
        elif sess["status"] == "paused":
            status_icon = "⏸️"
        else:
            status_icon = "❌"

        steps = sess["steps"]
        print(f"  {short_id:20} | {timestamp:19} | {status_icon} | {steps:3} steps")


def cmd_trace_list(args: Namespace) -> int:
    """List recent sessions for an agent."""
    agent_name = args.agent_name
    sessions = _list_sessions(agent_name)

    if not sessions:
        print(f"No sessions found for agent: {agent_name}")
        print(f"Run an agent first: ./hive run {agent_name} --input '...'")
        return 1

    _display_session_summary(sessions)
    return 0


def cmd_trace_last(args: Namespace) -> int:
    """Show the latest session timeline."""
    agent_name = args.agent_name
    sessions = _list_sessions(agent_name)

    if not sessions:
        print(f"No sessions found for agent: {agent_name}")
        return 1

    latest = sessions[0]
    latest["agent_name"] = agent_name
    _display_session_timeline(latest)
    return 0


def cmd_trace_show(args: Namespace) -> int:
    """Show a specific session by ID."""
    agent_name = args.agent_name
    session_id = args.session_id

    sessions = _list_sessions(agent_name)
    target = None
    for sess in sessions:
        if sess["id"] == session_id:
            target = sess
            break

    if not target:
        print(f"Session not found: {session_id}")
        print(f"Use 'hive trace list {agent_name}' to see available sessions")
        return 1

    target["agent_name"] = agent_name
    _display_session_timeline(target)
    return 0


def cmd_trace_export(args: Namespace) -> int:
    """Export session as JSON."""
    agent_name = args.agent_name
    session_id = args.session_id
    output_file = args.output

    agent_dir = _get_agent_dir(agent_name)
    state_file = agent_dir / "sessions" / session_id / "state.json"

    if not state_file.exists():
        print(f"Session not found: {session_id}")
        return 1

    try:
        with open(state_file, encoding="utf-8") as f:
            session_data = json.load(f)

        # Add conversation messages
        messages = _get_conversation_messages(agent_dir, session_id)
        session_data["conversation"] = messages

        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f, indent=2, default=str)
            print(f"✅ Exported to {output_file}")
        else:
            print(json.dumps(session_data, indent=2, default=str))

        return 0
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error exporting session: {e}")
        return 1


def register_trace_commands(subparsers: Any) -> None:
    """Register trace commands with the CLI parser."""
    trace_parser = subparsers.add_parser(
        "trace",
        help="View agent execution traces",
        description="Display runtime execution logs in human-readable format"
    )

    trace_subparsers = trace_parser.add_subparsers(
        dest="trace_command",
        required=True,
        title="trace commands"
    )

    # list command
    list_parser = trace_subparsers.add_parser(
        "list",
        help="List recent sessions",
        description="Show all recent sessions for an agent"
    )
    list_parser.add_argument(
        "agent_name",
        type=str,
        help="Name of the agent (folder name in ~/.hive/agents/)"
    )
    list_parser.set_defaults(func=cmd_trace_list)

    # last command
    last_parser = trace_subparsers.add_parser(
        "last",
        help="Show latest session timeline",
        description="Display the most recent session with full details"
    )
    last_parser.add_argument(
        "agent_name",
        type=str,
        help="Name of the agent (folder name in ~/.hive/agents/)"
    )
    last_parser.set_defaults(func=cmd_trace_last)

    # show command
    show_parser = trace_subparsers.add_parser(
        "show",
        help="Show specific session by ID",
        description="Display details for a specific session ID"
    )
    show_parser.add_argument(
        "agent_name",
        type=str,
        help="Name of the agent (folder name in ~/.hive/agents/)"
    )
    show_parser.add_argument(
        "session_id",
        type=str,
        help="Session ID to display (from hive trace list)"
    )
    show_parser.set_defaults(func=cmd_trace_show)

    # export command
    export_parser = trace_subparsers.add_parser(
        "export",
        help="Export session as JSON",
        description="Save session details to a JSON file"
    )
    export_parser.add_argument(
        "agent_name",
        type=str,
        help="Name of the agent (folder name in ~/.hive/agents/)"
    )
    export_parser.add_argument(
        "session_id",
        type=str,
        help="Session ID to export (from hive trace list)"
    )
    export_parser.add_argument(
        "--output", "-o",
        type=str,
        help="Output file path (default: stdout)"
    )
    export_parser.set_defaults(func=cmd_trace_export)
