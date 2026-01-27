"""Tests for StreamRuntime save behavior and retry handling."""

import asyncio

import pytest

from framework.runtime.stream_runtime import StreamRuntime


class FailingStorage:
    """Storage that always fails to save."""

    def __init__(self) -> None:
        self.called = asyncio.Event()

    async def save_run(self, run, immediate: bool = False) -> None:
        self.called.set()
        raise RuntimeError("save failed")


class FlakyStorage:
    """Storage that fails once, then succeeds."""

    def __init__(self) -> None:
        self.calls = 0
        self.called = asyncio.Event()

    async def save_run(self, run, immediate: bool = False) -> None:
        self.calls += 1
        self.called.set()
        if self.calls == 1:
            raise RuntimeError("transient failure")


class WorkingStorage:
    """Storage that always succeeds."""

    def __init__(self) -> None:
        self.called = asyncio.Event()

    async def save_run(self, run, immediate: bool = False) -> None:
        self.called.set()
        return None


@pytest.mark.asyncio
async def test_failed_save_does_not_drop_run():
    storage = FailingStorage()
    runtime = StreamRuntime(stream_id="s1", storage=storage)

    execution_id = "exec-1"
    runtime.start_run(execution_id=execution_id, goal_id="goal")
    runtime.end_run(execution_id=execution_id, success=True)

    await storage.called.wait()

    failed = runtime.get_failed_saves()
    assert execution_id in failed
    assert failed[execution_id]["attempts"] == 1
    assert "save failed" in failed[execution_id]["last_error"]
    assert runtime.get_run(execution_id) is not None


@pytest.mark.asyncio
async def test_retry_success_cleans_up():
    storage = FlakyStorage()
    runtime = StreamRuntime(stream_id="s2", storage=storage, base_delay=0.0)

    execution_id = "exec-2"
    runtime.start_run(execution_id=execution_id, goal_id="goal")
    runtime.end_run(execution_id=execution_id, success=True)

    await storage.called.wait()
    storage.called.clear()
    assert execution_id in runtime.get_failed_saves()

    result = await runtime.retry_failed_saves(max_attempts=3, base_delay=0.0)
    await storage.called.wait()
    assert result["saved"] == 1
    assert storage.calls == 2
    assert runtime.get_failed_saves() == {}
    assert runtime.get_run(execution_id) is None


@pytest.mark.asyncio
async def test_successful_save_cleans_up():
    storage = WorkingStorage()
    runtime = StreamRuntime(stream_id="s3", storage=storage)

    execution_id = "exec-3"
    runtime.start_run(execution_id=execution_id, goal_id="goal")
    runtime.end_run(execution_id=execution_id, success=True)

    await storage.called.wait()

    assert runtime.get_failed_saves() == {}
    assert runtime.get_run(execution_id) is None
