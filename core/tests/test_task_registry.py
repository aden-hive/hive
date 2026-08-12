import asyncio
import logging

import pytest

from framework.utils.task_registry import TaskRegistry


@pytest.mark.asyncio
async def test_spawn_tracks_task():
    registry = TaskRegistry("test_owner")

    async def dummy_coro():
        await asyncio.sleep(0.01)
        return "done"

    task = registry.spawn(dummy_coro(), name="test_task")
    assert len(registry) == 1
    assert task in registry._tasks

    # Wait for completion
    await task
    # It should be removed from registry after completion due to callback
    # Need to yield control slightly to allow callbacks to run
    await asyncio.sleep(0.01)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_task_exception_logged(caplog):
    registry = TaskRegistry("test_owner")

    async def failing_coro():
        raise ValueError("Test error")

    with caplog.at_level(logging.ERROR):
        task = registry.spawn(failing_coro(), name="failing_task")

        # Wait for task to finish
        with pytest.raises(ValueError):
            await task

        # Yield to ensure callback runs
        await asyncio.sleep(0.01)

        assert len(registry) == 0
        assert "Tracked task 'failing_task' (owner=test_owner) raised an unhandled exception" in caplog.text
        assert "Test error" in caplog.text


@pytest.mark.asyncio
async def test_cancel_all():
    registry = TaskRegistry("test_owner")

    async def long_running_coro():
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            pass

    task1 = registry.spawn(long_running_coro(), name="task1")
    task2 = registry.spawn(long_running_coro(), name="task2")

    assert len(registry) == 2

    await registry.cancel_all(timeout=1.0)

    assert task1.cancelled()
    assert task2.cancelled()

    # After cancel_all, the tasks should be done and removed from registry
    await asyncio.sleep(0.01)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_cancel_all_timeout(caplog):
    registry = TaskRegistry("test_owner")

    async def stubborn_coro():
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            # Swallow cancellation and refuse to exit immediately
            await asyncio.sleep(0.5)

    _ = registry.spawn(stubborn_coro(), name="stubborn_task")

    with caplog.at_level(logging.WARNING, logger="framework.utils.task_registry"):
        # cancel_all will wait for the task to finish, but it delays its exit
        # so we set a very short timeout
        await registry.cancel_all(timeout=0.01)

        # The timeout should trigger a warning
        assert "did not finish within" in caplog.text

    # Clean up the task so it doesn't leak into other tests
    await asyncio.sleep(0.6)
