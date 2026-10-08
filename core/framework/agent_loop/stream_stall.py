"""Stream-stall reminder source.

A :class:`ReminderSource` for the reactive :class:`ReminderPoint.STREAM_STALLED`.
When the stream watchdog in ``_run_turn_loop`` cancels a stalled stream,
the loop consults this source *synchronously* (``hub.collect`` inline) and
injects the returned nudge before re-streaming the same turn — so unlike the
idle nudge it cannot be deferred to the iteration-boundary drain.

The watchdog still owns *detecting* the stall and cancelling the stream; this
source owns only the nudge text and the per-turn cap. ``reset_turn`` must be
called by the loop at the start of every turn so the cap counts per turn.
"""

from __future__ import annotations

import logging

from framework.agent_loop.reminders import (
    Reminder,
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)

# Human-readable label per watchdog verdict — preserved verbatim from the
# pre-refactor inline nudge so the message the model sees is unchanged.
_REASON_LABELS = {
    "ttft": "no tokens before TTFT budget",
    "inactive": "stream went silent after producing events",
}


class StreamStallSource(ReminderSource):
    """Continue-nudge for a stalled LLM stream.

    Fires only at :attr:`ReminderPoint.STREAM_STALLED`. The per-turn cap
    keeps a genuinely dead endpoint from being nudged forever — once the
    cap is reached ``render`` returns ``None`` and the caller falls back
    to its stream-retry / error path.
    """

    name = "stream_stall"

    def __init__(self, *, max_per_turn: int, enabled: bool) -> None:
        self._max_per_turn = max_per_turn
        self._enabled = enabled
        self._nudges_this_turn = 0

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.STREAM_STALLED}

    def reset_turn(self) -> None:
        """Reset the per-turn nudge counter — call once per turn."""
        self._nudges_this_turn = 0

    async def render(self, rctx: ReminderContext) -> Reminder | None:
        if not self._enabled or self._max_per_turn <= 0:
            return None
        if self._nudges_this_turn >= self._max_per_turn:
            return None
        sig = rctx.signals
        if sig is None or sig.stall_reason is None:
            return None
        self._nudges_this_turn += 1
        label = _REASON_LABELS.get(sig.stall_reason, sig.stall_reason)
        body = (
            f"The previous stream stalled ({label}, "
            f"{sig.stall_elapsed:.0f}s). Continue from the last tool "
            "result already in this conversation. Do NOT repeat tool "
            "calls whose results are visible above — reuse them and "
            "move to the next step."
        )
        logger.info(
            "[stream_stall] producing nudge (count=%d/%d, reason=%s, elapsed=%.0fs)",
            self._nudges_this_turn,
            self._max_per_turn,
            sig.stall_reason,
            sig.stall_elapsed,
        )
        return Reminder(
            body=body,
            source=self.name,
            meta={
                "reason": sig.stall_reason,
                "elapsed": sig.stall_elapsed,
                "nudge_count": self._nudges_this_turn,
                "cap": self._max_per_turn,
            },
        )
