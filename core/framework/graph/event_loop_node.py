"""EventLoopNode: Multi-turn LLM streaming loop with tool execution and judge evaluation.

Implements NodeProtocol and runs a streaming event loop:
1. Calls LLMProvider.stream() to get streaming events
2. Processes text deltas, tool calls, and finish events
3. Executes tools and feeds results back to the conversation
4. Uses judge evaluation (or implicit stop-reason) to decide loop termination
5. Publishes lifecycle events to EventBus
6. Persists conversation and outputs via write-through to ConversationStore
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from framework.graph.conversation import ConversationStore, NodeConversation
from framework.graph.node import NodeContext, NodeProtocol, NodeResult
from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.runtime.event_bus import EventBus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Judge protocol (simple 3-action interface for event loop evaluation)
# ---------------------------------------------------------------------------


@dataclass
class JudgeVerdict:
    """Result of judge evaluation for the event loop."""

    action: Literal["ACCEPT", "RETRY", "ESCALATE"]
    feedback: str = ""


@runtime_checkable
class JudgeProtocol(Protocol):
    """Protocol for event-loop judges.

    Implementations evaluate the current state of the event loop and
    decide whether to accept the output, retry with feedback, or escalate.
    """

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict: ...


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LoopConfig:
    """Configuration for the event loop."""

    max_iterations: int = 50
    max_tool_calls_per_turn: int = 10
    judge_every_n_turns: int = 1
    stall_detection_threshold: int = 3
    max_history_tokens: int = 32_000
    store_prefix: str = ""

    # --- Tool result context management ---
    # When a tool result exceeds this character count, it is truncated in the
    # conversation context.  If *spillover_dir* is set the full result is
    # written to a file and the truncated message includes the filename so
    # the agent can retrieve it with load_data().  If *spillover_dir* is
    # ``None`` the result is simply truncated with an explanatory note.
    max_tool_result_chars: int = 3_000
    spillover_dir: str | None = None  # Path string; created on first use


# ---------------------------------------------------------------------------
# Output accumulator with write-through persistence
# ---------------------------------------------------------------------------


@dataclass
class OutputAccumulator:
    """Accumulates output key-value pairs with optional write-through persistence.

    Values are stored in memory and optionally written through to a
    ConversationStore's cursor data for crash recovery.
    """

    values: dict[str, Any] = field(default_factory=dict)
    store: ConversationStore | None = None

    async def set(self, key: str, value: Any) -> None:
        """Set a key-value pair, persisting immediately if store is available."""
        self.values[key] = value
        if self.store:
            cursor = await self.store.read_cursor() or {}
            outputs = cursor.get("outputs", {})
            outputs[key] = value
            cursor["outputs"] = outputs
            await self.store.write_cursor(cursor)

    def get(self, key: str) -> Any | None:
        """Get a value by key, or None if not present."""
        return self.values.get(key)

    def to_dict(self) -> dict[str, Any]:
        """Return a copy of all accumulated values."""
        return dict(self.values)

    def has_all_keys(self, required: list[str]) -> bool:
        """Check if all required keys have been set (non-None)."""
        return all(key in self.values and self.values[key] is not None for key in required)

    @classmethod
    async def restore(cls, store: ConversationStore) -> OutputAccumulator:
        """Restore an OutputAccumulator from a store's cursor data."""
        cursor = await store.read_cursor()
        values = {}
        if cursor and "outputs" in cursor:
            values = cursor["outputs"]
        return cls(values=values, store=store)


# ---------------------------------------------------------------------------
# EventLoopNode
# ---------------------------------------------------------------------------


class EventLoopNode(NodeProtocol):
    """Multi-turn LLM streaming loop with tool execution and judge evaluation.

    Lifecycle:
    1. Try to restore from durable state (crash recovery)
    2. If no prior state, init from NodeSpec.system_prompt + input_keys
    3. Loop: drain injection queue -> stream LLM -> execute tools
       -> if client_facing + no real tools: block for user input
       -> judge evaluates (acceptance criteria)
       (each add_* and set_output writes through to store immediately)
    4. Publish events to EventBus at each stage
    5. Write cursor after each iteration
    6. Terminate when judge returns ACCEPT, shutdown signaled, or max iterations
    7. Build output dict from OutputAccumulator

    Client-facing blocking: When ``client_facing=True`` and the LLM finishes
    without real tool calls (stop_reason != tool_call), the node blocks via
    ``_await_user_input()`` until ``inject_event()`` or ``signal_shutdown()``
    is called.  After user input, the judge evaluates — the judge is the
    sole mechanism for acceptance decisions.

    Always returns NodeResult with retryable=False semantics. The executor
    must NOT retry event loop nodes -- retry is handled internally by the
    judge (RETRY action continues the loop). See WP-7 enforcement.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        judge: JudgeProtocol | None = None,
        config: LoopConfig | None = None,
        tool_executor: Callable[[ToolUse], ToolResult | Awaitable[ToolResult]] | None = None,
        conversation_store: ConversationStore | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._judge = judge
        self._config = config or LoopConfig()
        self._tool_executor = tool_executor
        self._conversation_store = conversation_store
        self._injection_queue: asyncio.Queue[str] = asyncio.Queue()
        # Client-facing input blocking state
        self._input_ready = asyncio.Event()
        self._shutdown = False

    def validate_input(self, ctx: NodeContext) -> list[str]:
        """Validate hard requirements only.

        Event loop nodes are LLM-powered and can reason about flexible input,
        so input_keys are treated as hints — not strict requirements.
        Only the LLM provider is a hard dependency.
        """
        errors = []
        if ctx.llm is None:
            errors.append("LLM provider is required for EventLoopNode")
        return errors

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def execute(self, ctx: NodeContext) -> NodeResult:
        """Run the event loop."""
        start_time = time.time()
        total_input_tokens = 0
        total_output_tokens = 0
        stream_id = ctx.node_id
        node_id = ctx.node_id

        # 1. Guard: LLM required
        if ctx.llm is None:
            return NodeResult(success=False, error="LLM provider not available")

        # 2. Restore or create new conversation + accumulator
        conversation, accumulator, start_iteration = await self._restore(ctx)
        if conversation is None:
            system_prompt = ctx.node_spec.system_prompt or ""

            conversation = NodeConversation(
                system_prompt=system_prompt,
                max_history_tokens=self._config.max_history_tokens,
                output_keys=ctx.node_spec.output_keys or None,
                store=self._conversation_store,
            )
            accumulator = OutputAccumulator(store=self._conversation_store)
            start_iteration = 0

            # Add initial user message from input data
            initial_message = self._build_initial_message(ctx)
            if initial_message:
                await conversation.add_user_message(initial_message)

        # 3. Build tool list: node tools + synthetic set_output tool
        tools = list(ctx.available_tools)
        set_output_tool = self._build_set_output_tool(ctx.node_spec.output_keys)
        if set_output_tool:
            tools.append(set_output_tool)

        logger.info(
            "[%s] Tools available (%d): %s | client_facing=%s | judge=%s",
            node_id,
            len(tools),
            [t.name for t in tools],
            ctx.node_spec.client_facing,
            type(self._judge).__name__ if self._judge else "None",
        )

        # 4. Publish loop started
        await self._publish_loop_started(stream_id, node_id)

        # 5. Stall detection state
        recent_responses: list[str] = []

        # 6. Main loop
        for iteration in range(start_iteration, self._config.max_iterations):
            # 6a. Check pause
            if await self._check_pause(ctx, conversation, iteration):
                latency_ms = int((time.time() - start_time) * 1000)
                return NodeResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                )

            # 6b. Drain injection queue
            await self._drain_injection_queue(conversation)

            # 6c. Publish iteration event
            await self._publish_iteration(stream_id, node_id, iteration)

            # 6d. Pre-turn compaction check (tiered)
            if conversation.needs_compaction():
                await self._compact_tiered(ctx, conversation, accumulator)

            # 6e. Run single LLM turn
            logger.info(
                "[%s] iter=%d: running LLM turn (msgs=%d)",
                node_id,
                iteration,
                len(conversation.messages),
            )
            (
                assistant_text,
                real_tool_results,
                outputs_set,
                turn_tokens,
            ) = await self._run_single_turn(ctx, conversation, tools, iteration, accumulator)
            logger.info(
                "[%s] iter=%d: LLM done — text=%d chars, real_tools=%d, "
                "outputs_set=%s, tokens=%s, accumulator=%s",
                node_id,
                iteration,
                len(assistant_text),
                len(real_tool_results),
                outputs_set or "[]",
                turn_tokens,
                {k: ("set" if v is not None else "None") for k, v in accumulator.to_dict().items()},
            )
            total_input_tokens += turn_tokens.get("input", 0)
            total_output_tokens += turn_tokens.get("output", 0)

            # 6e'. Feed actual API token count back for accurate estimation
            turn_input = turn_tokens.get("input", 0)
            if turn_input > 0:
                conversation.update_token_count(turn_input)

            # 6e''. Post-turn compaction check (catches tool-result bloat)
            if conversation.needs_compaction():
                await self._compact_tiered(ctx, conversation, accumulator)

            # 6e'''. Empty response guard — if the LLM returned nothing
            # (no text, no real tools, no set_output) and all required
            # outputs are already set, accept immediately.  This prevents
            # wasted iterations when the LLM has genuinely finished its
            # work (e.g. after calling set_output in a previous turn).
            truly_empty = not assistant_text and not real_tool_results and not outputs_set
            if truly_empty and accumulator is not None:
                missing = self._get_missing_output_keys(
                    accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
                )
                if not missing:
                    logger.info(
                        "[%s] iter=%d: empty response but all outputs set — accepting",
                        node_id,
                        iteration,
                    )
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                    )

            # 6f. Stall detection
            recent_responses.append(assistant_text)
            if len(recent_responses) > self._config.stall_detection_threshold:
                recent_responses.pop(0)
            if self._is_stalled(recent_responses):
                await self._publish_stalled(stream_id, node_id)
                latency_ms = int((time.time() - start_time) * 1000)
                return NodeResult(
                    success=False,
                    error=(
                        f"Node stalled: {self._config.stall_detection_threshold} "
                        "consecutive identical responses"
                    ),
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                )

            # 6g. Write cursor checkpoint
            await self._write_cursor(ctx, conversation, accumulator, iteration)

            # 6h. Client-facing input blocking
            #
            # For client_facing nodes, block for user input whenever the
            # LLM finishes without making real tool calls (i.e. the LLM's
            # stop_reason is not tool_call).  set_output is separated from
            # real tools by _run_single_turn, so this correctly treats
            # set_output-only turns as conversational boundaries.
            #
            # After user input, always fall through to judge evaluation
            # (6i).  The judge handles all acceptance decisions.
            if ctx.node_spec.client_facing and not real_tool_results:
                if self._shutdown:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                    )

                logger.info("[%s] iter=%d: blocking for user input...", node_id, iteration)
                got_input = await self._await_user_input(ctx)
                logger.info("[%s] iter=%d: unblocked, got_input=%s", node_id, iteration, got_input)
                if not got_input:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                    )

                recent_responses.clear()
                # Fall through to judge evaluation (6i)

            # 6i. Judge evaluation
            should_judge = (
                (iteration + 1) % self._config.judge_every_n_turns == 0
                or not real_tool_results  # no real tool calls = natural stop
            )

            logger.info("[%s] iter=%d: 6i should_judge=%s", node_id, iteration, should_judge)
            if should_judge:
                verdict = await self._evaluate(
                    ctx,
                    conversation,
                    accumulator,
                    assistant_text,
                    real_tool_results,
                    iteration,
                )
                fb_preview = (verdict.feedback or "")[:200]
                logger.info(
                    "[%s] iter=%d: judge verdict=%s feedback=%r",
                    node_id,
                    iteration,
                    verdict.action,
                    fb_preview,
                )

                if verdict.action == "ACCEPT":
                    # Check for missing output keys
                    missing = self._get_missing_output_keys(
                        accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
                    )
                    if missing and self._judge is not None:
                        hint = (
                            f"Missing required output keys: {missing}. "
                            "Use set_output to provide them."
                        )
                        logger.info(
                            "[%s] iter=%d: ACCEPT but missing keys %s",
                            node_id,
                            iteration,
                            missing,
                        )
                        await conversation.add_user_message(hint)
                        continue

                    # Write outputs to shared memory
                    for key, value in accumulator.to_dict().items():
                        ctx.memory.write(key, value, validate=False)

                    await self._publish_loop_completed(stream_id, node_id, iteration + 1)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                    )

                elif verdict.action == "ESCALATE":
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return NodeResult(
                        success=False,
                        error=f"Judge escalated: {verdict.feedback}",
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                    )

                elif verdict.action == "RETRY":
                    if verdict.feedback:
                        await conversation.add_user_message(f"[Judge feedback]: {verdict.feedback}")
                    continue

        # 7. Max iterations exhausted
        await self._publish_loop_completed(stream_id, node_id, self._config.max_iterations)
        latency_ms = int((time.time() - start_time) * 1000)
        return NodeResult(
            success=False,
            error=(f"Max iterations ({self._config.max_iterations}) reached without acceptance"),
            output=accumulator.to_dict(),
            tokens_used=total_input_tokens + total_output_tokens,
            latency_ms=latency_ms,
        )

    async def inject_event(self, content: str) -> None:
        """Inject an external event into the running loop.

        The content becomes a user message prepended to the next iteration.
        Thread-safe via asyncio.Queue.
        Also unblocks _await_user_input() if the node is waiting.
        """
        await self._injection_queue.put(content)
        self._input_ready.set()

    def signal_shutdown(self) -> None:
        """Signal the node to exit its loop cleanly.

        Unblocks any pending _await_user_input() call and causes
        the loop to exit on the next check.
        """
        self._shutdown = True
        self._input_ready.set()

    async def _await_user_input(self, ctx: NodeContext) -> bool:
        """Block until user input arrives or shutdown is signaled.

        Called when a client_facing node produces text without tool calls —
        a natural conversational turn boundary.

        Returns True if input arrived, False if shutdown was signaled.
        """
        if self._event_bus:
            await self._event_bus.emit_client_input_requested(
                stream_id=ctx.node_id,
                node_id=ctx.node_id,
                prompt="",
            )

        self._input_ready.clear()
        await self._input_ready.wait()
        return not self._shutdown

    # -------------------------------------------------------------------
    # Single LLM turn with caller-managed tool orchestration
    # -------------------------------------------------------------------

    async def _run_single_turn(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        tools: list[Tool],
        iteration: int,
        accumulator: OutputAccumulator,
    ) -> tuple[str, list[dict], list[str], dict[str, int]]:
        """Run a single LLM turn with streaming and tool execution.

        Returns (assistant_text, real_tool_results, outputs_set, token_counts).

        ``real_tool_results`` contains only results from actual tools (web_search,
        etc.), NOT from the synthetic ``set_output`` tool.  ``outputs_set`` lists
        the output keys written via ``set_output`` during this turn.  This
        separation lets the caller treat set_output as a framework concern
        rather than a tool-execution concern.
        """
        stream_id = ctx.node_id
        node_id = ctx.node_id
        token_counts: dict[str, int] = {"input": 0, "output": 0}
        tool_call_count = 0
        final_text = ""
        # Track output keys set via set_output across all inner iterations
        outputs_set_this_turn: list[str] = []

        # Inner tool loop: stream may produce tool calls requiring re-invocation
        while True:
            # Pre-send guard: if context is at or over budget, compact before
            # calling the LLM — prevents API context-length errors.
            if conversation.usage_ratio() >= 1.0:
                logger.warning(
                    "Pre-send guard: context at %.0f%% of budget, compacting",
                    conversation.usage_ratio() * 100,
                )
                await self._compact_tiered(ctx, conversation, accumulator)

            messages = conversation.to_llm_messages()
            accumulated_text = ""
            tool_calls: list[ToolCallEvent] = []

            # Stream LLM response
            async for event in ctx.llm.stream(
                messages=messages,
                system=conversation.system_prompt,
                tools=tools if tools else None,
                max_tokens=ctx.max_tokens,
            ):
                if isinstance(event, TextDeltaEvent):
                    accumulated_text = event.snapshot
                    await self._publish_text_delta(
                        stream_id, node_id, event.content, event.snapshot, ctx
                    )

                elif isinstance(event, ToolCallEvent):
                    tool_calls.append(event)

                elif isinstance(event, FinishEvent):
                    token_counts["input"] += event.input_tokens
                    token_counts["output"] += event.output_tokens

                elif isinstance(event, StreamErrorEvent):
                    if not event.recoverable:
                        raise RuntimeError(f"Stream error: {event.error}")
                    logger.warning(f"Recoverable stream error: {event.error}")

            final_text = accumulated_text
            logger.info(
                "[%s] LLM response: text=%r tool_calls=%s",
                node_id,
                accumulated_text[:300] if accumulated_text else "(empty)",
                [tc.tool_name for tc in tool_calls] if tool_calls else "[]",
            )

            # Record assistant message (write-through via conversation store)
            tc_dicts = None
            if tool_calls:
                tc_dicts = [
                    {
                        "id": tc.tool_use_id,
                        "type": "function",
                        "function": {
                            "name": tc.tool_name,
                            "arguments": json.dumps(tc.tool_input),
                        },
                    }
                    for tc in tool_calls
                ]
            await conversation.add_assistant_message(
                content=accumulated_text,
                tool_calls=tc_dicts,
            )

            # If no tool calls, turn is complete
            if not tool_calls:
                return final_text, [], outputs_set_this_turn, token_counts

            # Execute tool calls — separate real tools from set_output
            real_tool_results: list[dict] = []
            limit_hit = False
            executed_in_batch = 0
            for tc in tool_calls:
                tool_call_count += 1
                if tool_call_count > self._config.max_tool_calls_per_turn:
                    limit_hit = True
                    break
                executed_in_batch += 1

                # Publish tool call started
                await self._publish_tool_started(
                    stream_id, node_id, tc.tool_use_id, tc.tool_name, tc.tool_input
                )

                logger.info(
                    "[%s] tool_call: %s(%s)",
                    node_id,
                    tc.tool_name,
                    json.dumps(tc.tool_input)[:200],
                )

                if tc.tool_name == "set_output":
                    # --- Framework-level set_output handling ---
                    result = self._handle_set_output(tc.tool_input, ctx.node_spec.output_keys)
                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content=result.content,
                        is_error=result.is_error,
                    )
                    if not result.is_error:
                        value = tc.tool_input["value"]
                        # Parse JSON strings into native types so downstream
                        # consumers get lists/dicts instead of serialised JSON,
                        # and the hallucination validator skips non-string values.
                        if isinstance(value, str):
                            try:
                                parsed = json.loads(value)
                                if isinstance(parsed, (list, dict)):
                                    value = parsed
                            except (json.JSONDecodeError, TypeError):
                                pass
                        await accumulator.set(tc.tool_input["key"], value)
                        outputs_set_this_turn.append(tc.tool_input["key"])
                else:
                    # --- Real tool execution ---
                    result = await self._execute_tool(tc)
                    result = self._truncate_tool_result(result, tc.tool_name)
                    real_tool_results.append(
                        {
                            "tool_use_id": tc.tool_use_id,
                            "tool_name": tc.tool_name,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                    )

                # Record tool result in conversation (both real and set_output
                # go into the conversation for LLM context continuity)
                await conversation.add_tool_result(
                    tool_use_id=tc.tool_use_id,
                    content=result.content,
                    is_error=result.is_error,
                )

                # Publish tool call completed
                await self._publish_tool_completed(
                    stream_id,
                    node_id,
                    tc.tool_use_id,
                    tc.tool_name,
                    result.content,
                    result.is_error,
                )

            # If the limit was hit, add error results for every remaining
            # tool call so the conversation stays consistent.  Without this,
            # the assistant message contains tool_calls that have no
            # corresponding tool results, causing the LLM to repeat them
            # in the next turn (infinite loop).
            if limit_hit:
                max_tc = self._config.max_tool_calls_per_turn
                skipped = tool_calls[executed_in_batch:]
                logger.warning(
                    "Max tool calls per turn (%d) exceeded — discarding %d remaining call(s): %s",
                    max_tc,
                    len(skipped),
                    ", ".join(tc.tool_name for tc in skipped),
                )
                discard_msg = (
                    f"Tool call discarded: max tool calls per turn "
                    f"({max_tc}) exceeded. Consolidate your work and "
                    f"use fewer tool calls."
                )
                for tc in skipped:
                    await conversation.add_tool_result(
                        tool_use_id=tc.tool_use_id,
                        content=discard_msg,
                        is_error=True,
                    )
                    # Discarded calls go into real_tool_results so the
                    # caller sees they were attempted (for judge context).
                    real_tool_results.append(
                        {
                            "tool_use_id": tc.tool_use_id,
                            "tool_name": tc.tool_name,
                            "content": discard_msg,
                            "is_error": True,
                        }
                    )
                # Prune old tool results NOW to prevent context bloat on the
                # next turn.  The char-based token estimator underestimates
                # actual API tokens, so the standard compaction check in the
                # outer loop may not trigger in time.
                protect = max(2000, self._config.max_history_tokens // 12)
                pruned = await conversation.prune_old_tool_results(
                    protect_tokens=protect,
                    min_prune_tokens=max(1000, protect // 3),
                )
                if pruned > 0:
                    logger.info(
                        "Post-limit pruning: cleared %d old tool results (budget: %d)",
                        pruned,
                        self._config.max_history_tokens,
                    )
                # Limit hit — return from this turn so the judge can
                # evaluate instead of looping back for another stream.
                return final_text, real_tool_results, outputs_set_this_turn, token_counts

            # --- Mid-turn pruning: prevent context blowup within a single turn ---
            if conversation.usage_ratio() >= 0.6:
                protect = max(2000, self._config.max_history_tokens // 12)
                pruned = await conversation.prune_old_tool_results(
                    protect_tokens=protect,
                    min_prune_tokens=max(1000, protect // 3),
                )
                if pruned > 0:
                    logger.info(
                        "Mid-turn pruning: cleared %d old tool results (usage now %.0f%%)",
                        pruned,
                        conversation.usage_ratio() * 100,
                    )

            # Tool calls processed -- loop back to stream with updated conversation

    # -------------------------------------------------------------------
    # set_output synthetic tool
    # -------------------------------------------------------------------

    def _build_set_output_tool(self, output_keys: list[str] | None) -> Tool | None:
        """Build the synthetic set_output tool for explicit output declaration."""
        if not output_keys:
            return None
        return Tool(
            name="set_output",
            description=(
                "Set an output value for this node. Call once per output key. "
                f"Valid keys: {output_keys}"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": f"Output key. Must be one of: {output_keys}",
                        "enum": output_keys,
                    },
                    "value": {
                        "type": "string",
                        "description": "The output value to store.",
                    },
                },
                "required": ["key", "value"],
            },
        )

    def _handle_set_output(
        self,
        tool_input: dict[str, Any],
        output_keys: list[str] | None,
    ) -> ToolResult:
        """Handle set_output tool call. Returns ToolResult (sync)."""
        key = tool_input.get("key", "")
        value = tool_input.get("value", "")
        valid_keys = output_keys or []

        # Recover from truncated JSON (max_tokens hit mid-argument).
        # The _raw key is set by litellm when json.loads fails.
        if not key and "_raw" in tool_input:
            import re

            raw = tool_input["_raw"]
            key_match = re.search(r'"key"\s*:\s*"(\w+)"', raw)
            if key_match:
                key = key_match.group(1)
            val_match = re.search(r'"value"\s*:\s*"', raw)
            if val_match:
                start = val_match.end()
                value = raw[start:].rstrip()
                for suffix in ('"}\n', '"}', '"'):
                    if value.endswith(suffix):
                        value = value[: -len(suffix)]
                        break
            if key:
                logger.warning(
                    "Recovered set_output args from truncated JSON: key=%s, value_len=%d",
                    key,
                    len(value),
                )
                # Re-inject so the caller sees proper key/value
                tool_input["key"] = key
                tool_input["value"] = value

        if key not in valid_keys:
            return ToolResult(
                tool_use_id="",
                content=f"Invalid output key '{key}'. Valid keys: {valid_keys}",
                is_error=True,
            )

        return ToolResult(
            tool_use_id="",
            content=f"Output '{key}' set successfully.",
            is_error=False,
        )

    # -------------------------------------------------------------------
    # Judge evaluation
    # -------------------------------------------------------------------

    async def _evaluate(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        assistant_text: str,
        tool_results: list[dict],
        iteration: int,
    ) -> JudgeVerdict:
        """Evaluate the current state using judge or implicit logic."""
        if self._judge is not None:
            context = {
                "assistant_text": assistant_text,
                "tool_calls": tool_results,
                "output_accumulator": accumulator.to_dict(),
                "accumulator": accumulator,
                "iteration": iteration,
                "conversation_summary": conversation.export_summary(),
                "output_keys": ctx.node_spec.output_keys,
                "missing_keys": self._get_missing_output_keys(
                    accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
                ),
            }
            return await self._judge.evaluate(context)

        # Implicit judge: accept when no tool calls and all output keys present
        if not tool_results:
            missing = self._get_missing_output_keys(
                accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
            )
            if not missing:
                return JudgeVerdict(action="ACCEPT")
            else:
                return JudgeVerdict(
                    action="RETRY",
                    feedback=(
                        f"Missing output keys: {missing}. Use set_output tool to provide them."
                    ),
                )

        # Tool calls were made -- continue loop
        return JudgeVerdict(action="RETRY", feedback="")

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_tool_call_history(
        conversation: NodeConversation,
        max_entries: int = 30,
    ) -> str:
        """Build a compact tool call history from the conversation.

        Used in compaction summaries to prevent the LLM from re-calling
        tools it already called. Extracts:
        - Tool call counts (e.g. "github_list_pull_requests (6x)")
        - Files saved via save_data
        - Outputs set via set_output
        - Errors encountered
        """
        tool_counts: dict[str, int] = {}
        files_saved: list[str] = []
        outputs_set: list[str] = []
        errors: list[str] = []

        for msg in conversation.messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    tool_counts[name] = tool_counts.get(name, 0) + 1
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    if name == "save_data" and args.get("filename"):
                        files_saved.append(args["filename"])
                    if name == "set_output" and args.get("key"):
                        outputs_set.append(args["key"])

            if msg.role == "tool" and msg.is_error:
                preview = msg.content[:120].replace("\n", " ")
                errors.append(preview)

        parts: list[str] = []
        if tool_counts:
            lines = [f"  {n} ({c}x)" for n, c in tool_counts.items()]
            parts.append("TOOLS ALREADY CALLED:\n" + "\n".join(lines[:max_entries]))
        if files_saved:
            unique = list(dict.fromkeys(files_saved))
            parts.append("FILES SAVED: " + ", ".join(unique))
        if outputs_set:
            unique = list(dict.fromkeys(outputs_set))
            parts.append("OUTPUTS SET: " + ", ".join(unique))
        if errors:
            parts.append(
                "ERRORS (do NOT retry these):\n" + "\n".join(f"  - {e}" for e in errors[:10])
            )
        return "\n\n".join(parts)

    def _build_initial_message(self, ctx: NodeContext) -> str:
        """Build the initial user message from input data and memory.

        Includes ALL input_data (not just declared input_keys) so that
        upstream handoff data flows through regardless of key naming.
        Declared input_keys are also checked in shared memory as fallback.
        """
        parts = []
        seen: set[str] = set()
        # Include everything from input_data (flexible handoff)
        for key, value in ctx.input_data.items():
            if value is not None:
                parts.append(f"{key}: {value}")
                seen.add(key)
        # Fallback: check memory for declared input_keys not already covered
        for key in ctx.node_spec.input_keys:
            if key not in seen:
                value = ctx.memory.read(key)
                if value is not None:
                    parts.append(f"{key}: {value}")
        if ctx.goal_context:
            parts.append(f"\nGoal: {ctx.goal_context}")
        return "\n".join(parts) if parts else "Begin."

    def _get_missing_output_keys(
        self,
        accumulator: OutputAccumulator,
        output_keys: list[str] | None,
        nullable_keys: list[str] | None = None,
    ) -> list[str]:
        """Return output keys that have not been set yet (excluding nullable keys)."""
        if not output_keys:
            return []
        skip = set(nullable_keys) if nullable_keys else set()
        return [k for k in output_keys if k not in skip and accumulator.get(k) is None]

    def _is_stalled(self, recent_responses: list[str]) -> bool:
        """Detect stall: N consecutive identical non-empty responses."""
        if len(recent_responses) < self._config.stall_detection_threshold:
            return False
        if not recent_responses[0]:
            return False
        return all(r == recent_responses[0] for r in recent_responses)

    async def _execute_tool(self, tc: ToolCallEvent) -> ToolResult:
        """Execute a tool call, handling both sync and async executors."""
        if self._tool_executor is None:
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=f"No tool executor configured for '{tc.tool_name}'",
                is_error=True,
            )
        tool_use = ToolUse(id=tc.tool_use_id, name=tc.tool_name, input=tc.tool_input)
        result = self._tool_executor(tool_use)
        if asyncio.iscoroutine(result) or asyncio.isfuture(result):
            result = await result
        return result

    def _truncate_tool_result(
        self,
        result: ToolResult,
        tool_name: str,
    ) -> ToolResult:
        """Truncate a large tool result to keep the conversation context small.

        If *spillover_dir* is configured and the result exceeds
        *max_tool_result_chars*, the full content is written to a file and
        the in-context result is replaced with a preview + filename reference.
        Without *spillover_dir*, large results are truncated with a note.

        Small results (and errors) pass through unchanged.
        """
        limit = self._config.max_tool_result_chars
        if limit <= 0 or result.is_error or len(result.content) <= limit:
            return result

        # Determine a preview size — leave room for the metadata wrapper
        preview_chars = max(limit - 300, limit // 2)
        preview = result.content[:preview_chars]

        spill_dir = self._config.spillover_dir
        if spill_dir:
            spill_path = Path(spill_dir)
            spill_path.mkdir(parents=True, exist_ok=True)
            # Use tool_use_id for uniqueness, sanitise for filesystem
            safe_id = result.tool_use_id.replace("/", "_")[:60]
            filename = f"tool_{tool_name}_{safe_id}.txt"

            # Pretty-print JSON content so load_data's line-based
            # pagination works correctly.  Compact JSON (no newlines)
            # would produce a single line that defeats pagination.
            write_content = result.content
            try:
                parsed = json.loads(result.content)
                write_content = json.dumps(parsed, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass  # Not JSON — write as-is

            (spill_path / filename).write_text(write_content, encoding="utf-8")

            truncated = (
                f"[Result from {tool_name}: {len(result.content)} chars — "
                f"too large for context, saved to '{filename}'. "
                f"Use load_data(filename='{filename}', data_dir='{spill_dir}') "
                f"to read the full result.]\n\n"
                f"Preview:\n{preview}…"
            )
            logger.info(
                "Tool result spilled to file: %s (%d chars → %s)",
                tool_name,
                len(result.content),
                filename,
            )
        else:
            truncated = (
                f"[Result from {tool_name}: {len(result.content)} chars — "
                f"truncated to fit context budget. Only the first "
                f"{preview_chars} chars are shown.]\n\n{preview}…"
            )
            logger.info(
                "Tool result truncated in-place: %s (%d → %d chars)",
                tool_name,
                len(result.content),
                len(truncated),
            )

        return ToolResult(
            tool_use_id=result.tool_use_id,
            content=truncated,
            is_error=False,
        )

    async def _compact_tiered(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator | None = None,
    ) -> None:
        """Run compaction with aggressiveness scaled to usage level.

        | Usage          | Strategy                                    |
        |----------------|---------------------------------------------|
        | 80-100%        | Normal: LLM summary, keep 4 recent messages |
        | 100-120%       | Aggressive: LLM summary, keep 2 recent      |
        | >= 120%        | Emergency: static summary, keep 1 recent     |
        """
        ratio = conversation.usage_ratio()

        # --- Tier 0: Prune old tool results (zero-cost, no LLM call) ---
        protect = max(2000, self._config.max_history_tokens // 12)
        pruned = await conversation.prune_old_tool_results(
            protect_tokens=protect,
            min_prune_tokens=max(1000, protect // 3),
        )
        if pruned > 0:
            new_ratio = conversation.usage_ratio()
            logger.info(
                "Pruned %d old tool results: %.0f%% -> %.0f%%",
                pruned,
                ratio * 100,
                new_ratio * 100,
            )
            if not conversation.needs_compaction():
                # Pruning freed enough — skip full compaction entirely
                if self._event_bus:
                    from framework.runtime.event_bus import AgentEvent, EventType

                    await self._event_bus.publish(
                        AgentEvent(
                            type=EventType.CUSTOM,
                            stream_id=ctx.node_id,
                            node_id=ctx.node_id,
                            data={
                                "custom_type": "node_compaction",
                                "node_id": ctx.node_id,
                                "level": "prune_only",
                                "usage_before": round(ratio * 100),
                                "usage_after": round(new_ratio * 100),
                            },
                        )
                    )
                return
            ratio = new_ratio

        if ratio >= 1.2:
            level = "emergency"
            logger.warning("Emergency compaction triggered (usage %.0f%%)", ratio * 100)
            summary = self._build_emergency_summary(ctx, accumulator, conversation)
            await conversation.compact(summary, keep_recent=1)
        elif ratio >= 1.0:
            level = "aggressive"
            logger.info("Aggressive compaction triggered (usage %.0f%%)", ratio * 100)
            summary = await self._generate_compaction_summary(ctx, conversation)
            await conversation.compact(summary, keep_recent=2)
        else:
            level = "normal"
            summary = await self._generate_compaction_summary(ctx, conversation)
            await conversation.compact(summary, keep_recent=4)

        new_ratio = conversation.usage_ratio()
        logger.info(
            "Compaction complete (%s): %.0f%% -> %.0f%%",
            level,
            ratio * 100,
            new_ratio * 100,
        )
        if self._event_bus:
            from framework.runtime.event_bus import AgentEvent, EventType

            await self._event_bus.publish(
                AgentEvent(
                    type=EventType.CUSTOM,
                    stream_id=ctx.node_id,
                    node_id=ctx.node_id,
                    data={
                        "custom_type": "node_compaction",
                        "node_id": ctx.node_id,
                        "level": level,
                        "usage_before": round(ratio * 100),
                        "usage_after": round(new_ratio * 100),
                    },
                )
            )

    async def _generate_compaction_summary(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
    ) -> str:
        """Use LLM to generate a conversation summary for compaction."""
        tool_history = self._extract_tool_call_history(conversation)

        messages_text = "\n".join(
            f"[{m.role}]: {m.content[:200]}" for m in conversation.messages[-10:]
        )
        prompt = (
            "Summarize this conversation so far in 2-3 sentences, "
            "preserving key decisions and results:\n\n"
            f"{messages_text}"
        )
        if tool_history:
            prompt += (
                "\n\nINCLUDE this tool history verbatim in your summary "
                "(the agent needs it to avoid re-calling tools):\n\n"
                f"{tool_history}"
            )

        try:
            response = ctx.llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "Summarize conversations concisely. Always preserve the tool history section."
                ),
                max_tokens=500,
            )
            summary = response.content
            # Ensure tool history is present even if LLM dropped it
            if tool_history and "TOOLS ALREADY CALLED" not in summary:
                summary += "\n\n" + tool_history
            return summary
        except Exception as e:
            logger.warning(f"Compaction summary generation failed: {e}")
            if tool_history:
                return f"Previous conversation context (summary unavailable).\n\n{tool_history}"
            return "Previous conversation context (summary unavailable)."

    def _build_emergency_summary(
        self,
        ctx: NodeContext,
        accumulator: OutputAccumulator | None = None,
        conversation: NodeConversation | None = None,
    ) -> str:
        """Build a structured emergency compaction summary.

        Unlike normal/aggressive compaction which uses an LLM summary,
        emergency compaction cannot afford an LLM call (context is already
        way over budget).  Instead, build a deterministic summary from the
        node's known state so the LLM can continue working after
        compaction without losing track of its task and inputs.
        """
        parts = [
            "EMERGENCY COMPACTION — previous conversation was too large "
            "and has been replaced with this summary.\n"
        ]

        # 1. Node identity
        spec = ctx.node_spec
        parts.append(f"NODE: {spec.name} (id={spec.id})")
        if spec.description:
            parts.append(f"PURPOSE: {spec.description}")

        # 2. Inputs the node received
        input_lines = []
        for key in spec.input_keys:
            value = ctx.input_data.get(key) or ctx.memory.read(key)
            if value is not None:
                # Truncate long values but keep them recognisable
                v_str = str(value)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "…"
                input_lines.append(f"  {key}: {v_str}")
        if input_lines:
            parts.append("INPUTS:\n" + "\n".join(input_lines))

        # 3. Output accumulator state (what's been set so far)
        if accumulator:
            acc_state = accumulator.to_dict()
            set_keys = {k: v for k, v in acc_state.items() if v is not None}
            missing = [k for k, v in acc_state.items() if v is None]
            if set_keys:
                lines = [f"  {k}: {str(v)[:150]}" for k, v in set_keys.items()]
                parts.append("OUTPUTS ALREADY SET:\n" + "\n".join(lines))
            if missing:
                parts.append(f"OUTPUTS STILL NEEDED: {', '.join(missing)}")
        elif spec.output_keys:
            parts.append(f"OUTPUTS STILL NEEDED: {', '.join(spec.output_keys)}")

        # 4. Available tools reminder
        if spec.tools:
            parts.append(f"AVAILABLE TOOLS: {', '.join(spec.tools)}")

        # 5. Spillover files hint
        if self._config.spillover_dir:
            spill = self._config.spillover_dir
            parts.append(
                "NOTE: Large tool results were saved to files. "
                f"Use load_data(filename='<filename>', data_dir='{spill}') "
                "to read them."
            )

        # 6. Tool call history (prevent re-calling tools)
        if conversation is not None:
            tool_history = self._extract_tool_call_history(conversation)
            if tool_history:
                parts.append(tool_history)

        parts.append(
            "\nContinue working towards setting the remaining outputs. "
            "Use your tools and the inputs above."
        )
        return "\n\n".join(parts)

    # -------------------------------------------------------------------
    # Persistence: restore, cursor, injection, pause
    # -------------------------------------------------------------------

    async def _restore(
        self,
        ctx: NodeContext,
    ) -> tuple[NodeConversation | None, OutputAccumulator | None, int]:
        """Attempt to restore from a previous checkpoint."""
        if self._conversation_store is None:
            return None, None, 0

        conversation = await NodeConversation.restore(self._conversation_store)
        if conversation is None:
            return None, None, 0

        accumulator = await OutputAccumulator.restore(self._conversation_store)

        cursor = await self._conversation_store.read_cursor()
        start_iteration = cursor.get("iteration", 0) + 1 if cursor else 0

        logger.info(
            f"Restored event loop: iteration={start_iteration}, "
            f"messages={conversation.message_count}, "
            f"outputs={list(accumulator.values.keys())}"
        )
        return conversation, accumulator, start_iteration

    async def _write_cursor(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        iteration: int,
    ) -> None:
        """Write checkpoint cursor for crash recovery."""
        if self._conversation_store:
            cursor = await self._conversation_store.read_cursor() or {}
            cursor.update(
                {
                    "iteration": iteration,
                    "node_id": ctx.node_id,
                    "next_seq": conversation.next_seq,
                    "outputs": accumulator.to_dict(),
                }
            )
            await self._conversation_store.write_cursor(cursor)

    async def _drain_injection_queue(self, conversation: NodeConversation) -> int:
        """Drain all pending injected events as user messages. Returns count."""
        count = 0
        while not self._injection_queue.empty():
            try:
                content = self._injection_queue.get_nowait()
                logger.info(
                    "[drain] injected message: %s",
                    content[:200] if content else "(empty)",
                )
                await conversation.add_user_message(f"[External event]: {content}")
                count += 1
            except asyncio.QueueEmpty:
                break
        return count

    async def _check_pause(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        iteration: int,
    ) -> bool:
        """Check if pause has been requested. Returns True if paused."""
        pause_requested = ctx.input_data.get("pause_requested", False)
        if not pause_requested:
            try:
                pause_requested = ctx.memory.read("pause_requested") or False
            except (PermissionError, KeyError):
                pause_requested = False
        if pause_requested:
            logger.info(f"Pause requested at iteration {iteration}")
            return True
        return False

    # -------------------------------------------------------------------
    # EventBus publishing helpers
    # -------------------------------------------------------------------

    async def _publish_loop_started(self, stream_id: str, node_id: str) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_started(
                stream_id=stream_id,
                node_id=node_id,
                max_iterations=self._config.max_iterations,
            )

    async def _publish_iteration(self, stream_id: str, node_id: str, iteration: int) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_iteration(
                stream_id=stream_id,
                node_id=node_id,
                iteration=iteration,
            )

    async def _publish_loop_completed(self, stream_id: str, node_id: str, iterations: int) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_completed(
                stream_id=stream_id,
                node_id=node_id,
                iterations=iterations,
            )

    async def _publish_stalled(self, stream_id: str, node_id: str) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_stalled(
                stream_id=stream_id,
                node_id=node_id,
                reason="Consecutive identical responses detected",
            )

    async def _publish_text_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        ctx: NodeContext,
    ) -> None:
        if self._event_bus:
            if ctx.node_spec.client_facing:
                await self._event_bus.emit_client_output_delta(
                    stream_id=stream_id,
                    node_id=node_id,
                    content=content,
                    snapshot=snapshot,
                )
            else:
                await self._event_bus.emit_llm_text_delta(
                    stream_id=stream_id,
                    node_id=node_id,
                    content=content,
                    snapshot=snapshot,
                )

    async def _publish_tool_started(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_tool_call_started(
                stream_id=stream_id,
                node_id=node_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input=tool_input,
            )

    async def _publish_tool_completed(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        result: str,
        is_error: bool,
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_tool_call_completed(
                stream_id=stream_id,
                node_id=node_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                result=result,
                is_error=is_error,
            )
