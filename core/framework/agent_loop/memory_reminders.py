"""How the queen's memory notes reach her before she answers.

Two :class:`ReminderSource`\\ s, one per ``memory_recall.mode`` (``framework.config.MemoryRecallConfig``).
The orchestrator wires both providers; each source shows notes only while its mode is set, read at each
message, so a change in Settings reaches running sessions:

  * :class:`MemoryIndexReminderSource` ("index", the default) — no pick: she is shown every note's
    one-line manifest entry (``agent_ctx.memory_index_provider``) and reads the notes she wants. Shown
    in full at the session's start and after compaction; after that only what changed.
  * :class:`MemoryRecallReminderSource` ("wait") — a model picks the notes for the user's message
    (``agent_ctx.memory_recall_provider``) and the turn waits for the pick, up to ``wait_seconds``.

The "background" mode is neither: the orchestrator picks after the turn has started and injects the
result whenever it lands (``queen_orchestrator._recall_on_user_input``).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)

RECALL_HEADER = "Recalled memories relevant to the latest user message (supersedes earlier recall reminders):"
INDEX_HEADER = (
    "Your memory notes: what earlier conversations taught you, one line per note "
    "(type, file name, what it holds). When one may bear on the conversation, read it with "
    'terminal_exec (cat "<folder>/<file name>"): the line is only its description.'
)
INDEX_CHANGED_HEADER = "Your memory notes changed since they were last listed (same folders):"


class MemoryRecallReminderSource(ReminderSource):
    """Inject the notes a model picked for the user's message, before she answers it."""

    name = "memory_recall"

    def __init__(self) -> None:
        # The last block shown; an unchanged pick isn't shown again.
        self._last = ""

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.SESSION_START, ReminderPoint.USER_PROMPT_SUBMIT, ReminderPoint.POST_COMPACT}

    def applies_to(self, agent_ctx: Any) -> bool:
        return bool(getattr(agent_ctx, "is_queen_stream", False)) and callable(getattr(agent_ctx, "memory_recall_provider", None))

    async def render(self, rctx: ReminderContext) -> str | None:
        from framework.config import get_memory_recall_config

        recall = get_memory_recall_config()
        if rctx.point == ReminderPoint.POST_COMPACT or recall.mode != "wait":
            # The summary doesn't carry the last pick, and one shown before another mode ran may be
            # long out of view: the next pick is shown even if the same.
            self._last = ""
            return None
        text = (rctx.user_text or "").strip()
        if not text:
            return None
        wait = recall.wait_seconds
        try:
            block = await asyncio.wait_for(rctx.agent_ctx.memory_recall_provider(text), timeout=wait)
        except TimeoutError:
            logger.info("memory_recall: the pick took over %.0fs; this turn proceeds without it", wait)
            return None
        except Exception:
            logger.debug("memory_recall: the pick failed", exc_info=True)
            return None
        if not block or block == self._last:
            return None
        self._last = block
        return f"{RECALL_HEADER}\n\n{block}"


class MemoryIndexReminderSource(ReminderSource):
    """List every memory note, so she can read the ones that bear on the conversation."""

    name = "memory_index"

    def __init__(self) -> None:
        # (folder, file name) → the line she was last shown for it.
        self._shown: dict[tuple[str, str], str] = {}
        # folder → the scope's label, for a scope that has since lost its last note.
        self._labels: dict[str, str] = {}

    def points(self) -> set[ReminderPoint]:
        return {ReminderPoint.SESSION_START, ReminderPoint.USER_PROMPT_SUBMIT, ReminderPoint.POST_COMPACT}

    def applies_to(self, agent_ctx: Any) -> bool:
        return bool(getattr(agent_ctx, "is_queen_stream", False)) and callable(getattr(agent_ctx, "memory_index_provider", None))

    async def render(self, rctx: ReminderContext) -> str | None:
        from framework.config import get_memory_recall_config

        if get_memory_recall_config().mode != "index":
            # Listed in full again once this mode is set again.
            self._shown.clear()
            return None
        try:
            scopes = await asyncio.to_thread(rctx.agent_ctx.memory_index_provider)
        except Exception:
            logger.debug("memory_index: listing the notes failed", exc_info=True)
            return None
        current = {(folder.as_posix(), name): line for _, folder, entries in scopes for name, line in entries.items()}
        full = rctx.point in (ReminderPoint.SESSION_START, ReminderPoint.POST_COMPACT) or not self._shown
        shown, self._shown = self._shown, current
        labels = dict(self._labels)
        self._labels.update({folder.as_posix(): label for label, folder, _ in scopes})
        if full:
            return _render_index(scopes) if scopes else None

        sections: list[str] = []
        for label, folder, entries in scopes:
            key = folder.as_posix()
            changed = [line for name, line in entries.items() if shown.get((key, name)) != line]
            removed = sorted(name for (f, name) in shown if f == key and (f, name) not in current)
            if changed or removed:
                sections.append(_render_scope(label, key, changed, removed))
        # A scope whose last note was removed is no longer among ``scopes``.
        listed = {folder.as_posix() for _, folder, _ in scopes}
        for folder in sorted({f for f, _ in shown} - listed):
            sections.append(_render_scope(labels.get(folder, folder), folder, [], sorted(name for f, name in shown if f == folder)))
        if not sections:
            return None
        return INDEX_CHANGED_HEADER + "\n\n" + "\n\n".join(sections)


def _render_index(scopes: list[tuple[str, Any, dict[str, str]]]) -> str:
    sections = [f"## {label} ({folder.as_posix()})\n" + "\n".join(f"- {line}" for line in entries.values()) for label, folder, entries in scopes]
    return INDEX_HEADER + "\n\n" + "\n\n".join(sections)


def _render_scope(label: str, folder: str, changed: list[str], removed: list[str]) -> str:
    parts = [f"## {label} ({folder})"]
    if changed:
        parts.append("New or updated:\n" + "\n".join(f"- {line}" for line in changed))
    if removed:
        parts.append("Removed:\n" + "\n".join(f"- {name}" for name in removed))
    return "\n".join(parts)
