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


async def generate_action_plan(
    event_bus: EventBus | None,
    ctx: NodeContext,
    stream_id: str,
    node_id: str,
    execution_id: str,
) -> None:
    """Generate a brief action plan via LLM and emit it as an SSE event.

    Runs as a fire-and-forget task so it never blocks the main loop.
    """
    try:
        system_prompt = ctx.agent_spec.system_prompt or ""
        # Trim to keep the prompt small
        prompt_summary = system_prompt[:500]
        if len(system_prompt) > 500:
            prompt_summary += "..."

        tool_names = [t.name for t in ctx.available_tools]
        output_keys = ctx.agent_spec.output_keys or []

        prompt = (
            f'You are about to work on a task as node "{node_id}".\n\n'
            f"System prompt:\n{prompt_summary}\n\n"
            f"Tools available: {tool_names}\n"
            f"Required outputs: {output_keys}\n\n"
            f"Write a brief action plan (2-5 bullet points) describing "
            f"what you will do to complete this task. Be specific and concise.\n"
            f"Return ONLY the plan text, no preamble."
        )

        response = await ctx.llm.acomplete(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        )

        plan = response.content.strip()
        if plan and event_bus:
            await event_bus.emit_node_action_plan(
                stream_id=stream_id,
                node_id=node_id,
                plan=plan,
                execution_id=execution_id,
            )
    except Exception as e:
        logger.warning("Action plan generation failed for node '%s': %s", node_id, e)


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
    execution_id: str = "",
    iteration: int | None = None,
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
            execution_id=execution_id,
            iteration=iteration,
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
) -> None:
    """Emit a CONTEXT_USAGE_UPDATED event with current context window state."""
    if not event_bus:
        return

    from framework.host.event_bus import AgentEvent, EventType

    estimated = conversation.estimate_tokens()
    max_tokens = conversation._max_context_tokens
    ratio = estimated / max_tokens if max_tokens > 0 else 0.0
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
