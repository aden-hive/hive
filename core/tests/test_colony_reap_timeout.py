"""Colony shutdown can't hang on an unresponsive browser bridge.

Stopping a colony closes each worker's browser tab group through
bridge_host, a process shared by everything on the machine. That wait had
no bound, so a bridge that stopped answering hung ``colony.stop()``.
"""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from framework.host import colony_runtime
from framework.host.colony_runtime import ColonyRuntime


@pytest.mark.asyncio
async def test_reap_gives_up_on_a_bridge_that_never_answers(monkeypatch):
    from gcu.browser.tools import lifecycle

    async def never_answers(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(lifecycle, "close_profile_context", never_answers)
    monkeypatch.setattr(colony_runtime, "_BROWSER_REAP_TIMEOUT_S", 0.2)

    started = time.monotonic()
    await ColonyRuntime._reap_worker_browsers(SimpleNamespace(_workers={}), ["w1", "w2", "w3"])

    assert time.monotonic() - started < 2.0
