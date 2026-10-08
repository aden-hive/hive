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
from datetime import datetime
from typing import Any

from framework.agent_loop.conversation import ConversationStore, NodeConversation
from framework.agent_loop.internals.types import LoopConfig, OutputAccumulator, TriggerEvent
from framework.llm.capabilities import supports_image_tool_results
from framework.orchestrator.node import NodeContext

logger = logging.getLogger(__name__)


@dataclass
class RestoredState:
    """State recovered from a previous checkpoint."""

    conversation: NodeConversation
    accumulator: OutputAccumulator
    start_iteration: int
    recent_responses: list[str]
    recent_tool_fingerprints: list[list[tuple[str, str]]]
    pending_input: dict[str, Any] | None
    # Whether the user explicitly clicked Stop before the process exited.
    # Persisted because `_user_stopped` is otherwise an in-memory flag —
    # without persistence, killing the runtime drops it, and the queen
    # resumes after restart (the very bug the user-stop flag prevents).
    user_stopped: bool
    # Cumulative tool calls executed across the whole run so far. Persisted
    # so a resumed worker's lifetime tool-call budget
    # (LoopConfig.tool_call_lifetime_budget) is a TRUE cap across resumes
    # rather than refilling to 0 each time the loop is re-entered. 0 when
    # the cursor predates this field (older checkpoints).
    tool_calls_used: int = 0


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
    # The queen has agent_id="queen" but messages are stored with phase_id=None.
    # Only apply phase filtering for non-queen workers in a multi-agent setup.
    phase_filter = None if (_is_continuous or ctx.agent_id == "queen") else ctx.agent_id
    conversation = await NodeConversation.restore(
        conversation_store,
        phase_id=phase_filter,
        run_id=ctx.effective_run_id,
    )
    if conversation is None:
        logger.info(
            "[restore] No conversation found for agent_id=%s phase_filter=%s run_id=%s",
            ctx.agent_id,
            phase_filter,
            ctx.effective_run_id,
        )
        return None

    logger.info(
        "[restore] Restored %d messages for agent_id=%s phase_filter=%s run_id=%s",
        conversation.message_count,
        ctx.agent_id,
        phase_filter,
        ctx.effective_run_id,
    )

    # If run_id filtering removed all messages, this is an intentional
    # restart (new run), not a crash recovery.  Return None so the caller
    # falls through to the fresh-conversation path.
    if conversation.message_count == 0:
        return None

    accumulator = await OutputAccumulator.restore(conversation_store, run_id=ctx.effective_run_id)
    accumulator.spillover_dir = config.spillover_dir
    accumulator.max_value_chars = config.max_output_value_chars

    cursor = await conversation_store.read_cursor() or {}
    start_iteration = cursor.get("iteration", 0) + 1

    # Restore stall/doom-loop detection state
    recent_responses: list[str] = cursor.get("recent_responses", [])
    raw_fps = cursor.get("recent_tool_fingerprints", [])
    recent_tool_fingerprints: list[list[tuple[str, str]]] = [
        [tuple(pair) for pair in fps]  # type: ignore[misc]
        for fps in raw_fps
    ]
    pending_input = cursor.get("pending_input")
    if not isinstance(pending_input, dict):
        pending_input = None
    user_stopped = bool(cursor.get("user_stopped", False))
    tool_calls_used = int(cursor.get("tool_calls_used", 0) or 0)

    logger.info(
        f"Restored event loop: iteration={start_iteration}, "
        f"messages={conversation.message_count}, "
        f"outputs={list(accumulator.values.keys())}, "
        f"stall_window={len(recent_responses)}, "
        f"doom_window={len(recent_tool_fingerprints)}, "
        f"user_stopped={user_stopped}, "
        f"tool_calls_used={tool_calls_used}"
    )
    return RestoredState(
        conversation=conversation,
        accumulator=accumulator,
        start_iteration=start_iteration,
        recent_responses=recent_responses,
        recent_tool_fingerprints=recent_tool_fingerprints,
        pending_input=pending_input,
        user_stopped=user_stopped,
        tool_calls_used=tool_calls_used,
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
    pending_input: dict[str, Any] | None = None,
    user_stopped: bool = False,
    tool_calls_used: int = 0,
) -> None:
    """Write checkpoint cursor for crash recovery.

    Persists iteration counter, accumulator outputs, and stall/doom-loop
    detection state so that resume picks up exactly where execution stopped.
    ``user_stopped`` carries the explicit-stop flag across restarts so a
    user-cancelled queen doesn't auto-resume after the runtime is killed.
    ``tool_calls_used`` carries the cumulative tool-call count so a resumed
    worker's lifetime tool-call budget caps across resumes instead of
    refilling.
    """
    if conversation_store:
        cursor = await conversation_store.read_cursor() or {}
        cursor.update(
            {
                "iteration": iteration,
                "node_id": ctx.agent_id,
                "outputs": accumulator.to_dict(),
                "tool_calls_used": tool_calls_used,
            }
        )
        # Persist stall/doom-loop detection state for reliable resume
        if recent_responses is not None:
            cursor["recent_responses"] = recent_responses
        if recent_tool_fingerprints is not None:
            # Convert list[list[tuple]] → list[list[list]] for JSON
            cursor["recent_tool_fingerprints"] = [[list(pair) for pair in fps] for fps in recent_tool_fingerprints]
        # Persist blocked-input state so restored runs re-block instead of
        # manufacturing a synthetic continuation turn.
        cursor["pending_input"] = pending_input
        cursor["user_stopped"] = user_stopped
        await conversation_store.write_cursor(cursor)


async def drain_injection_queue(
    queue: asyncio.Queue,
    conversation: NodeConversation,
    *,
    ctx: NodeContext,
    caption_image_fn: (Callable[[str, list[dict[str, Any]]], Awaitable[tuple[str, str] | None]] | None) = None,
    on_client_input_committed: (Callable[[int, str | None], Awaitable[None]] | None) = None,
) -> int:
    """Drain all pending injected events as user messages. Returns count.

    ``caption_image_fn`` is the unified vision fallback hook
    (``caption_tool_image`` from the vision_fallback module). It takes
    ``(intent, image_content)`` and returns ``(caption, model)`` on
    success — the model id is logged so the destination is observable.
    Single entry point for image-to-text on text-only models; the
    previous hidden generic chain (gpt-4o-mini / claude-3-haiku /
    gemini-flash) was removed in favor of the configured
    ``vision_fallback`` block so the destination is always controlled
    by ``configuration.json``.

    ``on_client_input_committed(seq, correlation_id)`` is invoked right after
    each client-input message is added, so the caller can emit a
    CLIENT_INPUT_COMMITTED event carrying the true injection time + conversation
    seq. Only fired for client input (not external events).
    """
    count = 0
    logger.debug(
        "[drain_injection_queue] Starting to drain queue, initial queue size: %s",
        queue.qsize() if hasattr(queue, "qsize") else "unknown",
    )
    while not queue.empty():
        try:
            content, is_client_input, image_content, correlation_id = queue.get_nowait()
            # Filter out non-data-URI attachments (e.g. hive:// URLs from
            # session replay) — only base64 data URIs can be sent to LLMs.
            # Two shapes are accepted: legacy image_url blocks and native
            # `file` blocks (used by the chat upload path for PDFs so
            # LiteLLM auto-remaps per provider, and by the sidecar's PDF
            # filter — keep these in sync).
            if image_content:

                def _is_data_uri_block(block: dict[str, Any]) -> bool:
                    iu = block.get("image_url")
                    if isinstance(iu, dict):
                        url = iu.get("url")
                        return isinstance(url, str) and url.startswith("data:")
                    if block.get("type") == "file":
                        file_obj = block.get("file")
                        if isinstance(file_obj, dict):
                            data = file_obj.get("file_data")
                            return isinstance(data, str) and data.startswith("data:")
                    return False

                image_content = [img for img in image_content if _is_data_uri_block(img)]
                if not image_content:
                    image_content = None
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
                if caption_image_fn is not None:
                    intent = content or ("Describe these user-injected images for a text-only agent.")
                    caption_result = await caption_image_fn(intent, image_content)
                    if caption_result:
                        description, vision_model = caption_result
                        content = f"{content}\n\n{description}" if content else description
                        logger.info(
                            "[drain] image described as text via vision fallback (model '%s')",
                            vision_model,
                        )
                    else:
                        logger.info("[drain] no vision fallback available; images dropped")
                image_content = None
            # Stamp every injected event with its arrival time so the model
            # has a consistent temporal log to reason over (and so the
            # stamp lives inside byte-stable conversation history instead
            # of a per-turn system-prompt tail). Minute precision is what
            # the queen needs for conversational / scheduling context.
            stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
            if is_client_input:
                stamped = f"[{stamp}] {content}" if content else f"[{stamp}]"
                msg = await conversation.add_user_message(
                    stamped,
                    is_client_input=True,
                    image_content=image_content,
                )
                if on_client_input_committed is not None:
                    # Announce the real injection moment + seq (this boundary
                    # drain) so the UI can position the bubble accurately.
                    await on_client_input_committed(msg.seq, correlation_id)
            else:
                await conversation.add_user_message(f"[{stamp}] [External event] {content}")
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

    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    combined = f"[{stamp}]\n" + "\n\n".join(parts)
    logger.info("[drain] %d trigger(s): %s", len(triggers), combined[:200])
    # Tag the message so the UI can render a banner instead of the raw
    # `[TRIGGER: ...]` text. The LLM still sees `combined` verbatim.
    await conversation.add_user_message(combined, is_trigger=True)
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
    if pause_requested:
        completed = iteration
        logger.info(f"⏸ Pausing after {completed} iteration(s) completed (context-level)")
        return True

    return False
