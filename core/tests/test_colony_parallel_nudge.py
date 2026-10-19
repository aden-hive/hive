"""Tests for the colony-phase 'fan out via playbook' nudge.

The nudge fires only AFTER the queen's pilot — she has done a unit end-to-end
(browser/scrape) and recorded it in the tracker — and stops once she calls
run_playbook.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from framework.agent_loop.colony_parallel_nudge import ColonyParallelNudgeSource
from framework.agent_loop.reminders import ReminderContext, ReminderPoint


def _colony_ctx():
    # Queen in colony phase: live tool list exposes run_playbook.
    return SimpleNamespace(
        is_queen_stream=True,
        dynamic_tools_provider=None,
        available_tools=[SimpleNamespace(name="run_playbook"), SimpleNamespace(name="write_skill")],
    )


def _render(src, ctx):
    return asyncio.run(src.render(ReminderContext(ReminderPoint.POST_TOOL_USE, ctx)))


def test_no_fire_before_pilot_work():
    # Tracker write but no pilot work yet (e.g. CREATE TABLE / seeding) -> silent.
    src = ColonyParallelNudgeSource()
    src.observe_turn(["tracker_sql"])
    assert _render(src, _colony_ctx()) is None


def test_no_fire_after_work_without_tracker_write():
    src = ColonyParallelNudgeSource()
    src.observe_turn(["browser_click"])  # did work...
    assert _render(src, _colony_ctx()) is None  # ...but hasn't recorded it


def test_fires_after_pilot_then_tracker_write():
    src = ColonyParallelNudgeSource()
    src.observe_turn(["browser_click", "web_scrape"])  # pilot work
    src.observe_turn(["tracker_upsert"])  # record the completed unit
    body = _render(src, _colony_ctx())
    assert body is not None
    assert "run_playbook" in body and "pilot" in body


def test_silent_once_fanned_out():
    src = ColonyParallelNudgeSource()
    src.observe_turn(["browser_click"])
    src.observe_turn(["run_playbook"])  # already converging
    src.observe_turn(["tracker_upsert"])
    assert _render(src, _colony_ctx()) is None


def test_silent_outside_colony_phase():
    src = ColonyParallelNudgeSource()
    src.observe_turn(["browser_click"])
    src.observe_turn(["tracker_upsert"])
    independent = SimpleNamespace(
        is_queen_stream=True,
        dynamic_tools_provider=None,
        available_tools=[SimpleNamespace(name="suggest_colony")],  # no fan-out tool
    )
    assert _render(src, independent) is None


def test_applies_to_queen_only():
    src = ColonyParallelNudgeSource()
    assert src.applies_to(SimpleNamespace(is_queen_stream=True)) is True
    assert src.applies_to(SimpleNamespace(is_queen_stream=False)) is False


def test_cooldown_blocks_repeat():
    src = ColonyParallelNudgeSource(cooldown_turns=4, max_per_session=10)
    src.observe_turn(["browser_click"])
    src.observe_turn(["tracker_upsert"])
    assert _render(src, _colony_ctx()) is not None  # fires once
    src.observe_turn(["tracker_upsert"])  # next turn, still pilot+write
    assert _render(src, _colony_ctx()) is None  # cooldown blocks
