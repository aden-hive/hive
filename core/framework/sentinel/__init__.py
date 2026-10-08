"""Sentinel — colony-queen autopilot (nudge / escalate-to-human / resume).

Promotes the idle-nudge into a per-colony autopilot: when the queen pauses
before its goal is done, decide whether to nudge it onward, escalate a genuine
blocker to the user over Telegram/Slack, or do nothing. Off by default;
enabled per-colony via ``notifications.json`` and the global ``sentinel`` config.
"""

from framework.sentinel.classifier import (
    VERDICT_CONTINUE,
    VERDICT_DONE,
    VERDICT_NEEDS_HUMAN,
    ClassifierVerdict,
    ParkContext,
    classify_park,
)
from framework.sentinel.escalation_source import EscalationSource
from framework.sentinel.manager import (
    SentinelManager,
    get_sentinel_manager,
    set_sentinel_manager,
)

__all__ = [
    "EscalationSource",
    "SentinelManager",
    "get_sentinel_manager",
    "set_sentinel_manager",
    "ParkContext",
    "ClassifierVerdict",
    "classify_park",
    "VERDICT_CONTINUE",
    "VERDICT_NEEDS_HUMAN",
    "VERDICT_DONE",
]
