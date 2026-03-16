"""
Session Store - Unified session storage with state.json.

Handles reading and writing session state to the new unified structure:
  sessions/session_YYYYMMDD_HHMMSS_{uuid}/state.json
"""

import asyncio
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from framework.schemas.session_state import SessionState
from framework.utils.io import atomic_write

logger = logging.getLogger(__name__)

SAFE_SESSION_ID = re.compile(r"^[a-zA-Z0-9_-]+$")


class SessionStore:
    """
    Unified session storage with state.json.

    Manages sessions in the new structure:
      {base_path}/sessions/session_YYYYMMDD_HHMMSS_{uuid}/
        ├── state.json            # Single source of truth
        ├── conversations/        # Flat EventLoop state (parts carry phase_id)
        ├── artifacts/            # Spillover data
        └── logs/                 # L1/L2/L3 observability
            ├── summary.json
            ├── details.jsonl
            └── tool_logs.jsonl
    """

    def __init__(self, base_path: Path):
        self.base_path = Path(base_path)
        self.sessions_dir = self.base_path / "sessions"

    def generate_session_id(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        short_uuid = uuid.uuid4().hex[:8]
        return f"session_{timestamp}_{short_uuid}"

    def get_session_path(self, session_id: str) -> Path:
        """
        Get path to session directory.

        Raises:
            ValueError: If session_id contains path traversal or invalid characters
        """
        if not SAFE_SESSION_ID.match(session_id):
            raise ValueError(f"Invalid session ID format: {session_id}")

        sessions_dir = self.sessions_dir.resolve()
        session_path = (sessions_dir / session_id).resolve()

        if not session_path.is_relative_to(sessions_dir):
            raise ValueError("Access denied: path traversal detected")

        return session_path

    def get_state_path(self, session_id: str) -> Path:
        return self.get_session_path(session_id) / "state.json"

    async def write_state(self, session_id: str, state: SessionState) -> None:
        def _write():
            state_path = self.get_state_path(session_id)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with atomic_write(state_path) as f:
                f.write(state.model_dump_json(indent=2))
        await asyncio.to_thread(_write)
        logger.debug(f"Wrote state.json for session {session_id}")

    async def read_state(self, session_id: str) -> SessionState | None:
        def _read():
            state_path = self.get_state_path(session_id)
            if not state_path.exists():
                return None
            return SessionState.model_validate_json(state_path.read_text(encoding="utf-8"))
        return await asyncio.to_thread(_read)

    async def list_sessions(
        self,
        status: str | None = None,
        goal_id: str | None = None,
        limit: int = 100,
    ) -> list[SessionState]:
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
                    state = SessionState.model_validate_json(state_path.read_text(encoding="utf-8"))
                    if status and state.status != status:
                        continue
                    if goal_id and state.goal_id != goal_id:
                        continue
                    sessions.append(state)
                except Exception as e:
                    logger.warning(f"Failed to load {state_path}: {e}")
                    continue
            sessions.sort(key=lambda s: s.timestamps.updated_at, reverse=True)
            return sessions[:limit]
        return await asyncio.to_thread(_scan)

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and all its data.

        Args:
            session_id: Session ID to delete

        Returns:
            True if deleted, False if not found or invalid
        """
        def _delete():
            import shutil
            try:
                session_path = self.get_session_path(session_id)
            except ValueError:
                logger.warning(f"Invalid session ID attempted: {session_id}")
                return False
            if not session_path.exists():
                return False
            shutil.rmtree(session_path)
            logger.info(f"Deleted session {session_id}")
            return True
        return await asyncio.to_thread(_delete)

    async def session_exists(self, session_id: str) -> bool:
        def _check():
            try:
                return self.get_state_path(session_id).exists()
            except ValueError:
                return False
        return await asyncio.to_thread(_check)
