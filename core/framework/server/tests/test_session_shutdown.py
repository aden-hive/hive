"""Stopping the server gives the sessions' last background work a short grace, not forever."""

from __future__ import annotations

import asyncio

import pytest

from framework.server.session_manager import SessionManager


@pytest.mark.asyncio
async def test_shutdown_work_gets_a_grace_then_is_cancelled():
    manager = SessionManager()
    finished: list[str] = []

    async def quick():
        await asyncio.sleep(0.01)
        finished.append("quick")

    async def stuck():
        await asyncio.sleep(60)
        finished.append("stuck")

    tasks = [asyncio.create_task(quick()), asyncio.create_task(stuck())]
    manager._background_tasks.update(tasks)

    started = asyncio.get_running_loop().time()
    await manager.finish_background_tasks(0.2)
    await asyncio.sleep(0)

    assert asyncio.get_running_loop().time() - started < 2
    assert finished == ["quick"]
    assert tasks[1].cancelled()
