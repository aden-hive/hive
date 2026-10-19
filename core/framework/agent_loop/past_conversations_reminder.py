"""Past-conversations reminder for the queen.

A :class:`ReminderSource` that puts excerpts of earlier conversations
related to the user's message in front of the queen before she answers.
Without it, recalling history depends on the queen deciding to call
``search_messages`` — and asked "how long is my commute?", she tends to ask
the user instead of looking.

Fires at :attr:`ReminderPoint.SESSION_START` (the session's first message)
and :attr:`ReminderPoint.USER_PROMPT_SUBMIT`, queen-only, when
``agent_ctx.past_conversation_recall_provider`` is wired. Silent when
nothing related clears the provider's relevance bar.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)

# Retrieval runs before the turn starts, so it must never hold a turn
# hostage: past this, the turn proceeds without excerpts.
RECALL_TIMEOUT_S = float(os.environ.get("HIVE_PAST_RECALL_TIMEOUT", "8"))
# Messages shorter than this ("ok", "thanks!") carry no topic to recall by.
MIN_MESSAGE_CHARS = 8


class PastConversationsReminderSource(ReminderSource):
    """Inject related past-conversation excerpts ahead of each user turn."""

    name = "past_conversations"

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.SESSION_START, ReminderPoint.USER_PROMPT_SUBMIT}

    def applies_to(self, agent_ctx: Any) -> bool:
        return bool(getattr(agent_ctx, "is_queen_stream", False)) and callable(getattr(agent_ctx, "past_conversation_recall_provider", None))

    async def render(self, rctx: ReminderContext) -> str | None:
        text = (rctx.user_text or "").strip()
        if len(text) < MIN_MESSAGE_CHARS:
            return None
        provider = rctx.agent_ctx.past_conversation_recall_provider
        try:
            return await asyncio.wait_for(asyncio.to_thread(provider, text), timeout=RECALL_TIMEOUT_S)
        except TimeoutError:
            logger.info("past_conversations: recall exceeded %.0fs; turn proceeds without excerpts", RECALL_TIMEOUT_S)
        except Exception:
            logger.debug("past_conversations: recall failed", exc_info=True)
        return None
