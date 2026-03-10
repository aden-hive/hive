# core/framework/schemas/session_state.py

from enum import Enum

class SessionStatus(Enum):
    ACTIVE = 1
    PAUSED = 2
    FAILED = 3
    COMPLETED = 4
    CANCELLED = 5

class SessionState:
    def __init__(self, status: SessionStatus):
        self.status = status

    @property
    def is_resumable(self) -> bool:
        return self.status in (SessionStatus.ACTIVE, SessionStatus.PAUSED, SessionStatus.FAILED)