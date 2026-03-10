# core/framework/schemas/session_state.py

from datetime import datetime

class SessionState:
    def __init__(self, session_id, status, completed_at=None, paused_at=None):
        self.session_id = session_id
        self.status = status
        self.completed_at = completed_at
        self.paused_at = paused_at

    @classmethod
    def from_execution_result(cls, result):
        now = datetime.now()
        status = "COMPLETED" if result.success else "FAILED"
        completed_at = now if (result.success and not result.paused_at) else None
        paused_at = result.paused_at
        return cls(session_id=result.session_id, status=status, completed_at=completed_at, paused_at=paused_at)