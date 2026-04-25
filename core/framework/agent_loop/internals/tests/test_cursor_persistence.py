"""Tests for cursor_persistence module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from framework.agent_loop.conversation import ConversationStore
from framework.agent_loop.internals.cursor_persistence import drain_trigger_queue
from framework.agent_loop.internals.types import TriggerEvent
from framework.orchestrator.node import NodeContext


@pytest.mark.asyncio
async def test_drain_trigger_queue_injects_payload_into_input_data() -> None:
    """Trigger payload is injected into ctx.input_data when ctx is provided."""
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    # Create a mock NodeContext
    ctx = MagicMock(spec=NodeContext)
    ctx.input_data = {}

    # Add trigger event with payload
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger",
            payload={"current_date": "2026-04-24", "task": "run it"},
        )
    )

    # Drain the queue with ctx
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)

    assert count == 1
    # Verify payload was injected into ctx.input_data
    assert ctx.input_data["current_date"] == "2026-04-24"
    assert ctx.input_data["task"] == "run it"
    # Verify conversation still got the message
    conversation.add_user_message.assert_called_once()


@pytest.mark.asyncio
async def test_drain_trigger_queue_does_not_override_existing_input_data() -> None:
    """Existing keys in ctx.input_data are not overridden by trigger payload."""
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    # Create a mock NodeContext with existing data
    ctx = MagicMock(spec=NodeContext)
    ctx.input_data = {"current_date": "2025-01-01"}  # Existing value

    # Add trigger event with conflicting payload
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger",
            payload={"current_date": "2026-04-24"},  # Should NOT override
        )
    )

    # Drain the queue with ctx
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)

    assert count == 1
    # Verify existing value was NOT overridden
    assert ctx.input_data["current_date"] == "2025-01-01"


@pytest.mark.asyncio
async def test_drain_trigger_queue_without_ctx() -> None:
    """Trigger queue works without ctx (backward compatibility)."""
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    # Add trigger event
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger",
            payload={"task": "run it"},
        )
    )

    # Drain without ctx (old behavior)
    count = await drain_trigger_queue(queue, conversation)

    assert count == 1
    # Verify conversation still got the message
    conversation.add_user_message.assert_called_once()


@pytest.mark.asyncio
async def test_drain_trigger_queue_empty() -> None:
    """Empty trigger queue returns 0 and does nothing."""
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    ctx = MagicMock(spec=NodeContext)
    ctx.input_data = {}

    # Drain empty queue
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)

    assert count == 0
    conversation.add_user_message.assert_not_called()
