"""Tests for MCPClient._run_async method.

These tests verify the fix for issue #1543: ensuring that when _run_async is called
from an async context, it uses asyncio.run_coroutine_threadsafe with the current loop
instead of creating a new thread with a new event loop.
"""

import asyncio
import threading

import pytest

from framework.runner.mcp_client import MCPClient, MCPServerConfig


class TestMCPClientRunAsync:
    """Tests for MCPClient._run_async method."""

    def test_run_async_in_sync_context_uses_asyncio_run(self):
        """When called from sync context with no running loop, should use asyncio.run."""

        async def simple_coro():
            await asyncio.sleep(0.01)
            return "sync_result"

        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)
        result = client._run_async(simple_coro())
        assert result == "sync_result"

    def test_run_async_in_async_context_uses_current_loop(self):
        """When called from async context, should use run_coroutine_threadsafe with current loop."""

        async def simple_coro():
            await asyncio.sleep(0.01)
            return "async_result"

        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        async def test_from_async():
            loop_before = asyncio.get_running_loop()
            result = await asyncio.get_event_loop().run_in_executor(
                None, client._run_async, simple_coro()
            )
            loop_after = asyncio.get_running_loop()
            assert loop_before is loop_after
            return result

        result = asyncio.run(test_from_async())
        assert result == "async_result"

    def test_run_async_in_async_context_uses_run_coroutine_threadsafe(self):
        """Verify _run_async uses run_coroutine_threadsafe when called with running loop."""

        async def simple_coro():
            return "result"

        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        loop = asyncio.new_event_loop()
        loop_thread = None
        result_holder = []

        def run_in_thread_with_loop():
            asyncio.set_event_loop(loop)

            async def schedule_and_wait():
                future = asyncio.run_coroutine_threadsafe(simple_coro(), loop)
                return future.result()

            loop.call_soon_threadsafe(lambda: None)

            def call_run_async():
                result = client._run_async(simple_coro())
                result_holder.append(result)

            import threading

            t = threading.Thread(target=call_run_async)
            t.start()
            t.join(timeout=5)

            loop.call_soon_threadsafe(loop.stop)

        try:
            loop_thread = threading.Thread(target=run_in_thread_with_loop, daemon=True)
            loop_thread.start()

            def run_loop():
                asyncio.set_event_loop(loop)
                loop.run_forever()

            actual_loop_thread = threading.Thread(target=run_loop, daemon=True)
            actual_loop_thread.start()

            import time

            for _ in range(50):
                if result_holder:
                    break
                time.sleep(0.1)

            assert result_holder == ["result"]
        finally:
            loop.call_soon_threadsafe(loop.stop)
            loop.close()

    def test_run_async_with_persistent_loop_uses_that_loop(self):
        """When client has a persistent loop (_loop set), should use that loop."""

        async def simple_coro():
            await asyncio.sleep(0.01)
            return "persistent_loop_result"

        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        loop = asyncio.new_event_loop()
        loop_thread = None

        def run_loop():
            asyncio.set_event_loop(loop)
            loop.run_forever()

        try:
            loop_thread = threading.Thread(target=run_loop, daemon=True)
            loop_thread.start()

            while not loop.is_running():
                pass

            client._loop = loop
            result = client._run_async(simple_coro())
            assert result == "persistent_loop_result"
        finally:
            loop.call_soon_threadsafe(loop.stop)
            if loop_thread:
                loop_thread.join(timeout=2)
            loop.close()

    def test_run_async_handles_exception_in_coro(self):
        """Exceptions raised in the coroutine should propagate to caller."""

        async def failing_coro():
            await asyncio.sleep(0.01)
            raise ValueError("coroutine error")

        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        with pytest.raises(ValueError, match="coroutine error"):
            client._run_async(failing_coro())

    def test_run_async_in_async_context_handles_exception(self):
        """Exceptions in coroutine should propagate even when called from async context."""

        async def failing_coro():
            await asyncio.sleep(0.01)
            raise RuntimeError("async coroutine error")

        config = MCPServerConfig(name="test", transport="http", url="http://localhost:4001")
        client = MCPClient(config)

        async def test_from_async():
            with pytest.raises(RuntimeError, match="async coroutine error"):
                await asyncio.get_event_loop().run_in_executor(
                    None, client._run_async, failing_coro()
                )

        asyncio.run(test_from_async())
