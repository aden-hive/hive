"""
Tests for ClientIO gateway (WP-9).

Covers:
- ActiveNodeClientIO: emit_output → output_stream round-trip, request_input, timeout
- InertNodeClientIO: emit_output publishes NODE_INTERNAL_OUTPUT, request_input returns redirect
- ClientIOGateway: factory creates correct variant
"""

import asyncio

import pytest

from framework.graph.client_io import (
    ActiveNodeClientIO,
    ClientIOGateway,
    InertNodeClientIO,
    NodeClientIO,
)
from framework.runtime.event_bus import AgentEvent, EventType

_AGENT_EVENT_FIELDS = {"stream_id", "node_id", "execution_id", "correlation_id"}


class MockEventBus:
    """Lightweight stand-in for EventBus that records published events."""

    def __init__(self) -> None:
        self.events: list[AgentEvent] = []

    async def _record(self, event_type: EventType, **kwargs) -> None:
        agent_kwargs = {k: v for k, v in kwargs.items() if k in _AGENT_EVENT_FIELDS}
        data = {k: v for k, v in kwargs.items() if k not in _AGENT_EVENT_FIELDS}
        self.events.append(AgentEvent(type=event_type, **agent_kwargs, data=data))

    async def emit_client_output_delta(self, **kwargs) -> None:
        await self._record(EventType.CLIENT_OUTPUT_DELTA, **kwargs)

    async def emit_client_input_requested(self, **kwargs) -> None:
        await self._record(EventType.CLIENT_INPUT_REQUESTED, **kwargs)

    async def emit_node_internal_output(self, **kwargs) -> None:
        await self._record(EventType.NODE_INTERNAL_OUTPUT, **kwargs)

    async def emit_node_input_blocked(self, **kwargs) -> None:
        await self._record(EventType.NODE_INPUT_BLOCKED, **kwargs)


# --- ActiveNodeClientIO tests ---


@pytest.mark.asyncio
async def test_active_emit_and_consume():
    """emit_output → output_stream round-trip works correctly."""
    bus = MockEventBus()
    io = ActiveNodeClientIO(node_id="n1", event_bus=bus)

    await io.emit_output("Hello ")
    await io.emit_output("World", is_final=True)

    chunks = []
    async for chunk in io.output_stream():
        chunks.append(chunk)

    assert chunks == ["Hello ", "World"]
    assert len(bus.events) == 2
    assert all(e.type == EventType.CLIENT_OUTPUT_DELTA for e in bus.events)
    # Verify snapshot accumulates
    assert bus.events[0].data["snapshot"] == "Hello "
    assert bus.events[1].data["snapshot"] == "Hello World"


@pytest.mark.asyncio
async def test_active_request_input():
    """request_input blocks until provide_input is called."""
    bus = MockEventBus()
    io = ActiveNodeClientIO(node_id="n1", event_bus=bus)

    async def fulfill_later():
        await asyncio.sleep(0.01)
        await io.provide_input("user says hi")

    task = asyncio.create_task(fulfill_later())
    result = await io.request_input(prompt="What?")
    await task

    assert result == "user says hi"
    assert len(bus.events) == 1
    assert bus.events[0].type == EventType.CLIENT_INPUT_REQUESTED
    assert bus.events[0].data["prompt"] == "What?"


@pytest.mark.asyncio
async def test_active_request_input_timeout():
    """request_input raises TimeoutError when timeout expires."""
    io = ActiveNodeClientIO(node_id="n1")

    with pytest.raises(TimeoutError):
        await io.request_input(prompt="waiting", timeout=0.01)


@pytest.mark.asyncio
async def test_active_request_input_cancellation_leak_regression():
    """
    Regression test for cancellation during emit_client_input_requested.

    If request_input is cancelled while awaiting the event bus emission, internal state must be
    reset so that a subsequent request_input can proceed normally.
    """

    class SlowEventBus(MockEventBus):
        async def emit_client_input_requested(self, **kwargs) -> None:
            await asyncio.sleep(1.0)
            await super().emit_client_input_requested(**kwargs)

    bus = SlowEventBus()
    io = ActiveNodeClientIO(node_id="n1", event_bus=bus)

    task1 = asyncio.create_task(io.request_input(prompt="Wait"))
    await asyncio.sleep(0.01)
    task1.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task1

    task2 = asyncio.create_task(io.request_input(prompt="Second"))
    await asyncio.sleep(0.01)
    await io.provide_input("data")
    assert await task2 == "data"


@pytest.mark.asyncio
async def test_active_request_input_result_read_happens_with_event_active_regression():
    """
    Regression test for a critical section gap where _input_event was cleared before _input_result
    was read, enabling a concurrent request to wipe the result.
    """

    class ResultTracker:
        reads_with_event_active: list[bool] = []

        def __get__(self, obj, objtype=None):
            if obj is None:
                return self
            self.reads_with_event_active.append(obj._input_event is not None)
            return getattr(obj, "_mock_result", None)

        def __set__(self, obj, value):
            obj._mock_result = value

    class TrackedIO(ActiveNodeClientIO):
        _input_result = ResultTracker()

    io = TrackedIO(node_id="n1")

    task = asyncio.create_task(io.request_input(prompt="1"))
    await asyncio.sleep(0.01)

    await io.provide_input("test_data")
    assert await task == "test_data"

    assert True in TrackedIO._input_result.reads_with_event_active


# --- InertNodeClientIO tests ---


@pytest.mark.asyncio
async def test_inert_emit_publishes_internal():
    """InertNodeClientIO.emit_output publishes NODE_INTERNAL_OUTPUT."""
    bus = MockEventBus()
    io = InertNodeClientIO(node_id="n2", event_bus=bus)

    await io.emit_output("internal log")

    assert len(bus.events) == 1
    assert bus.events[0].type == EventType.NODE_INTERNAL_OUTPUT
    assert bus.events[0].data["content"] == "internal log"


@pytest.mark.asyncio
async def test_inert_request_input_returns_redirect():
    """request_input returns a redirect string and publishes NODE_INPUT_BLOCKED."""
    bus = MockEventBus()
    io = InertNodeClientIO(node_id="n2", event_bus=bus)

    result = await io.request_input(prompt="need data")

    assert "internal processing node" in result
    assert len(bus.events) == 1
    assert bus.events[0].type == EventType.NODE_INPUT_BLOCKED
    assert bus.events[0].data["prompt"] == "need data"


# --- ClientIOGateway tests ---


def test_gateway_creates_active_for_client_facing():
    """ClientIOGateway.create_io returns ActiveNodeClientIO when client_facing=True."""
    gateway = ClientIOGateway()
    io = gateway.create_io(node_id="n1", client_facing=True)

    assert isinstance(io, ActiveNodeClientIO)
    assert isinstance(io, NodeClientIO)


def test_gateway_creates_inert_for_internal():
    """ClientIOGateway.create_io returns InertNodeClientIO when client_facing=False."""
    gateway = ClientIOGateway()
    io = gateway.create_io(node_id="n2", client_facing=False)

    assert isinstance(io, InertNodeClientIO)
    assert isinstance(io, NodeClientIO)
