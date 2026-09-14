import asyncio

import pytest

from core.framework.utils.task_registry import TaskRegistry


@pytest.fixture
def registry():
    return TaskRegistry("test_owner")


@pytest.mark.asyncio
async def test_spawn_tracks_task(registry):
    async def noop():
        return 42

    task = registry.spawn(noop(), name="noop")
    assert len(registry) == 1
    assert task.get_name() == "noop"
    result = await task
    assert result == 42


@pytest.mark.asyncio
async def test_task_removed_on_completion(registry):
    async def noop():
        pass

    registry.spawn(noop())
    await asyncio.sleep(0.05)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_cancel_all(registry):
    async def long_running():
        await asyncio.sleep(100)

    registry.spawn(long_running(), name="long_running")
    assert len(registry) == 1
    await registry.cancel_all(timeout=1.0)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_cancel_all_empty(registry):
    # Should not raise
    await registry.cancel_all()


@pytest.mark.asyncio
async def test_owner_labeling(registry):
    assert registry._owner == "test_owner"
    labeled = TaskRegistry("my_owner")
    assert labeled._owner == "my_owner"


@pytest.mark.asyncio
async def test_error_handling(registry, caplog):
    async def failing():
        raise ValueError("boom")

    registry.spawn(failing(), name="failing")
    await asyncio.sleep(0.1)
    assert "boom" in caplog.text or "ValueError" in caplog.text


@pytest.mark.asyncio
async def test_multiple_tasks(registry):
    async def noop():
        pass

    for _ in range(5):
        registry.spawn(noop())
    assert len(registry) == 5
    await asyncio.sleep(0.05)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_task_exception_does_not_remove_early(registry, caplog):
    async def failing():
        raise RuntimeError("fail")

    task = registry.spawn(failing(), name="fail")
    await asyncio.sleep(0.1)
    # Task should be removed after done
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_len_reflects_active(registry):
    async def long_running():
        await asyncio.sleep(100)

    t1 = registry.spawn(long_running())
    t2 = registry.spawn(long_running())
    assert len(registry) == 2
    t1.cancel()
    await asyncio.sleep(0.05)
    assert len(registry) >= 1
