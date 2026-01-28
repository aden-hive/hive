"""
Session management MCP tools.

Handles session CRUD operations: create, list, load, delete, and status.
"""

import json
from typing import Annotated

from framework.mcp.session import (
    ACTIVE_SESSION_FILE,
    SESSIONS_DIR,
    BuildSession,
    _ensure_sessions_dir,
    _load_session,
    get_session,
    save_session,
    set_current_session,
)


def register(mcp):
    """Register session management tools on the MCP server."""

    @mcp.tool()
    def create_session(name: Annotated[str, "Name for the agent being built"]) -> str:
        """Create a new agent building session. Call this first before building an agent."""
        session = BuildSession(name)
        set_current_session(session)
        save_session(session)
        return json.dumps(
            {
                "session_id": session.id,
                "name": name,
                "status": "created",
                "persisted": True,
            }
        )

    @mcp.tool()
    def list_sessions() -> str:
        """List all saved agent building sessions."""
        _ensure_sessions_dir()

        sessions = []
        if SESSIONS_DIR.exists():
            for session_file in SESSIONS_DIR.glob("*.json"):
                try:
                    with open(session_file) as f:
                        data = json.load(f)
                        sessions.append(
                            {
                                "session_id": data["session_id"],
                                "name": data["name"],
                                "created_at": data.get("created_at"),
                                "last_modified": data.get("last_modified"),
                                "node_count": len(data.get("nodes", [])),
                                "edge_count": len(data.get("edges", [])),
                                "has_goal": data.get("goal") is not None,
                            }
                        )
                except Exception:
                    pass  # Skip corrupted files

        # Check which session is currently active
        active_id = None
        if ACTIVE_SESSION_FILE.exists():
            try:
                with open(ACTIVE_SESSION_FILE) as f:
                    active_id = f.read().strip()
            except Exception:
                pass

        return json.dumps(
            {
                "sessions": sorted(sessions, key=lambda s: s["last_modified"], reverse=True),
                "total": len(sessions),
                "active_session_id": active_id,
            },
            indent=2,
        )

    @mcp.tool()
    def load_session_by_id(session_id: Annotated[str, "ID of the session to load"]) -> str:
        """Load a previously saved agent building session by its ID."""
        try:
            session = _load_session(session_id)
            set_current_session(session)

            # Update active session pointer
            with open(ACTIVE_SESSION_FILE, "w") as f:
                f.write(session_id)

            return json.dumps(
                {
                    "success": True,
                    "session_id": session.id,
                    "name": session.name,
                    "node_count": len(session.nodes),
                    "edge_count": len(session.edges),
                    "has_goal": session.goal is not None,
                    "created_at": session.created_at,
                    "last_modified": session.last_modified,
                    "message": f"Session '{session.name}' loaded successfully",
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def delete_session(session_id: Annotated[str, "ID of the session to delete"]) -> str:
        """Delete a saved agent building session."""
        from framework.mcp.session import get_current_session_raw

        session_file = SESSIONS_DIR / f"{session_id}.json"
        if not session_file.exists():
            return json.dumps({"success": False, "error": f"Session '{session_id}' not found"})

        try:
            # Remove session file
            session_file.unlink()

            # Clear active session if it was the deleted one
            current = get_current_session_raw()
            if current and current.id == session_id:
                set_current_session(None)

            if ACTIVE_SESSION_FILE.exists():
                with open(ACTIVE_SESSION_FILE) as f:
                    active_id = f.read().strip()
                    if active_id == session_id:
                        ACTIVE_SESSION_FILE.unlink()

            return json.dumps(
                {
                    "success": True,
                    "deleted_session_id": session_id,
                    "message": f"Session '{session_id}' deleted successfully",
                }
            )
        except Exception as e:
            return json.dumps({"success": False, "error": str(e)})

    @mcp.tool()
    def get_session_status() -> str:
        """Get the current status of the build session."""
        session = get_session()
        return json.dumps(
            {
                "session_id": session.id,
                "name": session.name,
                "has_goal": session.goal is not None,
                "goal_name": session.goal.name if session.goal else None,
                "node_count": len(session.nodes),
                "edge_count": len(session.edges),
                "mcp_servers_count": len(session.mcp_servers),
                "nodes": [n.id for n in session.nodes],
                "edges": [(e.source, e.target) for e in session.edges],
                "mcp_servers": [s["name"] for s in session.mcp_servers],
            }
        )
