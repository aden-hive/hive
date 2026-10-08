"""Process-wide runtime health flag for upstream-network failures.

The renderer-side connectivity banner only sees renderer↔runtime
traffic. When the user's wifi drops or the LLM proxy is unreachable,
all the renderer↔runtime IPC keeps working (it's local) but the
queen's outbound LLM calls fail with DNS/connection errors and
silently retry. Without this module the UI has no signal.

The agent_loop retry path calls ``mark_upstream_degraded(reason)`` on
network-class exceptions (name resolution, connection refused, TLS
handshake timeout) and ``mark_upstream_healthy()`` on the next
successful stream. The ``/api/sessions/live`` SSE feed reads the
current state on each tick and includes it in the payload, so the
renderer's connectivity banner flips amber within ~3 s of wifi loss.

Module-level singleton — there is exactly one runtime per desktop
process so global state is the right shape here.
"""

from __future__ import annotations

import threading
import time
from typing import TypedDict

# Patterns that mark an exception as "the upstream LLM is unreachable
# right now, this is a connectivity issue, not a logic bug." Kept
# narrow so genuine application errors (auth, schema, payment) don't
# light the banner.
_NETWORK_ERROR_MARKERS = (
    "name resolution",  # DNS failure ("Temporary failure in name resolution")
    "name or service not known",
    "cannot connect to host",
    "connection refused",
    "connection reset",
    "network is unreachable",
    "no route to host",
    "ssl handshake",
    "ssl: handshake_failure",
    "remote disconnected",
    "connect timeout",
    "connectionerror",  # Python's bare ConnectionError repr
)


class RuntimeNetworkSnapshot(TypedDict):
    degraded: bool
    reason: str | None
    since_epoch: float | None
    last_event_epoch: float | None


_lock = threading.Lock()
_state: RuntimeNetworkSnapshot = {
    "degraded": False,
    "reason": None,
    "since_epoch": None,
    "last_event_epoch": None,
}


def is_upstream_network_error(exc: BaseException | str) -> bool:
    """True if *exc* (exception or str) reads like a connectivity failure."""
    text = str(exc).lower()
    return any(m in text for m in _NETWORK_ERROR_MARKERS)


def mark_upstream_degraded(reason: str) -> None:
    """Record that an upstream call (LLM proxy, web fetch, etc.) just
    failed with a network-class error. Idempotent — re-flagging while
    already degraded only refreshes ``last_event_epoch`` and leaves
    ``since_epoch`` as the original onset.
    """
    now = time.time()
    with _lock:
        if not _state["degraded"]:
            _state["since_epoch"] = now
        _state["degraded"] = True
        _state["reason"] = reason[:240]  # bound for sensible payload size
        _state["last_event_epoch"] = now


def mark_upstream_healthy() -> None:
    """Record that an upstream call just succeeded. Clears the
    degraded flag if set; otherwise no-op (cheap to call on every
    successful stream)."""
    with _lock:
        if not _state["degraded"]:
            return
        _state["degraded"] = False
        _state["reason"] = None
        _state["since_epoch"] = None
        _state["last_event_epoch"] = time.time()


def get_runtime_network() -> RuntimeNetworkSnapshot:
    """Return a copy of the current runtime network snapshot for
    serialisation into SSE payloads."""
    with _lock:
        return {
            "degraded": _state["degraded"],
            "reason": _state["reason"],
            "since_epoch": _state["since_epoch"],
            "last_event_epoch": _state["last_event_epoch"],
        }
