"""Sender rotation + per-day usage counters.

The "easy primitive" the agent uses to rotate senders across a campaign.
Given a candidate pool it picks the next sender under one of three policies
and enforces per-sender ``daily_limit``. Usage is persisted per UTC day so
limits survive process restarts within a day.

State file: ``$HIVE_HOME/senders/usage.json`` (falls back to
``~/.hive/senders/usage.json``). Writes are best-effort atomic; under heavy
cross-process concurrency the counts may undercount slightly — acceptable
for rotation/limit shaping, not billing.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .registry import SenderConfig

log = logging.getLogger(__name__)

Policy = str  # "round_robin" | "weighted" | "least_used"
_POLICIES = ("round_robin", "weighted", "least_used")


def _state_path() -> Path:
    base = os.environ.get("HIVE_HOME") or str(Path.home() / ".hive")
    return Path(base) / "senders" / "usage.json"


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _load_state() -> dict[str, Any]:
    path = _state_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception as e:  # pragma: no cover - defensive
        log.warning("Sender usage: failed to read state: %s", e)
    return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except Exception as e:  # pragma: no cover - defensive
        log.warning("Sender usage: failed to write state: %s", e)


def _usage_today(state: dict[str, Any]) -> dict[str, int]:
    """Return today's per-sender counts, resetting on a new UTC day."""
    today = _today()
    if state.get("date") != today:
        state["date"] = today
        state["usage"] = {}
    usage = state.setdefault("usage", {})
    return usage


def usage_today() -> dict[str, int]:
    """Public read of today's per-sender send counts."""
    state = _load_state()
    return dict(_usage_today(state))


def record_send(sender_id: str) -> None:
    """Increment today's counter for a sender after a successful send."""
    state = _load_state()
    usage = _usage_today(state)
    usage[sender_id] = int(usage.get(sender_id, 0)) + 1
    _save_state(state)


def remaining_today(sender: SenderConfig) -> int | None:
    """Sends left for this sender today. None means no limit is set.

    Exists because a daily limit enforced only inside :func:`pick` is not a
    limit at all: the picker is bypassed whenever an agent addresses a sender
    BY NAME (send_from_sender), which is exactly what personalized outreach
    does — one custom message per recipient, in a loop. Enforcement has to sit
    at the send boundary, so the check lives here and every send path calls it.
    """
    if sender.daily_limit is None:
        return None
    sent = usage_today().get(sender.id, 0)
    return max(0, sender.daily_limit - int(sent))


def _pool_key(senders: list[SenderConfig]) -> str:
    return "|".join(sorted(s.id for s in senders))


def _eligible(senders: list[SenderConfig], usage: dict[str, int]) -> list[SenderConfig]:
    out: list[SenderConfig] = []
    for s in senders:
        if not s.enabled:
            continue
        if s.daily_limit is not None and usage.get(s.id, 0) >= s.daily_limit:
            continue
        out.append(s)
    return out


def pick(
    senders: list[SenderConfig],
    policy: Policy = "round_robin",
    usage: dict[str, int] | None = None,
) -> SenderConfig | None:
    """Pick the next sender from ``senders`` under ``policy``.

    Skips disabled senders and any that have hit their ``daily_limit`` today.
    Returns None if no sender is eligible.

    ``usage`` is the team-wide count from the cloud send log, passed in by the
    caller. It must be injected rather than read from local state, because the
    local file only ever knew about THIS device — a sender a teammate had
    already exhausted still looked fresh here. Rotation is only a preference,
    though: the cap is enforced by the cloud reservation at send time, which is
    the one place that can be atomic.

    The rotation CURSORS remain local. They're a fairness heuristic, not a
    safety rail, so a per-device cursor is harmless.
    """
    if policy not in _POLICIES:
        policy = "round_robin"
    state = _load_state()
    if usage is None:
        usage = _usage_today(state)
    eligible = _eligible(senders, usage)
    if not eligible:
        return None

    chosen: SenderConfig
    if policy == "least_used":
        chosen = min(eligible, key=lambda s: usage.get(s.id, 0))
    elif policy == "weighted":
        # Expand by weight, then advance a persisted cursor over the expansion.
        expanded: list[SenderConfig] = []
        for s in eligible:
            expanded.extend([s] * max(1, s.weight))
        cursors = state.setdefault("cursors", {})
        key = "w:" + _pool_key(eligible)
        idx = int(cursors.get(key, 0)) % len(expanded)
        chosen = expanded[idx]
        cursors[key] = (idx + 1) % len(expanded)
        _save_state(state)
    else:  # round_robin
        cursors = state.setdefault("cursors", {})
        key = "r:" + _pool_key(eligible)
        idx = int(cursors.get(key, 0)) % len(eligible)
        chosen = eligible[idx]
        cursors[key] = (idx + 1) % len(eligible)
        _save_state(state)

    return chosen
