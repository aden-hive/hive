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

    # Overflow margin for max_tool_calls_per_turn.  Tool calls are only
    # discarded when the count exceeds max_tool_calls_per_turn * (1 + margin).
    # Default 0.5 means 50% wiggle room (e.g. limit=10 → hard cutoff at 15).
    tool_call_overflow_margin: float = 0.5

    # --- Tool result context management ---
    # When a tool result exceeds this character count, it is truncated in the
    # conversation context.  If *spillover_dir* is set the full result is
    # written to a file and the truncated message includes the filename so
    # the agent can retrieve it with load_data().  If *spillover_dir* is
    # ``None`` the result is simply truncated with an explanatory note.
    max_tool_result_chars: int = 3_000
    spillover_dir: str | None = None  # Path string; created on first use

    # --- Stream retry (transient error recovery within EventLoopNode) ---
    # When _run_single_turn() raises a transient error (network, rate limit,
    # server error), retry up to this many times with exponential backoff
    # before re-raising.  Set to 0 to disable.
    max_stream_retries: int = 3
    stream_retry_backoff_base: float = 2.0
    stream_retry_max_delay: float = 60.0  # cap per-retry sleep

    # --- Tool doom loop detection ---
    # Detect when the LLM calls the same tool(s) with identical args for
    # N consecutive turns.  For client-facing nodes, blocks for user input.
    # For non-client-facing nodes, injects a warning into the conversation.
    tool_doom_loop_threshold: int = 3
    tool_doom_loop_enabled: bool = True


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
       -> if client_facing: block for user input (see below)
       -> judge evaluates (acceptance criteria)
       (each add_* and set_output writes through to store immediately)
    4. Publish events to EventBus at each stage
    5. Write cursor after each iteration
    6. Terminate when judge returns ACCEPT, shutdown signaled, or max iterations
    7. Build output dict from OutputAccumulator

    Client-facing blocking (``client_facing=True``):

    - **Text-only turns** (no real tool calls, no set_output)
      automatically block for user input.  If the LLM is talking to the
      user (not calling tools or setting outputs), it should wait for
      the user's response before the judge runs.
    - **Work turns** (tool calls or set_output) flow through without
      blocking — the LLM is making progress, not asking the user.
    - A synthetic ``ask_user`` tool is also injected for explicit
      blocking when the LLM wants to be deliberate about requesting
      input (e.g. mid-tool-call).

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
        self._injection_queue: asyncio.Queue[tuple[str, bool]] = asyncio.Queue()
        # Client-facing input blocking state
        self._input_ready = asyncio.Event()
        self._awaiting_input = False
        self._shutdown = False
        # Track which nodes already have an action plan emitted (skip on revisit)
        self._action_plan_emitted: set[str] = set()

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
        stream_id = ctx.stream_id or ctx.node_id
        node_id = ctx.node_id
        execution_id = ctx.execution_id or ""

        # Verdict counters for runtime logging
        _accept_count = _retry_count = _escalate_count = _continue_count = 0

        # 1. Guard: LLM required
        if ctx.llm is None:
            error_msg = "LLM provider not available"
            # Log guard failure
            if ctx.runtime_logger:
                ctx.runtime_logger.log_node_complete(
                    node_id=node_id,
                    node_name=ctx.node_spec.name,
                    node_type="event_loop",
                    success=False,
                    error=error_msg,
                    exit_status="guard_failure",
                    total_steps=0,
                    tokens_used=0,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=0,
                )
            return NodeResult(success=False, error=error_msg)

        # 2. Restore or create new conversation + accumulator
        # Track whether we're in continuous mode (conversation threaded across nodes)
        _is_continuous = getattr(ctx, "continuous_mode", False)

        if _is_continuous and ctx.inherited_conversation is not None:
            # Continuous mode with inherited conversation from prior node.
            # This takes priority over store restoration — when the graph loops
            # back to a previously-visited node, the inherited conversation
            # carries forward the full thread rather than restoring stale state.
            # System prompt already updated by executor. Transition marker
            # already inserted by executor. Fresh accumulator for this phase.
            # Phase already set by executor via set_current_phase().
            conversation = ctx.inherited_conversation
            # Use cumulative output keys for compaction protection (all phases),
            # falling back to current node's keys if not in continuous mode.
            conversation._output_keys = (
                ctx.cumulative_output_keys or ctx.node_spec.output_keys or None
            )
            accumulator = OutputAccumulator(store=self._conversation_store)
            start_iteration = 0
            _restored_recent_responses: list[str] = []
            _restored_tool_fingerprints: list[list[tuple[str, str]]] = []
        else:
            # Try crash-recovery restore from store, then fall back to fresh.
            restored = await self._restore(ctx)
            if restored is not None:
                conversation = restored.conversation
                accumulator = restored.accumulator
                start_iteration = restored.start_iteration
                _restored_recent_responses = restored.recent_responses
                _restored_tool_fingerprints = restored.recent_tool_fingerprints

                # Refresh the system prompt to the current node spec's version.
                # The stored prompt may be stale after code changes or when
                # runtime-injected context (e.g. worker identity) has changed.
                from framework.graph.prompt_composer import _with_datetime

                _current_prompt = _with_datetime(ctx.node_spec.system_prompt or "")
                if ctx.accounts_prompt:
                    _current_prompt = f"{_current_prompt}\n\n{ctx.accounts_prompt}"
                if conversation.system_prompt != _current_prompt:
                    conversation.update_system_prompt(_current_prompt)
                    logger.info("Refreshed system prompt for restored conversation")
            else:
                _restored_recent_responses = []
                _restored_tool_fingerprints = []

                # Fresh conversation: either isolated mode or first node in continuous mode.
                from framework.graph.prompt_composer import _with_datetime

                system_prompt = _with_datetime(ctx.node_spec.system_prompt or "")
                # Append connected accounts info if available
                if ctx.accounts_prompt:
                    system_prompt = f"{system_prompt}\n\n{ctx.accounts_prompt}"

                # Inject agent working memory (adapt.md).
                # If it doesn't exist yet, seed it with available context.
                if self._config.spillover_dir:
                    _adapt_path = Path(self._config.spillover_dir) / "adapt.md"
                    if not _adapt_path.exists() and ctx.accounts_prompt:
                        _adapt_path.parent.mkdir(parents=True, exist_ok=True)
                        _adapt_path.write_text(
                            f"## Identity\n{ctx.accounts_prompt}\n",
                            encoding="utf-8",
                        )
                    if _adapt_path.exists():
                        _adapt_text = _adapt_path.read_text(encoding="utf-8").strip()
                        if _adapt_text:
                            system_prompt = (
                                f"{system_prompt}\n\n"
                                f"--- Your Memory ---\n{_adapt_text}\n--- End Memory ---\n\n"
                                'Maintain your memory by calling save_data("adapt.md", ...) '
                                'or edit_data("adapt.md", ...) as you work.\n'
                                "IMMEDIATELY save: user rules about which account/identity to use, "
                                "behavioral constraints, and preferences. "
                                "Also record session history, decisions, and working notes."
                            )

                conversation = NodeConversation(
                    system_prompt=system_prompt,
                    max_history_tokens=self._config.max_history_tokens,
                    output_keys=ctx.node_spec.output_keys or None,
                    store=self._conversation_store,
                )
                # Stamp phase for first node in continuous mode
                if _is_continuous:
                    conversation.set_current_phase(ctx.node_id)
                accumulator = OutputAccumulator(store=self._conversation_store)
                start_iteration = 0

                # Add initial user message from input data
                initial_message = self._build_initial_message(ctx)
                if initial_message:
                    await conversation.add_user_message(initial_message)

        # 3. Build tool list: node tools + synthetic set_output + ask_user tools
        tools = list(ctx.available_tools)
        set_output_tool = self._build_set_output_tool(ctx.node_spec.output_keys)
        if set_output_tool:
            tools.append(set_output_tool)
        if ctx.node_spec.client_facing and not ctx.event_triggered:
            if stream_id != "queen":
                tools.append(self._build_ask_user_tool())
            tools.append(self._build_escalate_tool())

        logger.info(
            "[%s] Tools available (%d): %s | client_facing=%s | judge=%s",
            node_id,
            len(tools),
            [t.name for t in tools],
            ctx.node_spec.client_facing,
            type(self._judge).__name__ if self._judge else "None",
        )

        # 4. Publish loop started
        await self._publish_loop_started(stream_id, node_id, execution_id)

        # 4b. Fire-and-forget action plan generation (once per node per lifetime)
        # Skip for queen/judge — action plans are only meaningful for worker nodes.
        if (
            start_iteration == 0
            and ctx.llm
            and self._event_bus
            and node_id not in self._action_plan_emitted
            and stream_id not in ("queen", "judge")
        ):
            self._action_plan_emitted.add(node_id)
            asyncio.create_task(self._generate_action_plan(ctx, stream_id, node_id, execution_id))

        # 5. Stall / doom loop detection state (restored from cursor if resuming)
        recent_responses: list[str] = _restored_recent_responses
        recent_tool_fingerprints: list[list[tuple[str, str]]] = _restored_tool_fingerprints

        # 6. Main loop
        for iteration in range(start_iteration, self._config.max_iterations):
            iter_start = time.time()

            # 6a. Check pause (no current-iteration data yet — only log_node_complete needed)
            if await self._check_pause(ctx, conversation, iteration):
                latency_ms = int((time.time() - start_time) * 1000)
                if ctx.runtime_logger:
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.node_spec.name,
                        node_type="event_loop",
                        success=True,
                        total_steps=iteration,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="paused",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return NodeResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=conversation if _is_continuous else None,
                )

            # 6b. Drain injection queue
            await self._drain_injection_queue(conversation)

            # 6c. Publish iteration event
            await self._publish_iteration(stream_id, node_id, iteration, execution_id)

            # 6d. Pre-turn compaction check (tiered)
            if conversation.needs_compaction():
                await self._compact_tiered(ctx, conversation, accumulator)

            # 6e. Run single LLM turn (with transient error retry)
            logger.info(
                "[%s] iter=%d: running LLM turn (msgs=%d)",
                node_id,
                iteration,
                len(conversation.messages),
            )
            _stream_retry_count = 0
            while True:
                try:
                    (
                        assistant_text,
                        real_tool_results,
                        outputs_set,
                        turn_tokens,
                        logged_tool_calls,
                        user_input_requested,
                        ask_user_prompt,
                    ) = await self._run_single_turn(
                        ctx, conversation, tools, iteration, accumulator
                    )
                    logger.info(
                        "[%s] iter=%d: LLM done — text=%d chars, real_tools=%d, "
                        "outputs_set=%s, tokens=%s, accumulator=%s",
                        node_id,
                        iteration,
                        len(assistant_text),
                        len(real_tool_results),
                        outputs_set or "[]",
                        turn_tokens,
                        {
                            k: ("set" if v is not None else "None")
                            for k, v in accumulator.to_dict().items()
                        },
                    )
                    total_input_tokens += turn_tokens.get("input", 0)
                    total_output_tokens += turn_tokens.get("output", 0)
                    break  # success — exit retry loop

                except Exception as e:
                    # Retry transient errors with exponential backoff
                    if (
                        self._is_transient_error(e)
                        and _stream_retry_count < self._config.max_stream_retries
                    ):
                        _stream_retry_count += 1
                        delay = min(
                            self._config.stream_retry_backoff_base
                            * (2 ** (_stream_retry_count - 1)),
                            self._config.stream_retry_max_delay,
                        )
                        logger.warning(
                            "[%s] iter=%d: transient error (%s), retrying in %.1fs (%d/%d): %s",
                            node_id,
                            iteration,
                            type(e).__name__,
                            delay,
                            _stream_retry_count,
                            self._config.max_stream_retries,
                            str(e)[:200],
                        )
                        if self._event_bus:
                            await self._event_bus.emit_node_retry(
                                stream_id=stream_id,
                                node_id=node_id,
                                retry_count=_stream_retry_count,
                                max_retries=self._config.max_stream_retries,
                                error=str(e)[:500],
                                execution_id=execution_id,
                            )
                        await asyncio.sleep(delay)
                        continue  # retry same iteration

                    # Non-transient or retries exhausted — existing crash handler
                    import traceback

                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    latency_ms = int((time.time() - start_time) * 1000)
                    error_msg = f"LLM call failed: {e}"
                    stack_trace = traceback.format_exc()

                    if ctx.runtime_logger:
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            error=error_msg,
                            stacktrace=stack_trace,
                            is_partial=True,
                            input_tokens=0,
                            output_tokens=0,
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.node_spec.name,
                            node_type="event_loop",
                            success=False,
                            error=error_msg,
                            stacktrace=stack_trace,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="failure",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )

                    # Re-raise to maintain existing error handling
                    raise

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
            truly_empty = (
                not assistant_text
                and not real_tool_results
                and not outputs_set
                and not user_input_requested
            )
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
                    await self._publish_loop_completed(
                        stream_id, node_id, iteration + 1, execution_id
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=conversation if _is_continuous else None,
                    )

            # 6f. Stall detection
            recent_responses.append(assistant_text)
            if len(recent_responses) > self._config.stall_detection_threshold:
                recent_responses.pop(0)
            if self._is_stalled(recent_responses):
                await self._publish_stalled(stream_id, node_id, execution_id)
                latency_ms = int((time.time() - start_time) * 1000)
                _continue_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="CONTINUE",
                        verdict_feedback="Stall detected before judge evaluation",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.node_spec.name,
                        node_type="event_loop",
                        success=False,
                        error="Node stalled",
                        total_steps=iteration + 1,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="stalled",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return NodeResult(
                    success=False,
                    error=(
                        f"Node stalled: {self._config.stall_detection_threshold} "
                        "consecutive identical responses"
                    ),
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=conversation if _is_continuous else None,
                )

            # 6f'. Tool doom loop detection
            # Use logged_tool_calls (persists across inner iterations) and
            # filter to real MCP tools (exclude set_output, ask_user, errors).
            mcp_tool_calls = [
                tc
                for tc in logged_tool_calls
                if tc.get("tool_name") not in ("set_output", "ask_user", "escalate_to_coder")
                and not tc.get("is_error")
            ]
            if mcp_tool_calls:
                fps = self._fingerprint_tool_calls(mcp_tool_calls)
                recent_tool_fingerprints.append(fps)
                threshold = self._config.tool_doom_loop_threshold
                if len(recent_tool_fingerprints) > threshold:
                    recent_tool_fingerprints.pop(0)
                is_doom, doom_desc = self._is_tool_doom_loop(
                    recent_tool_fingerprints,
                )
                if is_doom:
                    logger.warning("[%s] %s", node_id, doom_desc)
                    if self._event_bus:
                        await self._event_bus.emit_tool_doom_loop(
                            stream_id=stream_id,
                            node_id=node_id,
                            description=doom_desc,
                            execution_id=execution_id,
                        )
                    warning_msg = (
                        f"[SYSTEM] {doom_desc}. You are repeating the "
                        "same tool calls with identical arguments. "
                        "Try a different approach or different arguments."
                    )
                    if ctx.node_spec.client_facing and not ctx.event_triggered:
                        await conversation.add_user_message(warning_msg)
                        self._input_ready.clear()
                        if self._event_bus:
                            await self._event_bus.emit_client_input_requested(
                                stream_id=stream_id,
                                node_id=node_id,
                                prompt=doom_desc,
                                execution_id=execution_id,
                            )
                        self._awaiting_input = True
                        try:
                            await self._input_ready.wait()
                        finally:
                            self._awaiting_input = False
                        recent_tool_fingerprints.clear()
                        recent_responses.clear()
                    else:
                        await conversation.add_user_message(warning_msg)
                        recent_tool_fingerprints.clear()
            else:
                # Text-only turn breaks the doom loop chain
                recent_tool_fingerprints.clear()

            # 6g. Write cursor checkpoint (includes stall/doom state for resume)
            await self._write_cursor(
                ctx,
                conversation,
                accumulator,
                iteration,
                recent_responses=recent_responses,
                recent_tool_fingerprints=recent_tool_fingerprints,
            )

            # 6h. Client-facing input blocking
            #
            # Two triggers:
            # (a) Explicit ask_user() — always blocks, then falls through
            #     to judge evaluation (6i).
            # (b) Auto-block — a text-only turn (no real tools, no
            #     set_output) from a client-facing node is addressed to the
            #     user.  Block for their response, then *skip* judge so the
            #     next LLM turn can process the reply without confusing
            #     "missing outputs" feedback.
            #
            # Turns that include tool calls or set_output are *work*, not
            # conversation — they flow through without blocking.
            _cf_block = False
            _cf_auto = False
            _cf_prompt = ""
            if ctx.node_spec.client_facing and not ctx.event_triggered:
                if user_input_requested:
                    _cf_block = True
                    _cf_prompt = ask_user_prompt
                elif assistant_text and not real_tool_results and not outputs_set:
                    _cf_block = True
                    _cf_auto = True

            if _cf_block:
                if self._shutdown:
                    await self._publish_loop_completed(
                        stream_id, node_id, iteration + 1, execution_id
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback="Shutdown signaled (client-facing)",
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.node_spec.name,
                            node_type="event_loop",
                            success=True,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="success",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=conversation if _is_continuous else None,
                    )

                logger.info(
                    "[%s] iter=%d: blocking for user input (auto=%s)...",
                    node_id,
                    iteration,
                    _cf_auto,
                )
                got_input = await self._await_user_input(
                    ctx, prompt=_cf_prompt, skip_emit=user_input_requested
                )
                logger.info("[%s] iter=%d: unblocked, got_input=%s", node_id, iteration, got_input)
                if not got_input:
                    await self._publish_loop_completed(
                        stream_id, node_id, iteration + 1, execution_id
                    )
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback="No input received (shutdown during wait)",
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.node_spec.name,
                            node_type="event_loop",
                            success=True,
                            total_steps=iteration + 1,
                            tokens_used=total_input_tokens + total_output_tokens,
                            input_tokens=total_input_tokens,
                            output_tokens=total_output_tokens,
                            latency_ms=latency_ms,
                            exit_status="success",
                            accept_count=_accept_count,
                            retry_count=_retry_count,
                            escalate_count=_escalate_count,
                            continue_count=_continue_count,
                        )
                    return NodeResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=conversation if _is_continuous else None,
                    )

                recent_responses.clear()

                if _cf_auto:
                    # Auto-block: skip judge — let the LLM process the
                    # user's response on the next turn without confusing
                    # "missing outputs" feedback injected between the
                    # assistant's question and the user's answer.
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback="Auto-blocked for user input (pre-interaction)",
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                    continue
                # Explicit ask_user: fall through to judge evaluation (6i)

            # 6i. Judge evaluation
            should_judge = (
                (iteration + 1) % self._config.judge_every_n_turns == 0
                or not real_tool_results  # no real tool calls = natural stop
            )

            logger.info("[%s] iter=%d: 6i should_judge=%s", node_id, iteration, should_judge)
            if not should_judge:
                # Gap C: unjudged iteration — log as CONTINUE
                _continue_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="CONTINUE",
                        verdict_feedback="Unjudged (judge_every_n_turns skip)",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                continue

            # Judge evaluation (should_judge is always True here)
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

            # Publish judge verdict event
            judge_type = "custom" if self._judge is not None else "implicit"
            await self._publish_judge_verdict(
                stream_id,
                node_id,
                action=verdict.action,
                feedback=fb_preview,
                judge_type=judge_type,
                iteration=iteration,
                execution_id=execution_id,
            )

            if verdict.action == "ACCEPT":
                # Check for missing output keys
                missing = self._get_missing_output_keys(
                    accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
                )
                if missing and self._judge is not None:
                    hint = (
                        f"Missing required output keys: {missing}. Use set_output to provide them."
                    )
                    logger.info(
                        "[%s] iter=%d: ACCEPT but missing keys %s",
                        node_id,
                        iteration,
                        missing,
                    )
                    await conversation.add_user_message(hint)
                    # Gap D: log ACCEPT-with-missing-keys as RETRY
                    _retry_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="RETRY",
                            verdict_feedback=(f"Judge accepted but missing output keys: {missing}"),
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                    continue

                # Exit point 5: Judge ACCEPT — log step + log_node_complete
                # Write outputs to shared memory
                for key, value in accumulator.to_dict().items():
                    ctx.memory.write(key, value, validate=False)

                await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                latency_ms = int((time.time() - start_time) * 1000)
                _accept_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="ACCEPT",
                        verdict_feedback=verdict.feedback,
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.node_spec.name,
                        node_type="event_loop",
                        success=True,
                        total_steps=iteration + 1,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="success",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return NodeResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=conversation if _is_continuous else None,
                )

            elif verdict.action == "ESCALATE":
                # Exit point 6: Judge ESCALATE — log step + log_node_complete
                await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                latency_ms = int((time.time() - start_time) * 1000)
                _escalate_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="ESCALATE",
                        verdict_feedback=verdict.feedback,
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.node_spec.name,
                        node_type="event_loop",
                        success=False,
                        error=f"Judge escalated: {verdict.feedback}",
                        total_steps=iteration + 1,
                        tokens_used=total_input_tokens + total_output_tokens,
                        input_tokens=total_input_tokens,
                        output_tokens=total_output_tokens,
                        latency_ms=latency_ms,
                        exit_status="escalated",
                        accept_count=_accept_count,
                        retry_count=_retry_count,
                        escalate_count=_escalate_count,
                        continue_count=_continue_count,
                    )
                return NodeResult(
                    success=False,
                    error=f"Judge escalated: {verdict.feedback}",
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=conversation if _is_continuous else None,
                )

            elif verdict.action == "RETRY":
                _retry_count += 1
                if ctx.runtime_logger:
                    iter_latency_ms = int((time.time() - iter_start) * 1000)
                    ctx.runtime_logger.log_step(
                        node_id=node_id,
                        node_type="event_loop",
                        step_index=iteration,
                        verdict="RETRY",
                        verdict_feedback=verdict.feedback,
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                if verdict.feedback:
                    await conversation.add_user_message(f"[Judge feedback]: {verdict.feedback}")
                continue

        # 7. Max iterations exhausted
        await self._publish_loop_completed(
            stream_id, node_id, self._config.max_iterations, execution_id
        )
        latency_ms = int((time.time() - start_time) * 1000)
        if ctx.runtime_logger:
            ctx.runtime_logger.log_node_complete(
                node_id=node_id,
                node_name=ctx.node_spec.name,
                node_type="event_loop",
                success=False,
                error=f"Max iterations ({self._config.max_iterations}) reached without acceptance",
                total_steps=self._config.max_iterations,
                tokens_used=total_input_tokens + total_output_tokens,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                latency_ms=latency_ms,
                exit_status="failure",
                accept_count=_accept_count,
                retry_count=_retry_count,
                escalate_count=_escalate_count,
                continue_count=_continue_count,
            )
        return NodeResult(
            success=False,
            error=(f"Max iterations ({self._config.max_iterations}) reached without acceptance"),
            output=accumulator.to_dict(),
            tokens_used=total_input_tokens + total_output_tokens,
            latency_ms=latency_ms,
            conversation=conversation if _is_continuous else None,
        )

    async def inject_event(self, content: str, *, is_client_input: bool = False) -> None:
        """Inject an external event or user input into the running loop.

        The content becomes a user message prepended to the next iteration.
        Thread-safe via asyncio.Queue.
        Also unblocks _await_user_input() if the node is waiting.

        Args:
            content: The message text.
            is_client_input: True when the message originates from a real
                human user (e.g. /chat endpoint), False for external events.
        """
        await self._injection_queue.put((content, is_client_input))
        self._input_ready.set()

    def signal_shutdown(self) -> None:
        """Signal the node to exit its loop cleanly.

        Unblocks any pending _await_user_input() call and causes
        the loop to exit on the next check.
        """
        self._shutdown = True
        self._input_ready.set()

    async def _await_user_input(
        self, ctx: NodeContext, prompt: str = "", *, skip_emit: bool = False
    ) -> bool:
        """Block until user input arrives or shutdown is signaled.

        Called in two situations:
        - The LLM explicitly calls ask_user().
        - Auto-block: any text-only turn (no real tools, no set_output)
          from a client-facing node — ensures the user sees and responds
          before the judge runs.

        Args:
            skip_emit: If True, skip emitting client_input_requested
                (already emitted earlier, e.g. during ask_user detection).

        Returns True if input arrived, False if shutdown was signaled.
        """
        # Clear BEFORE emitting so that synchronous handlers (e.g. the
        # headless stdin handler) can call inject_event() during the emit
        # and the signal won't be lost.  TUI handlers return immediately
        # without injecting, so the wait still blocks until the user types.
        self._input_ready.clear()

        if self._event_bus and not skip_emit:
            await self._event_bus.emit_client_input_requested(
                stream_id=ctx.stream_id or ctx.node_id,
                node_id=ctx.node_id,
                prompt=prompt,
                execution_id=ctx.execution_id or "",
            )

        self._awaiting_input = True
        try:
            await self._input_ready.wait()
        finally:
            self._awaiting_input = False
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
    ) -> tuple[str, list[dict], list[str], dict[str, int], list[dict], bool, str]:
        """Run a single LLM turn with streaming and tool execution.

        Returns (assistant_text, real_tool_results, outputs_set, token_counts, logged_tool_calls,
        user_input_requested, ask_user_prompt).

        ``real_tool_results`` contains only results from actual tools (web_search,
        etc.), NOT from the synthetic ``set_output`` or ``ask_user`` tools.
        ``outputs_set`` lists the output keys written via ``set_output`` during
        this turn.  ``user_input_requested`` is True if the LLM called
        ``ask_user`` during this turn.  This separation lets the caller treat
        synthetic tools as framework concerns rather than tool-execution concerns.

        ``logged_tool_calls`` accumulates ALL tool calls across inner iterations
        (real tools, set_output, and discarded calls) for L3 logging.  Unlike
        ``real_tool_results`` which resets each inner iteration, this list grows
        across the entire turn.
        """
        stream_id = ctx.stream_id or ctx.node_id
        node_id = ctx.node_id
        execution_id = ctx.execution_id or ""
        token_counts: dict[str, int] = {"input": 0, "output": 0}
        tool_call_count = 0
        final_text = ""
        # Track output keys set via set_output across all inner iterations
        outputs_set_this_turn: list[str] = []
        user_input_requested = False
        ask_user_prompt = ""
        # Accumulate ALL tool calls across inner iterations for L3 logging.
        # Unlike real_tool_results (reset each inner iteration), this persists.
        logged_tool_calls: list[dict] = []

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

            # Defensive guard: ensure messages don't end with an assistant
            # message.  The Anthropic API rejects "assistant message prefill"
            # (conversations must end with a user or tool message).  This can
            # happen after compaction trims messages leaving an assistant tail,
            # or when a conversation is inherited without a transition marker
            # (e.g. parallel-branch execution).
            if messages and messages[-1].get("role") == "assistant":
                logger.info(
                    "[%s] Messages end with assistant — injecting continuation prompt",
                    node_id,
                )
                await conversation.add_user_message("[Continue working on your current task.]")
                messages = conversation.to_llm_messages()

            accumulated_text = ""
            tool_calls: list[ToolCallEvent] = []
            _stream_error: StreamErrorEvent | None = None

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
                        stream_id,
                        node_id,
                        event.content,
                        event.snapshot,
                        ctx,
                        execution_id,
                        iteration=iteration,
                    )

                elif isinstance(event, ToolCallEvent):
                    tool_calls.append(event)

                elif isinstance(event, FinishEvent):
                    token_counts["input"] += event.input_tokens
                    token_counts["output"] += event.output_tokens

                elif isinstance(event, StreamErrorEvent):
                    if not event.recoverable:
                        raise RuntimeError(f"Stream error: {event.error}")
                    _stream_error = event
                    logger.warning("Recoverable stream error: %s", event.error)

            # If a recoverable stream error produced an empty response,
            # raise so the outer transient-error retry can handle it
            # with proper backoff instead of burning judge iterations.
            if _stream_error and not accumulated_text and not tool_calls:
                raise ConnectionError(
                    f"Stream failed with recoverable error: {_stream_error.error}"
                )

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
                return (
                    final_text,
                    [],
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    ask_user_prompt,
                )

            # Execute tool calls — framework tools (set_output, ask_user)
            # run inline; real MCP tools run in parallel.
            real_tool_results: list[dict] = []
            limit_hit = False
            executed_in_batch = 0
            hard_limit = int(
                self._config.max_tool_calls_per_turn * (1 + self._config.tool_call_overflow_margin)
            )

            # Phase 1: triage — handle framework tools immediately,
            # queue real tools for parallel execution.
            results_by_id: dict[str, ToolResult] = {}
            pending_real: list[ToolCallEvent] = []

            for tc in tool_calls:
                tool_call_count += 1
                if tool_call_count > hard_limit:
                    limit_hit = True
                    break
                executed_in_batch += 1

                await self._publish_tool_started(
                    stream_id,
                    node_id,
                    tc.tool_use_id,
                    tc.tool_name,
                    tc.tool_input,
                    execution_id,
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
                        value = tc.tool_input.get("value", "")
                        # Parse JSON strings into native types so downstream
                        # consumers get lists/dicts instead of serialised JSON,
                        # and the hallucination validator skips non-string values.
                        if isinstance(value, str):
                            try:
                                parsed = json.loads(value)
                                if isinstance(parsed, (list, dict, bool, int, float)):
                                    value = parsed
                            except (json.JSONDecodeError, TypeError):
                                pass
                        key = tc.tool_input.get("key", "")
                        await accumulator.set(key, value)
                        outputs_set_this_turn.append(key)
                        await self._publish_output_key_set(stream_id, node_id, key, execution_id)
                    logged_tool_calls.append(
                        {
                            "tool_use_id": tc.tool_use_id,
                            "tool_name": "set_output",
                            "tool_input": tc.tool_input,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "ask_user":
                    # --- Framework-level ask_user handling ---
                    user_input_requested = True
                    ask_user_prompt = tc.tool_input.get("question", "")
                    # Emit immediately so the frontend transitions to
                    # "awaiting input" without waiting for post-turn
                    # processing (compaction, stall check, cursor write).
                    if self._event_bus and ctx.node_spec.client_facing:
                        await self._event_bus.emit_client_input_requested(
                            stream_id=stream_id,
                            node_id=node_id,
                            prompt=ask_user_prompt,
                            execution_id=execution_id,
                        )
                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Waiting for user input...",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "escalate_to_coder":
                    # --- Framework-level escalation handling ---
                    if self._event_bus:
                        await self._event_bus.emit_escalation_requested(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason=tc.tool_input.get("reason", ""),
                            context=tc.tool_input.get("context", ""),
                            execution_id=ctx.execution_id,
                        )
                    # Block like ask_user — the TUI loads the coder,
                    # and /back injects a message to unblock us.
                    user_input_requested = True
                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Escalating to Hive Coder. You will resume when done.",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                else:
                    # --- Real tool: check for truncated args, else queue ---
                    if "_raw" in tc.tool_input:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                f"Tool call to '{tc.tool_name}' failed: your arguments "
                                "were truncated (hit output token limit). "
                                "Simplify or shorten your arguments and try again."
                            ),
                            is_error=True,
                        )
                        logger.warning(
                            "[%s] Blocked truncated _raw tool call: %s",
                            node_id,
                            tc.tool_name,
                        )
                        results_by_id[tc.tool_use_id] = result
                    else:
                        pending_real.append(tc)

            # Phase 2: execute real tools in parallel.
            if pending_real:
                raw_results = await asyncio.gather(
                    *(self._execute_tool(tc) for tc in pending_real),
                    return_exceptions=True,
                )
                for tc, raw in zip(pending_real, raw_results, strict=True):
                    if isinstance(raw, BaseException):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=f"Tool '{tc.tool_name}' raised: {raw}",
                            is_error=True,
                        )
                    else:
                        result = raw
                    results_by_id[tc.tool_use_id] = self._truncate_tool_result(result, tc.tool_name)

            # Phase 3: record results into conversation in original order,
            # build logged/real lists, and publish completed events.
            for tc in tool_calls[:executed_in_batch]:
                result = results_by_id.get(tc.tool_use_id)
                if result is None:
                    continue  # shouldn't happen

                # Build log entries for real tools
                if tc.tool_name not in ("set_output", "ask_user", "escalate_to_coder"):
                    tool_entry = {
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                    real_tool_results.append(tool_entry)
                    logged_tool_calls.append(tool_entry)

                await conversation.add_tool_result(
                    tool_use_id=tc.tool_use_id,
                    content=result.content,
                    is_error=result.is_error,
                )
                await self._publish_tool_completed(
                    stream_id,
                    node_id,
                    tc.tool_use_id,
                    tc.tool_name,
                    result.content,
                    result.is_error,
                    execution_id,
                )

            # If the limit was hit, add error results for every remaining
            # tool call so the conversation stays consistent.  Without this,
            # the assistant message contains tool_calls that have no
            # corresponding tool results, causing the LLM to repeat them
            # in the next turn (infinite loop).
            if limit_hit:
                skipped = tool_calls[executed_in_batch:]
                logger.warning(
                    "Hard tool call limit (%d) exceeded — discarding %d remaining call(s): %s",
                    hard_limit,
                    len(skipped),
                    ", ".join(tc.tool_name for tc in skipped),
                )
                discard_msg = (
                    f"Tool call discarded: hard limit of {hard_limit} tool calls "
                    f"per turn exceeded. Consolidate your work and "
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
                    discard_entry = {
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "content": discard_msg,
                        "is_error": True,
                    }
                    real_tool_results.append(discard_entry)
                    logged_tool_calls.append(discard_entry)
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
                return (
                    final_text,
                    real_tool_results,
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    ask_user_prompt,
                )

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

            # If ask_user was called, return immediately so the outer loop
            # can block for user input instead of re-invoking the LLM.
            if user_input_requested:
                return (
                    final_text,
                    real_tool_results,
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    ask_user_prompt,
                )

            # Tool calls processed -- loop back to stream with updated conversation

    # -------------------------------------------------------------------
    # Synthetic tools: set_output, ask_user
    # -------------------------------------------------------------------

    def _build_ask_user_tool(self) -> Tool:
        """Build the synthetic ask_user tool for explicit user-input requests.

        Client-facing nodes call ask_user() when they need to pause and wait
        for user input.  Text-only turns WITHOUT ask_user flow through without
        blocking, allowing progress updates and summaries to stream freely.
        """
        return Tool(
            name="ask_user",
            description=(
                "Call this tool when you need to wait for the user's response. "
                "Use it after greeting the user, asking a question, or requesting "
                "approval. Do NOT call it when you are just providing a status "
                "update or summary that doesn't require a response."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Optional: the question or prompt shown to the user.",
                    },
                },
                "required": [],
            },
        )

    def _build_escalate_tool(self) -> Tool:
        """Build the synthetic escalate_to_coder tool.

        Client-facing nodes call this when the user's request requires
        capabilities beyond the current agent (code changes, feature
        expansion, debugging).  The TUI intercepts the event and loads
        hive_coder in the foreground.
        """
        return Tool(
            name="escalate_to_coder",
            description=(
                "Call this tool when the user requests something you "
                "cannot handle — a code change, feature expansion, bug "
                "fix, or framework-level modification. This will bring "
                "in Hive Coder, a coding agent that can read and write "
                "files. Provide a clear reason and relevant context so "
                "the coder can pick up where you left off."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Why you are escalating (what the user needs that you cannot do)."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": (
                            "Relevant context: what you discussed, "
                            "what files are involved, what the user "
                            "wants changed."
                        ),
                    },
                },
                "required": ["reason"],
            },
        )

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
                # Safety check: when ALL output keys are nullable and NONE
                # have been set, the node produced nothing useful.  Retry
                # instead of accepting an empty result — this prevents
                # client-facing nodes from terminating before the user
                # ever interacts, and non-client-facing nodes from
                # short-circuiting without doing their work.
                output_keys = ctx.node_spec.output_keys or []
                nullable_keys = set(ctx.node_spec.nullable_output_keys or [])
                all_nullable = output_keys and nullable_keys >= set(output_keys)
                none_set = not any(accumulator.get(k) is not None for k in output_keys)
                if all_nullable and none_set:
                    return JudgeVerdict(
                        action="RETRY",
                        feedback=(
                            f"No output keys have been set yet. "
                            f"Use set_output to set at least one of: {output_keys}"
                        ),
                    )

                # Client-facing nodes with no output keys are meant for
                # continuous interaction — they should not auto-accept.
                # Only exit via shutdown, max_iterations, or max_node_visits.
                if not output_keys and ctx.node_spec.client_facing:
                    return JudgeVerdict(action="RETRY", feedback="")

                # Level 2: conversation-aware quality check (if success_criteria set)
                if ctx.node_spec.success_criteria and ctx.llm:
                    from framework.graph.conversation_judge import evaluate_phase_completion

                    verdict = await evaluate_phase_completion(
                        llm=ctx.llm,
                        conversation=conversation,
                        phase_name=ctx.node_spec.name,
                        phase_description=ctx.node_spec.description,
                        success_criteria=ctx.node_spec.success_criteria,
                        accumulator_state=accumulator.to_dict(),
                        max_history_tokens=self._config.max_history_tokens,
                    )
                    if verdict.action != "ACCEPT":
                        return JudgeVerdict(
                            action=verdict.action,
                            feedback=verdict.feedback or "Phase criteria not met.",
                        )

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
        - Tool call details: name, count, and *inputs* for key tools
          (search queries, scrape URLs, loaded filenames)
        - Files saved via save_data
        - Outputs set via set_output
        - Errors encountered
        """
        # Per-tool: list of input summaries (one per call)
        tool_calls_detail: dict[str, list[str]] = {}
        files_saved: list[str] = []
        outputs_set: list[str] = []
        errors: list[str] = []

        # Tool-specific input extractors: return a short summary string
        def _summarize_input(name: str, args: dict) -> str:
            if name == "web_search":
                return args.get("query", "")
            if name == "web_scrape":
                return args.get("url", "")
            if name == "load_data":
                return args.get("filename", "")
            if name == "save_data":
                return args.get("filename", "")
            return ""

        for msg in conversation.messages:
            if msg.role == "assistant" and msg.tool_calls:
                for tc in msg.tool_calls:
                    func = tc.get("function", {})
                    name = func.get("name", "unknown")
                    try:
                        args = json.loads(func.get("arguments", "{}"))
                    except (json.JSONDecodeError, TypeError):
                        args = {}

                    summary = _summarize_input(name, args)
                    tool_calls_detail.setdefault(name, []).append(summary)

                    if name == "save_data" and args.get("filename"):
                        files_saved.append(args["filename"])
                    if name == "set_output" and args.get("key"):
                        outputs_set.append(args["key"])

            if msg.role == "tool" and msg.is_error:
                preview = msg.content[:120].replace("\n", " ")
                errors.append(preview)

        parts: list[str] = []
        if tool_calls_detail:
            lines: list[str] = []
            for name, inputs in list(tool_calls_detail.items())[:max_entries]:
                count = len(inputs)
                # Include input details for tools where inputs matter
                non_empty = [s for s in inputs if s]
                if non_empty:
                    detail_lines = [f"    - {s[:120]}" for s in non_empty[:8]]
                    lines.append(f"  {name} ({count}x):\n" + "\n".join(detail_lines))
                else:
                    lines.append(f"  {name} ({count}x)")
            parts.append("TOOLS ALREADY CALLED:\n" + "\n".join(lines))
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

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """Classify whether an exception is transient (retryable) vs permanent.

        Transient: network errors, rate limits, server errors, timeouts.
        Permanent: auth errors, bad requests, context window exceeded.
        """
        try:
            from litellm.exceptions import (
                APIConnectionError,
                BadGatewayError,
                InternalServerError,
                RateLimitError,
                ServiceUnavailableError,
            )

            transient_types: tuple[type[BaseException], ...] = (
                RateLimitError,
                APIConnectionError,
                InternalServerError,
                BadGatewayError,
                ServiceUnavailableError,
                TimeoutError,
                ConnectionError,
                OSError,
            )
        except ImportError:
            transient_types = (TimeoutError, ConnectionError, OSError)

        if isinstance(exc, transient_types):
            return True

        # RuntimeError from StreamErrorEvent with "Stream error:" prefix
        if isinstance(exc, RuntimeError):
            error_str = str(exc).lower()
            transient_keywords = [
                "rate limit",
                "429",
                "timeout",
                "connection",
                "internal server",
                "502",
                "503",
                "504",
                "service unavailable",
                "bad gateway",
                "overloaded",
            ]
            return any(kw in error_str for kw in transient_keywords)

        return False

    @staticmethod
    def _fingerprint_tool_calls(
        tool_results: list[dict],
    ) -> list[tuple[str, str]]:
        """Create deterministic fingerprints for a turn's tool calls.

        Each fingerprint is (tool_name, canonical_args_json).  Order-sensitive
        so [search("a"), fetch("b")] != [fetch("b"), search("a")].
        """
        fingerprints = []
        for tr in tool_results:
            name = tr.get("tool_name", "")
            args = tr.get("tool_input", {})
            try:
                canonical = json.dumps(args, sort_keys=True, default=str)
            except (TypeError, ValueError):
                canonical = str(args)
            fingerprints.append((name, canonical))
        return fingerprints

    def _is_tool_doom_loop(
        self,
        recent_tool_fingerprints: list[list[tuple[str, str]]],
    ) -> tuple[bool, str]:
        """Detect doom loop: N consecutive turns with identical tool calls.

        Returns (is_doom_loop, description).
        """
        if not self._config.tool_doom_loop_enabled:
            return False, ""
        threshold = self._config.tool_doom_loop_threshold
        if len(recent_tool_fingerprints) < threshold:
            return False, ""
        # All entries must be non-empty and identical
        first = recent_tool_fingerprints[0]
        if not first:
            return False, ""
        if all(fp == first for fp in recent_tool_fingerprints):
            tool_names = [name for name, _ in first]
            desc = (
                f"Doom loop detected: {threshold} consecutive identical "
                f"tool calls ({', '.join(tool_names)})"
            )
            return True, desc
        return False, ""

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

        # load_data is the designated mechanism for reading spilled files.
        # Don't re-spill (circular), but DO truncate with a pagination hint.
        if tool_name == "load_data":
            preview_chars = max(limit - 300, limit // 2)
            preview = result.content[:preview_chars]
            truncated = (
                f"[load_data result: {len(result.content)} chars — "
                f"too large for context. Use offset_bytes and limit_bytes parameters "
                f"to read smaller chunks, e.g. "
                f"load_data(filename=..., offset_bytes=0, limit_bytes=5000).]\n\n"
                f"Preview:\n{preview}…"
            )
            logger.info(
                "load_data result truncated: %d → %d chars "
                "(use offset_bytes/limit_bytes to paginate)",
                len(result.content),
                len(truncated),
            )
            return ToolResult(
                tool_use_id=result.tool_use_id,
                content=truncated,
                is_error=False,
            )

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
                f"Use load_data(filename='{filename}') "
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
                prune_before = round(ratio * 100)
                prune_after = round(new_ratio * 100)
                if ctx.runtime_logger:
                    ctx.runtime_logger.log_step(
                        node_id=ctx.node_id,
                        node_type="event_loop",
                        step_index=-1,
                        llm_text=f"Context pruned (tool results): "
                        f"{prune_before}% \u2192 {prune_after}%",
                        verdict="COMPACTION",
                        verdict_feedback=f"level=prune_only "
                        f"before={prune_before}% after={prune_after}%",
                    )
                if self._event_bus:
                    from framework.runtime.event_bus import AgentEvent, EventType

                    await self._event_bus.publish(
                        AgentEvent(
                            type=EventType.CONTEXT_COMPACTED,
                            stream_id=ctx.stream_id or ctx.node_id,
                            node_id=ctx.node_id,
                            data={
                                "level": "prune_only",
                                "usage_before": prune_before,
                                "usage_after": prune_after,
                            },
                        )
                    )
                return
            ratio = new_ratio

        _phase_grad = getattr(ctx, "continuous_mode", False)

        if ratio >= 1.2:
            level = "emergency"
            logger.warning("Emergency compaction triggered (usage %.0f%%)", ratio * 100)
            summary = self._build_emergency_summary(ctx, accumulator, conversation)
            await conversation.compact(summary, keep_recent=1, phase_graduated=_phase_grad)
        elif ratio >= 1.0:
            level = "aggressive"
            logger.info("Aggressive compaction triggered (usage %.0f%%)", ratio * 100)
            summary = await self._generate_compaction_summary(ctx, conversation)
            await conversation.compact(summary, keep_recent=2, phase_graduated=_phase_grad)
        else:
            level = "normal"
            summary = await self._generate_compaction_summary(ctx, conversation)
            await conversation.compact(summary, keep_recent=4, phase_graduated=_phase_grad)

        new_ratio = conversation.usage_ratio()
        logger.info(
            "Compaction complete (%s): %.0f%% -> %.0f%%",
            level,
            ratio * 100,
            new_ratio * 100,
        )

        # Log compaction to session logs (tool_logs.jsonl)
        before_pct = round(ratio * 100)
        after_pct = round(new_ratio * 100)
        if ctx.runtime_logger:
            ctx.runtime_logger.log_step(
                node_id=ctx.node_id,
                node_type="event_loop",
                step_index=-1,  # Not a regular LLM step
                llm_text=f"Context compacted ({level}): {before_pct}% \u2192 {after_pct}%",
                verdict="COMPACTION",
                verdict_feedback=f"level={level} before={before_pct}% after={after_pct}%",
            )

        if self._event_bus:
            from framework.runtime.event_bus import AgentEvent, EventType

            await self._event_bus.publish(
                AgentEvent(
                    type=EventType.CONTEXT_COMPACTED,
                    stream_id=ctx.stream_id or ctx.node_id,
                    node_id=ctx.node_id,
                    data={
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
            "preserving key decisions and results.\n\n"
            "IMPORTANT: Always preserve any user-stated rules, constraints, "
            "or preferences — especially which account/identity to use, "
            "formatting preferences, and behavioral instructions. "
            "These MUST appear verbatim or near-verbatim in your summary.\n\n"
            f"{messages_text}"
        )
        if tool_history:
            prompt += (
                "\n\nINCLUDE this tool history verbatim in your summary "
                "(the agent needs it to avoid re-calling tools):\n\n"
                f"{tool_history}"
            )

        # Dynamic budget: reasoning models (o1, gpt-5-mini) spend max_tokens on
        # internal thinking. 500 leaves nothing for the actual summary.
        summary_budget = max(1024, self._config.max_history_tokens // 10)
        try:
            response = await ctx.llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                system=(
                    "Summarize conversations concisely. Always preserve the tool "
                    "history section. Always preserve user-stated rules, constraints, "
                    "and account/identity preferences verbatim."
                ),
                max_tokens=summary_budget,
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

        # 5. Spillover files — list actual files so the LLM can load
        # them immediately instead of having to call list_data_files first.
        # Inline adapt.md (agent memory) directly — it contains user rules
        # and identity preferences that must survive emergency compaction.
        if self._config.spillover_dir:
            try:
                from pathlib import Path

                data_dir = Path(self._config.spillover_dir)
                if data_dir.is_dir():
                    # Inline adapt.md content directly
                    adapt_path = data_dir / "adapt.md"
                    if adapt_path.is_file():
                        adapt_text = adapt_path.read_text(encoding="utf-8").strip()
                        if adapt_text:
                            parts.append(f"AGENT MEMORY (adapt.md):\n{adapt_text}")

                    files = sorted(
                        f.name for f in data_dir.iterdir() if f.is_file() and f.name != "adapt.md"
                    )
                    if files:
                        file_list = "\n".join(f"  - {f}" for f in files[:30])
                        parts.append("DATA FILES (use load_data to read):\n" + file_list)
                    else:
                        parts.append(
                            "NOTE: Large tool results may have been saved to files. "
                            "Use list_data_files() to check."
                        )
            except Exception:
                parts.append(
                    "NOTE: Large tool results were saved to files. "
                    "Use load_data(filename='<filename>') to read them."
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

    @dataclass
    class _RestoredState:
        """State recovered from a previous checkpoint."""

        conversation: NodeConversation
        accumulator: OutputAccumulator
        start_iteration: int
        recent_responses: list[str]
        recent_tool_fingerprints: list[list[tuple[str, str]]]

    async def _restore(
        self,
        ctx: NodeContext,
    ) -> _RestoredState | None:
        """Attempt to restore from a previous checkpoint.

        Returns a ``_RestoredState`` with conversation, accumulator, iteration
        counter, and stall/doom-loop detection state — everything needed to
        resume exactly where execution stopped.
        """
        if self._conversation_store is None:
            return None

        # In isolated mode, filter parts by phase_id so the node only sees
        # its own messages in the shared flat conversation store.  In
        # continuous mode (or when _restore is called for timer-resume)
        # load all parts — the full conversation threads across nodes.
        _is_continuous = getattr(ctx, "continuous_mode", False)
        phase_filter = None if _is_continuous else ctx.node_id
        conversation = await NodeConversation.restore(
            self._conversation_store,
            phase_id=phase_filter,
        )
        if conversation is None:
            return None

        accumulator = await OutputAccumulator.restore(self._conversation_store)

        cursor = await self._conversation_store.read_cursor()
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
        return EventLoopNode._RestoredState(
            conversation=conversation,
            accumulator=accumulator,
            start_iteration=start_iteration,
            recent_responses=recent_responses,
            recent_tool_fingerprints=recent_tool_fingerprints,
        )

    async def _write_cursor(
        self,
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
            # Persist stall/doom-loop detection state for reliable resume
            if recent_responses is not None:
                cursor["recent_responses"] = recent_responses
            if recent_tool_fingerprints is not None:
                # Convert list[list[tuple]] → list[list[list]] for JSON
                cursor["recent_tool_fingerprints"] = [
                    [list(pair) for pair in fps] for fps in recent_tool_fingerprints
                ]
            await self._conversation_store.write_cursor(cursor)

    async def _drain_injection_queue(self, conversation: NodeConversation) -> int:
        """Drain all pending injected events as user messages. Returns count."""
        count = 0
        while not self._injection_queue.empty():
            try:
                content, is_client_input = self._injection_queue.get_nowait()
                logger.info(
                    "[drain] injected message (client_input=%s): %s",
                    is_client_input,
                    content[:200] if content else "(empty)",
                )
                # Real user input is stored as-is; external events get a prefix
                if is_client_input:
                    await conversation.add_user_message(content, is_client_input=True)
                else:
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

    # -------------------------------------------------------------------
    # EventBus publishing helpers
    # -------------------------------------------------------------------

    async def _publish_loop_started(
        self, stream_id: str, node_id: str, execution_id: str = ""
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_started(
                stream_id=stream_id,
                node_id=node_id,
                max_iterations=self._config.max_iterations,
                execution_id=execution_id,
            )

    async def _generate_action_plan(
        self,
        ctx: NodeContext,
        stream_id: str,
        node_id: str,
        execution_id: str,
    ) -> None:
        """Generate a brief action plan via LLM and emit it as an SSE event.

        Runs as a fire-and-forget task so it never blocks the main loop.
        """
        try:
            system_prompt = ctx.node_spec.system_prompt or ""
            # Trim to keep the prompt small
            prompt_summary = system_prompt[:500]
            if len(system_prompt) > 500:
                prompt_summary += "..."

            tool_names = [t.name for t in ctx.available_tools]
            output_keys = ctx.node_spec.output_keys or []

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
                max_tokens=300,
            )

            plan = response.content.strip()
            if plan and self._event_bus:
                await self._event_bus.emit_node_action_plan(
                    stream_id=stream_id,
                    node_id=node_id,
                    plan=plan,
                    execution_id=execution_id,
                )
        except Exception as e:
            logger.warning("Action plan generation failed for node '%s': %s", node_id, e)

    async def _publish_iteration(
        self, stream_id: str, node_id: str, iteration: int, execution_id: str = ""
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_iteration(
                stream_id=stream_id,
                node_id=node_id,
                iteration=iteration,
                execution_id=execution_id,
            )

    async def _publish_loop_completed(
        self, stream_id: str, node_id: str, iterations: int, execution_id: str = ""
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_completed(
                stream_id=stream_id,
                node_id=node_id,
                iterations=iterations,
                execution_id=execution_id,
            )

    async def _publish_stalled(self, stream_id: str, node_id: str, execution_id: str = "") -> None:
        if self._event_bus:
            await self._event_bus.emit_node_stalled(
                stream_id=stream_id,
                node_id=node_id,
                reason="Consecutive identical responses detected",
                execution_id=execution_id,
            )

    async def _publish_text_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        ctx: NodeContext,
        execution_id: str = "",
        iteration: int | None = None,
    ) -> None:
        if self._event_bus:
            if ctx.node_spec.client_facing:
                await self._event_bus.emit_client_output_delta(
                    stream_id=stream_id,
                    node_id=node_id,
                    content=content,
                    snapshot=snapshot,
                    execution_id=execution_id,
                    iteration=iteration,
                )
            else:
                await self._event_bus.emit_llm_text_delta(
                    stream_id=stream_id,
                    node_id=node_id,
                    content=content,
                    snapshot=snapshot,
                    execution_id=execution_id,
                )

    async def _publish_tool_started(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        tool_input: dict,
        execution_id: str = "",
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_tool_call_started(
                stream_id=stream_id,
                node_id=node_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                tool_input=tool_input,
                execution_id=execution_id,
            )

    async def _publish_tool_completed(
        self,
        stream_id: str,
        node_id: str,
        tool_use_id: str,
        tool_name: str,
        result: str,
        is_error: bool,
        execution_id: str = "",
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_tool_call_completed(
                stream_id=stream_id,
                node_id=node_id,
                tool_use_id=tool_use_id,
                tool_name=tool_name,
                result=result,
                is_error=is_error,
                execution_id=execution_id,
            )

    async def _publish_judge_verdict(
        self,
        stream_id: str,
        node_id: str,
        action: str,
        feedback: str = "",
        judge_type: str = "implicit",
        iteration: int = 0,
        execution_id: str = "",
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_judge_verdict(
                stream_id=stream_id,
                node_id=node_id,
                action=action,
                feedback=feedback,
                judge_type=judge_type,
                iteration=iteration,
                execution_id=execution_id,
            )

    async def _publish_output_key_set(
        self,
        stream_id: str,
        node_id: str,
        key: str,
        execution_id: str = "",
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_output_key_set(
                stream_id=stream_id,
                node_id=node_id,
                key=key,
                execution_id=execution_id,
            )
