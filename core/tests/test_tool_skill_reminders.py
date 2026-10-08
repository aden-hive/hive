"""Tests for the queen searchable-tools + skills-catalog reminder sources.

Intent: the queen is told what she can load (and how) via a <system-reminder>
rather than the static prompt — and that reminder must (a) carry the
search_tools "select:<name>" contract, (b) list exactly the searchable tools,
(c) gate to the queen, and (d) re-emit only when the set changes (so a long
conversation isn't bloated turn after turn), re-arming after compaction.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework.agent_loop.reminders import ReminderContext, ReminderPoint
from framework.agent_loop.tool_skill_reminders import (
    SearchableToolsReminderSource,
    SkillsCatalogReminderSource,
)


def _tool(name: str):
    return SimpleNamespace(name=name, description=f"desc of {name}")


def _ctx(point: ReminderPoint, **ctx_attrs) -> ReminderContext:
    return ReminderContext(point=point, agent_ctx=SimpleNamespace(**ctx_attrs))


async def _render(src, point, **ctx_attrs):
    return await src.render(_ctx(point, **ctx_attrs))


class TestSearchableToolsReminder:
    def _attrs(self, tools, loaded=(), **extra):
        return {
            "is_queen_stream": True,
            "searchable_tools_provider": lambda: tools,
            "loaded_tool_names_provider": lambda: list(loaded),
            **extra,
        }

    @pytest.mark.asyncio
    async def test_lists_searchable_tools_with_contract(self):
        src = SearchableToolsReminderSource()
        out = await _render(
            src,
            ReminderPoint.USER_PROMPT_SUBMIT,
            **self._attrs([_tool("gmail_send"), _tool("notion_search")]),
        )
        assert out is not None
        # The load contract the agent must follow.
        assert "search_tools" in out
        assert "select:<name>" in out
        assert "schemas are NOT loaded" in out
        # Both searchable tools listed (initial delta = everything added).
        assert "gmail_send" in out and "notion_search" in out

    @pytest.mark.asyncio
    async def test_queen_only(self):
        src = SearchableToolsReminderSource()
        assert src.applies_to(SimpleNamespace(is_queen_stream=False)) is False
        assert src.applies_to(SimpleNamespace(is_queen_stream=True)) is True

    @pytest.mark.asyncio
    async def test_fires_at_session_start(self):
        """The manifest must land on the opening turn — the seed user message
        bypasses the USER_PROMPT_SUBMIT queue gate, so SESSION_START is the only
        point that places it before the first LLM call."""
        src = SearchableToolsReminderSource()
        assert ReminderPoint.SESSION_START in src.points()
        out = await _render(src, ReminderPoint.SESSION_START, **self._attrs([_tool("gmail_send")]))
        assert out is not None and "gmail_send" in out
        # Already announced at session start → first tool-result tail is silent.
        assert await _render(src, ReminderPoint.POST_TOOL_USE, **self._attrs([_tool("gmail_send")])) is None

    @pytest.mark.asyncio
    async def test_delta_added_then_silent(self):
        src = SearchableToolsReminderSource()
        attrs = self._attrs([_tool("gmail_send")])
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is not None
        # Unchanged → no delta → silent.
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None
        # A genuinely new searchable tool appears → only the new one announced.
        attrs2 = self._attrs([_tool("gmail_send"), _tool("calendar_create")])
        out = await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs2)
        assert out is not None
        assert "calendar_create" in out
        assert "gmail_send" not in out  # already announced — not repeated

    @pytest.mark.asyncio
    async def test_loaded_departure_is_silent(self):
        """A tool that left searchable because it was LOADED is not announced
        as removed — the model already knows it's now callable."""
        src = SearchableToolsReminderSource()
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **self._attrs([_tool("gmail_send")])) is not None
        # gmail_send loaded → gone from searchable, present in loaded set.
        out = await _render(src, ReminderPoint.POST_TOOL_USE, **self._attrs([], loaded=["gmail_send"]))
        assert out is None

    @pytest.mark.asyncio
    async def test_removed_departure_is_announced(self):
        """A tool that left searchable and is NOT loaded was removed from the
        allowed pool → announced as no longer available."""
        src = SearchableToolsReminderSource()
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **self._attrs([_tool("gmail_send")])) is not None
        out = await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **self._attrs([], loaded=[]))
        assert out is not None
        assert "no longer available" in out and "gmail_send" in out

    @pytest.mark.asyncio
    async def test_empty_searchable_set_is_silent(self):
        src = SearchableToolsReminderSource()
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **self._attrs([])) is None

    @pytest.mark.asyncio
    async def test_post_compact_reannounces_full(self):
        src = SearchableToolsReminderSource()
        attrs = self._attrs([_tool("gmail_send")])
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is not None
        # Steady state: unchanged → silent.
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None
        # Compaction boundary: re-announce the FULL current pool (not None).
        boundary = await _render(src, ReminderPoint.POST_COMPACT, **attrs)
        assert boundary is not None and "gmail_send" in boundary
        # Already re-announced as the new baseline → next turn silent (no dup).
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None

    @pytest.mark.asyncio
    async def test_no_provider_is_silent(self):
        src = SearchableToolsReminderSource()
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, is_queen_stream=True) is None


class TestSkillsCatalogReminder:
    @pytest.mark.asyncio
    async def test_emits_catalog_verbatim_then_on_change(self):
        src = SkillsCatalogReminderSource()
        cat = "<available_skills>\n  <skill><name>pdf</name></skill>\n</available_skills>"
        attrs = {"is_queen_stream": True, "queen_skills_catalog_provider": lambda: cat}
        out = await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs)
        assert out == cat
        # Unchanged catalog → suppressed.
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None
        # Catalog changes (a colony skill was written) → re-emit.
        cat2 = cat.replace("pdf", "pdf</name></skill>\n  <skill><name>enrich")
        attrs2 = {"is_queen_stream": True, "queen_skills_catalog_provider": lambda: cat2}
        assert await _render(src, ReminderPoint.POST_TOOL_USE, **attrs2) == cat2

    @pytest.mark.asyncio
    async def test_post_compact_reannounces_full_catalog(self):
        src = SkillsCatalogReminderSource()
        cat = "<available_skills>\n  <skill><name>pdf</name></skill>\n</available_skills>"
        attrs = {"is_queen_stream": True, "queen_skills_catalog_provider": lambda: cat}
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) == cat
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None
        # Compaction boundary: re-emit the full catalog even though unchanged.
        assert await _render(src, ReminderPoint.POST_COMPACT, **attrs) == cat
        # New baseline → next turn silent (no duplicate).
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None

    @pytest.mark.asyncio
    async def test_empty_catalog_silent_and_queen_only(self):
        src = SkillsCatalogReminderSource()
        assert src.applies_to(SimpleNamespace(is_queen_stream=False)) is False
        attrs = {"is_queen_stream": True, "queen_skills_catalog_provider": lambda: ""}
        assert await _render(src, ReminderPoint.USER_PROMPT_SUBMIT, **attrs) is None
