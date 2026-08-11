"""
Basic unit tests for EventBus pub/sub and wait_for behavior.

These tests focus on core functionality and timeout handling
without asserting internal implementation details.
"""

import pytest
import asyncio
from typing import List
from framework.runtime.event_bus import EventBus, AgentEvent, EventType

@pytest.mark.asyncio
async def test_pub_sub_basic():
    """Test basic publish-subscribe mechanism."""
    bus = EventBus()
    received: List[AgentEvent] = []

    async def handler(event: AgentEvent):
        received.append(event)

    # Subscribe is synchronous
    bus.subscribe([EventType.CUSTOM], handler)
    
    event = AgentEvent(type=EventType.CUSTOM, stream_id="test_stream", data={"hello": "world"})
    await bus.publish(event)
    
    # Allow async tasks to complete (since publish uses asyncio.gather)
    assert len(received) == 1
    assert received[0].data["hello"] == "world"
    assert received[0].stream_id == "test_stream"

@pytest.mark.asyncio
async def test_wait_for_timeout():
    """Test that wait_for correctly times out when event doesn't occur."""
    bus = EventBus()
    # Should timeout immediately (0.1s)
    # We use a custom event type that won't be fired
    event = await bus.wait_for(EventType.CUSTOM, timeout=0.1)
    assert event is None

@pytest.mark.asyncio
async def test_wait_for_success():
    """Test that wait_for correctly captures an event."""
    bus = EventBus()
    
    async def delayed_publish():
        await asyncio.sleep(0.1)
        await bus.publish(AgentEvent(type=EventType.CUSTOM, stream_id="test", data={"status": "ok"}))

    # Start publisher in background
    asyncio.create_task(delayed_publish())
    
    # Wait for it
    event = await bus.wait_for(EventType.CUSTOM, timeout=1.0)
    
    assert event is not None
    assert event.data["status"] == "ok"

@pytest.mark.asyncio
async def test_filtering():
    """Test stream filtering."""
    bus = EventBus()
    received: List[AgentEvent] = []
    
    async def handler(event: AgentEvent):
        received.append(event)
        
    # Only listen to stream="wanted"
    bus.subscribe([EventType.CUSTOM], handler, filter_stream="wanted")
    
    # Publish unwanted
    await bus.publish(AgentEvent(type=EventType.CUSTOM, stream_id="unwanted"))
    
    # Publish wanted
    await bus.publish(AgentEvent(type=EventType.CUSTOM, stream_id="wanted"))
    
    assert len(received) == 1
    assert received[0].stream_id == "wanted"
