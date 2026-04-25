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
    """Existing keys in ctx.input_data are not overridden by trigger payload.

    Also verifies that non-conflicting payload keys are still merged in.
    """
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    # Create a mock NodeContext with existing data
    ctx = MagicMock(spec=NodeContext)
    ctx.input_data = {"current_date": "2025-01-01"}  # Existing value (should be preserved)

    # Add trigger event with both conflicting and new keys
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger",
            payload={
                "current_date": "2026-04-24",  # conflicts — should NOT override
                "task": "run it",  # new key — SHOULD be injected
            },
        )
    )

    # Drain the queue with ctx
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)

    assert count == 1
    # Verify existing value was NOT overridden
    assert ctx.input_data["current_date"] == "2025-01-01"
    # Verify non-conflicting payload key was still merged in
    assert ctx.input_data["task"] == "run it"


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


@pytest.mark.asyncio
async def test_drain_trigger_queue_clears_stale_keys() -> None:
    """Stale trigger keys are cleared before injecting new ones."""
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    ctx = MagicMock(spec=NodeContext)
    ctx.input_data = {}

    # First drain: inject trigger keys
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger-1",
            payload={"current_date": "2026-04-24", "task": "run it"},
        )
    )
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)
    assert count == 1
    assert ctx.input_data["current_date"] == "2026-04-24"
    assert ctx.input_data["task"] == "run it"

    # Second drain: new trigger with different values for the same keys
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger-2",
            payload={"current_date": "2026-04-25", "task": "new task"},
        )
    )
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)
    assert count == 1
    # Verify NEW values were injected (old ones were cleared)
    assert ctx.input_data["current_date"] == "2026-04-25"
    assert ctx.input_data["task"] == "new task"


@pytest.mark.asyncio
async def test_drain_trigger_queue_preserves_keys_when_empty() -> None:
    """When no new triggers arrive, old trigger keys are preserved."""
    queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
    conversation = MagicMock(spec=ConversationStore)
    conversation.add_user_message = AsyncMock()

    ctx = MagicMock(spec=NodeContext)
    ctx.input_data = {}

    # First drain: inject trigger keys
    await queue.put(
        TriggerEvent(
            trigger_type="timer",
            source_id="test-trigger",
            payload={"current_date": "2026-04-24", "task": "run it"},
        )
    )
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)
    assert count == 1
    assert ctx.input_data["current_date"] == "2026-04-24"
    assert ctx.input_data["task"] == "run it"

    # Second drain: NO triggers - old keys are preserved (no new data)
    count = await drain_trigger_queue(queue, conversation, ctx=ctx)
    assert count == 0
    # Verify old keys are still present (no new triggers to replace them)
    assert ctx.input_data["current_date"] == "2026-04-24"
    assert ctx.input_data["task"] == "run it"
