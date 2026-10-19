"""Turn-context reminder: what installed turn-context packages want the queen to see.

Fires at :attr:`ReminderPoint.SESSION_START` (the session's first message) and
:attr:`ReminderPoint.USER_PROMPT_SUBMIT`, queen-only, when ``agent_ctx.turn_context_provider``
is wired (see ``framework.server.turn_context``). Silent when no package has anything to add.
"""

from __future__ import annotations

from typing import Any

from framework.agent_loop.reminders import ReminderContext, ReminderPoint, ReminderSource


class TurnContextReminderSource(ReminderSource):
    """Put the turn-context packages' text ahead of each user turn."""

    name = "turn_context"

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.SESSION_START, ReminderPoint.USER_PROMPT_SUBMIT}

    def applies_to(self, agent_ctx: Any) -> bool:
        return bool(getattr(agent_ctx, "is_queen_stream", False)) and callable(getattr(agent_ctx, "turn_context_provider", None))

    async def render(self, rctx: ReminderContext) -> str | None:
        text = (rctx.user_text or "").strip()
        if not text:
            return None
        # The provider bounds each package's time and swallows its failures.
        return await rctx.agent_ctx.turn_context_provider(text)
