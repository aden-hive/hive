"""Regression tests for ActiveNodeClientIO race conditions.

Covers:
- Coroutine cancellation leak: _input_event not cleaned up when cancelled
  during emit_client_input_requested (before the try/finally block).
- Premature lock release: _input_result wiped by a concurrent request_input
  because _input_event was cleared before the result was captured.
"""

import asyncio

import pytest

from framework.graph.client_io import ActiveNodeClientIO


class _MockEventBus:
    """Minimal event bus stub — no-ops all emit calls."""

    async def emit_client_input_requested(self, **kwargs) -> None:
        pass


class _SlowEventBus(_MockEventBus):
    """Event bus that blocks in emit_client_input_requested for cancellation tests."""

    async def emit_client_input_requested(self, **kwargs) -> None:
        await asyncio.sleep(1.0)


@pytest.mark.asyncio
async def test_request_input_cancellation_leak():
    """Cancelling during emit must not leave _input_event set.

    If _input_event leaks, the second request_input raises
    'request_input already pending for this node'.
    """
    bus = _SlowEventBus()
    io = ActiveNodeClientIO(node_id="n1", event_bus=bus)

    # Cancel during the slow emit
    task1 = asyncio.create_task(io.request_input(prompt="Wait"))
    await asyncio.sleep(0.01)
    task1.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task1

    # A second request must succeed — no leaked state
    task2 = asyncio.create_task(io.request_input(prompt="Second"))
    await asyncio.sleep(0.01)
    await io.provide_input("data")
    assert await task2 == "data"


@pytest.mark.asyncio
async def test_request_input_result_captured_before_lock_release():
    """_input_result must be read while _input_event is still set.

    In the old code, _input_event = None ran in finally *before* the result
    was captured, opening a race window where a concurrent request could
    overwrite _input_result with None.
    """

    reads_with_event_active: list[bool] = []

    class _TrackerDescriptor:
        def __get__(self, obj, objtype=None):
            if obj is None:
                return self
            reads_with_event_active.append(obj._input_event is not None)
            return getattr(obj, "_mock_result", None)

        def __set__(self, obj, value):
            obj._mock_result = value

    class _TrackedIO(ActiveNodeClientIO):
        _input_result = _TrackerDescriptor()

    io = _TrackedIO(node_id="n1")

    task = asyncio.create_task(io.request_input(prompt="1"))
    await asyncio.sleep(0.01)
    await io.provide_input("test_data")
    assert await task == "test_data"

    # The result must have been read while _input_event was still active (True)
    assert any(reads_with_event_active), (
        "Expected at least one _input_result read while _input_event was set; "
        "got reads_with_event_active=%r" % reads_with_event_active
    )
