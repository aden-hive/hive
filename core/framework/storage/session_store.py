"""
Session Store - Unified session storage with state.json.

Handles reading and writing session state to the new unified structure:
  sessions/session_YYYYMMDD_HHMMSS_{uuid}/state.json
"""

import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path

from framework.schemas.session_state import SessionState
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)


class SessionStore:
    """
    Unified session storage with state.json.

    Manages sessions in the new structure:
      {base_path}/sessions/session_YYYYMMDD_HHMMSS_{uuid}/
        ├── state.json            # Single source of truth
        ├── conversations/        # Per-node EventLoop state
        ├── artifacts/            # Spillover data
        └── logs/                 # L1/L2/L3 observability
            ├── summary.json
            ├── details.jsonl
            └── tool_logs.jsonl
    """

    def __init__(self, base_path: Path):
        """
        Initialize session store.

        Args:
            base_path: Base path for storage (e.g., ~/.hive/agents/deep_research_agent)
        """
        self.base_path = Path(base_path)
        self.sessions_dir = self.base_path / "sessions"

    def generate_session_id(self) -> str:
        """
        Generate session ID in format: session_YYYYMMDD_HHMMSS_{uuid}.

        Returns:
            Session ID string (e.g., "session_20260206_143022_abc12345")
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"session_{timestamp}_{short_uuid}"

    def get_session_path(self, session_id: str) -> Path:
        """
        Get path to session directory.

        Args:
            session_id: Session ID

        Returns:
            Path to session directory
        """
        return self.sessions_dir / session_id

    def get_state_path(self, session_id: str) -> Path:
        """
        Get path to state.json file.

        Args:
            session_id: Session ID

        Returns:
            Path to state.json
        """
        return self.get_session_path(session_id) / "state.json"

    async def write_state(self, session_id: str, state: SessionState) -> None:
        """
        Atomically write state.json for a session.

        Uses temp file + rename for crash safety.

        Args:
            session_id: Session ID
            state: SessionState to write
        """

        def _write():
            state_path = self.get_state_path(session_id)
            state_path.parent.mkdir(parents=True, exist_ok=True)

            with atomic_write(state_path) as f:
                f.write(state.model_dump_json(indent=2))

        await asyncio.to_thread(_write)
        logger.debug(f"Wrote state.json for session {session_id}")

    async def read_state(self, session_id: str) -> SessionState | None:
        """
        Read state.json for a session.

        Args:
            session_id: Session ID

        Returns:
            SessionState or None if not found
        """

        def _read():
            state_path = self.get_state_path(session_id)
            if not state_path.exists():
                return None

            return SessionState.model_validate_json(state_path.read_text())

        return await asyncio.to_thread(_read)

    async def list_sessions(
        self,
        status: str | None = None,
        goal_id: str | None = None,
        limit: int = 100,
    ) -> list[SessionState]:
        """
        List sessions, optionally filtered by status or goal.

        Args:
            status: Optional status filter (e.g., "paused", "completed")
            goal_id: Optional goal ID filter
            limit: Maximum number of sessions to return

        Returns:
            List of SessionState objects
        """

        def _scan():
            sessions = []

            if not self.sessions_dir.exists():
                return sessions

            for session_dir in self.sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                state_path = session_dir / "state.json"
                if not state_path.exists():
                    continue

                try:
                    state = SessionState.model_validate_json(state_path.read_text())

                    # Apply filters
                    if status and state.status != status:
                        continue

                    if goal_id and state.goal_id != goal_id:
                        continue

                    sessions.append(state)

                except Exception as e:
                    logger.warning(f"Failed to load {state_path}: {e}")
                    continue

            # Sort by updated_at descending (most recent first)
            sessions.sort(key=lambda s: s.timestamps.updated_at, reverse=True)
            return sessions[:limit]

        return await asyncio.to_thread(_scan)

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and all its data.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted, False if not found
        """

        def _delete():
            import shutil

            session_path = self.get_session_path(session_id)
            if not session_path.exists():
                return False

            shutil.rmtree(session_path)
            logger.info(f"Deleted session {session_id}")
            return True

        return await asyncio.to_thread(_delete)

    async def session_exists(self, session_id: str) -> bool:
        """
        Check if a session exists.

        Args:
            session_id: Session ID

        Returns:
            True if session exists
        """

        def _check():
            return self.get_state_path(session_id).exists()

        return await asyncio.to_thread(_check)
