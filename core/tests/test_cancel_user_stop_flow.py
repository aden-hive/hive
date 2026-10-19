"""Integration test for the cancel-queen / user-stop / idle-nudge pipeline.

Exercises the wiring between four pieces that have unit-level coverage
elsewhere but no end-to-end test:

  1. ``handle_cancel_queen`` must call ``mark_user_stopped`` BEFORE
     ``cancel_current_turn`` so the idle-nudge gate sees ``_user_stopped``
     from the very first tick after the cancelled stream parks the loop.
  2. ``handle_session_presence`` must NOT mutate user-stop. A
     user-cancelled agent persists until the user sends a real message
     (``inject_event`` clears it server-side).
  3. ``IdleNudgeSource.render`` suppresses the nudge when the
     ``user_stopped`` signal is True, regardless of park reason / idle
     time / budgets.
  4. The cursor persistence round-trip carries ``user_stopped`` across
     runtime restart — killing the app on a user-stopped session must
     not let it auto-resume on reload.

The per-piece tests live in ``test_idle_nudge.py``; this file proves the
pieces compose correctly.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from aiohttp import web

from framework.agent_loop.idle_nudge import IdleNudgeSource
from framework.agent_loop.reminders import (
    LoopSignals,
    ParkReason,
    ReminderContext,
    ReminderPoint,
)
from framework.server.routes_execution import (
    handle_cancel_queen,
    handle_session_presence,
)

# ---------------------------------------------------------------------------
# Mock scaffolding
# ---------------------------------------------------------------------------


class _CallOrderNode:
    """Mock queen node that records the order ``mark_user_stopped`` and
    ``cancel_current_turn`` are called."""

    def __init__(self) -> None:
        self._user_stopped = False
        self._calls: list[str] = []

    def mark_user_stopped(self) -> None:
        self._calls.append("mark_user_stopped")
        self._user_stopped = True

    def cancel_current_turn(self) -> list:
        self._calls.append("cancel_current_turn")
        return []  # no tasks to await


def _request_for(node) -> web.Request:
    """A fake aiohttp request whose ``resolve_session`` resolves to a
    session whose queen executor's node registry returns ``node``."""
    session = SimpleNamespace(
        queen_executor=SimpleNamespace(node_registry={"queen": node}),
    )
    manager = MagicMock()
    manager.get_session.return_value = session
    request = MagicMock(spec=web.Request)
    request.app = {"manager": manager}
    request.match_info = {"session_id": "sid-1"}
    return request


# ---------------------------------------------------------------------------
# Gap 2: cancel-queen sets user-stop BEFORE issuing the cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_queen_marks_user_stop_before_cancelling() -> None:
    """The cancelled stream can park the loop on the very next event loop
    tick — if ``mark_user_stopped`` ran AFTER ``cancel_current_turn`` the
    idle-nudge gate would see a brief window where ``_user_stopped`` was
    still False but the loop was already parked. Ordering must match the
    docstring on ``mark_user_stopped``: flag first, cancel second."""
    node = _CallOrderNode()
    request = _request_for(node)

    response = await handle_cancel_queen(request)

    assert response.status == 200
    body = node._calls
    assert body == ["mark_user_stopped", "cancel_current_turn"], f"expected mark_user_stopped to precede cancel_current_turn, got {body}"
    assert node._user_stopped is True


@pytest.mark.asyncio
async def test_cancel_queen_returns_200_with_no_queen() -> None:
    """When the queen executor is missing the route still returns 200 +
    ``cancelled: false`` so the frontend can surface a system message
    without special-casing HTTP errors."""
    session = SimpleNamespace(queen_executor=None)
    manager = MagicMock()
    manager.get_session.return_value = session
    request = MagicMock(spec=web.Request)
    request.app = {"manager": manager}
    request.match_info = {"session_id": "sid-1"}

    response = await handle_cancel_queen(request)
    assert response.status == 200


# ---------------------------------------------------------------------------
# Gap 1: /presence must not lift user-stop
# ---------------------------------------------------------------------------


class _UserStopTrackingNode:
    def __init__(self, initially_stopped: bool) -> None:
        self._user_stopped = initially_stopped
        # Both old methods are present so the test fails loudly if the
        # route ever starts calling them again.
        self.resume_called = False
        self.mark_called = False

    def resume_from_user_stop(self) -> None:
        self.resume_called = True
        self._user_stopped = False

    def mark_user_stopped(self) -> None:
        self.mark_called = True
        self._user_stopped = True


@pytest.mark.asyncio
async def test_presence_does_not_resume_user_stopped_agent() -> None:
    """Chat re-entry must not lift the user-stop. The agent stays parked
    in INTERRUPTED with park_reason=USER_STOPPED until the user sends a
    real message (``inject_event`` is the only legitimate clearer)."""
    node = _UserStopTrackingNode(initially_stopped=True)
    request = _request_for(node)

    response = await handle_session_presence(request)

    assert response.status == 200
    assert node.resume_called is False
    assert node._user_stopped is True, "user-stop must persist across /presence"


@pytest.mark.asyncio
async def test_presence_no_queen_returns_200() -> None:
    """When no queen executor is loaded, /presence still answers 200 so
    the frontend's fire-and-forget call doesn't see network errors."""
    session = SimpleNamespace(queen_executor=None)
    # No real path for resolve_session except a real Session — but the
    # route returns before touching the executor when it's None, after
    # the resolve. Simplest exercise: use the same shape as before with
    # queen_executor=None.
    manager = MagicMock()
    manager.get_session.return_value = session
    request = MagicMock(spec=web.Request)
    request.app = {"manager": manager}
    request.match_info = {"session_id": "sid-1"}

    response = await handle_session_presence(request)
    assert response.status == 200


# ---------------------------------------------------------------------------
# Gap 3: the full pipeline — user-stop signal suppresses the nudge across
# every park reason and the slow_ttft / between_turns substates
# ---------------------------------------------------------------------------


def _signals(**overrides) -> ReminderContext:
    base = {
        "idle_seconds": 999.0,  # well over any budget
        "awaiting_input": True,
        "park_reason": ParkReason.UNKNOWN,
        "stream_active": False,
        "first_event_seen": False,
        "user_stopped": True,
    }
    base.update(overrides)
    return ReminderContext(
        point=ReminderPoint.IDLE_TICK,
        agent_ctx=SimpleNamespace(),
        signals=LoopSignals(**base),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "park_reason",
    [
        ParkReason.UNKNOWN,
        ParkReason.TURN_DONE,
        ParkReason.LLM_ERROR,
        ParkReason.DOOM_LOOP,
        ParkReason.EMPTY_RESPONSES,
        ParkReason.USER_STOPPED,
    ],
)
async def test_idle_nudge_suppressed_for_every_park_reason_when_user_stopped(
    park_reason: ParkReason,
) -> None:
    """``user_stopped`` is checked BEFORE the park-reason classifier — no
    matter which park the loop is on, an explicit user-stop wins."""
    src = IdleNudgeSource(
        budget_seconds=1.0,
        max_nudges=3,
        awaiting_budget_seconds=1.0,
        broken_budget_seconds=1.0,
    )
    out = await src.render(_signals(park_reason=park_reason))
    assert out is None


@pytest.mark.asyncio
async def test_idle_nudge_suppressed_when_user_stopped_between_turns() -> None:
    """The non-park substates (between_turns / slow_ttft) also defer to
    ``user_stopped`` — a user who clicked Stop during a stream stall must
    not be nudged."""
    src = IdleNudgeSource(budget_seconds=1.0, max_nudges=3)
    out = await src.render(_signals(awaiting_input=False, stream_active=False, park_reason=None))
    assert out is None


@pytest.mark.asyncio
async def test_idle_nudge_fires_again_once_user_stop_cleared() -> None:
    """Sanity counterpart: with ``user_stopped=False`` (e.g. after
    ``inject_event`` cleared it) the same questionless park does produce
    a reminder. Proves the suppression isn't permanent — only the gate."""
    src = IdleNudgeSource(
        budget_seconds=1.0,
        max_nudges=3,
        awaiting_budget_seconds=1.0,
    )
    out = await src.render(_signals(user_stopped=False))
    assert out is not None
    assert out.meta["substate"] == "parked_no_question"


@pytest.mark.asyncio
async def test_idle_nudge_suppressed_for_turn_done_even_without_user_stop() -> None:
    """A clean end-of-turn park is a silent stopping point — the idle
    nudge suppresses it regardless of the ``user_stopped`` flag. This
    is a separate semantic from cancel: the queen finished her turn
    cleanly and is awaiting the next user message. Auto-resuming would
    override the user's pause."""
    src = IdleNudgeSource(
        budget_seconds=1.0,
        max_nudges=3,
        awaiting_budget_seconds=1.0,
    )
    out = await src.render(_signals(park_reason=ParkReason.TURN_DONE, user_stopped=False))
    assert out is None


# ---------------------------------------------------------------------------
# Cursor persistence — user_stopped survives runtime restart
# ---------------------------------------------------------------------------


class _FakeNodeContext:
    """Minimal NodeContext stand-in for cursor_persistence write_cursor.

    write_cursor only reads ``ctx.agent_id``; everything else is unused.
    """

    def __init__(self, agent_id: str = "queen") -> None:
        self.agent_id = agent_id


class _FakeAccumulator:
    """write_cursor calls ``accumulator.to_dict()``; that's all we need."""

    def to_dict(self) -> dict:
        return {}


class _InMemoryConversationStore:
    """Stand-in for ConversationStore: read/write a cursor dict in memory."""

    def __init__(self) -> None:
        self._cursor: dict | None = None

    async def read_cursor(self) -> dict | None:
        return dict(self._cursor) if self._cursor else None

    async def write_cursor(self, cursor: dict) -> None:
        self._cursor = dict(cursor)


@pytest.mark.asyncio
async def test_cursor_persists_user_stopped_flag() -> None:
    """write_cursor passes ``user_stopped`` through to the persisted
    cursor dict so the AgentLoop can restore it on the next process."""
    from framework.agent_loop.internals.cursor_persistence import write_cursor

    store = _InMemoryConversationStore()
    await write_cursor(
        conversation_store=store,
        ctx=_FakeNodeContext(),
        conversation=MagicMock(),
        accumulator=_FakeAccumulator(),
        iteration=3,
        user_stopped=True,
    )
    assert store._cursor is not None
    assert store._cursor["user_stopped"] is True


@pytest.mark.asyncio
async def test_cursor_default_user_stopped_is_false() -> None:
    """Default ``user_stopped=False`` so legacy cursor writes (which
    don't pass the flag explicitly) don't accidentally mark a session
    as stopped."""
    from framework.agent_loop.internals.cursor_persistence import write_cursor

    store = _InMemoryConversationStore()
    await write_cursor(
        conversation_store=store,
        ctx=_FakeNodeContext(),
        conversation=MagicMock(),
        accumulator=_FakeAccumulator(),
        iteration=1,
    )
    assert store._cursor is not None
    assert store._cursor["user_stopped"] is False


@pytest.mark.asyncio
async def test_user_stop_park_persists_then_restores() -> None:
    """Round-trip: write a user-stop park to the cursor, then verify
    the persisted shape carries both the pending_input park reason AND
    the user_stopped flag — the two halves the loop reads on restore to
    re-enter the USER_STOPPED park and re-arm the idle-nudge gate."""
    from framework.agent_loop.internals.cursor_persistence import write_cursor

    store = _InMemoryConversationStore()
    await write_cursor(
        conversation_store=store,
        ctx=_FakeNodeContext(),
        conversation=MagicMock(),
        accumulator=_FakeAccumulator(),
        iteration=42,
        pending_input={
            "reason": ParkReason.USER_STOPPED.value,
            "emit_client_request": True,
        },
        user_stopped=True,
    )
    cursor = store._cursor
    assert cursor is not None
    # Loop re-enters _await_user_input(USER_STOPPED) from this.
    assert cursor["pending_input"]["reason"] == "user_stopped"
    assert cursor["pending_input"]["emit_client_request"] is True
    # Idle-nudge gate suppresses nudges from this.
    assert cursor["user_stopped"] is True
