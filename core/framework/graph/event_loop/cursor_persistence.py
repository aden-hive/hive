"""Cursor persistence, queue draining, and pause detection.

Handles the checkpoint/resume cycle: restoring state from a previous
conversation store, writing cursor data, and managing injection/trigger
queues between iterations.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from framework.graph.conversation import ConversationStore, NodeConversation
from framework.graph.event_loop.types import LoopConfig, OutputAccumulator, TriggerEvent
from framework.graph.node import NodeContext
from framework.llm.capabilities import supports_image_tool_results

logger = logging.getLogger(__name__)


@dataclass
class RestoredState:
    """State recovered from a previous checkpoint."""

    conversation: NodeConversation
    accumulator: OutputAccumulator
    start_iteration: int
    recent_responses: list[str]
    recent_tool_fingerprints: list[list[tuple[str, str]]]


async def restore(
    conversation_store: ConversationStore | None,
    ctx: NodeContext,
    config: LoopConfig,
) -> RestoredState | None:
    """Attempt to restore from a previous checkpoint.

    Returns a ``RestoredState`` with conversation, accumulator, iteration
    counter, and stall/doom-loop detection state — everything needed to
    resume exactly where execution stopped.
    """
    if conversation_store is None:
        return None

    # In isolated mode, filter parts by phase_id so the node only sees
    # its own messages in the shared flat conversation store.  In
    # continuous mode (or when _restore is called for timer-resume)
    # load all parts — the full conversation threads across nodes.
    _is_continuous = getattr(ctx, "continuous_mode", False)
    phase_filter = None if _is_continuous else ctx.node_id
    conversation = await NodeConversation.restore(
        conversation_store,
        phase_id=phase_filter,
    )
    if conversation is None:
        return None

    accumulator = await OutputAccumulator.restore(conversation_store)
    accumulator.spillover_dir = config.spillover_dir
    accumulator.max_value_chars = config.max_output_value_chars

    cursor = await conversation_store.read_cursor()
    start_iteration = cursor.get("iteration", 0) + 1 if cursor else 0

    # Restore stall/doom-loop detection state
    recent_responses: list[str] = cursor.get("recent_responses", []) if cursor else []
    raw_fps = cursor.get("recent_tool_fingerprints", []) if cursor else []
    recent_tool_fingerprints: list[list[tuple[str, str]]] = [
        [tuple(pair) for pair in fps]  # type: ignore[misc]
        for fps in raw_fps
    ]

    logger.info(
        f"Restored event loop: iteration={start_iteration}, "
        f"messages={conversation.message_count}, "
        f"outputs={list(accumulator.values.keys())}, "
        f"stall_window={len(recent_responses)}, "
        f"doom_window={len(recent_tool_fingerprints)}"
    )
    return RestoredState(
        conversation=conversation,
        accumulator=accumulator,
        start_iteration=start_iteration,
        recent_responses=recent_responses,
        recent_tool_fingerprints=recent_tool_fingerprints,
    )


async def write_cursor(
    conversation_store: ConversationStore | None,
    ctx: NodeContext,
    conversation: NodeConversation,
    accumulator: OutputAccumulator,
    iteration: int,
    *,
    recent_responses: list[str] | None = None,
    recent_tool_fingerprints: list[list[tuple[str, str]]] | None = None,
) -> None:
    """Write checkpoint cursor for crash recovery.

    Persists iteration counter, accumulator outputs, and stall/doom-loop
    detection state so that resume picks up exactly where execution stopped.
    """
    if conversation_store:
        cursor = await conversation_store.read_cursor() or {}
        cursor.update(
            {
                "iteration": iteration,
                "node_id": ctx.node_id,
                "next_seq": conversation.next_seq,
                "outputs": accumulator.to_dict(),
            }
        )
        # Persist stall/doom-loop detection state for reliable resume
        if recent_responses is not None:
            cursor["recent_responses"] = recent_responses
        if recent_tool_fingerprints is not None:
            # Convert list[list[tuple]] → list[list[list]] for JSON
            cursor["recent_tool_fingerprints"] = [
                [list(pair) for pair in fps] for fps in recent_tool_fingerprints
            ]
        await conversation_store.write_cursor(cursor)


async def drain_injection_queue(
    queue: asyncio.Queue,
    conversation: NodeConversation,
    *,
    ctx: NodeContext,
    describe_images_as_text_fn: (
        Callable[[list[dict[str, Any]]], Awaitable[str | None]] | None
    ) = None,
) -> int:
    """Drain all pending injected events as user messages. Returns count."""
    count = 0
    while not queue.empty():
        try:
            content, is_client_input, image_content = queue.get_nowait()
            logger.info(
                "[drain] injected message (client_input=%s, images=%d): %s",
                is_client_input,
                len(image_content) if image_content else 0,
                content[:200] if content else "(empty)",
            )
            if image_content and ctx.llm and not supports_image_tool_results(ctx.llm.model):
                logger.info(
                    "Model '%s' does not support images; attempting vision fallback",
                    ctx.llm.model,
                )
                if describe_images_as_text_fn is not None:
                    description = await describe_images_as_text_fn(image_content)
                    if description:
                        content = f"{content}\n\n{description}" if content else description
                        logger.info("[drain] image described as text via vision fallback")
                    else:
                        logger.info("[drain] no vision fallback available; images dropped")
                image_content = None
            # Real user input is stored as-is; external events get a prefix
            if is_client_input:
                await conversation.add_user_message(
                    content,
                    is_client_input=True,
                    image_content=image_content,
                )
            else:
                await conversation.add_user_message(f"[External event]: {content}")
            count += 1
        except asyncio.QueueEmpty:
            break
    return count


async def drain_trigger_queue(
    queue: asyncio.Queue,
    conversation: NodeConversation,
) -> int:
    """Drain all pending trigger events as a single batched user message.

    Multiple triggers are merged so the LLM sees them atomically and can
    reason about all pending triggers before acting.
    """
    triggers: list[TriggerEvent] = []
    while not queue.empty():
        try:
            triggers.append(queue.get_nowait())
        except asyncio.QueueEmpty:
            break

    if not triggers:
        return 0

    parts: list[str] = []
    for t in triggers:
        task = t.payload.get("task", "")
        task_line = f"\nTask: {task}" if task else ""
        payload_str = json.dumps(t.payload, default=str)
        parts.append(f"[TRIGGER: {t.trigger_type}/{t.source_id}]{task_line}\n{payload_str}")

    combined = "\n\n".join(parts)
    logger.info("[drain] %d trigger(s): %s", len(triggers), combined[:200])
    await conversation.add_user_message(combined)
    return len(triggers)


async def check_pause(
    ctx: NodeContext,
    conversation: NodeConversation,
    iteration: int,
) -> bool:
    """
    Check if pause has been requested. Returns True if paused.

    Note: This check happens BEFORE starting iteration N, after completing N-1.
    If paused, the node exits having completed {iteration} iterations (0 to iteration-1).
    """
    # Check executor-level pause event (for /pause command, Ctrl+Z)
    if ctx.pause_event and ctx.pause_event.is_set():
        completed = iteration  # 0-indexed: iteration=3 means 3 iterations completed (0,1,2)
        logger.info(f"⏸ Pausing after {completed} iteration(s) completed (executor-level)")
        return True

    # Check context-level pause flags (legacy/alternative methods)
    pause_requested = ctx.input_data.get("pause_requested", False)
    if not pause_requested:
        try:
            pause_requested = ctx.memory.read("pause_requested") or False
        except (PermissionError, KeyError):
            pause_requested = False
    if pause_requested:
        completed = iteration
        logger.info(f"⏸ Pausing after {completed} iteration(s) completed (context-level)")
        return True

    return False
