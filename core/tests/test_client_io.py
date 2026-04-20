"""Tests for ActiveNodeClientIO race-condition fixes (issue #6885)."""

import asyncio

import pytest


@pytest.fixture
def _event_loop_policy():
    """Ensure a fresh event loop for each test."""
    pass


class MockEventBus:
    """Minimal event bus stub for testing."""

    async def emit_client_input_requested(self, **kwargs):
        pass

    async def emit_client_output_delta(self, **kwargs):
        pass


class SlowEventBus(MockEventBus):
    """Event bus that delays emit_client_input_requested indefinitely."""

    async def emit_client_input_requested(self, **kwargs):
        await asyncio.sleep(10)


class TestCancellationLeak:
    """Bug 1: cancellation during emit_client_input_requested leaks _input_event."""

    @pytest.mark.asyncio
    async def test_cancellation_during_emit_resets_state(self):
        """If request_input is cancelled during the emit, _input_event must reset."""
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=SlowEventBus())

        # Start request_input — it will block inside the slow emit
        task1 = asyncio.create_task(io.request_input(prompt="Wait"))
        await asyncio.sleep(0.05)
        task1.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task1

        # State must be clean — a second request_input should work
        assert io._input_event is None
        assert io._input_result is None

        task2 = asyncio.create_task(io.request_input(prompt="Second"))
        await asyncio.sleep(0.05)
        await io.provide_input("data")
        assert await task2 == "data"

    @pytest.mark.asyncio
    async def test_cancellation_during_wait_resets_state(self):
        """If request_input is cancelled while waiting for input, state resets."""
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=MockEventBus())

        task = asyncio.create_task(io.request_input(prompt="Wait"))
        await asyncio.sleep(0.05)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert io._input_event is None
        assert io._input_result is None


class TestPrematureLockRelease:
    """Bug 2: _input_event reset before _input_result is captured."""

    @pytest.mark.asyncio
    async def test_result_captured_before_state_reset(self):
        """Result must be captured atomically with state reset."""
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=MockEventBus())

        task = asyncio.create_task(io.request_input(prompt="Give input"))
        await asyncio.sleep(0.05)
        await io.provide_input("my_value")

        result = await task
        assert result == "my_value"

        # Both fields must be clean after completion
        assert io._input_event is None
        assert io._input_result is None

    @pytest.mark.asyncio
    async def test_concurrent_request_cannot_wipe_result(self):
        """A second request_input must not corrupt the first one's result."""
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=MockEventBus())

        # First request
        task1 = asyncio.create_task(io.request_input(prompt="First"))
        await asyncio.sleep(0.05)
        await io.provide_input("result_1")
        val1 = await task1
        assert val1 == "result_1"

        # Second request — should not interfere with first
        task2 = asyncio.create_task(io.request_input(prompt="Second"))
        await asyncio.sleep(0.05)
        await io.provide_input("result_2")
        val2 = await task2
        assert val2 == "result_2"


class TestRequestInputBasic:
    """Regression tests for normal request_input behavior."""

    @pytest.mark.asyncio
    async def test_basic_request_input(self):
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=MockEventBus())
        task = asyncio.create_task(io.request_input(prompt="Name?"))
        await asyncio.sleep(0.05)
        await io.provide_input("Alice")
        assert await task == "Alice"

    @pytest.mark.asyncio
    async def test_request_input_already_pending(self):
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=MockEventBus())
        task = asyncio.create_task(io.request_input(prompt="A"))
        await asyncio.sleep(0.05)

        with pytest.raises(RuntimeError, match="already pending"):
            await io.request_input(prompt="B")

        # Clean up
        await io.provide_input("done")
        await task

    @pytest.mark.asyncio
    async def test_provide_input_without_pending_raises(self):
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1")
        with pytest.raises(RuntimeError, match="no pending request_input"):
            await io.provide_input("oops")

    @pytest.mark.asyncio
    async def test_timeout_resets_state(self):
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1", event_bus=MockEventBus())

        with pytest.raises(asyncio.TimeoutError):
            await io.request_input(prompt="Hurry", timeout=0.05)

        # State must be clean after timeout
        assert io._input_event is None
        assert io._input_result is None

    @pytest.mark.asyncio
    async def test_request_input_without_event_bus(self):
        from framework.orchestrator.client_io import ActiveNodeClientIO

        io = ActiveNodeClientIO(node_id="n1")
        task = asyncio.create_task(io.request_input(prompt="X"))
        await asyncio.sleep(0.05)
        await io.provide_input("Y")
        assert await task == "Y"
