"""
MCP Server for Agent Building Tools
Exposes tools for building goal-driven agents via the Model Context Protocol.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Annotated

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

    def __init__(self, name: str, session_id: str | None = None):
        self.id = session_id or f"build_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.name = name
        self.plan = Plan(goal=Goal(description=f"Build agent: {name}"))
        self.created_at = datetime.now()
        self.updated_at = datetime.now()


class SessionManager:
    """Thread-safe manager for MCP agent building sessions."""

    def __init__(self):
        self._sessions: dict[str, BuildSession] = {}
        self._lock = asyncio.Lock()
        self._active_id: str | None = None

    async def get_active_session(self) -> BuildSession | None:
        async with self._lock:
            if not self._active_id and ACTIVE_SESSION_FILE.exists():
                self._active_id = ACTIVE_SESSION_FILE.read_text().strip()
            return self._sessions.get(self._active_id) if self._active_id else None

    async def set_active_session(self, session: BuildSession):
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


@mcp.tool()
async def get_current_status() -> str:
    """Get the current status of the agent being built."""
    session = await session_manager.get_active_session()
    if not session:
        return "No active session found."
    return f"Active session: {session.name} (ID: {session.id})"
