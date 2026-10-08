"""Queen reminder sources for on-demand tool loading + the skills catalog.

Instead of baking the full tool/skill surface into the static system prompt,
the agent is handed a ``<system-reminder>`` that lists what's *available* by
name and tells it how to load the full schema on demand. Two sources:

  * :class:`SearchableToolsReminderSource` — the queen's searchable
    (load-on-demand) tools, with the ``search_tools(query="select:…")`` load
    contract.
  * :class:`SkillsCatalogReminderSource` — the queen's phase-filtered skills
    catalog (the ``<available_skills>`` block), relocated out of the static
    prompt into a reminder.

Both ride the user turn (``USER_PROMPT_SUBMIT``) and the tool-result tail
(``POST_TOOL_USE``), but only render when their content *changes* — so a long
conversation carries the reminder once near its start, not on every turn:

  * Tools emit a true **delta**: tools newly available are announced ("now
    available"); a tool that left the searchable set is dropped *silently* when
    it was loaded (now callable directly) or announced as "no longer available"
    when it was removed from the allowed pool.
  * Skills emit the catalog as one structured ``<available_skills>`` unit when
    it changes (the block carries its own read-the-SKILL.md header, so a
    fragmentary per-skill delta would break it).

At ``POST_COMPACT`` (fired right after the summary is built) both re-announce
their FULL current state into the fresh post-compact context — so the first
post-compact turn still knows what's loadable. This matters because these
surfaces are invisible to the model unless announced (no schema, no tool entry),
and the summary does not faithfully reproduce a tool/skill listing. Both are
queen-only; non-queen contexts leave the backing providers unset and self-skip.
"""

from __future__ import annotations

import logging
from typing import Any

from framework.agent_loop.reminders import (
    ReminderContext,
    ReminderPoint,
    ReminderSource,
)

logger = logging.getLogger(__name__)

# SESSION_START fires once at bringup, just before the first user message is
# seeded and before the first LLM call — without it the manifest would miss the
# opening turn, because the seed message bypasses the injection queue that gates
# USER_PROMPT_SUBMIT. It precedes the seed message so the frame lands ahead of
# the user's request, matching the USER_PROMPT_SUBMIT ordering on later turns. USER_PROMPT_SUBMIT then rides each subsequent inbound
# message; POST_TOOL_USE rides the tool-result tail so a search that just shrank
# the searchable set refreshes in the same turn; POST_COMPACT re-announces the
# full state into the fresh post-summary context. The change-guard makes the
# extra points cheap — they emit only when the content actually changed.
_FIRE_POINTS = {
    ReminderPoint.SESSION_START,
    ReminderPoint.USER_PROMPT_SUBMIT,
    ReminderPoint.POST_TOOL_USE,
    ReminderPoint.POST_COMPACT,
}


class SearchableToolsReminderSource(ReminderSource):
    """Announce a stream's load-on-demand tools as an added/removed delta.

    Reads ``agent_ctx.searchable_tools_provider`` (current searchable ``Tool``
    objects) and ``agent_ctx.loaded_tool_names_provider`` (tools loaded via
    search_tools this session) to classify departures. Tracks the set of names
    already announced so each turn emits only what changed. Serves the queen
    (provider wired from ``QueenPhaseState``) and tiered workers (wired from
    ``ToolTierState`` at spawn); other streams have no provider and skip.
    """

    name = "searchable_tools"

    def __init__(self) -> None:
        # Tool names the model has been told are searchable. The delta is
        # computed against this; it becomes the current set after each emit.
        self._announced: set[str] = set()

    def points(self) -> set[ReminderPoint]:
        return set(_FIRE_POINTS)

    def applies_to(self, agent_ctx: Any) -> bool:
        # Queens always bind (the provider is wired after bind on some boot
        # paths); any other stream binds iff its spawn wired a searchable
        # provider (tiered workers). ``applies_to`` runs once per session, so
        # provider presence must be decided at spawn — which it is.
        if bool(getattr(agent_ctx, "is_queen_stream", False)):
            return True
        return getattr(agent_ctx, "searchable_tools_provider", None) is not None

    async def render(self, rctx: ReminderContext) -> str | None:
        provider = getattr(rctx.agent_ctx, "searchable_tools_provider", None)
        if provider is None:
            return None
        try:
            tools = provider() or []
        except Exception:
            logger.debug("searchable_tools_provider raised", exc_info=True)
            return None
        current = {getattr(t, "name", "") for t in tools if getattr(t, "name", "")}

        if rctx.point == ReminderPoint.POST_COMPACT:
            # Re-announce the full current pool into the fresh post-compact
            # context so the first post-compact turn still knows what's
            # loadable. Reset the baseline to "all current announced".
            self._announced = set(current)
            return _render_searchable_body(added=sorted(current), removed=[]) if current else None

        added = sorted(current - self._announced)
        departed = self._announced - current
        # A departed tool that's now LOADED (eager) is silent — the model
        # already got "Tool loaded" from search_tools. One that's simply gone
        # from the allowed pool (allowlist tightened / server removed) is
        # announced as no longer available.
        loaded = _loaded_names(rctx.agent_ctx)
        removed = sorted(n for n in departed if n not in loaded)
        self._announced = set(current)
        if not added and not removed:
            return None
        return _render_searchable_body(added=added, removed=removed)


def _loaded_names(agent_ctx: Any) -> set[str]:
    provider = getattr(agent_ctx, "loaded_tool_names_provider", None)
    if provider is None:
        return set()
    try:
        return set(provider() or [])
    except Exception:
        logger.debug("loaded_tool_names_provider raised", exc_info=True)
        return set()


def _render_searchable_body(*, added: list[str], removed: list[str]) -> str:
    """Render the searchable-tools reminder body from an added/removed delta."""
    parts: list[str] = []
    if added:
        parts.append(
            "The following tools are available but their schemas are NOT loaded — "
            "calling them directly will fail. Use search_tools with query "
            '"select:<name>[,<name>...]" to load their schemas before calling them '
            "(or pass keywords to search). Loaded tools stay loaded for the rest of "
            "the session:\n" + "\n".join(added)
        )
    if removed:
        parts.append("The following tools are no longer available:\n" + "\n".join(removed))
    return "\n\n".join(parts)


class SkillsCatalogReminderSource(ReminderSource):
    """Emit the queen's phase-filtered skills catalog as a reminder.

    Reads ``agent_ctx.queen_skills_catalog_provider`` — a callable returning the
    rendered ``<available_skills>`` block (with its own "read the SKILL.md with
    terminal_exec cat, then follow it" header). Emitted as one unit when it changes, and
    in full at the compaction boundary.
    """

    name = "skills_catalog"

    def __init__(self) -> None:
        self._last_sig: int | None = None

    def points(self) -> set[ReminderPoint]:
        return set(_FIRE_POINTS)

    def applies_to(self, agent_ctx: Any) -> bool:
        return bool(getattr(agent_ctx, "is_queen_stream", False))

    async def render(self, rctx: ReminderContext) -> str | None:
        provider = getattr(rctx.agent_ctx, "queen_skills_catalog_provider", None)
        if provider is None:
            return None
        try:
            catalog = (provider() or "").strip()
        except Exception:
            logger.debug("queen_skills_catalog_provider raised", exc_info=True)
            return None
        if not catalog:
            self._last_sig = hash("")
            return None
        sig = hash(catalog)
        # POST_COMPACT: re-emit the full catalog into the fresh post-compact
        # context regardless of the guard. Otherwise emit only on change.
        if rctx.point != ReminderPoint.POST_COMPACT and sig == self._last_sig:
            return None
        self._last_sig = sig
        return catalog
