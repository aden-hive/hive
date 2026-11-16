"""A live worker's ``started_at`` is a wall-clock epoch timestamp.

The workers panel formats it as a date. It used to be ``time.monotonic()``
(seconds since boot), which rendered as a bogus early-morning 1970 time.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.host.worker import Worker


@pytest.mark.asyncio
async def test_info_started_at_is_wall_clock():
    agent_loop = MagicMock()
    res = MagicMock()
    res.success = True
    agent_loop.execute = AsyncMock(return_value=res)

    w = Worker(
        worker_id="w-clock",
        task="say hello",
        agent_loop=agent_loop,
        context=MagicMock(),
    )
    w._emit_terminal_events = AsyncMock()
    w._build_result = MagicMock(return_value=MagicMock(status="success"))

    before = time.time()
    await w.run()

    assert before <= w.info.started_at <= time.time()
