"""The `energizes` wake policy: hub-side plumbing between a source and the loop.

`fire()` merges every source into one block and so loses which of them produced
it. These pin the part that survives that merge — whether ANY contributor wanted
a parked agent woken — because the loop's auto-block decision reads exactly that
bit, and a source whose wake policy got lost in the merge is a reminder the user
never sees the effect of.
"""

import asyncio

from framework.agent_loop.reminders import (
    ReminderHub,
    ReminderPoint,
    ReminderSource,
)


class _Source(ReminderSource):
    def __init__(self, name, body, energizes=False):
        self.name = name
        self.energizes = energizes
        self._body = body

    def points(self):
        return {ReminderPoint.STOP}

    async def render(self, rctx):
        return self._body


def _fire(*sources):
    hub = ReminderHub()
    for s in sources:
        hub.register(s)
    return asyncio.run(hub.fire_energized(ReminderPoint.STOP, object()))


def test_default_source_does_not_wake_the_loop():
    """Off by default — a parked queen is usually parked because the user's
    move is genuinely next, and waking it would talk over them."""
    block, energized = _fire(_Source("plain", "just context"))
    assert block and not energized


def test_energizing_source_wakes_the_loop():
    block, energized = _fire(_Source("urgent", "act now", energizes=True))
    assert block and energized


def test_one_energizing_source_carries_the_whole_block():
    """The bit must survive the merge: reminders are combined into a single
    block, and the loop only gets to ask one question of it."""
    _, energized = _fire(
        _Source("plain", "context"),
        _Source("urgent", "act now", energizes=True),
    )
    assert energized


def test_a_silent_energizing_source_does_not_wake_the_loop():
    """Declaring the policy is not the same as having something to say —
    otherwise every quiet turn would refuse to park."""
    block, energized = _fire(_Source("urgent", None, energizes=True))
    assert block is None and not energized


def test_fire_still_returns_just_the_block():
    """`fire()` is the back-compat entry point; the STOP site is the only
    caller that needs the extra bit."""
    hub = ReminderHub()
    hub.register(_Source("urgent", "act now", energizes=True))
    block = asyncio.run(hub.fire(ReminderPoint.STOP, object()))
    assert isinstance(block, str) and "act now" in block
