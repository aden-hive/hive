"""A freshly forked colony queen gets her first turn instead of idling.

Regression: Create Colony restored the colony queen parked for input, and
the fork route dropped the dialog's goal/handover on the floor, so the
request that created the colony sat unanswered until the user repeated it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from framework.host.event_bus import EventBus, EventType
from framework.server.routes_sessions import _seed_colony_queen


class _Queen:
    def __init__(self) -> None:
        self.injected: list[tuple[str, bool]] = []

    async def inject_event(self, content: str, *, is_client_input: bool = False, **_kw) -> None:
        self.injected.append((content, is_client_input))


def _session(bus: EventBus) -> SimpleNamespace:
    return SimpleNamespace(id="session_colony", event_bus=bus, queen_executor=None)


@pytest.mark.asyncio
async def test_dialog_goal_reaches_the_colony_queen_as_the_users_message():
    bus = EventBus()
    received: list = []

    async def on_input(event):
        received.append(event)

    bus.subscribe([EventType.CLIENT_INPUT_RECEIVED], on_input)
    session, queen = _session(bus), _Queen()
    session.queen_executor = SimpleNamespace(node_registry={"queen": queen})

    await _seed_colony_queen(session, colony_id="watchlist", user_goal="Goal: refresh all six repos")

    assert queen.injected == [("Goal: refresh all six repos", True)]
    assert [e.data["content"] for e in received] == ["Goal: refresh all six repos"]


@pytest.mark.asyncio
async def test_without_a_goal_the_queen_is_told_to_carry_on():
    session, queen = _session(EventBus()), _Queen()
    session.queen_executor = SimpleNamespace(node_registry={"queen": queen})

    await _seed_colony_queen(session, colony_id="watchlist", user_goal="   ")

    [(content, is_client_input)] = queen.injected
    assert "Carry on with the work agreed" in content
    assert is_client_input is False  # a framework note, not words the user typed


@pytest.mark.asyncio
async def test_waits_for_the_queen_loop_to_come_up():
    session, queen = _session(EventBus()), _Queen()

    async def boot_later():
        await asyncio.sleep(0.5)
        session.queen_executor = SimpleNamespace(node_registry={"queen": queen})

    booting = asyncio.create_task(boot_later())
    await _seed_colony_queen(session, colony_id="watchlist", user_goal=None, wait_s=5)
    await booting

    assert len(queen.injected) == 1


@pytest.mark.asyncio
async def test_gives_up_quietly_when_the_queen_never_starts():
    await _seed_colony_queen(_session(EventBus()), colony_id="watchlist", user_goal=None, wait_s=0.3)
