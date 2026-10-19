"""EventBus publishing helpers for the event loop.

Thin wrappers around EventBus.emit_*() calls that check for bus existence
before publishing.  Extracted to reduce noise in the main orchestrator.
"""

from __future__ import annotations

import logging
import time

from framework.agent_loop.conversation import NodeConversation
from framework.agent_loop.internals.types import HookContext
from framework.host.event_bus import EventBus
from framework.orchestrator.node import NodeContext

logger = logging.getLogger(__name__)


async def publish_loop_started(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    max_iterations: int,
    execution_id: str = "",
) -> None:
    if event_bus:
        await event_bus.emit_node_loop_started(
            stream_id=stream_id,
            node_id=node_id,
            max_iterations=max_iterations,
            execution_id=execution_id,
        )


async def publish_iteration(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    iteration: int,
    execution_id: str = "",
    extra_data: dict | None = None,
) -> None:
    if event_bus:
        await event_bus.emit_node_loop_iteration(
            stream_id=stream_id,
            node_id=node_id,
            iteration=iteration,
            execution_id=execution_id,
            extra_data=extra_data,
        )


async def publish_llm_turn_complete(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    stop_reason: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cost_usd: float = 0.0,
    credits: float | None = None,
    execution_id: str = "",
    iteration: int | None = None,
    system_prefix_sha: str | None = None,
    system_suffix_sha: str | None = None,
    history_anchor_idx: int | None = None,
    message_count: int | None = None,
) -> None:
    if event_bus:
        await event_bus.emit_llm_turn_complete(
            stream_id=stream_id,
            node_id=node_id,
            stop_reason=stop_reason,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd,
            credits=credits,
            execution_id=execution_id,
            iteration=iteration,
            system_prefix_sha=system_prefix_sha,
            system_suffix_sha=system_suffix_sha,
            history_anchor_idx=history_anchor_idx,
            message_count=message_count,
        )


def log_skip_judge(
    ctx: NodeContext,
    node_id: str,
    iteration: int,
    feedback: str,
    tool_calls: list[dict],
    llm_text: str,
    turn_tokens: dict[str, int],
    iter_start: float,
) -> None:
    """Log a CONTINUE step that skips judge evaluation (e.g., waiting for input)."""
    if ctx.runtime_logger:
        ctx.runtime_logger.log_step(
            node_id=node_id,
            node_type="event_loop",
            step_index=iteration,
            verdict="CONTINUE",
            verdict_feedback=feedback,
            tool_calls=tool_calls,
            llm_text=llm_text,
            input_tokens=turn_tokens.get("input", 0),
            output_tokens=turn_tokens.get("output", 0),
            latency_ms=int((time.time() - iter_start) * 1000),
        )


async def publish_loop_completed(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    iterations: int,
    execution_id: str = "",
) -> None:
    if event_bus:
        await event_bus.emit_node_loop_completed(
            stream_id=stream_id,
            node_id=node_id,
            iterations=iterations,
            execution_id=execution_id,
        )


async def publish_context_usage(
    event_bus: EventBus | None,
    ctx: NodeContext,
    conversation: NodeConversation,
    trigger: str,
    *,
    tools: list | None = None,
) -> None:
    """Emit CONTEXT_USAGE_UPDATED with a real-time estimate of the NEXT prompt.

    The reported ``estimated_tokens`` is a char-based projection of everything
    the next LLM request will carry: conversation messages (content + tool
    args + image blocks), the rendered system prompt (static + dynamic
    suffix), and the JSON tool definitions. This is the number the debug
    panel should show as "how full is the request that's about to go out".

    Unlike ``conversation.estimate_tokens()`` which is conversation-only and
    intentionally narrow (used by compaction triggers), this estimate always
    uses the char-based heuristic so the value updates immediately as
    messages are added — without waiting for the next API response to
    re-calibrate the cached ``_last_api_input_tokens``.

    ``tools`` is optional; when omitted, the tool-definitions component is
    counted as 0. Callers in the inner tool loop should pass it for the most
    accurate readout.
    """
    if not event_bus:
        return

    import json

    from framework.host.event_bus import AgentEvent, EventType

    # Conversation portion (always char-based here, not the cached API value,
    # so the readout reflects "size right now" rather than "size at the last
    # LLM call").
    conv_chars, image_blocks = conversation.conversation_chars_and_images()

    # System prompt as it would be sent next: static + dynamic suffix already
    # concatenated by the conversation's ``system_prompt`` property.
    system_chars = len(conversation.system_prompt)

    # Tool definitions as the LLM wrapper will serialise them: name +
    # description + JSON-encoded parameters per tool. Cheap to compute and
    # rare to be large enough to matter on its own, but for queens with 100+
    # tools registered this contributes meaningfully.
    tool_defs_chars = 0
    if tools:
        for t in tools:
            tool_defs_chars += len(getattr(t, "name", "") or "")
            tool_defs_chars += len(getattr(t, "description", "") or "")
            params = getattr(t, "parameters", None)
            if params:
                try:
                    tool_defs_chars += len(json.dumps(params))
                except (TypeError, ValueError):
                    # Non-serialisable parameters shouldn't crash telemetry.
                    pass

    total_chars = conv_chars + system_chars + tool_defs_chars
    # 4/3 safety margin (chars/4 with a 4/3 correction = chars/3).
    char_tokens = (total_chars * 4) // (3 * 4)
    image_tokens = image_blocks * 2000
    estimated = char_tokens + image_tokens

    max_tokens = conversation._max_context_tokens
    ratio = estimated / max_tokens if max_tokens > 0 else 0.0

    # NOTE: this event intentionally carries only the lightweight metrics
    # below — never a `full_request` snapshot of the whole prompt. It used
    # to embed one (~280 KB: system text + every message + tool defs) for a
    # debug panel, but it fires on every context tick, so events.jsonl
    # ballooned to tens of MB and the desktop could no longer load the
    # session. The metrics here are enough to drive the usage gauge.

    # Diagnostic for "why does the UI show window=X?" — single line at the
    # final emission boundary so future regressions on context_usage_updated
    # can be traced without re-instrumenting the agent loop.
    logger.debug(
        "context_usage emit agent=%s trigger=%s max=%d estimated=%d (conv=%d sys=%d tools=%d imgs=%d) msgs=%d",
        ctx.agent_id,
        trigger,
        max_tokens,
        estimated,
        conv_chars,
        system_chars,
        tool_defs_chars,
        image_blocks,
        conversation.message_count,
    )
    await event_bus.publish(
        AgentEvent(
            type=EventType.CONTEXT_USAGE_UPDATED,
            stream_id=ctx.stream_id or ctx.agent_id,
            node_id=ctx.agent_id,
            data={
                "usage_ratio": round(ratio, 4),
                "usage_pct": round(ratio * 100),
                "message_count": conversation.message_count,
                "estimated_tokens": estimated,
                "max_context_tokens": max_tokens,
                "trigger": trigger,
                # Component breakdown so the debug panel can show where the
                # tokens go, not just the total.
                "breakdown": {
                    "conversation_chars": conv_chars,
                    "system_chars": system_chars,
                    "tool_defs_chars": tool_defs_chars,
                    "image_blocks": image_blocks,
                    "image_tokens": image_tokens,
                },
            },
        )
    )


async def publish_stalled(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    execution_id: str = "",
) -> None:
    if event_bus:
        await event_bus.emit_node_stalled(
            stream_id=stream_id,
            node_id=node_id,
            reason="Consecutive similar responses detected",
            execution_id=execution_id,
        )


async def publish_text_delta(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    content: str,
    snapshot: str,
    ctx: NodeContext,
    execution_id: str = "",
    iteration: int | None = None,
    inner_turn: int = 0,
) -> None:
    if event_bus:
        if ctx.emits_client_io:
            await event_bus.emit_client_output_delta(
                stream_id=stream_id,
                node_id=node_id,
                content=content,
                snapshot=snapshot,
                execution_id=execution_id,
                iteration=iteration,
                inner_turn=inner_turn,
            )
        else:
            await event_bus.emit_llm_text_delta(
                stream_id=stream_id,
                node_id=node_id,
                content=content,
                snapshot=snapshot,
                execution_id=execution_id,
                inner_turn=inner_turn,
            )


async def publish_tool_started(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    tool_use_id: str,
    tool_name: str,
    tool_input: dict,
    execution_id: str = "",
) -> None:
    if event_bus:
        await event_bus.emit_tool_call_started(
            stream_id=stream_id,
            node_id=node_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            tool_input=tool_input,
            execution_id=execution_id,
        )


async def publish_tool_completed(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    tool_use_id: str,
    tool_name: str,
    result: str,
    is_error: bool,
    execution_id: str = "",
) -> None:
    if event_bus:
        await event_bus.emit_tool_call_completed(
            stream_id=stream_id,
            node_id=node_id,
            tool_use_id=tool_use_id,
            tool_name=tool_name,
            result=result,
            is_error=is_error,
            execution_id=execution_id,
        )


async def publish_judge_verdict(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    action: str,
    feedback: str = "",
    judge_type: str = "implicit",
    iteration: int = 0,
    execution_id: str = "",
) -> None:
    if event_bus:
        await event_bus.emit_judge_verdict(
            stream_id=stream_id,
            node_id=node_id,
            action=action,
            feedback=feedback,
            judge_type=judge_type,
            iteration=iteration,
            execution_id=execution_id,
        )


async def publish_output_key_set(
    event_bus: EventBus | None,
    stream_id: str,
    node_id: str,
    key: str,
    execution_id: str = "",
) -> None:
    if event_bus:
        pass


async def run_hooks(
    hooks_config: dict[str, list],
    event: str,
    conversation: NodeConversation,
    trigger: str | None = None,
) -> None:
    """Run all registered hooks for *event*, applying their results.

    Each hook receives a HookContext and may return a HookResult that:
    - replaces the system prompt (result.system_prompt)
    - injects an extra user message (result.inject)
    Hooks run in registration order; each sees the prompt as left by the
    previous hook.
    """
    hook_list = hooks_config.get(event, [])
    if not hook_list:
        return
    for hook in hook_list:
        ctx = HookContext(
            event=event,
            trigger=trigger,
            system_prompt=conversation.system_prompt,
        )
        try:
            result = await hook(ctx)
        except Exception:
            logger.warning("Hook '%s' raised an exception", event, exc_info=True)
            continue
        if result is None:
            continue
        if result.system_prompt:
            conversation.update_system_prompt(result.system_prompt)
        if result.inject:
            await conversation.add_user_message(result.inject)
