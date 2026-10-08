"""Tests for the stream-stall reminder source.

``StreamStallSource`` fires at the reactive ``ReminderPoint.STREAM_STALLED``:
the loop consults it synchronously when the stream watchdog cancels a
stalled stream. We exercise the source's policy (text, per-turn cap,
reset) in isolation.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from framework.agent_loop.reminders import (
    LoopSignals,
    Reminder,
    ReminderContext,
    ReminderPoint,
)
from framework.agent_loop.stream_stall import StreamStallSource


def _ctx(reason: str | None = "inactive", elapsed: float = 120.0) -> ReminderContext:
    return ReminderContext(
        point=ReminderPoint.STREAM_STALLED,
        agent_ctx=SimpleNamespace(),
        signals=LoopSignals(stall_reason=reason, stall_elapsed=elapsed),
    )


@pytest.mark.asyncio
async def test_render_returns_nudge_for_inactive_stall() -> None:
    src = StreamStallSource(max_per_turn=3, enabled=True)
    out = await src.render(_ctx(reason="inactive", elapsed=121.0))
    assert isinstance(out, Reminder)
    assert out.source == "stream_stall"
    assert out.meta["reason"] == "inactive"
    assert out.meta["nudge_count"] == 1
    assert out.meta["cap"] == 3
    # Core wording preserved (the [System: …] framing moved to the
    # uniform <system-reminder> wrapper applied at injection time).
    assert "previous stream stalled" in out.body
    assert "stream went silent after producing events" in out.body
    assert "121s" in out.body


@pytest.mark.asyncio
async def test_render_ttft_reason_label() -> None:
    src = StreamStallSource(max_per_turn=3, enabled=True)
    out = await src.render(_ctx(reason="ttft", elapsed=600.0))
    assert isinstance(out, Reminder)
    assert "no tokens before TTFT budget" in out.body


@pytest.mark.asyncio
async def test_per_turn_cap_then_reset() -> None:
    src = StreamStallSource(max_per_turn=2, enabled=True)
    assert await src.render(_ctx()) is not None  # 1
    assert await src.render(_ctx()) is not None  # 2
    assert await src.render(_ctx()) is None  # cap hit
    # A new turn re-arms the source.
    src.reset_turn()
    out = await src.render(_ctx())
    assert isinstance(out, Reminder)
    assert out.meta["nudge_count"] == 1


@pytest.mark.asyncio
async def test_disabled_returns_none() -> None:
    src = StreamStallSource(max_per_turn=3, enabled=False)
    assert await src.render(_ctx()) is None


@pytest.mark.asyncio
async def test_zero_cap_returns_none() -> None:
    src = StreamStallSource(max_per_turn=0, enabled=True)
    assert await src.render(_ctx()) is None


@pytest.mark.asyncio
async def test_no_stall_reason_returns_none() -> None:
    """A STREAM_STALLED collect with no stall_reason set → no nudge."""
    src = StreamStallSource(max_per_turn=3, enabled=True)
    assert await src.render(_ctx(reason=None)) is None


def test_points() -> None:
    assert StreamStallSource(max_per_turn=3, enabled=True).points() == {ReminderPoint.STREAM_STALLED}
