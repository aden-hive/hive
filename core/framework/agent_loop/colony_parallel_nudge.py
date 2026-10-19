"""Colony-phase 'fan out via playbook' nudge.

A :class:`ReminderSource` that fires AFTER a colony-phase queen completes her
own *pilot* — does one unit end-to-end (``browser_*``/``web_scrape`` work) and
records the result in the tracker — to suggest she now factor the protocol into
a skill + playbook and converge the rest via ``run_playbook``.

Why gate on the pilot (not on inline browsing): a queen who runs the first unit
herself discovers the real selectors/edge-cases, validates the protocol, and
seeds the tracker — so the playbook she writes next is correct. Nudging *before*
the pilot would push her to fan out a guess. The nudge therefore stays quiet
until both signals are present:

  * she has done **pilot work** (a ``browser_*`` / ``web_scrape`` call) in this
    colony-phase session, and
  * she **just wrote to the tracker** (``tracker_upsert`` / ``tracker_sql``) —
    i.e. recorded the completed unit.

It goes silent again once she calls ``run_playbook`` (she's fanning out).

Scope and gating:

  * **Queen only** — ``applies_to`` returns False for any non-queen agent.
  * **Colony phase only** — checked at render time via the live tool list
    (``run_playbook`` / ``run_worker`` present).
  * **Per-turn cooldown + per-session cap** — so a queen who keeps doing rows
    inline is nudged repeatedly but not on every turn.

Policy (cooldown, cap, message) lives here. State is in-memory per ``AgentLoop``;
the nudge is advisory and a restart resetting it is harmless.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


# Turns between successive reminders. A queen still doing rows inline after the
# pilot gets nudged again, just not every turn.
COLONY_PARALLEL_COOLDOWN_TURNS = _env_int("HIVE_COLONY_PARALLEL_COOLDOWN", 4)
# Hard cap on firings per session — keeps the reminder from becoming wallpaper.
COLONY_PARALLEL_MAX_PER_SESSION = _env_int("HIVE_COLONY_PARALLEL_MAX", 4)

# A tool call that counts as "pilot work" — actually executing a unit (vs.
# orchestration / tracker bookkeeping). Substring/prefix checks are fine: no
# non-browser tool begins with this prefix today.
_WORK_TOOL_PREFIX = "browser_"
_WORK_TOOL_NAMES = frozenset({"web_scrape"})
# Writing the result of a unit into the tracker — the "I finished one" signal.
_TRACKER_WRITE_TOOLS = frozenset({"tracker_upsert", "tracker_sql"})
# The fan-out tool — once used, the queen is already converging; stop nudging.
_FANOUT_TOOL = "run_playbook"
# Tools whose presence in the live tool list indicates colony phase.
_COLONY_PHASE_MARKER_TOOLS = frozenset({"run_playbook", "run_worker"})


_REMINDER_BODY = (
    "You've completed a pilot unit and recorded it in the tracker. "
    "Think if the protocol works. It it works, don't keep doing rows inline. "
    "Factor it into a skill (write_skill), "
    "write a playbook, and call run_playbook to converge the "
    "rest of the table"
)


class ColonyParallelNudgeSource(ReminderSource):
    """Nudge a colony-phase queen toward ``run_playbook`` once she's piloted.

    Fires at :attr:`ReminderPoint.POST_TOOL_USE` on a turn that wrote to the
    tracker, provided she has already done pilot work this session, has not yet
    called ``run_playbook``, is in colony phase, and the cooldown / cap allow.
    """

    name = "colony_parallel"

    def __init__(
        self,
        *,
        cooldown_turns: int = COLONY_PARALLEL_COOLDOWN_TURNS,
        max_per_session: int = COLONY_PARALLEL_MAX_PER_SESSION,
    ) -> None:
        self._cooldown_turns = cooldown_turns
        self._max_per_session = max_per_session
        # Start high so the first eligible turn is never blocked by cooldown.
        self._turns_since_last_reminder = 1_000_000
        self._reminders_sent = 0
        # Sticky: has the queen done pilot work (executed a unit) at all yet?
        self._did_pilot_work = False
        # Sticky: has she started fanning out via run_playbook? Then stop.
        self._fanned_out = False
        # Per-turn: did THIS turn record a unit in the tracker?
        self._wrote_tracker_this_turn = False

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.POST_TOOL_USE}

    def applies_to(self, agent_ctx: Any) -> bool:
        """Queens only. Phase is rechecked at render time (it can change)."""
        return bool(getattr(agent_ctx, "is_queen_stream", False))

    def observe_turn(self, tool_names: list[str]) -> None:
        """Track pilot-work / tracker-write / fan-out signals and tick cooldown."""
        self._turns_since_last_reminder += 1
        if any(self._is_work_tool(n) for n in tool_names):
            self._did_pilot_work = True
        if _FANOUT_TOOL in tool_names:
            self._fanned_out = True
        self._wrote_tracker_this_turn = any(n in _TRACKER_WRITE_TOOLS for n in tool_names)

    @staticmethod
    def _is_work_tool(name: str) -> bool:
        return name.startswith(_WORK_TOOL_PREFIX) or name in _WORK_TOOL_NAMES

    async def render(self, rctx: ReminderContext) -> str | None:
        # Only after the pilot: work done AND a unit just recorded.
        if not self._did_pilot_work or not self._wrote_tracker_this_turn:
            return None
        # Already converging — nothing to nudge.
        if self._fanned_out:
            return None
        if self._reminders_sent >= self._max_per_session:
            return None
        if self._turns_since_last_reminder < self._cooldown_turns:
            return None
        if not _is_colony_phase(rctx.agent_ctx):
            return None
        self._turns_since_last_reminder = 0
        self._reminders_sent += 1
        return _REMINDER_BODY


def _is_colony_phase(agent_ctx: Any) -> bool:
    """True when the queen's live tool list exposes a colony fan-out tool.

    Uses ``dynamic_tools_provider`` (the phase-aware accessor — see
    ``QueenPhaseState.get_current_tools``) rather than the static
    ``available_tools`` snapshot, which is set once at bind time and does not
    reflect a mid-session phase switch.
    """
    provider = getattr(agent_ctx, "dynamic_tools_provider", None)
    if provider is None:
        tools = getattr(agent_ctx, "available_tools", None) or []
    else:
        try:
            tools = provider() or []
        except Exception:
            logger.debug(
                "colony_parallel: dynamic_tools_provider raised; falling back to available_tools",
                exc_info=True,
            )
            tools = getattr(agent_ctx, "available_tools", None) or []
    return any(getattr(t, "name", "") in _COLONY_PHASE_MARKER_TOOLS for t in tools)
