"""Tests for TaskRegistry — tracked asyncio task lifecycle."""

from __future__ import annotations

import asyncio
import logging

import pytest

from framework.utils.task_registry import TaskRegistry


# ---------------------------------------------------------------------------
# spawn / lifecycle
# ---------------------------------------------------------------------------
class TestTaskRegistrySpawn:
    """Tests for ``spawn`` and basic task lifecycle."""

    @pytest.mark.asyncio
    async def test_spawn_adds_task_to_registry(self):
        """spawn creates a tracked task and increments len."""
        registry = TaskRegistry("test")
        assert len(registry) == 0

        async def work() -> None:
            await asyncio.sleep(0)

        registry.spawn(work(), name="worker")
        assert len(registry) == 1

    @pytest.mark.asyncio
    async def test_spawn_returns_task(self):
        """spawn returns the created asyncio.Task."""
        registry = TaskRegistry("test")

        async def work() -> str:
            return "done"

        task = registry.spawn(work(), name="worker")
        assert isinstance(task, asyncio.Task)
        result = await task
        assert result == "done"

    @pytest.mark.asyncio
    async def test_task_removed_after_completion(self):
        """Task is removed from registry once it finishes."""
        registry = TaskRegistry("test")

        async def work() -> None:
            await asyncio.sleep(0)

        task = registry.spawn(work(), name="worker")
        await task
        # Allow done callback to fire
        await asyncio.sleep(0)
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_multiple_tasks_tracked_independently(self):
        """Multiple spawned tasks are tracked and removed independently."""
        registry = TaskRegistry("test")

        async def quick() -> None:
            await asyncio.sleep(0)

        async def slow() -> None:
            await asyncio.sleep(0.05)

        quick_task = registry.spawn(quick(), name="quick")
        slow_task = registry.spawn(slow(), name="slow")
        assert len(registry) == 2

        await quick_task
        await asyncio.sleep(0)
        assert len(registry) == 1  # quick removed, slow still tracked

        await slow_task
        await asyncio.sleep(0)
        assert len(registry) == 0


# ---------------------------------------------------------------------------
# cancel_all
# ---------------------------------------------------------------------------
class TestTaskRegistryCancelAll:
    """Tests for ``cancel_all``."""

    @pytest.mark.asyncio
    async def test_cancel_all_cancels_tracked_tasks(self):
        """cancel_all cancels every tracked task."""
        registry = TaskRegistry("test")

        async def work() -> None:
            await asyncio.sleep(10)

        task = registry.spawn(work(), name="worker")
        await registry.cancel_all()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_cancel_all_empty_registry_is_noop(self):
        """cancel_all on an empty registry does nothing."""
        registry = TaskRegistry("test")
        await registry.cancel_all()  # should not raise

    @pytest.mark.asyncio
    async def test_cancel_all_clears_registry(self):
        """After cancel_all, the registry is empty."""
        registry = TaskRegistry("test")

        async def work() -> None:
            await asyncio.sleep(10)

        registry.spawn(work(), name="worker")
        await registry.cancel_all()
        # Cancelled tasks are still removed via _on_done
        await asyncio.sleep(0)
        assert len(registry) == 0

    @pytest.mark.asyncio
    async def test_cancel_all_with_short_timeout(self):
        """cancel_all handles tasks that don't finish within timeout."""
        registry = TaskRegistry("test")

        async def work() -> None:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                await asyncio.sleep(10)  # ignore cancellation

        registry.spawn(work(), name="stubborn")
        # Should not raise — TimeoutError is caught internally
        await registry.cancel_all(timeout=0.01)


# ---------------------------------------------------------------------------
# error handling
# ---------------------------------------------------------------------------
class TestTaskRegistryErrorHandling:
    """Tests for error logging in ``_on_done``."""

    @pytest.mark.asyncio
    async def test_task_exception_is_logged(self, caplog):
        """When a tracked task raises, the exception is logged."""
        registry = TaskRegistry("test")

        async def failing() -> None:
            raise ValueError("boom")

        with caplog.at_level(logging.ERROR):
            task = registry.spawn(failing(), name="failing_worker")
            # Wait for the task to finish
            try:
                await task
            except ValueError:
                pass
            await asyncio.sleep(0)

        assert "unhandled exception" in caplog.text
        assert "boom" in caplog.text
        assert "failing_worker" in caplog.text

    @pytest.mark.asyncio
    async def test_cancelled_task_does_not_log_error(self, caplog):
        """Cancelled tasks skip error logging."""
        registry = TaskRegistry("test")

        async def work() -> None:
            await asyncio.sleep(10)

        task = registry.spawn(work(), name="cancelled_worker")
        task.cancel()

        with caplog.at_level(logging.ERROR):
            try:
                await task
            except asyncio.CancelledError:
                pass
            await asyncio.sleep(0)

        assert "unhandled exception" not in caplog.text

    @pytest.mark.asyncio
    async def test_successful_task_does_not_log_error(self, caplog):
        """Successfully completed tasks produce no error log."""
        registry = TaskRegistry("test")

        async def work() -> str:
            return "ok"

        with caplog.at_level(logging.ERROR):
            task = registry.spawn(work(), name="good_worker")
            await task
            await asyncio.sleep(0)

        assert "unhandled exception" not in caplog.text


# ---------------------------------------------------------------------------
# owner
# ---------------------------------------------------------------------------
class TestTaskRegistryOwner:
    """Tests for owner label in log messages."""

    def test_default_owner_is_empty(self):
        """Default owner is empty string."""
        registry = TaskRegistry()
        assert registry._owner == ""

    def test_owner_stored(self):
        """Owner name is stored."""
        registry = TaskRegistry("agent_loop")
        assert registry._owner == "agent_loop"

    @pytest.mark.asyncio
    async def test_owner_in_error_log(self, caplog):
        """Owner name appears in error log messages."""
        registry = TaskRegistry("agent_loop")

        async def failing() -> None:
            raise RuntimeError("something went wrong")

        with caplog.at_level(logging.ERROR):
            task = registry.spawn(failing(), name="worker")
            try:
                await task
            except RuntimeError:
                pass
            await asyncio.sleep(0)

        assert "agent_loop" in caplog.text
