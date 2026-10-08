"""Process-global launch status for the web dashboard.

The Electron desktop shell owns a staged loading screen, but when the
runtime is opened via ``hive open`` the browser lands on the SPA while
the first queen session is still bootstrapping (MCP tool servers,
history scan, prompt composition) — previously a bare spinner with no
hint of progress. The bootstrap path reports coarse stages here and the
frontend's loading overlay polls ``GET /api/startup-status`` to display
them.

Deliberately tiny: a stage is a display string, not a state machine.
Reporting is fire-and-forget from whatever thread or task is booting;
readers get the latest stage plus a short history for debugging. A
later cold-session resume reports through the same channel, so the
overlay shows progress on every slow session open, not just the first.
"""

import threading
import time

_MAX_HISTORY = 32

_lock = threading.Lock()
_state: dict = {
    "ready": False,
    "stage": "Starting runtime",
    "detail": "",
    "updated_at": time.time(),
    "history": [],
}


def report(stage: str, detail: str = "") -> None:
    """Record a boot stage. Marks the runtime busy until :func:`mark_ready`."""
    with _lock:
        _state["ready"] = False
        _state["stage"] = stage
        _state["detail"] = detail
        _state["updated_at"] = time.time()
        _state["history"].append({"stage": stage, "detail": detail, "at": _state["updated_at"]})
        del _state["history"][:-_MAX_HISTORY]


def mark_ready(stage: str = "Ready") -> None:
    """Record that the current bootstrap finished."""
    with _lock:
        _state["ready"] = True
        _state["stage"] = stage
        _state["detail"] = ""
        _state["updated_at"] = time.time()
        _state["history"].append({"stage": stage, "detail": "", "at": _state["updated_at"]})
        del _state["history"][:-_MAX_HISTORY]


def get_status() -> dict:
    """Snapshot for GET /api/startup-status."""
    with _lock:
        return {
            "ready": _state["ready"],
            "stage": _state["stage"],
            "detail": _state["detail"],
            "updated_at": _state["updated_at"],
            "history": list(_state["history"]),
        }
