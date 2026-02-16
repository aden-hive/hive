"""
Analytics exporter for Hive agent sessions.
"""
import csv
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

def export_sessions_to_csv(agent_name: str, output_file: str = "sessions.csv") -> None:
    """Export session metadata to CSV."""
    home = Path.home()
    agent_dir = home / ".hive" / "agents" / agent_name
    sessions_dir = agent_dir / "sessions"

    if not sessions_dir.exists():
        print(f"No sessions found for agent '{agent_name}'")
        return

    rows = []
    for session_path in sessions_dir.iterdir():
        if not session_path.is_dir():
            continue
            
        session_id = session_path.name
        state_path = session_path / "state.json"
        
        if not state_path.exists():
            continue
            
        try:
            with open(state_path) as f:
                state = json.load(f)
                
            progress = state.get("progress", {})
            timestamps = state.get("timestamps", {})
            
            row = {
                "session_id": session_id,
                "agent": agent_name,
                "status": "completed" if not progress.get("paused_at") else "paused",
                "steps": progress.get("steps_executed", 0),
                "current_node": progress.get("current_node", ""),
                "started_at": timestamps.get("started_at", ""),
                "updated_at": timestamps.get("updated_at", ""),
                "memory_keys": len(state.get("memory", {})),
            }
            rows.append(row)
        except Exception as e:
            logger.warning(f"Failed to read session {session_id}: {e}")

    if not rows:
        print(f"No valid session data found for '{agent_name}'")
        return

    # Write to CSV
    keys = rows[0].keys()
    try:
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(rows)
        print(f"Exported {len(rows)} sessions to {output_file}")
    except Exception as e:
        print(f"Error writing CSV: {e}")
