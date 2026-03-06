"""Trigger definitions for queen-level heartbeats (timers, webhooks)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerDefinition:
    """A registered trigger that can be activated on the queen runtime.

    Trigger *definitions* come from the worker's ``async_entry_points``.
    Activation state is per-session (persisted in ``SessionState.active_triggers``).
    """

    id: str
    trigger_type: str  # "timer" | "webhook"
    trigger_config: dict[str, Any] = field(default_factory=dict)
    description: str = ""
    active: bool = False
