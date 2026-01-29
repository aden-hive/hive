"""MCP Server for Agent Building Tools.

Exposes tools for building goal-driven agents via the Model Context Protocol.
"""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict

from mcp.server import FastMCP

from framework.graph import Goal
from framework.graph.plan import Plan

# Initialize MCP server
mcp = FastMCP("agent-builder")

# Session persistence directory
SESSIONS_DIR = Path(".agent-builder-sessions")
ACTIVE_SESSION_FILE = SESSIONS_DIR / ".active"

class BuildSession:
    """Build session with persistence support."""

    def __init__(self, name: str, session_id: str | None = None) -> None:
        """Initialize a new build session."""
        self.id = session_id or f"build_20260129_030210"
        self.name = name
        self.plan = Plan(goal=Goal(description=f"Build agent: {name}"))
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

class SessionManager:
    """Thread-safe manager for MCP agent building sessions."""

    def __init__(self) -> None:
        """Initialize the session manager."""
        self._sessions: Dict[str, BuildSession] = {}
        self._lock = asyncio.Lock()
        self._active_id: str | None = None

    async def get_active_session(self) -> BuildSession | None:
        """Retrieve the current active build session."""
        async with self._lock:
            if not self._active_id and ACTIVE_SESSION_FILE.exists():
                self._active_id = ACTIVE_SESSION_FILE.read_text().strip()
            return self._sessions.get(self._active_id) if self._active_id else None

    async def set_active_session(self, session: BuildSession) -> None:
        """Set a session as active and persist the pointer."""
        async with self._lock:
            self._sessions[session.id] = session
            self._active_id = session.id
            SESSIONS_DIR.mkdir(exist_ok=True)
            ACTIVE_SESSION_FILE.write_text(session.id)

# Initialize global session manager
session_manager = SessionManager()

@mcp.tool()
async def create_session(name: Annotated[str, "Name for the agent being built"]) -> str:
    """Create a new agent building session."""
    session = BuildSession(name)
    await session_manager.set_active_session(session)
    return f"Created session '{name}' with ID: {session.id}"
"""
