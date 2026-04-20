"""AgentLoop: Multi-turn LLM streaming loop with tool execution and judge evaluation.

Implements AgentProtocol and runs a streaming event loop:
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
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from framework.agent_loop.conversation import ConversationStore, NodeConversation
from framework.agent_loop.internals import types as event_loop_types
from framework.agent_loop.internals.compaction import (
    build_emergency_summary,
    build_llm_compaction_prompt,
    compact,
    format_messages_for_summary,
    llm_compact,
)
from framework.agent_loop.internals.cursor_persistence import (
    RestoredState,
    check_pause,
    drain_injection_queue,
    drain_trigger_queue,
    restore,
    write_cursor,
)
from framework.agent_loop.internals.event_publishing import (
    generate_action_plan,
    log_skip_judge,
    publish_context_usage,
    publish_iteration,
    publish_judge_verdict,
    publish_llm_turn_complete,
    publish_loop_completed,
    publish_loop_started,
    publish_output_key_set,
    publish_stalled,
    publish_text_delta,
    publish_tool_completed,
    publish_tool_started,
    run_hooks,
)
from framework.agent_loop.internals.judge_pipeline import (
    SubagentJudge as SharedSubagentJudge,
    judge_turn,
)
from framework.agent_loop.internals.stall_detector import (
    fingerprint_tool_calls,
    is_stalled,
    is_tool_doom_loop,
    ngram_similarity,
)
from framework.agent_loop.internals.synthetic_tools import (
    build_ask_user_tool,
    build_escalate_tool,
    build_report_to_parent_tool,
    handle_report_to_parent,
)
from framework.agent_loop.internals.tool_result_handler import (
    build_json_preview,
    execute_tool,
    extract_json_metadata,
    is_transient_error,
    restore_spill_counter,
    truncate_tool_result,
)
from framework.agent_loop.internals.types import (
    JudgeProtocol,
    JudgeVerdict,
    TriggerEvent,
)
from framework.agent_loop.types import AgentContext, AgentProtocol, AgentResult
from framework.host.event_bus import EventBus
from framework.llm.capabilities import filter_tools_for_model, supports_image_tool_results
from framework.llm.provider import Tool, ToolResult, ToolUse
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)
from framework.tracker.llm_debug_logger import log_llm_turn
from framework.utils.task_registry import TaskRegistry

logger = logging.getLogger(__name__)

# Tags that wrap internal reasoning and must be stripped from the
# user-visible stream.  These are the 5-pillar character assessment
# labels, written by the queen as a prefix to every response in either
# closed (<tag>val</tag>) or bare (<tag> val) form.
_INTERNAL_TAGS = frozenset(
    {
        "relationship",
        "context",
        "sentiment",
        "physical_state",
        "tone",
    }
)

# Closed-block form: <tag>value</tag>
_STRIP_RE = re.compile(
    r"<(?:" + "|".join(_INTERNAL_TAGS) + r")>"
    r".*?"
    r"</(?:" + "|".join(_INTERNAL_TAGS) + r")>\s*",
    re.DOTALL,
)

# Bare-label form: <tag> value-up-to-next-tag-or-newline.
# The value cannot contain `<` or `\n` — those terminate the label.
# Trailing whitespace (including the terminating newline) is consumed
# so the visible text that follows starts cleanly.
_LABEL_STRIP_RE = re.compile(r"<(?:" + "|".join(_INTERNAL_TAGS) + r")>[^<\n]*\s*")

# Matches a trailing `<` that could be the start of an internal tag.
# We build a pattern that matches `<` followed by any prefix of any
# internal tag name (e.g. `<rela`, `<contex`).
_PARTIAL_PREFIXES: set[str] = set()
for _tag in _INTERNAL_TAGS:
    for _i in range(1, len(_tag) + 1):
        _PARTIAL_PREFIXES.add(_tag[:_i])
_PARTIAL_OPEN_RE = re.compile(
    r"<(?:" + "|".join(re.escape(p) for p in sorted(_PARTIAL_PREFIXES, key=len, reverse=True)) + r")$"
)

_GENERIC_TAG_RE = re.compile(r"</?[a-zA-Z_][\w-]*\s*/?>")
_GENERIC_TAG_OR_PARTIAL_RE = re.compile(r"<[a-zA-Z_]|</[a-zA-Z_]|<$")


def _strip_internal_tags_from_snapshot(snapshot: str) -> str:
    """Remove internal tag blocks and bare labels from accumulated text.

    The 5-pillar character assessment tags appear in two forms:
      1. Closed block: <relationship>neutral</relationship>
      2. Bare label:   <relationship> neutral
    Both are stripped.  Partial tags at the end of a streaming snapshot
    are truncated so reasoning never leaks mid-stream.
    """
    # Pass 1: closed <tag>...</tag> blocks
    cleaned = _STRIP_RE.sub("", snapshot)

    # Pass 2: bare-label <tag> value pairs (value runs to next tag or newline)
    cleaned = _LABEL_STRIP_RE.sub("", cleaned)

    # Pass 3: trailing partial tag (e.g. `<rela`) — mid-stream guard
    m = _PARTIAL_OPEN_RE.search(cleaned)
    if m:
        cleaned = cleaned[: m.start()]

    # Generic pass: strip any remaining XML-like tags the LLM hallucinated
    # (e.g. <professional>, <staging>, </neutral>).  These are never
    # intentional markup — just remove them outright.
    cleaned = _GENERIC_TAG_RE.sub("", cleaned)
    # Truncate at any remaining `<` that looks like it could be a tag
    # start (followed by a letter) or a bare `<` at end of string.
    # During streaming this suppresses partial tags until they resolve.
    m3 = _GENERIC_TAG_OR_PARTIAL_RE.search(cleaned)
    if m3:
        cleaned = cleaned[: m3.start()]

    return cleaned


async def _describe_images_as_text(image_content: list[dict[str, Any]]) -> str | None:
    """Describe images using the best available vision model."""
    import litellm

    blocks: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Describe the following image(s) concisely but with enough detail "
                "that a text-only AI assistant can understand the content and context."
            ),
        }
    ]
    blocks.extend(image_content)

    candidates: list[str] = []
    if os.environ.get("OPENAI_API_KEY"):
        candidates.append("gpt-4o-mini")
    if os.environ.get("ANTHROPIC_API_KEY"):
        candidates.append("claude-3-haiku-20240307")
    if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
        candidates.append("gemini/gemini-1.5-flash")

    for model in candidates:
        try:
            response = await litellm.acompletion(
                model=model,
                messages=[{"role": "user", "content": blocks}],
                max_tokens=512,
            )
            description = (response.choices[0].message.content or "").strip()
            if description:
                count = len(image_content)
                label = "image" if count == 1 else f"{count} images"
                return f"[{label} attached  — description: {description}]"
        except Exception as exc:
            logger.debug("Vision fallback model '%s' failed: %s", model, exc)
            continue

    return None


# Pattern for detecting context-window-exceeded errors across LLM providers.
_CONTEXT_TOO_LARGE_RE = re.compile(
    r"context.{0,20}(length|window|limit|size)|"
    r"too.{0,10}(long|large|many.{0,10}tokens)|"
    r"(exceed|exceeds|exceeded).{0,30}(limit|window|context|tokens)|"
    r"maximum.{0,20}token|prompt.{0,20}too.{0,10}long",
    re.IGNORECASE,
)


def _is_context_too_large_error(exc: BaseException) -> bool:
    """Detect whether an exception indicates the LLM input was too large."""
    cls = type(exc).__name__
    if "ContextWindow" in cls:
        return True
    return bool(_CONTEXT_TOO_LARGE_RE.search(str(exc)))


def _build_tool_error_result(tc: Any, exc: BaseException) -> ToolResult:
    """Convert a tool exception into a ToolResult for the model.

    Special-cases ``CredentialExpiredError`` so the agent receives a
    structured ``credential_expired`` payload (with credential_id, provider,
    alias, reauth_url) instead of an opaque error string. The agent's
    behavior block recognizes this shape and prompts the user to reauthorize.
    """
    try:
        from framework.credentials.models import CredentialExpiredError
    except ImportError:
        CredentialExpiredError = None  # type: ignore[assignment]

    if CredentialExpiredError is not None and isinstance(exc, CredentialExpiredError):
        payload: dict[str, Any] = {
            "error": "credential_expired",
            "credential_id": exc.credential_id,
            "message": str(exc),
        }
        if exc.provider:
            payload["provider"] = exc.provider
        if exc.alias:
            payload["alias"] = exc.alias
        if exc.help_url:
            payload["reauth_url"] = exc.help_url
        return ToolResult(
            tool_use_id=tc.tool_use_id,
            content=json.dumps(payload),
            is_error=True,
        )

    return ToolResult(
        tool_use_id=tc.tool_use_id,
        content=f"Tool '{tc.tool_name}' raised: {exc}",
        is_error=True,
    )


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Judge protocol (simple 3-action interface for event loop evaluation)
# ---------------------------------------------------------------------------


class TurnCancelled(Exception):
    """Raised when a turn is cancelled mid-stream."""

    pass


# Re-export shared event-loop types from the legacy parent module.
SubagentJudge = SharedSubagentJudge
LoopConfig = event_loop_types.LoopConfig
HookContext = event_loop_types.HookContext
HookResult = event_loop_types.HookResult
OutputAccumulator = event_loop_types.OutputAccumulator


# ---------------------------------------------------------------------------
# EventLoopNode
# ---------------------------------------------------------------------------


class AgentLoop(AgentProtocol):
    """Multi-turn LLM streaming loop with tool execution and judge evaluation.

    Lifecycle:
    1. Try to restore from durable state (crash recovery)
    2. If no prior state, init from AgentSpec.system_prompt + input_keys
    3. Loop: drain injection queue -> stream LLM -> execute tools
       -> if queen-interactive: block for user input (see below)
       -> judge evaluates (acceptance criteria)
    4. Publish events to EventBus at each stage
    5. Write cursor after each iteration
    6. Terminate when judge returns ACCEPT, shutdown signaled, or max iterations
    7. Build output dict from OutputAccumulator

    Queen interaction blocking:

    - **Text-only turns** (no real tool calls)
      automatically block for user input.  If the LLM is talking to the
      user (not calling tools), it should wait for the user's response
      before the judge runs.
    - **Work turns** (tool calls) flow through without blocking —
      the LLM is making progress, not asking the user.
    - A synthetic ``ask_user`` tool is also injected for explicit
      blocking when the LLM wants to be deliberate about requesting
      input (e.g. mid-tool-call).

    Always returns AgentResult with retryable=False semantics. The executor
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
        self._injection_queue: asyncio.Queue[tuple[str, bool, list[dict[str, Any]] | None]] = asyncio.Queue()
        self._trigger_queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
        # Queen input blocking state
        self._input_ready = asyncio.Event()
        self._awaiting_input = False
        self._shutdown = False
        self._stream_task: asyncio.Task | None = None
        self._tool_task: asyncio.Task | None = None  # gather task while tools run
        # Track which nodes already have an action plan emitted (skip on revisit)
        self._action_plan_emitted: set[str] = set()
        # Tracked background tasks (action plan, etc.) — prevents GC loss
        # and surfaces unhandled exceptions via the done callback.
        self._bg_tasks: TaskRegistry = TaskRegistry(owner="AgentLoop")
        # Monotonic counter for spillover file naming (web_search_1.txt, etc.)
        self._spill_counter: int = 0
        # Set to True by the report_to_parent synthetic tool handler so the
        # next loop iteration exits cleanly (parallel worker termination).
        self._report_terminated: bool = False
        # Back-reference to the Worker that owns this AgentLoop, if any.
        # Set by the Worker's __init__ so the report_to_parent handler can
        # record the explicit report payload on the owning Worker instance.
        self._owner_worker: Any = None
        # Reliability counters — populated throughout execute() and
        # copied onto AgentResult.reliability_stats at return time.
        # Kept on the instance so ``stats()`` can expose them externally
        # without waiting for execute() to return. Keys are stable so
        # dashboards can build aggregates over many runs.
        self._counters: dict[str, int] = {}

    def _bump(self, key: str, by: int = 1) -> None:
        """Increment a reliability counter (creates the key on first use)."""
        self._counters[key] = self._counters.get(key, 0) + by

    def stats(self) -> dict[str, int]:
        """Return a snapshot of reliability counters for this loop."""
        return dict(self._counters)

    def _finalize_result(self, result: AgentResult, reason: str) -> AgentResult:
        """Stamp exit_reason + reliability_stats on an AgentResult before return.

        Central point so every exit path in execute() carries the same
        observability payload, and new counters show up in results
        without touching every return site.
        """
        result.exit_reason = reason
        result.reliability_stats = dict(self._counters)
        return result

    def validate_input(self, ctx: AgentContext) -> list[str]:
        """Validate hard requirements only.

        Event loop nodes are LLM-powered and can reason about flexible input,
        so input_keys are treated as hints — not strict requirements.
        Only the LLM provider is a hard dependency.
        """
        errors = []
        if ctx.llm is None:
            errors.append("LLM provider is required for AgentLoop")
        return errors

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def execute(self, ctx: AgentContext) -> AgentResult:
        """Run the event loop.

        Thin wrapper around :meth:`_execute_impl` that stamps reliability
        counters on whatever AgentResult the implementation returns, and
        fills in a best-effort ``exit_reason`` from the result fields
        when the implementation didn't set one explicitly. This way
        every return path in ``_execute_impl`` automatically carries
        telemetry without having to edit 13+ return sites.
        """
        result = await self._execute_impl(ctx)
        # Always refresh counters at the outermost boundary, in case a
        # nested return in _execute_impl used _finalize_result with a
        # stale copy.
        result.reliability_stats = dict(self._counters)
        if result.exit_reason == "?":
            # Best-effort classification from the AgentResult payload.
            # _execute_impl can (and should) set reason explicitly at
            # key sites via _finalize_result — this only handles the
            # returns that weren't updated yet.
            err = (result.error or "").lower()
            if result.success:
                result.exit_reason = "completed"
            elif "max iterations" in err:
                result.exit_reason = "max_iterations"
            elif "input_validation_errors" in err or result.validation_errors:
                result.exit_reason = "validation_error"
            elif "timed out" in err or "timeout" in err:
                result.exit_reason = "timeout"
            elif "cancel" in err or "stopped" in err:
                result.exit_reason = "cancelled"
            else:
                result.exit_reason = "failed"
        return result

    async def _execute_impl(self, ctx: AgentContext) -> AgentResult:
        """Run the event loop."""
        self._last_ctx = ctx
        logger.debug(
            "[AgentLoop.execute] Starting execution for node=%s, stream=%s",
            ctx.agent_id,
            ctx.stream_id,
        )
        start_time = time.time()
        total_input_tokens = 0
        total_output_tokens = 0
        stream_id = ctx.stream_id or ctx.agent_id
        node_id = ctx.agent_id
        execution_id = ctx.execution_id or ""
        # Store skill dirs for AS-9 file-read interception in _execute_tool
        self._skill_dirs: list[str] = ctx.skill_dirs
        logger.debug(
            "[AgentLoop.execute] node_id=%s, execution_id=%s, max_iterations=%d",
            node_id,
            execution_id,
            self._config.max_iterations,
        )

        # DS-13: context preservation warning state
        _context_warn_sent = False

        # Verdict counters for runtime logging
        _accept_count = _retry_count = _escalate_count = _continue_count = 0

        # Queen auto-block grace: consecutive text-only turns without
        # any real tool call or set_output.  Resets on progress.
        _cf_text_only_streak = 0
        # Worker auto-escalation: consecutive text-only turns.
        # After grace, auto-escalate to queen for guidance.
        _worker_text_only_streak = 0
        # Silent worker detection: consecutive turns with tool calls
        # but no user-facing text.  After the threshold, inject a
        # nudge asking the agent to communicate progress.
        _silent_tool_streak = 0

        # 1. Guard: LLM required
        if ctx.llm is None:
            error_msg = "LLM provider not available"
            # Log guard failure
            if ctx.runtime_logger:
                ctx.runtime_logger.log_node_complete(
                    node_id=node_id,
                    node_name=ctx.agent_spec.name,
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
            return self._finalize_result(AgentResult(success=False, error=error_msg), "guard_failure")

        # 2. Restore or create new conversation + accumulator
        restored = await self._restore(ctx)
        if restored is not None:
            conversation = restored.conversation
            accumulator = restored.accumulator
            start_iteration = restored.start_iteration
            _restored_recent_responses = restored.recent_responses
            _restored_tool_fingerprints = restored.recent_tool_fingerprints
            _restored_pending_input = restored.pending_input

            # Refresh the system prompt
            from framework.agent_loop.prompting import (
                build_system_prompt_for_context,
                stamp_prompt_datetime,
            )

            _current_prompt = build_system_prompt_for_context(ctx)
            if conversation.system_prompt != _current_prompt:
                conversation.update_system_prompt(_current_prompt)
                logger.info("Refreshed system prompt for restored conversation")

            # Refresh other meta fields that may differ across runs
            conversation._max_context_tokens = self._config.max_context_tokens
            if ctx.agent_spec.output_keys:
                conversation._output_keys = ctx.agent_spec.output_keys
            conversation._meta_persisted = False
        else:
            _restored_recent_responses = []
            _restored_tool_fingerprints = []
            _restored_pending_input = None

            if self._conversation_store is not None:
                await self._conversation_store.clear()

            from framework.agent_loop.prompting import (
                build_system_prompt_for_context,
                stamp_prompt_datetime,
            )

            system_prompt = build_system_prompt_for_context(ctx)

            if ctx.skills_catalog_prompt:
                logger.info(
                    "[%s] Injected skills catalog (%d chars)",
                    node_id,
                    len(ctx.skills_catalog_prompt),
                )
            if ctx.protocols_prompt:
                logger.info(
                    "[%s] Injected operational protocols (%d chars)",
                    node_id,
                    len(ctx.protocols_prompt),
                )

            if ctx.default_skill_batch_nudge:
                from framework.skills.defaults import is_batch_scenario as _is_batch

                _input_text = (ctx.goal_context or "") + " " + " ".join(str(v) for v in ctx.input_data.values() if v)
                if _is_batch(_input_text):
                    system_prompt = f"{system_prompt}\n\n{ctx.default_skill_batch_nudge}"
                    logger.info("[%s] DS-12: batch scenario detected, nudge injected", node_id)

            conversation = NodeConversation(
                system_prompt=system_prompt,
                max_context_tokens=self._config.max_context_tokens,
                output_keys=ctx.agent_spec.output_keys or None,
                store=self._conversation_store,
                run_id=ctx.effective_run_id,
                compaction_buffer_tokens=self._config.compaction_buffer_tokens,
                compaction_warning_buffer_tokens=(self._config.compaction_warning_buffer_tokens),
            )
            accumulator = OutputAccumulator(
                store=self._conversation_store,
                spillover_dir=self._config.spillover_dir,
                max_value_chars=self._config.max_output_value_chars,
                run_id=ctx.effective_run_id,
            )
            start_iteration = 0

            initial_message = self._build_initial_message(ctx)
            if initial_message:
                await conversation.add_user_message(initial_message)

            await self._run_hooks("session_start", conversation, trigger=initial_message)

        # 2a. Guard: ensure at least one non-system message exists.
        # A restored conversation may have 0 messages if phase_id filtering
        # removes them all, or if a prior run stored metadata without messages
        # (e.g. node that failed before the first LLM call).
        if conversation.message_count == 0:
            initial_message = self._build_initial_message(ctx)
            if not initial_message:
                initial_message = "Hello"
            await conversation.add_user_message(initial_message)

        # 2b. Restore spill counter from existing files (resume safety)
        self._restore_spill_counter()

        # 3. Build tool list: node tools + synthetic framework tools + delegate tools
        tools = list(ctx.available_tools)
        if ctx.supports_direct_user_io:
            tools.append(self._build_ask_user_tool())
        # Workers (parallel ephemeral agents) get escalate + report_to_parent.
        # The overseer is client-facing like the queen and has neither.
        if stream_id not in ("queen", "judge", "overseer"):
            tools.append(self._build_escalate_tool())
        # Only parallel workers (stream_id="worker:{uuid}") get report_to_parent.
        if isinstance(stream_id, str) and stream_id.startswith("worker:"):
            tools.append(build_report_to_parent_tool())

        # Hide image-producing tools from text-only models so they never try
        # to call them. Avoids wasted turns + "screenshot failed" lessons
        # getting saved to memory. See framework.llm.capabilities.
        _llm_model = ctx.llm.model if ctx.llm else ""
        tools, _hidden_image_tools = filter_tools_for_model(tools, _llm_model)

        logger.info(
            "[%s] Tools available (%d): %s | direct_user_io=%s | judge=%s | hidden_image_tools=%s",
            node_id,
            len(tools),
            [t.name for t in tools],
            ctx.supports_direct_user_io,
            type(self._judge).__name__ if self._judge else "None",
            _hidden_image_tools,
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
            self._bg_tasks.spawn(
                self._generate_action_plan(ctx, stream_id, node_id, execution_id),
                name=f"action_plan:{node_id}",
            )

        # 5. Stall / doom loop detection state (restored from cursor if resuming)
        recent_responses: list[str] = _restored_recent_responses
        recent_tool_fingerprints: list[list[tuple[str, str]]] = _restored_tool_fingerprints
        pending_input_state: dict[str, Any] | None = _restored_pending_input
        _consecutive_empty_turns: int = 0

        # 6. Main loop
        logger.debug("[AgentLoop.execute] Entering main loop, start_iteration=%d", start_iteration)
        for iteration in range(start_iteration, self._config.max_iterations):
            iter_start = time.time()
            logger.debug("[AgentLoop.execute] iteration=%d starting", iteration)

            # 6a-pre. Early exit for workers that called report_to_parent on
            # the previous turn. The report_to_parent handler sets this
            # flag; the loop finishes the current turn (so the LLM sees
            # the acknowledgement tool result) and exits at the top of the
            # next iteration. Parallel workers terminate here.
            if self._report_terminated:
                latency_ms = int((time.time() - start_time) * 1000)
                logger.info(
                    "[%s] iter=%d: worker terminated via report_to_parent",
                    node_id,
                    iteration,
                )
                await self._publish_loop_completed(stream_id, node_id, iteration, execution_id)
                return AgentResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            # 6a. Check pause (no current-iteration data yet — only log_node_complete needed)
            if await self._check_pause(ctx, conversation, iteration):
                latency_ms = int((time.time() - start_time) * 1000)
                if ctx.runtime_logger:
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
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
                return AgentResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            # 6b. Drain injection queue
            logger.debug("[AgentLoop.execute] iteration=%d: draining injection queue...", iteration)
            drained_injections = await self._drain_injection_queue(conversation, ctx)
            logger.debug(
                "[AgentLoop.execute] iteration=%d: drained %d injections",
                iteration,
                drained_injections,
            )
            # 6b1. Drain trigger queue (framework-level signals)
            drained_triggers = await self._drain_trigger_queue(conversation)
            logger.debug(
                "[AgentLoop.execute] iteration=%d: drained %d triggers",
                iteration,
                drained_triggers,
            )

            # Resume blocked ask_user/auto-block waits durably across restarts.
            # If the node was parked for input and no new message has been
            # injected yet, re-enter the wait instead of continuing the last
            # assistant turn with a synthetic prompt.
            if pending_input_state is not None:
                if drained_injections > 0 or drained_triggers > 0:
                    pending_input_state = None
                    await self._write_cursor(
                        ctx,
                        conversation,
                        accumulator,
                        iteration,
                        recent_responses=recent_responses,
                        recent_tool_fingerprints=recent_tool_fingerprints,
                        pending_input=None,
                    )
                else:
                    logger.info(
                        "[%s] iter=%d: restored pending input wait (emit_client_request=%s)",
                        node_id,
                        iteration,
                        pending_input_state.get("emit_client_request", True),
                    )
                    got_input = await self._await_user_input(
                        ctx,
                        questions=pending_input_state.get("questions"),
                        emit_client_request=bool(pending_input_state.get("emit_client_request", True)),
                    )
                    logger.info(
                        "[%s] iter=%d: restored wait unblocked, got_input=%s",
                        node_id,
                        iteration,
                        got_input,
                    )
                    if not got_input:
                        await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                        latency_ms = int((time.time() - start_time) * 1000)
                        return AgentResult(
                            success=True,
                            output=accumulator.to_dict(),
                            tokens_used=total_input_tokens + total_output_tokens,
                            latency_ms=latency_ms,
                            conversation=None,
                        )
                    if self._injection_queue.empty() and self._trigger_queue.empty():
                        logger.info(
                            "[%s] iter=%d: pending-input wait woke without queued input; re-waiting",
                            node_id,
                            iteration,
                        )
                        continue
                    pending_input_state = None
                    continue

            # 6b2. Dynamic tool refresh (mode switching)
            if ctx.dynamic_tools_provider is not None:
                _synthetic_names = {
                    "ask_user",
                    "escalate",
                }
                synthetic = [t for t in tools if t.name in _synthetic_names]
                tools.clear()
                tools.extend(ctx.dynamic_tools_provider())
                tools.extend(synthetic)

            # 6b3. Dynamic prompt refresh (phase switching / memory refresh)
            if ctx.dynamic_prompt_provider is not None or ctx.dynamic_memory_provider is not None:
                if ctx.dynamic_prompt_provider is not None:
                    _new_prompt = stamp_prompt_datetime(ctx.dynamic_prompt_provider())
                else:
                    _new_prompt = build_system_prompt_for_context(ctx)
                if _new_prompt != conversation.system_prompt:
                    conversation.update_system_prompt(_new_prompt)
                    logger.info("[%s] Dynamic prompt updated", node_id)

            # 6c. Publish iteration event (with per-iteration metadata when available)
            _iter_meta = None
            if ctx.iteration_metadata_provider is not None:
                try:
                    _iter_meta = ctx.iteration_metadata_provider()
                except Exception:
                    pass
            await self._publish_iteration(
                stream_id,
                node_id,
                iteration,
                execution_id,
                extra_data=_iter_meta,
            )
            # Sync max_context_tokens from live config so mid-session model
            # switches are reflected in compaction decisions and the UI bar.
            from framework.config import get_max_context_tokens as _live_mct

            conversation._max_context_tokens = _live_mct()

            await self._publish_context_usage(ctx, conversation, "iteration_start")

            # 6d. Pre-turn compaction check (tiered)
            _compacted_this_iter = False
            if conversation.needs_compaction():
                await self._compact(ctx, conversation, accumulator)
                _compacted_this_iter = True

            # 6e. Run single LLM turn (with transient error retry)
            logger.info(
                "[%s] iter=%d: running LLM turn (msgs=%d)",
                node_id,
                iteration,
                len(conversation.messages),
            )
            logger.debug("[AgentLoop.execute] iteration=%d: entering _run_single_turn loop", iteration)
            _stream_retry_count = 0
            _capacity_retry_started_at: float | None = None
            _capacity_retry_attempt = 0
            _turn_cancelled = False
            _llm_turn_failed_waiting_input = False
            _turn_t0 = time.monotonic()
            while True:
                try:
                    logger.debug(
                        "[AgentLoop.execute] iteration=%d: calling _run_single_turn (retry=%d)",
                        iteration,
                        _stream_retry_count,
                    )
                    (
                        assistant_text,
                        real_tool_results,
                        outputs_set,
                        turn_tokens,
                        logged_tool_calls,
                        user_input_requested,
                        queen_input_requested,
                        request_system_prompt,
                        request_messages,
                        _,
                    ) = await self._run_single_turn(ctx, conversation, tools, iteration, accumulator)
                    logger.debug(
                        "[AgentLoop.execute] iteration=%d: _run_single_turn completed successfully",
                        iteration,
                    )
                    _turn_ms = int((time.monotonic() - _turn_t0) * 1000)
                    logger.info(
                        "[%s] iter=%d: LLM done (%dms) — text=%d chars, real_tools=%d, "
                        "outputs_set=%s, tokens=%s, accumulator=%s",
                        node_id,
                        iteration,
                        _turn_ms,
                        len(assistant_text),
                        len(real_tool_results),
                        outputs_set or "[]",
                        turn_tokens,
                        {k: ("set" if v is not None else "None") for k, v in accumulator.to_dict().items()},
                    )
                    total_input_tokens += turn_tokens.get("input", 0)
                    total_output_tokens += turn_tokens.get("output", 0)
                    await self._publish_llm_turn_complete(
                        stream_id,
                        node_id,
                        stop_reason=turn_tokens.get("stop_reason", ""),
                        model=turn_tokens.get("model", ""),
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        cached_tokens=turn_tokens.get("cached", 0),
                        execution_id=execution_id,
                        iteration=iteration,
                    )
                    log_llm_turn(
                        node_id=node_id,
                        stream_id=stream_id,
                        execution_id=execution_id,
                        iteration=iteration,
                        system_prompt=request_system_prompt,
                        messages=request_messages,
                        assistant_text=assistant_text,
                        tool_calls=logged_tool_calls,
                        tool_results=real_tool_results,
                        token_counts=turn_tokens,
                    )

                    # DS-13: inject context preservation warning once when token usage
                    # crosses warn_ratio (default 0.45), before the 0.6 framework prune
                    if (
                        ctx.default_skill_warn_ratio is not None
                        and not _context_warn_sent
                        and conversation.usage_ratio() >= ctx.default_skill_warn_ratio
                    ):
                        _ratio_pct = int(conversation.usage_ratio() * 100)
                        await conversation.add_user_message(
                            f"[CONTEXT ALERT — {_ratio_pct}% used] "
                            "Extract all critical data to `_working_notes` and "
                            "`_preserved_data` now — context pruning occurs at 60% usage."
                        )
                        _context_warn_sent = True
                        logger.info(
                            "[%s] DS-13: context preservation warning injected at %d%%",
                            node_id,
                            _ratio_pct,
                        )

                    break  # success — exit retry loop

                except TurnCancelled:
                    logger.debug("[AgentLoop.execute] iteration=%d: TurnCancelled", iteration)
                    _turn_cancelled = True
                    break

                except Exception as e:
                    logger.debug(
                        "[AgentLoop.execute] iteration=%d: Exception in _run_single_turn: %s (%s)",
                        iteration,
                        type(e).__name__,
                        str(e)[:200],
                    )
                    # Persistent retry for capacity errors (429/529/overloaded).
                    # Unlike the bounded branch below, this one keeps trying
                    # within a wall-clock budget instead of burning through
                    # five attempts in ~1 minute and giving up. Each attempt
                    # still publishes a retry event so the UI can see us
                    # waiting (the "heartbeat" — no silent stalls).
                    self._bump("llm_turn_exception")
                    if self._is_capacity_error(e) and self._config.capacity_retry_max_seconds > 0:
                        self._bump("capacity_error")
                        now = time.monotonic()
                        if _capacity_retry_started_at is None:
                            _capacity_retry_started_at = now
                        elapsed = now - _capacity_retry_started_at
                        if elapsed < self._config.capacity_retry_max_seconds:
                            _capacity_retry_attempt += 1
                            delay = min(
                                self._config.stream_retry_backoff_base * (2 ** min(_capacity_retry_attempt - 1, 6)),
                                self._config.capacity_retry_max_delay,
                            )
                            logger.warning(
                                "[%s] iter=%d: capacity error (%s), persistent retry "
                                "#%d after %.1fs (elapsed %.0fs / %.0fs budget): %s",
                                node_id,
                                iteration,
                                type(e).__name__,
                                _capacity_retry_attempt,
                                delay,
                                elapsed,
                                self._config.capacity_retry_max_seconds,
                                str(e)[:200],
                            )
                            if self._event_bus:
                                await self._event_bus.emit_node_retry(
                                    stream_id=stream_id,
                                    node_id=node_id,
                                    retry_count=_capacity_retry_attempt,
                                    max_retries=-1,  # -1 == persistent / unbounded
                                    error=str(e)[:500],
                                    execution_id=execution_id,
                                )
                            await asyncio.sleep(delay)
                            continue  # retry same iteration

                    # Retry transient errors with exponential backoff
                    if self._is_transient_error(e) and _stream_retry_count < self._config.max_stream_retries:
                        self._bump("llm_transient_retry")
                        _stream_retry_count += 1
                        delay = min(
                            self._config.stream_retry_backoff_base * (2 ** (_stream_retry_count - 1)),
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

                        # For malformed tool call errors, inject feedback into
                        # the conversation before retrying.  Retrying with the
                        # same messages is futile — the LLM will reproduce the
                        # same truncated JSON.  The nudge tells it to shorten
                        # its arguments.
                        error_str = str(e).lower()
                        if "failed to parse tool call" in error_str:
                            await conversation.add_user_message(
                                "[System: Your previous tool call had malformed "
                                "JSON arguments (likely truncated). Keep your "
                                "tool call arguments shorter and simpler. Do NOT "
                                "repeat the same long argument — summarize or "
                                "split into multiple calls.]"
                            )

                        await asyncio.sleep(delay)
                        continue  # retry same iteration

                    # Non-transient or retries exhausted.
                    # For queen turns, surface the error and wait
                    # for user input instead of killing the loop.  The user
                    # can retry or adjust the request.
                    if ctx.supports_direct_user_io:
                        error_msg = f"LLM call failed: {e}"
                        _guardrail_phrase = (
                            "no endpoints available matching your guardrail restrictions and data policy"
                        )
                        if _guardrail_phrase in str(e).lower():
                            error_msg += (
                                " OpenRouter blocked this model under current privacy settings. "
                                "Update https://openrouter.ai/settings/privacy or choose another "
                                "OpenRouter model."
                            )
                        logger.error(
                            "[%s] iter=%d: %s — waiting for user input",
                            node_id,
                            iteration,
                            error_msg,
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
                        # Emit the error via SSE so the frontend renders
                        # it in the chat, then persist it in the conversation.
                        visible_error = f"[Error: {error_msg}. Please try again.]"
                        if self._event_bus and ctx.emits_client_io:
                            await self._event_bus.emit_client_output_delta(
                                stream_id=stream_id,
                                node_id=node_id,
                                content=visible_error,
                                snapshot=visible_error,
                                execution_id=execution_id,
                                iteration=iteration,
                                inner_turn=0,
                            )
                        await conversation.add_assistant_message(visible_error)
                        await self._await_user_input(ctx)
                        _llm_turn_failed_waiting_input = True
                        break  # exit retry loop, continue outer iteration

                    # Non-interactive nodes: crash as before
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
                            node_name=ctx.agent_spec.name,
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

            if _turn_cancelled:
                logger.info("[%s] iter=%d: turn cancelled by user", node_id, iteration)
                if ctx.supports_direct_user_io:
                    await self._await_user_input(ctx)
                continue  # back to top of for-iteration loop

            # Queen non-transient LLM failures wait for user input and then
            # continue the outer loop without touching per-turn token vars.
            if _llm_turn_failed_waiting_input:
                continue

            # 6e'. Feed actual API token count back for accurate estimation
            turn_input = turn_tokens.get("input", 0)
            if turn_input > 0:
                conversation.update_token_count(turn_input)

            # 6e''. Post-turn compaction check (catches tool-result bloat).
            # Skip if pre-turn already compacted this iteration — two compactions
            # in one iteration produce back-to-back spillover files and leave the
            # agent disoriented on the very next turn.
            if not _compacted_this_iter and conversation.needs_compaction():
                await self._compact(ctx, conversation, accumulator)

            # Reset auto-block grace streak when real work happens
            if real_tool_results or outputs_set:
                _cf_text_only_streak = 0
                _worker_text_only_streak = 0

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
                and not queen_input_requested
            )
            if truly_empty and accumulator is not None:
                missing = self._get_missing_output_keys(
                    accumulator, ctx.agent_spec.output_keys, ctx.agent_spec.nullable_output_keys
                )
                # Only accept on empty response if the node actually has
                # output_keys that are all satisfied.  Nodes with NO
                # output_keys (e.g. the forever-alive queen) should never
                # be terminated by a ghost empty stream — "missing" is
                # trivially empty when there are no required outputs.
                has_real_outputs = bool(ctx.agent_spec.output_keys)
                if not missing and has_real_outputs:
                    logger.info(
                        "[%s] iter=%d: empty response but all outputs set — accepting",
                        node_id,
                        iteration,
                    )
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )
                elif missing:
                    # Ghost empty stream: LLM returned nothing and outputs
                    # are still missing.  The conversation hasn't changed, so
                    # repeating the same call will produce the same empty
                    # result.  Inject a nudge to break the cycle.
                    _consecutive_empty_turns += 1
                    logger.warning(
                        "[%s] iter=%d: empty response with missing outputs %s (consecutive=%d)",
                        node_id,
                        iteration,
                        missing,
                        _consecutive_empty_turns,
                    )
                    if _consecutive_empty_turns >= self._config.stall_detection_threshold:
                        # Persistent ghost stream — fail the node.
                        error_msg = (
                            f"Ghost empty stream: {_consecutive_empty_turns} "
                            f"consecutive empty responses with missing "
                            f"outputs {missing}"
                        )
                        latency_ms = int((time.time() - start_time) * 1000)
                        if ctx.runtime_logger:
                            ctx.runtime_logger.log_node_complete(
                                node_id=node_id,
                                node_name=ctx.agent_spec.name,
                                node_type="event_loop",
                                success=False,
                                error=error_msg,
                                total_steps=iteration + 1,
                                tokens_used=total_input_tokens + total_output_tokens,
                                input_tokens=total_input_tokens,
                                output_tokens=total_output_tokens,
                                latency_ms=latency_ms,
                                exit_status="ghost_stream",
                                accept_count=_accept_count,
                                retry_count=_retry_count,
                                escalate_count=_escalate_count,
                                continue_count=_continue_count,
                            )
                        raise RuntimeError(error_msg)
                    # First nudge — inject a system message to break the
                    # empty-response cycle.
                    await conversation.add_user_message(
                        "[System: Your response was empty. You have required "
                        f"outputs that are not yet set: {missing}. Review "
                        "your task and call the appropriate tools to make "
                        "progress.]"
                    )
                    continue
                else:
                    # No output_keys and empty response — forever-alive node
                    # got a ghost empty stream.  Nudge like the missing-outputs
                    # path but without failing (no outputs to demand).
                    _consecutive_empty_turns += 1
                    logger.warning(
                        "[%s] iter=%d: empty response on node with no output_keys (consecutive=%d)",
                        node_id,
                        iteration,
                        _consecutive_empty_turns,
                    )
                    if _consecutive_empty_turns >= self._config.stall_detection_threshold:
                        # Persistent ghost — but since this is a forever-alive
                        # node, block for user input instead of crashing.
                        logger.warning(
                            "[%s] iter=%d: %d consecutive empty responses, blocking for user input",
                            node_id,
                            iteration,
                            _consecutive_empty_turns,
                        )
                        await self._await_user_input(ctx)
                        _consecutive_empty_turns = 0
                    else:
                        await conversation.add_user_message(
                            "[System: Your response was empty. Review the "
                            "conversation and respond to the user or take "
                            "action with your tools.]"
                        )
                    continue
            else:
                _consecutive_empty_turns = 0

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
                        node_name=ctx.agent_spec.name,
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
                return AgentResult(
                    success=False,
                    error=(
                        f"Node stalled: {self._config.stall_detection_threshold} similar "
                        f"responses ({self._config.stall_similarity_threshold * 100:.0f}+"
                        " threshold)"
                    ),
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
                )

            # 6f'. Tool doom loop detection
            # Use logged_tool_calls (persists across inner iterations) and
            # filter to real MCP tools (exclude set_output, ask_user).
            # NOTE: errored tool calls ARE included — a tool that keeps
            # failing with the same args is the canonical doom loop case
            # (e.g. a tool repeatedly hitting the same error).
            mcp_tool_calls = [
                tc
                for tc in logged_tool_calls
                if tc.get("tool_name")
                not in (
                    "ask_user",
                    "escalate",
                )
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
                    if (
                        not ctx.supports_direct_user_io
                        and not ctx.event_triggered
                        and stream_id not in ("queen", "judge")
                        and self._event_bus is not None
                    ):
                        await self._event_bus.emit_escalation_requested(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason="Tool doom loop detected",
                            context=doom_desc,
                            execution_id=execution_id,
                            request_id=uuid.uuid4().hex,
                        )
                        await conversation.add_user_message(
                            "[SYSTEM] Escalated tool doom loop to queen for intervention."
                        )
                        recent_tool_fingerprints.clear()
                        recent_responses.clear()
                    elif ctx.supports_direct_user_io:
                        await conversation.add_user_message(warning_msg)
                        await self._await_user_input(ctx)
                        recent_tool_fingerprints.clear()
                        recent_responses.clear()
                    else:
                        await conversation.add_user_message(warning_msg)
                        recent_tool_fingerprints.clear()
            else:
                # Text-only turn breaks the doom loop chain
                recent_tool_fingerprints.clear()

            # 6f'. Silent worker detection — tool calls without user-facing text.
            #
            # When the agent makes tool calls but produces no text for the
            # user, it feels like a runaway process.  After a configurable
            # number of consecutive silent turns, inject a nudge asking it
            # to communicate what it's doing and why.
            _has_tools_no_text = bool(real_tool_results) and not assistant_text
            if _has_tools_no_text:
                _silent_tool_streak += 1
                if _silent_tool_streak > 0 and _silent_tool_streak % self._config.silent_tool_streak_threshold == 0:
                    nudge = (
                        "[SYSTEM] You have been calling tools for "
                        f"{_silent_tool_streak} consecutive turns without "
                        "any text output. Continue working, but include a "
                        "brief explanation alongside your next tool calls "
                        "so the user can see what you are doing."
                    )
                    await conversation.add_user_message(nudge)
                    logger.info(
                        "[%s] iter=%d: silent tool streak %d, injected communication nudge",
                        node_id,
                        iteration,
                        _silent_tool_streak,
                    )
            else:
                _silent_tool_streak = 0

            # 6g. Write cursor checkpoint (includes stall/doom state for resume)
            await self._write_cursor(
                ctx,
                conversation,
                accumulator,
                iteration,
                recent_responses=recent_responses,
                recent_tool_fingerprints=recent_tool_fingerprints,
                pending_input=None,
            )

            # 6h. Worker auto-escalation on text-only turns
            #
            # Workers that produce text without tool calls or set_output
            # get a grace period to plan/think, then auto-escalate to the
            # queen so the worker doesn't spin uselessly.  Sets
            # queen_input_requested so the existing 6h'' block handles
            # blocking and resumption.
            _is_worker = (
                stream_id not in ("queen", "judge")
                and not False
                and not ctx.supports_direct_user_io
                and self._event_bus is not None
            )
            _worker_no_tool_turn = (
                not real_tool_results and not outputs_set and not queen_input_requested and not user_input_requested
            )
            if _is_worker and _worker_no_tool_turn:
                _worker_text_only_streak += 1
                if _worker_text_only_streak <= self._config.worker_escalation_grace_turns:
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback=(
                                "Worker auto-escalation grace"
                                f" ({_worker_text_only_streak}"
                                f"/{self._config.worker_escalation_grace_turns})"
                            ),
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                    continue
                # Grace exhausted — auto-escalate to queen
                logger.info(
                    "[%s] iter=%d: worker text-only streak %d > grace %d, auto-escalating",
                    node_id,
                    iteration,
                    _worker_text_only_streak,
                    self._config.worker_escalation_grace_turns,
                )
                await self._event_bus.emit_escalation_requested(
                    stream_id=stream_id,
                    node_id=node_id,
                    reason="Worker produced text-only turns without progress; auto-escalating",
                    context=assistant_text[:2000] if assistant_text else "",
                    execution_id=execution_id,
                    request_id=uuid.uuid4().hex,
                )
                queen_input_requested = True

            # 6h'. Queen input blocking
            #
            # Two triggers:
            # (a) Explicit ask_user() — blocks, then skips judge (6i).
            #     The LLM intentionally asked a question; judging before the
            #     user answers would inject confusing "missing outputs"
            #     feedback. Works for the queen's interactive turns.
            # (b) Auto-block (queen only) — a text-only turn (no real
            #     tools, no set_output) from the queen node.  Blocks for
            #     the user's response, then falls through to judge so
            #     models stuck in a clarification loop get RETRY feedback.
            #     Workers are autonomous and don't auto-block — they use
            #     ask_user() explicitly when they need input.
            #
            # Turns that include tool calls or set_output are *work*, not
            # conversation — they flow through without blocking.
            _cf_block = False
            _cf_auto = False
            if ctx.supports_direct_user_io:
                if user_input_requested:
                    _cf_block = True
                elif stream_id == "queen" and not real_tool_results and not outputs_set:
                    # Auto-block: only for the queen (conversational node).
                    # Workers are autonomous — they block only on explicit
                    # ask_user().  Turns without tool calls or set_output
                    # (including empty ghost streams) are not work — block
                    # and wait for user input.
                    _cf_block = True
                    _cf_auto = True

            if _cf_block:
                # Auto-block grace: when required outputs are still
                # missing and we're within the grace period, skip
                # blocking and continue to the next LLM turn so the
                # judge can apply RETRY pressure on lazy models.
                # Without this, _await_user_input() would block
                # forever since no inject_event is coming.
                #
                # When no outputs are missing (e.g. queen monitoring
                # with output_keys=[]), text-only is legitimate
                # conversation and should always block.
                if _cf_auto:
                    _auto_missing = (
                        self._get_missing_output_keys(
                            accumulator,
                            ctx.agent_spec.output_keys,
                            ctx.agent_spec.nullable_output_keys,
                        )
                        if accumulator is not None
                        else True
                    )
                    if _auto_missing:
                        _cf_text_only_streak += 1
                        if _cf_text_only_streak <= self._config.cf_grace_turns:
                            _continue_count += 1
                            if ctx.runtime_logger:
                                iter_latency_ms = int((time.time() - iter_start) * 1000)
                                ctx.runtime_logger.log_step(
                                    node_id=node_id,
                                    node_type="event_loop",
                                    step_index=iteration,
                                    verdict="CONTINUE",
                                    verdict_feedback=(
                                        f"Auto-block grace ({_cf_text_only_streak}/{self._config.cf_grace_turns})"
                                    ),
                                    tool_calls=logged_tool_calls,
                                    llm_text=assistant_text,
                                    input_tokens=turn_tokens.get("input", 0),
                                    output_tokens=turn_tokens.get("output", 0),
                                    latency_ms=iter_latency_ms,
                                )
                            continue
                        # Beyond grace — block below, then fall
                        # through to judge

                if self._shutdown:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    if ctx.runtime_logger:
                        iter_latency_ms = int((time.time() - iter_start) * 1000)
                        ctx.runtime_logger.log_step(
                            node_id=node_id,
                            node_type="event_loop",
                            step_index=iteration,
                            verdict="CONTINUE",
                            verdict_feedback="Shutdown signaled (queen interaction)",
                            tool_calls=logged_tool_calls,
                            llm_text=assistant_text,
                            input_tokens=turn_tokens.get("input", 0),
                            output_tokens=turn_tokens.get("output", 0),
                            latency_ms=iter_latency_ms,
                        )
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
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
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                logger.info(
                    "[%s] iter=%d: blocking for user input (auto=%s)...",
                    node_id,
                    iteration,
                    _cf_auto,
                )
                # Pull the pending questions array set by the ask_user
                # handler (a 1-item list for a single question, 2-8 for a
                # batch). None for auto-block turns with no explicit ask.
                pending_qs = getattr(self, "_pending_questions", None)
                self._pending_questions = None
                pending_input_state = {
                    "questions": pending_qs,
                    "emit_client_request": True,
                }
                await self._write_cursor(
                    ctx,
                    conversation,
                    accumulator,
                    iteration,
                    recent_responses=recent_responses,
                    recent_tool_fingerprints=recent_tool_fingerprints,
                    pending_input=pending_input_state,
                )
                got_input = await self._await_user_input(
                    ctx,
                    questions=pending_qs,
                )
                # Emit deferred tool_call_completed for ask_user
                deferred = getattr(self, "_deferred_tool_complete", None)
                if deferred:
                    self._deferred_tool_complete = None
                    await self._publish_tool_completed(
                        deferred["stream_id"],
                        deferred["node_id"],
                        deferred["tool_use_id"],
                        deferred["tool_name"],
                        deferred["content"],
                        deferred["is_error"],
                        deferred["execution_id"],
                    )
                logger.info("[%s] iter=%d: unblocked, got_input=%s", node_id, iteration, got_input)
                if not got_input:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
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
                            node_name=ctx.agent_spec.name,
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
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                if self._injection_queue.empty() and self._trigger_queue.empty():
                    logger.info(
                        "[%s] iter=%d: input wait woke without queued input; continuing to wait",
                        node_id,
                        iteration,
                    )
                    continue

                pending_input_state = None

                recent_responses.clear()

                # -- Judge-skip decision after queen blocking --
                #
                # Explicit ask_user: skip judge while the queen is
                # still gathering information from the user.  BUT if
                # all required outputs have already been set, don't
                # skip -- fall through to the judge so it can accept.
                if not _cf_auto:
                    _missing = (
                        self._get_missing_output_keys(
                            accumulator,
                            ctx.agent_spec.output_keys,
                            ctx.agent_spec.nullable_output_keys,
                        )
                        if accumulator is not None
                        else True
                    )
                    _outputs_complete = not _missing
                    if not _outputs_complete:
                        _cf_text_only_streak = 0
                        _continue_count += 1
                        self._log_skip_judge(
                            ctx,
                            node_id,
                            iteration,
                            "Blocked for ask_user input (skip judge)",
                            logged_tool_calls,
                            assistant_text,
                            turn_tokens,
                            iter_start,
                        )
                        continue
                    # All outputs set -- fall through to judge

                # Auto-block beyond grace -- fall through to judge (6i).
                # The queen's runtime AgentSpec sets skip_judge=True in
                # queen_orchestrator.py, so the judge short-circuits to
                # RETRY (no feedback) and the loop continues cleanly.

            # 6h''. Worker wait for queen guidance
            # When a worker escalates, pause here and skip judge evaluation
            # until the queen injects guidance.
            if queen_input_requested:
                if self._shutdown:
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    self._log_skip_judge(
                        ctx,
                        node_id,
                        iteration,
                        "Shutdown signaled (waiting for queen input)",
                        logged_tool_calls,
                        assistant_text,
                        turn_tokens,
                        iter_start,
                    )
                    if ctx.runtime_logger:
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
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
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                logger.info("[%s] iter=%d: waiting for queen input...", node_id, iteration)
                pending_input_state = {
                    "prompt": "",
                    "options": None,
                    "questions": None,
                    "emit_client_request": False,
                }
                await self._write_cursor(
                    ctx,
                    conversation,
                    accumulator,
                    iteration,
                    recent_responses=recent_responses,
                    recent_tool_fingerprints=recent_tool_fingerprints,
                    pending_input=pending_input_state,
                )
                got_input = await self._await_user_input(ctx, emit_client_request=False)
                logger.info(
                    "[%s] iter=%d: queen wait unblocked, got_input=%s",
                    node_id,
                    iteration,
                    got_input,
                )
                if not got_input:
                    # Blocked by missing user input - emit escalation before returning
                    if self._event_bus:
                        await self._event_bus.emit_escalation_requested(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason="Blocked waiting for queen guidance - no input received",
                            context=("Worker escalated but received no queen guidance before shutdown"),
                            execution_id=execution_id,
                            request_id=uuid.uuid4().hex,
                        )
                    await self._publish_loop_completed(stream_id, node_id, iteration + 1, execution_id)
                    latency_ms = int((time.time() - start_time) * 1000)
                    _continue_count += 1
                    self._log_skip_judge(
                        ctx,
                        node_id,
                        iteration,
                        "No queen input received (shutdown during wait)",
                        logged_tool_calls,
                        assistant_text,
                        turn_tokens,
                        iter_start,
                    )
                    if ctx.runtime_logger:
                        ctx.runtime_logger.log_node_complete(
                            node_id=node_id,
                            node_name=ctx.agent_spec.name,
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
                    return AgentResult(
                        success=True,
                        output=accumulator.to_dict(),
                        tokens_used=total_input_tokens + total_output_tokens,
                        latency_ms=latency_ms,
                        conversation=None,
                    )

                if self._injection_queue.empty() and self._trigger_queue.empty():
                    logger.info(
                        "[%s] iter=%d: queen-input wait woke without queued guidance; re-waiting",
                        node_id,
                        iteration,
                    )
                    continue

                pending_input_state = None

                recent_responses.clear()
                _cf_text_only_streak = 0
                _worker_text_only_streak = 0
                _continue_count += 1
                self._log_skip_judge(
                    ctx,
                    node_id,
                    iteration,
                    "Blocked for queen input (skip judge)",
                    logged_tool_calls,
                    assistant_text,
                    turn_tokens,
                    iter_start,
                )
                continue

            # 6i. Judge evaluation
            should_judge = (
                False
                or (iteration + 1) % self._config.judge_every_n_turns == 0
                or not real_tool_results  # no real tool calls = natural stop
            )

            logger.info("[%s] iter=%d: 6i should_judge=%s", node_id, iteration, should_judge)
            if not should_judge:
                # Gap C: unjudged iteration — log as CONTINUE
                _continue_count += 1
                self._log_skip_judge(
                    ctx,
                    node_id,
                    iteration,
                    "Unjudged (judge_every_n_turns skip)",
                    logged_tool_calls,
                    assistant_text,
                    turn_tokens,
                    iter_start,
                )
                continue

            # Judge evaluation (should_judge is always True here)
            verdict = await self._judge_turn(
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
                    accumulator, ctx.agent_spec.output_keys, ctx.agent_spec.nullable_output_keys
                )
                if missing and self._judge is not None:
                    hint = (
                        f"Task incomplete. Required outputs not yet produced: {missing}. "
                        f"Follow your system prompt instructions to complete the work."
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
                # Write outputs to data buffer
                for key, value in accumulator.to_dict().items():
                    ctx.input_data[key] = value

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
                        verdict_feedback=verdict.feedback or "",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
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
                return AgentResult(
                    success=True,
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
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
                        verdict_feedback=verdict.feedback or "",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                    ctx.runtime_logger.log_node_complete(
                        node_id=node_id,
                        node_name=ctx.agent_spec.name,
                        node_type="event_loop",
                        success=False,
                        error=f"Judge escalated: {verdict.feedback or 'no feedback'}",
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
                return AgentResult(
                    success=False,
                    error=f"Judge escalated: {verdict.feedback or 'no feedback'}",
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=None,
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
                        verdict_feedback=verdict.feedback or "",
                        tool_calls=logged_tool_calls,
                        llm_text=assistant_text,
                        input_tokens=turn_tokens.get("input", 0),
                        output_tokens=turn_tokens.get("output", 0),
                        latency_ms=iter_latency_ms,
                    )
                if verdict.feedback is not None:
                    fb = verdict.feedback or "[Judge returned RETRY without feedback]"
                    await conversation.add_user_message(f"[Judge feedback]: {fb}")
                continue

        # 7. Max iterations exhausted
        await self._publish_loop_completed(stream_id, node_id, self._config.max_iterations, execution_id)
        latency_ms = int((time.time() - start_time) * 1000)
        if ctx.runtime_logger:
            ctx.runtime_logger.log_node_complete(
                node_id=node_id,
                node_name=ctx.agent_spec.name,
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
        return self._finalize_result(
            AgentResult(
                success=False,
                error=(f"Max iterations ({self._config.max_iterations}) reached without acceptance"),
                output=accumulator.to_dict(),
                tokens_used=total_input_tokens + total_output_tokens,
                latency_ms=latency_ms,
                conversation=None,
            ),
            "max_iterations",
        )

    async def inject_event(
        self,
        content: str,
        *,
        is_client_input: bool = False,
        image_content: list[dict[str, Any]] | None = None,
    ) -> None:
        """Inject an external event or user input into the running loop.

        The content becomes a user message prepended to the next iteration.
        Thread-safe via asyncio.Queue.
        Always unblocks _await_user_input() so the node processes the
        message promptly — both real user input and external events
        (e.g. worker ask_user forwarded via queenContext) need to wake
        the node.

        Args:
            content: The message text.
            is_client_input: True when the message originates from a real
                human user (e.g. /chat endpoint), False for external events
                (e.g. worker question forwarded by the frontend).  Controls
                message formatting in _drain_injection_queue, not wake behavior.
            image_content: Optional list of OpenAI-style image blocks to attach.
        """
        logger.debug(
            "[AgentLoop.inject_event] content_len=%d, is_client_input=%s, has_images=%s, queue_size_before=%d",
            len(content) if content else 0,
            is_client_input,
            bool(image_content),
            self._injection_queue.qsize() if hasattr(self._injection_queue, "qsize") else -1,
        )
        try:
            await self._injection_queue.put((content, is_client_input, image_content))
            logger.debug("[AgentLoop.inject_event] Message queued successfully")
        except Exception as e:
            logger.exception("[AgentLoop.inject_event] Failed to queue message: %s", e)
            raise
        try:
            self._input_ready.set()
            logger.debug("[AgentLoop.inject_event] _input_ready.set() called")
        except Exception as e:
            logger.exception("[AgentLoop.inject_event] Failed to set _input_ready: %s", e)
            raise

    async def inject_trigger(self, trigger: TriggerEvent) -> None:
        """Inject a framework-level trigger into the running queen loop.

        Triggers are queued separately from user messages and drained
        atomically via _drain_trigger_queue().
        """
        await self._trigger_queue.put(trigger)
        self._input_ready.set()

    def signal_shutdown(self) -> None:
        """Signal the node to exit its loop cleanly.

        Unblocks any pending _await_user_input() call and causes
        the loop to exit on the next check.
        """
        self._shutdown = True
        self._input_ready.set()

    def cancel_current_turn(self) -> None:
        """Cancel the current LLM streaming turn or in-progress tool calls instantly.

        Unlike signal_shutdown() which permanently stops the event loop,
        this only kills the in-progress HTTP stream or tool gather task.
        The queen stays alive for the next user message.
        """
        if self._stream_task and not self._stream_task.done():
            self._stream_task.cancel()
        if self._tool_task and not self._tool_task.done():
            self._tool_task.cancel()

    async def _await_user_input(
        self,
        ctx: AgentContext,
        *,
        questions: list[dict] | None = None,
        emit_client_request: bool = True,
    ) -> bool:
        """Block until user input arrives or shutdown is signaled.

        Called in two situations:
        - The LLM explicitly calls ask_user().
        - Auto-block: any text-only turn (no real tools, no set_output)
          from the queen node — ensures the user sees and responds
          before the judge runs.

        Args:
            questions: Optional list of question dicts from ask_user. Each
                dict has id, prompt, and optional options. Passed through to
                the CLIENT_INPUT_REQUESTED event so the frontend can render
                the appropriate widget (QuestionWidget for one, else
                MultiQuestionWidget).
            emit_client_request: When False, wait silently without publishing
                CLIENT_INPUT_REQUESTED. Used for worker waits where input is
                expected from the queen via inject_message().

        Returns True if input arrived, False if shutdown was signaled.
        """
        # If messages or triggers arrived while the LLM was processing, skip
        # blocking — the next drain pass will pick them up.
        if not self._injection_queue.empty() or not self._trigger_queue.empty():
            return True

        # Clear BEFORE emitting so that synchronous handlers (e.g. the
        # headless stdin handler) can call inject_event() during the emit
        # and the signal won't be lost.  TUI handlers return immediately
        # without injecting, so the wait still blocks until the user types.
        self._input_ready.clear()

        # Close the lost-wakeup window: a message can arrive between the
        # pre-check above and the clear() we just did. Re-check the queues
        # after clearing; if anything snuck in, skip the wait entirely.
        # Same after emit (sync handlers may inject during the emit).
        if not self._injection_queue.empty() or not self._trigger_queue.empty():
            return True

        if emit_client_request and self._event_bus:
            await self._event_bus.emit_client_input_requested(
                stream_id=ctx.stream_id or ctx.agent_id,
                node_id=ctx.agent_id,
                execution_id=ctx.execution_id or "",
                questions=questions,
            )

        if not self._injection_queue.empty() or not self._trigger_queue.empty():
            return True

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
        ctx: AgentContext,
        conversation: NodeConversation,
        tools: list[Tool],
        iteration: int,
        accumulator: OutputAccumulator,
    ) -> tuple[
        str,
        list[dict],
        list[str],
        dict[str, int],
        list[dict],
        bool,
        bool,
        str,
        list[dict[str, Any]],
        bool,
    ]:
        """Run a single LLM turn with streaming and tool execution.

        Returns (assistant_text, real_tool_results, outputs_set, token_counts, logged_tool_calls,
        user_input_requested, queen_input_requested, system_prompt, messages, reported_to_parent).

        ``real_tool_results`` contains only results from actual tools (web_search,
        etc.), NOT from synthetic framework tools such as ``set_output``,
        ``ask_user``, or ``escalate``.
        ``outputs_set`` lists the output keys written via ``set_output`` during
        this turn.  ``user_input_requested`` is True if the LLM called
        ``ask_user`` during this turn.  This separation lets the caller treat
        synthetic tools as framework concerns rather than tool-execution concerns.
        ``queen_input_requested`` is True when the worker called
        ``escalate`` and should wait for queen guidance before judge
        evaluation.

        ``logged_tool_calls`` accumulates ALL tool calls across inner iterations
        (real tools, set_output, and discarded calls) for L3 logging.  Unlike
        ``real_tool_results`` which resets each inner iteration, this list grows
        across the entire turn.
        """
        stream_id = ctx.stream_id or ctx.agent_id
        node_id = ctx.agent_id
        execution_id = ctx.execution_id or ""
        token_counts: dict[str, int] = {"input": 0, "output": 0, "cached": 0}
        tool_call_count = 0
        final_text = ""
        final_system_prompt = conversation.system_prompt
        final_messages: list[dict[str, Any]] = []
        # Track output keys set via set_output across all inner iterations
        outputs_set_this_turn: list[str] = []
        user_input_requested = False
        queen_input_requested = False
        # Accumulate ALL tool calls across inner iterations for L3 logging.
        # Unlike real_tool_results (reset each inner iteration), this persists.
        logged_tool_calls: list[dict] = []
        # Counter for LLM calls within a single iteration.  Each pass through
        # the inner tool loop starts a fresh LLM stream whose snapshot resets
        # to "".  Without this, all calls share the same message ID on the
        # frontend and the second call's text silently replaces the first.
        inner_turn = 0
        logger.debug(
            "[_run_single_turn] node_id=%s, tools_count=%d, execution_id=%s",
            node_id,
            len(tools),
            execution_id,
        )

        # Continue-nudge counter: how many times we've re-streamed within this
        # _run_single_turn because the idle/TTFT watchdog fired. Caps to avoid
        # nudging forever when the endpoint is genuinely dead.
        _nudge_count_this_turn = 0

        # Inner tool loop: stream may produce tool calls requiring re-invocation
        while True:
            # Pre-send guard: if context is at or over budget, compact before
            # calling the LLM — prevents API context-length errors.
            if conversation.usage_ratio() >= 1.0:
                logger.warning(
                    "Pre-send guard: context at %.0f%% of budget, compacting",
                    conversation.usage_ratio() * 100,
                )
                await self._compact(ctx, conversation, accumulator)

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
            final_system_prompt = conversation.system_prompt
            final_messages = messages

            accumulated_text = ""
            tool_calls: list[ToolCallEvent] = []
            _stream_error: StreamErrorEvent | None = None

            # Gap 1 - Streaming tool execution. Any tool flagged as
            # concurrency_safe is kicked off the moment its ToolCallEvent
            # arrives in the stream, instead of waiting for the full
            # assistant message stop event. The dispatch phase below
            # reuses these already-running tasks so read_file / grep /
            # glob overlap with whatever text the model is still
            # generating. Unsafe tools (bash, edits, browser actions)
            # still wait for FinishEvent so we don't race a write
            # against a decision the model hasn't finished making.
            _early_safe_names = {t.name for t in tools if getattr(t, "concurrency_safe", False)}
            _early_tasks: dict[str, asyncio.Task] = {}

            async def _timed_execute(
                _tc: ToolCallEvent,
            ) -> tuple[ToolResult | BaseException, str, float]:
                """Execute a tool and return (result, start_iso, duration_s)."""
                _s = time.time()
                _iso = datetime.now(UTC).isoformat()
                try:
                    _r = await self._execute_tool(_tc)
                except BaseException as _exc:
                    _r = _exc
                _dur = round(time.time() - _s, 3)
                return _r, _iso, _dur

            logger.debug(
                "[_run_single_turn] inner_turn=%d: Starting LLM stream with %d messages, %d tools",
                inner_turn,
                len(messages),
                len(tools),
            )
            logger.debug(
                "[_run_single_turn] inner_turn=%d: request context node=%s roles=%s system_chars=%d max_tokens=%d",
                inner_turn,
                node_id,
                [m.get("role") for m in messages],
                len(conversation.system_prompt or ""),
                ctx.max_tokens,
            )
            if not messages:
                logger.warning(
                    "[_run_single_turn] inner_turn=%d: no non-system conversation messages "
                    "before LLM call for node=%s model=%s api_base=%s. "
                    "This will produce a system-only payload, which some providers reject.",
                    inner_turn,
                    node_id,
                    getattr(ctx.llm, "model", type(ctx.llm).__name__),
                    getattr(ctx.llm, "api_base", None),
                )

            # Stream LLM response in a child task so cancel_current_turn()
            # can kill it instantly without terminating the queen's main loop.
            # Capture loop-scoped variables as defaults to satisfy B023.
            # _stream_last_event_at is bumped on every event; the watchdog
            # below uses it to detect silently hung HTTP connections.
            _stream_start_at = time.monotonic()
            _stream_last_event_at = _stream_start_at
            # None until the first event arrives. Before first event, the
            # watchdog uses the (much looser) TTFT budget — large-context
            # local models legitimately take minutes to first token. Once
            # any event has been observed, tight inter-event idle applies.
            _first_event_at: float | None = None
            # Partial tool_calls accumulated so far, as OpenAI-format dicts
            # ready for persistence if the stream is cut short.
            _partial_tc_dicts: list[dict[str, Any]] = []

            async def _do_stream(
                _msgs: list = messages,  # noqa: B006
                _tc: list[ToolCallEvent] = tool_calls,  # noqa: B006
                inner_turn: int = inner_turn,
                _safe_names: set = _early_safe_names,  # noqa: B006,B008
                _tasks: dict = _early_tasks,  # noqa: B006,B008
                _exec_fn=_timed_execute,
                _partial_dicts: list[dict[str, Any]] = _partial_tc_dicts,  # noqa: B006,B008
            ) -> None:
                nonlocal accumulated_text, _stream_error, _stream_last_event_at
                nonlocal _first_event_at
                _clean_snapshot = ""  # visible-only text for the frontend

                async for event in ctx.llm.stream(
                    messages=_msgs,
                    system=conversation.system_prompt,
                    tools=tools if tools else None,
                    max_tokens=ctx.max_tokens,
                ):
                    _stream_last_event_at = time.monotonic()
                    if _first_event_at is None:
                        _first_event_at = _stream_last_event_at
                    if isinstance(event, TextDeltaEvent):
                        accumulated_text = event.snapshot
                        # Strip internal reasoning tags from the full
                        # snapshot, then diff against what we already
                        # emitted to get the new visible delta.
                        _new_clean = _strip_internal_tags_from_snapshot(event.snapshot)
                        if len(_new_clean) > len(_clean_snapshot):
                            _delta = _new_clean[len(_clean_snapshot) :]
                            _clean_snapshot = _new_clean
                            await self._publish_text_delta(
                                stream_id,
                                node_id,
                                _delta,
                                _clean_snapshot,
                                ctx,
                                execution_id,
                                iteration=iteration,
                                inner_turn=inner_turn,
                            )
                        # Checkpoint partial state so a watchdog cancel or
                        # crash doesn't discard whatever the model has
                        # produced so far. Cheap — one atomic file write.
                        try:
                            await conversation.checkpoint_partial_assistant(
                                accumulated_text,
                                _partial_dicts or None,
                            )
                        except Exception as _cp_err:  # noqa: BLE001
                            logger.debug(
                                "[_run_single_turn] partial checkpoint failed: %s",
                                _cp_err,
                            )

                    elif isinstance(event, ToolCallEvent):
                        _tc.append(event)
                        _partial_dicts.append(
                            {
                                "id": event.tool_use_id,
                                "type": "function",
                                "function": {
                                    "name": event.tool_name,
                                    "arguments": json.dumps(event.tool_input),
                                },
                            }
                        )
                        # Checkpoint now that a tool call has landed —
                        # this is the important one: if the stream dies
                        # right after a tool call but before FinishEvent,
                        # we still have the intent recorded.
                        try:
                            await conversation.checkpoint_partial_assistant(
                                accumulated_text,
                                _partial_dicts or None,
                            )
                        except Exception as _cp_err:  # noqa: BLE001
                            logger.debug(
                                "[_run_single_turn] partial checkpoint failed: %s",
                                _cp_err,
                            )
                        # Gap 1: start concurrency-safe tools immediately
                        # while the rest of the stream is still arriving,
                        # so read-heavy turns don't stall after the last
                        # text delta. Unsafe tools wait for FinishEvent.
                        if (
                            event.tool_name in _safe_names
                            and "_raw" not in event.tool_input
                            and event.tool_use_id not in _tasks
                        ):
                            _tasks[event.tool_use_id] = asyncio.create_task(_exec_fn(event))

                    elif isinstance(event, FinishEvent):
                        token_counts["input"] += event.input_tokens
                        token_counts["output"] += event.output_tokens
                        token_counts["cached"] += event.cached_tokens
                        token_counts["stop_reason"] = event.stop_reason
                        token_counts["model"] = event.model

                    elif isinstance(event, StreamErrorEvent):
                        if not event.recoverable:
                            raise RuntimeError(f"Stream error: {event.error}")
                        _stream_error = event
                        logger.warning("Recoverable stream error: %s", event.error)

            _llm_stream_t0 = time.monotonic()
            self._stream_task = asyncio.create_task(_do_stream())
            logger.debug("[_run_single_turn] inner_turn=%d: Stream task created, waiting...", inner_turn)

            # Watchdog budgets — see LoopConfig docstring for rationale.
            _ttft_limit = self._config.llm_stream_ttft_timeout_seconds
            _inter_event_limit = self._config.llm_stream_inter_event_idle_seconds
            # Back-compat: if the legacy inactivity knob was overridden to
            # a value below the new default, respect it as the inter-event
            # budget (historic behaviour) so existing configs don't regress.
            _legacy = self._config.llm_stream_inactivity_timeout_seconds
            if _legacy and _legacy > 0 and _legacy < _inter_event_limit:
                _inter_event_limit = _legacy
            _watchdog_active = (_ttft_limit and _ttft_limit > 0) or (_inter_event_limit and _inter_event_limit > 0)
            # Result of the watchdog: "ok" (stream finished), "ttft" (no first
            # event in budget), "inactive" (silence after first event).
            _watchdog_verdict: str = "ok"
            _watchdog_elapsed: float = 0.0
            _watchdog_limit: float = 0.0

            try:
                if _watchdog_active:
                    # Poll cheapest-valid interval: at most every 5s, at least
                    # half the tighter budget. Must use asyncio.wait (not
                    # wait_for) so "poll interval elapsed" and "task raised
                    # TimeoutError of its own" stay distinguishable.
                    _tight = min(
                        _ttft_limit or float("inf"),
                        _inter_event_limit or float("inf"),
                    )
                    _check_interval = max(1.0, min(5.0, _tight / 2))
                    while True:
                        done, _pending = await asyncio.wait({self._stream_task}, timeout=_check_interval)
                        if self._stream_task in done:
                            break
                        now = time.monotonic()
                        if _first_event_at is None:
                            # TTFT phase — stream open but silent. Use the
                            # looser budget; don't confuse slow models with
                            # dead connections.
                            elapsed = now - _stream_start_at
                            if _ttft_limit and _ttft_limit > 0 and elapsed >= _ttft_limit:
                                _watchdog_verdict = "ttft"
                                _watchdog_elapsed = elapsed
                                _watchdog_limit = _ttft_limit
                                break
                        else:
                            # Post-first-event silence. A stream that produced
                            # events and then went quiet is a real stall.
                            idle = now - _stream_last_event_at
                            if _inter_event_limit and _inter_event_limit > 0 and idle >= _inter_event_limit:
                                _watchdog_verdict = "inactive"
                                _watchdog_elapsed = idle
                                _watchdog_limit = _inter_event_limit
                                break
                        # Still active — keep polling.

                if _watchdog_verdict != "ok":
                    logger.warning(
                        "[_run_single_turn] inner_turn=%d: watchdog=%s %.0fs >= %.0fs — cancelling stream",
                        inner_turn,
                        _watchdog_verdict,
                        _watchdog_elapsed,
                        _watchdog_limit,
                    )
                    self._bump(f"stream_watchdog_{_watchdog_verdict}")
                    self._stream_task.cancel()
                    try:
                        await self._stream_task
                    except BaseException:
                        pass
                else:
                    # Re-raise any exception the stream task stored. When the
                    # watchdog loop exited via ``break`` the task is done, and
                    # ``await`` is the cheapest way to surface its exception.
                    await self._stream_task
                    logger.debug(
                        "[_run_single_turn] inner_turn=%d: Stream task completed normally",
                        inner_turn,
                    )
            except asyncio.CancelledError:
                logger.debug("[_run_single_turn] inner_turn=%d: Stream task cancelled", inner_turn)
                if accumulated_text or _partial_tc_dicts:
                    await conversation.add_assistant_message(
                        content=accumulated_text,
                        tool_calls=_partial_tc_dicts or None,
                        truncated=True,
                    )
                # Gap 1: kill any early-dispatched tool tasks too.
                # Without this, a safe tool started during streaming
                # would leak past cancellation and keep running.
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                # Distinguish cancel_current_turn() (cancels the child
                # _stream_task) from stop_worker (cancels the parent
                # execution task).  When the parent itself is cancelled,
                # cancelling() > 0 — propagate so the executor can save
                # state.  When only the child was cancelled, convert to
                # TurnCancelled so the event loop continues.
                task = asyncio.current_task()
                if task and task.cancelling() > 0:
                    raise
                raise TurnCancelled() from None
            except Exception as e:
                logger.exception("[_run_single_turn] inner_turn=%d: Stream task failed: %s", inner_turn, e)
                # Don't orphan early tool tasks on a stream failure
                # either - the outer retry loop will re-emit the tool
                # calls on the next attempt.
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                raise
            finally:
                self._stream_task = None

            # Continue-nudge recovery path. Runs AFTER the stream task is
            # cleaned up so all state is consistent. We persist whatever
            # partial text + tool-calls the model produced (as a truncated
            # message so the model can see its own in-flight work on the
            # next turn), cancel early tool tasks, append a terse
            # continuation hint, and restart the stream.
            if _watchdog_verdict != "ok":
                # Kill any safe-tool tasks the stream dispatched early —
                # their results would have had nowhere to land anyway
                # because the assistant message was incomplete.
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                # Promote whatever we captured into a real truncated
                # message. The partial checkpoint for this seq is cleared
                # automatically when add_assistant_message persists.
                if accumulated_text or _partial_tc_dicts:
                    await conversation.add_assistant_message(
                        content=accumulated_text,
                        tool_calls=_partial_tc_dicts or None,
                        truncated=True,
                    )

                reason_label = (
                    "no tokens before TTFT budget"
                    if _watchdog_verdict == "ttft"
                    else "stream went silent after producing events"
                )
                if self._event_bus:
                    if _watchdog_verdict == "ttft":
                        await self._event_bus.emit_stream_ttft_exceeded(
                            stream_id=stream_id,
                            node_id=node_id,
                            ttft_seconds=_watchdog_elapsed,
                            limit_seconds=_watchdog_limit,
                            execution_id=execution_id,
                        )
                    else:
                        await self._event_bus.emit_stream_inactive(
                            stream_id=stream_id,
                            node_id=node_id,
                            idle_seconds=_watchdog_elapsed,
                            limit_seconds=_watchdog_limit,
                            execution_id=execution_id,
                        )

                nudge_enabled = self._config.continue_nudge_enabled
                nudge_cap = self._config.continue_nudge_max_per_turn
                if nudge_enabled and _nudge_count_this_turn < nudge_cap:
                    _nudge_count_this_turn += 1
                    nudge_msg = (
                        f"[System: the previous stream stalled ({reason_label}, "
                        f"{_watchdog_elapsed:.0f}s). Continue from the last tool "
                        "result already in this conversation. Do NOT repeat tool "
                        "calls whose results are visible above — reuse them and "
                        "move to the next step.]"
                    )
                    await conversation.add_user_message(
                        nudge_msg,
                        is_system_nudge=True,
                    )
                    if self._event_bus:
                        await self._event_bus.emit_stream_nudge_sent(
                            stream_id=stream_id,
                            node_id=node_id,
                            reason=_watchdog_verdict,
                            nudge_count=_nudge_count_this_turn,
                            execution_id=execution_id,
                        )
                    logger.info(
                        "[%s] continue-nudge sent (count=%d/%d, reason=%s)",
                        node_id,
                        _nudge_count_this_turn,
                        nudge_cap,
                        _watchdog_verdict,
                    )
                    # Reset the outer _turn_t0 timer so the "LLM done in
                    # Xms" log line reflects real work not the nudge cycle.
                    _llm_stream_ms = int((time.monotonic() - _llm_stream_t0) * 1000)
                    logger.debug(
                        "[_run_single_turn] inner_turn=%d: nudge restart after %dms",
                        inner_turn,
                        _llm_stream_ms,
                    )
                    continue  # restart the inner loop, re-fetches messages
                # Nudge disabled or cap exhausted — fall back to the
                # existing retry path so a truly dead endpoint eventually
                # surfaces as an error.
                raise ConnectionError(
                    f"LLM stream {_watchdog_verdict} for {_watchdog_elapsed:.0f}s "
                    f"(limit {_watchdog_limit:.0f}s) — nudge cap reached"
                )

            _llm_stream_ms = int((time.monotonic() - _llm_stream_t0) * 1000)

            # If a recoverable stream error produced an empty response,
            # raise so the outer transient-error retry can handle it
            # with proper backoff instead of burning judge iterations.
            if _stream_error and not accumulated_text and not tool_calls:
                for _early in _early_tasks.values():
                    if not _early.done():
                        _early.cancel()
                raise ConnectionError(f"Stream failed with recoverable error: {_stream_error.error}")

            final_text = accumulated_text
            logger.info(
                "[%s] LLM response (%dms): text=%r tool_calls=%s stop=%s model=%s",
                node_id,
                _llm_stream_ms,
                accumulated_text[:300] if accumulated_text else "(empty)",
                [tc.tool_name for tc in tool_calls] if tool_calls else "[]",
                token_counts.get("stop_reason", "?"),
                token_counts.get("model", "?"),
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
            # Skip storing empty turns — no content, no tool calls.
            # An empty assistant message (e.g. Codex returning nothing after
            # a tool result) confuses some models on the next turn and causes
            # cascading empty-stream failures.
            if accumulated_text or tc_dicts:
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
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # Priority drain: if user sent a message while the LLM was
            # streaming, inject it into the conversation NOW -- before tool
            # execution.  The LLM will see it on the next inner turn.
            if not self._injection_queue.empty():
                while not self._injection_queue.empty():
                    _inj_content, _inj_client, _inj_images = self._injection_queue.get_nowait()
                    if _inj_client:
                        await conversation.add_user_message(_inj_content)
                        logger.info(
                            "[%s] Priority-injected user message mid-turn (%d chars)",
                            node_id,
                            len(_inj_content),
                        )
                    else:
                        await conversation.add_user_message(_inj_content)

            # Execute tool calls -- framework tools (set_output, ask_user)
            # run inline; real MCP tools run in parallel.
            real_tool_results: list[dict] = []
            limit_hit = False
            executed_in_batch = 0
            # hard_limit <= 0 disables the per-turn cap entirely. Some
            # models routinely emit 50+ tool calls per turn during wide
            # fan-out scenarios (browser exploration, bulk code reads);
            # capping them strands work mid-turn and the next turn just
            # re-emits the discarded calls, which is strictly worse.
            if self._config.max_tool_calls_per_turn > 0:
                hard_limit = int(self._config.max_tool_calls_per_turn * (1 + self._config.tool_call_overflow_margin))
            else:
                hard_limit = 0  # disabled

            # Phase 1: triage — handle framework tools immediately,
            # queue real tools for parallel execution.
            results_by_id: dict[str, ToolResult] = {}
            timing_by_id: dict[str, dict[str, Any]] = {}  # tool_use_id -> {start_timestamp, duration_s}
            pending_real: list[ToolCallEvent] = []
            # Replay detector: per-turn map from tool_use_id -> steer prefix.
            # Populated below when we detect that the model is re-emitting a
            # tool call whose (name + canonical args) matches a prior success.
            # Applied to the stored tool result content so the model sees the
            # nudge on its next turn without losing the real execution output.
            replay_prefixes_by_id: dict[str, str] = {}

            for tc in tool_calls:
                tool_call_count += 1
                if hard_limit > 0 and tool_call_count > hard_limit:
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
                    # set_output is no longer supported — inform the agent
                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="set_output is no longer available. Report your results via conversation instead.",
                        is_error=True,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "ask_user":
                    # --- Framework-level ask_user handling ---
                    # The consolidated tool always takes a `questions`
                    # array (1-8 entries). A single-entry array is the
                    # common case; longer arrays batch several questions
                    # into one turn so the user answers them all at once.
                    from framework.agent_loop.internals.synthetic_tools import (
                        sanitize_ask_user_inputs,
                    )

                    raw_questions = tc.tool_input.get("questions", None)
                    if not isinstance(raw_questions, list) or not raw_questions:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: ask_user requires a non-empty "
                                "'questions' array. Each entry must have "
                                "{id, prompt, options?}. Example: "
                                '{"questions": [{"id": "q1", "prompt": '
                                '"What now?", "options": ["A", "B"]}]}'
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Normalize + self-heal each question entry. Some
                    # model families cram options inside the prompt as a
                    # pseudo-XML blob like "What now?</question>\n
                    # _OPTIONS: [\"A\", \"B\"]". sanitize_ask_user_inputs
                    # strips the tag and recovers the inline options.
                    questions: list[dict] = []
                    for i, q in enumerate(raw_questions):
                        if not isinstance(q, dict):
                            continue
                        qid = str(q.get("id", f"q{i + 1}"))
                        raw_prompt = q.get("prompt", q.get("question", ""))
                        raw_opts = q.get("options", None)
                        cleaned_prompt, recovered_opts = sanitize_ask_user_inputs(raw_prompt, raw_opts)
                        if recovered_opts is not None and raw_opts is None:
                            raw_opts = recovered_opts

                        opts: list[str] | None = None
                        if isinstance(raw_opts, list):
                            opts = [str(o) for o in raw_opts if o]
                        elif isinstance(raw_opts, str) and raw_opts.strip():
                            # Defensive: smaller models sometimes send a
                            # JSON-encoded string instead of an array.
                            try:
                                parsed = json.loads(raw_opts)
                                if isinstance(parsed, list):
                                    opts = [str(o) for o in parsed if o]
                            except (json.JSONDecodeError, TypeError):
                                pass
                        if opts is not None and len(opts) < 2:
                            opts = None  # fall back to free-text

                        questions.append(
                            {
                                "id": qid,
                                "prompt": cleaned_prompt,
                                **({"options": opts} if opts else {}),
                            }
                        )

                    if not questions:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: no valid question objects in "
                                "'questions'. Each entry must be an "
                                "object with 'id' and 'prompt'."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Workers MUST provide options on every question —
                    # free-text asks are queen-only.
                    if stream_id != "queen" and any("options" not in q for q in questions):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: options are required on every "
                                "question for worker nodes. Provide at "
                                "least 2 predefined choices in the "
                                "'options' array of each question."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    user_input_requested = True

                    # Single free-form question: stream the prompt as a
                    # chat message so the user sees it. Widget-rendered
                    # cases (single-with-options, multi) draw their own
                    # question text, so no text delta is needed.
                    if (
                        len(questions) == 1
                        and "options" not in questions[0]
                        and questions[0]["prompt"]
                        and ctx.emits_client_io
                    ):
                        _q_text = questions[0]["prompt"]
                        await self._publish_text_delta(
                            stream_id,
                            node_id,
                            content=_q_text,
                            snapshot=_q_text,
                            ctx=ctx,
                            execution_id=execution_id,
                            iteration=iteration,
                            inner_turn=inner_turn,
                        )

                    # Stash the normalized questions list for the
                    # blocking path (§1612) + event emission.
                    self._pending_questions = questions

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Waiting for user input...",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "escalate":
                    # --- Framework-level escalate handling ---
                    reason = str(tc.tool_input.get("reason", "")).strip()
                    context = str(tc.tool_input.get("context", "")).strip()

                    if stream_id in ("queen", "judge"):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: escalate is only available to worker nodes/sub-agents, not queen/judge streams."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    if self._event_bus is None:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=("ERROR: EventBus unavailable. Could not emit escalation request."),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    await self._event_bus.emit_escalation_requested(
                        stream_id=stream_id,
                        node_id=node_id,
                        reason=reason,
                        context=context,
                        execution_id=execution_id,
                        request_id=uuid.uuid4().hex,
                    )
                    queen_input_requested = True

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Escalation requested to queen; waiting for guidance.",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "report_to_parent":
                    # --- Framework-level report_to_parent handling ---
                    # Parallel workers call this to emit a structured
                    # SUBAGENT_REPORT and terminate cleanly. The worker
                    # owner (Worker instance) records the explicit report
                    # via ``record_explicit_report`` so Worker.run()'s
                    # terminal event emission picks it up.
                    if not (isinstance(stream_id, str) and stream_id.startswith("worker:")):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: report_to_parent is only available to "
                                "parallel workers (stream_id='worker:*'). "
                                "The overseer talks to the user directly."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    report_tc_input = dict(tc.tool_input)
                    report_tc_input["tool_use_id"] = tc.tool_use_id
                    result = handle_report_to_parent(report_tc_input)
                    results_by_id[tc.tool_use_id] = result

                    # Record on the owning Worker so its terminal event
                    # emission picks up the explicit report.
                    owner_worker = getattr(self, "_owner_worker", None)
                    if owner_worker is not None:
                        normalised = report_tc_input.get("_normalised", {})
                        owner_worker.record_explicit_report(
                            status=normalised.get("status", "success"),
                            summary=normalised.get("summary", ""),
                            data=normalised.get("data", {}),
                        )

                    # Terminate the loop cleanly after this turn. Set the
                    # same completion flag path that set_output used so
                    # the next iteration exits with success.
                    self._report_terminated = True

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
                        # Replay detector: flag re-executions of recent
                        # successful calls. We still run the tool (some
                        # are legitimately repeated, e.g. screenshots and
                        # read-only evaluates) but prepend a terse steer
                        # onto the stored result so the model sees the
                        # signal on its next turn.
                        if self._config.replay_detector_enabled:
                            prior = conversation.find_completed_tool_call(
                                tc.tool_name,
                                tc.tool_input,
                                within_last_turns=self._config.replay_detector_within_last_turns,
                            )
                            if prior is not None:
                                logger.warning(
                                    "[%s] replay detected: %s matches prior seq=%d — executing anyway",
                                    node_id,
                                    tc.tool_name,
                                    prior.seq,
                                )
                                self._bump("tool_call_replay_detected")
                                if self._event_bus:
                                    await self._event_bus.emit_tool_call_replay_detected(
                                        stream_id=stream_id,
                                        node_id=node_id,
                                        tool_name=tc.tool_name,
                                        prior_seq=prior.seq,
                                        execution_id=execution_id,
                                    )
                                replay_prefixes_by_id[tc.tool_use_id] = (
                                    f"[Replay detected: {tc.tool_name} matches "
                                    f"seq={prior.seq}. Result still produced below — "
                                    "consider whether the retry was necessary.]\n"
                                )
                        pending_real.append(tc)

            # Phase 2a: partition real tools by concurrency safety.
            # Read-only tools flagged concurrency_safe run in one parallel
            # batch (bounded by a semaphore). Everything else - shell, file
            # writes, browser actions, unknown MCP tools - runs serially
            # afterwards so we can't race an edit against a bash command
            # that touches the same path. Result ordering is preserved via
            # results_by_id below; the split only affects scheduling.
            # Reuses the same _early_safe_names set the stream used for
            # Gap 1 early dispatch, so "safe" means exactly the same
            # thing in both places.
            parallel_batch: list[ToolCallEvent] = []
            serial_batch: list[ToolCallEvent] = []
            for tc in pending_real:
                if tc.tool_name in _early_safe_names:
                    parallel_batch.append(tc)
                else:
                    serial_batch.append(tc)

            if pending_real:
                # Cap on concurrent read-only tool executions. Ten matches
                # Claude Code's StreamingToolExecutor default and keeps MCP
                # server load bounded on turns where the model issues a
                # big fan-out of reads.
                _PARALLEL_CAP = 10
                _parallel_sem = asyncio.Semaphore(_PARALLEL_CAP)

                async def _capped(
                    _tc: ToolCallEvent,
                    _sem: asyncio.Semaphore = _parallel_sem,  # noqa: B008,B023
                ) -> tuple[ToolResult | BaseException, str, float]:
                    async with _sem:
                        return await _timed_execute(_tc)

                timed_results_by_id: dict[str, tuple[ToolResult | BaseException, str, float] | BaseException] = {}

                async def _cancel_turn_with_stubs(
                    _pending: list[ToolCallEvent] = pending_real,  # noqa: B006,B008
                ) -> None:
                    """Populate [Tool call cancelled by user] stubs for
                    every pending tool so the conversation doesn't end
                    up with dangling tool_use blocks, then raise
                    TurnCancelled so the queen event loop continues
                    cleanly. Shared between the parallel and serial
                    phases because either can observe CancelledError.
                    """
                    for _tc in _pending:
                        await conversation.add_tool_result(
                            tool_use_id=_tc.tool_use_id,
                            content="[Tool call cancelled by user]",
                            is_error=True,
                        )
                        await self._publish_tool_completed(
                            stream_id,
                            node_id,
                            _tc.tool_use_id,
                            _tc.tool_name,
                            "[Tool call cancelled by user]",
                            is_error=True,
                            execution_id=execution_id,
                        )
                    raise TurnCancelled() from None

                # Phase 2b: resolve the concurrency-safe batch. Prefer
                # any early task already started during streaming (Gap
                # 1) so we don't accidentally execute the same tool
                # twice; for everything else, schedule via the semaphore-
                # capped wrapper as before.
                if parallel_batch:
                    _awaitables: list = []
                    for tc in parallel_batch:
                        early = _early_tasks.get(tc.tool_use_id)
                        if early is not None:
                            _awaitables.append(early)
                        else:
                            _awaitables.append(_capped(tc))
                    self._tool_task = asyncio.ensure_future(asyncio.gather(*_awaitables, return_exceptions=True))
                    try:
                        parallel_timed = await self._tool_task
                    finally:
                        self._tool_task = None
                    # gather(return_exceptions=True) captures CancelledError
                    # as a return value instead of propagating it.
                    # Distinguish cancel_current_turn() (cancels only
                    # _tool_task) from stop_worker (cancels the parent
                    # execution task). When the parent itself is
                    # cancelled, cancelling() > 0 — propagate so the
                    # executor can save state. Otherwise convert to
                    # TurnCancelled so the queen event loop continues,
                    # writing cancellation stubs for every pending tool
                    # first so the conversation has no dangling
                    # tool_use blocks.
                    for entry in parallel_timed:
                        if isinstance(entry, asyncio.CancelledError):
                            task = asyncio.current_task()
                            if task and task.cancelling() > 0:
                                raise entry
                            await _cancel_turn_with_stubs()
                    for tc, entry in zip(parallel_batch, parallel_timed, strict=True):
                        timed_results_by_id[tc.tool_use_id] = entry

                # Phase 2c: run unsafe tools sequentially. On a raised
                # exception, cancel the remaining siblings with a clear
                # error so the model sees the cascade instead of a silent
                # drop. A ToolResult with is_error=True is a normal return
                # (e.g. "file not found") and does NOT trip the cascade -
                # the model should see subsequent errors too.
                # CancelledError is handled separately via the shared
                # user-cancel helper above.
                _serial_cascade_broken = False
                for tc in serial_batch:
                    if _serial_cascade_broken:
                        timed_results_by_id[tc.tool_use_id] = (
                            ToolResult(
                                tool_use_id=tc.tool_use_id,
                                content=(
                                    "Cancelled: an earlier non-concurrent tool "
                                    "in this turn raised an exception. Re-issue "
                                    "this call once the previous error is resolved."
                                ),
                                is_error=True,
                            ),
                            datetime.now(UTC).isoformat(),
                            0.0,
                        )
                        continue

                    self._tool_task = asyncio.ensure_future(_timed_execute(tc))
                    try:
                        entry = await self._tool_task
                    finally:
                        self._tool_task = None

                    timed_results_by_id[tc.tool_use_id] = entry
                    raw_check = entry[0] if isinstance(entry, tuple) else entry
                    if isinstance(raw_check, asyncio.CancelledError):
                        task = asyncio.current_task()
                        if task and task.cancelling() > 0:
                            raise raw_check
                        await _cancel_turn_with_stubs()
                    elif isinstance(raw_check, BaseException):
                        _serial_cascade_broken = True

                # Phase 2d: reassemble results in original call order so
                # the rest of the loop sees no difference from the
                # pre-partition world.
                for tc in pending_real:
                    entry = timed_results_by_id[tc.tool_use_id]
                    if isinstance(entry, BaseException):
                        raw = entry
                        _start_iso = datetime.now(UTC).isoformat()
                        _dur_s = 0
                    else:
                        raw, _start_iso, _dur_s = entry
                    timing_by_id[tc.tool_use_id] = {
                        "start_timestamp": _start_iso,
                        "duration_s": _dur_s,
                    }
                    if isinstance(raw, BaseException):
                        result = _build_tool_error_result(tc, raw)
                    else:
                        result = raw
                    results_by_id[tc.tool_use_id] = await self._truncate_tool_result(result, tc.tool_name)

            # Phase 3: record results into conversation in original order,
            # build logged/real lists, and publish completed events.
            for tc in tool_calls[:executed_in_batch]:
                result = results_by_id.get(tc.tool_use_id)
                if result is None:
                    continue  # shouldn't happen

                # Build log entries for real tools (exclude synthetic tools)
                if tc.tool_name not in (
                    "ask_user",
                    "escalate",
                ):
                    tool_entry = {
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "tool_input": tc.tool_input,
                        "content": result.content,
                        "is_error": result.is_error,
                        **timing_by_id.get(tc.tool_use_id, {}),
                    }
                    real_tool_results.append(tool_entry)
                    logged_tool_calls.append(tool_entry)

                image_content = result.image_content
                if image_content and ctx.llm and not supports_image_tool_results(ctx.llm.model):
                    logger.info(
                        "Stripping image_content from tool result; model '%s' does not support images in tool results",
                        ctx.llm.model,
                    )
                    image_content = None

                # Apply replay-detector steer prefix if this call matched a
                # recent successful invocation. Only applies to non-error
                # results — an error already breaks the replay chain.
                stored_content = result.content
                if not result.is_error:
                    _prefix = replay_prefixes_by_id.get(tc.tool_use_id)
                    if _prefix:
                        stored_content = f"{_prefix}{stored_content or ''}"

                await conversation.add_tool_result(
                    tool_use_id=tc.tool_use_id,
                    content=stored_content,
                    is_error=result.is_error,
                    image_content=image_content,
                    is_skill_content=result.is_skill_content,
                )
                if tc.tool_name == "ask_user" and user_input_requested and not result.is_error:
                    # Defer tool_call_completed until after user responds
                    self._deferred_tool_complete = {
                        "stream_id": stream_id,
                        "node_id": node_id,
                        "tool_use_id": tc.tool_use_id,
                        "tool_name": tc.tool_name,
                        "content": result.content,
                        "is_error": result.is_error,
                        "execution_id": execution_id,
                    }
                else:
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
                protect = max(2000, self._config.max_context_tokens // 12)
                pruned = await conversation.prune_old_tool_results(
                    protect_tokens=protect,
                    min_prune_tokens=max(1000, protect // 3),
                )
                if pruned > 0:
                    logger.info(
                        "Post-limit pruning: cleared %d old tool results (budget: %d)",
                        pruned,
                        self._config.max_context_tokens,
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
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # --- Image eviction: strip old screenshot image_content ---
            # Screenshots from browser_screenshot are inlined as base64
            # data URLs in message.image_content. Each screenshot costs
            # ~250k tokens when the provider counts base64 as text
            # (gemini, most non-Anthropic providers). Four screenshots
            # in one conversation blew through gemini's 1M context in
            # session_20260415_104727_5c4ed7ff and caused garbage
            # output ("协日" as the final assistant text). We evict
            # aggressively after every tool batch — independent of the
            # char-based usage_ratio, which severely underestimates
            # image cost (counts each image as ~2000 tokens vs the
            # ~250k actually billed). Text metadata stays on the
            # evicted messages so the agent can still reason about
            # "I took a screenshot at step N".
            _max_imgs = self._config.max_retained_screenshots
            if _max_imgs >= 0:
                await conversation.evict_old_images(keep_latest=_max_imgs)

            # --- Mid-turn pruning: prevent context blowup within a single turn ---
            if conversation.usage_ratio() >= 0.6:
                protect = max(2000, self._config.max_context_tokens // 12)
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

            await self._publish_context_usage(ctx, conversation, "post_tool_results")

            # If the turn requested external input (ask_user or queen handoff),
            # return immediately so the outer loop can block before judge eval.
            if user_input_requested or queen_input_requested:
                return (
                    final_text,
                    real_tool_results,
                    outputs_set_this_turn,
                    token_counts,
                    logged_tool_calls,
                    user_input_requested,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    False,
                )

            # Tool calls processed -- loop back to stream with updated conversation
            inner_turn += 1

    # -------------------------------------------------------------------
    # Synthetic tools: set_output, ask_user, escalate
    # ask_user is used by queen
    # escalate is used by worker
    # -------------------------------------------------------------------

    def _build_ask_user_tool(self) -> Tool:
        """Build the synthetic ask_user tool. Delegates to synthetic_tools module."""
        return build_ask_user_tool()

    def _build_escalate_tool(self) -> Tool:
        """Build the synthetic escalate tool. Delegates to synthetic_tools module."""
        return build_escalate_tool()

    # -------------------------------------------------------------------
    # Judge evaluation
    # -------------------------------------------------------------------

    async def _judge_turn(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        assistant_text: str,
        tool_results: list[dict],
        iteration: int,
    ) -> JudgeVerdict:
        """Evaluate the current state, with retry + fallback.

        The judge makes its own LLM call, which can fail transiently
        (network blip, 429/529, stream stall). Without a safety net here
        a single hiccup in the judge would crash the whole loop — even
        though the work under evaluation was perfectly fine. We retry
        transient failures a few times, then fall back to ACCEPT so the
        loop keeps moving instead of dying on a judge outage.
        """
        max_attempts = max(1, self._config.max_stream_retries)
        for attempt in range(max_attempts):
            try:
                return await judge_turn(
                    mark_complete_flag=False,
                    judge=self._judge,
                    ctx=ctx,
                    conversation=conversation,
                    accumulator=accumulator,
                    assistant_text=assistant_text,
                    tool_results=tool_results,
                    iteration=iteration,
                    get_missing_output_keys_fn=self._get_missing_output_keys,
                    max_context_tokens=self._config.max_context_tokens,
                )
            except Exception as e:
                is_last = attempt == max_attempts - 1
                if not self._is_transient_error(e) or is_last:
                    if is_last and self._is_transient_error(e):
                        self._bump("judge_fallback_accept")
                        logger.error(
                            "[judge] iter=%d: transient failure persisted across %d attempts "
                            "(%s) — skipping judgment and accepting the turn to keep moving: %s",
                            iteration,
                            max_attempts,
                            type(e).__name__,
                            str(e)[:200],
                        )
                        return JudgeVerdict(
                            action="ACCEPT",
                            feedback=(
                                f"[judge unavailable after {max_attempts} attempts: "
                                f"{type(e).__name__}; accepting to avoid stalling the loop]"
                            ),
                        )
                    # Non-transient — re-raise so the caller sees it.
                    raise
                self._bump("judge_transient_retry")
                delay = min(
                    self._config.stream_retry_backoff_base * (2**attempt),
                    self._config.stream_retry_max_delay,
                )
                logger.warning(
                    "[judge] iter=%d: transient error (%s), retrying in %.1fs (%d/%d): %s",
                    iteration,
                    type(e).__name__,
                    delay,
                    attempt + 1,
                    max_attempts,
                    str(e)[:200],
                )
                await asyncio.sleep(delay)
        # Unreachable — the loop above always returns or raises.
        raise RuntimeError("_judge_turn retry loop exited unexpectedly")

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_tool_call_history(
        conversation: NodeConversation,
        max_entries: int = 30,
    ) -> str:
        """Build a compact tool call history from the conversation.

        Delegates to :func:`extract_tool_call_history` in conversation.py.
        """
        from framework.agent_loop.conversation import extract_tool_call_history

        return extract_tool_call_history(conversation.messages, max_entries=max_entries)

    def _build_initial_message(self, ctx: AgentContext) -> str:
        """Build the initial user message from input data and buffer.

        Includes ALL input_data (not just declared input_keys) so that
        upstream handoff data flows through regardless of key naming.
        Declared input_keys are also checked in data buffer as fallback.
        """
        parts = []
        seen: set[str] = set()
        # Include everything from input_data (flexible handoff)
        for key, value in ctx.input_data.items():
            if value is not None:
                parts.append(f"{key}: {value}")
                seen.add(key)
        # Fallback: check data buffer for declared input_keys not already covered
        for key in ctx.agent_spec.input_keys:
            if key not in seen:
                value = ctx.input_data.get(key)
                if value is not None:
                    parts.append(f"{key}: {value}")
        if ctx.goal_context:
            parts.append(f"\nGoal: {ctx.goal_context}")
        return "\n".join(parts) if parts else ""

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

    @staticmethod
    def _ngram_similarity(s1: str, s2: str, n: int = 2) -> float:
        """Jaccard similarity of n-gram sets. Delegates to stall_detector module."""
        return ngram_similarity(s1, s2, n)

    def _is_stalled(self, recent_responses: list[str]) -> bool:
        """Detect stall using n-gram similarity. Delegates to stall_detector module."""
        return is_stalled(
            recent_responses,
            self._config.stall_detection_threshold,
            self._config.stall_similarity_threshold,
        )

    @staticmethod
    def _is_transient_error(exc: BaseException) -> bool:
        """Classify whether an exception is transient. Delegates to tool_result_handler module."""
        return is_transient_error(exc)

    @staticmethod
    def _is_capacity_error(exc: BaseException) -> bool:
        """Detect provider-side capacity / rate-limit errors.

        These are the errors that typically resolve on their own if we
        just wait long enough — 429 rate limit, 529 overloaded, and the
        equivalent provider-specific flavours. We treat these differently
        from generic transient errors (network blips) and retry them
        persistently within a wall-clock budget instead of giving up
        after a fixed attempt count.
        """
        cls_name = type(exc).__name__.lower()
        if "ratelimit" in cls_name or "overloaded" in cls_name:
            return True
        try:
            from litellm.exceptions import RateLimitError, ServiceUnavailableError

            if isinstance(exc, (RateLimitError, ServiceUnavailableError)):
                return True
        except ImportError:
            pass
        error_str = str(exc).lower()
        keywords = (
            "429",
            "529",
            "rate limit",
            "rate_limit",
            "overloaded",
            "capacity",
            "too many requests",
            "service unavailable",
        )
        return any(kw in error_str for kw in keywords)

    @staticmethod
    def _fingerprint_tool_calls(
        tool_results: list[dict],
    ) -> list[tuple[str, str]]:
        """Create deterministic fingerprints. Delegates to stall_detector module."""
        return fingerprint_tool_calls(tool_results)

    def _is_tool_doom_loop(
        self,
        recent_tool_fingerprints: list[list[tuple[str, str]]],
    ) -> tuple[bool, str]:
        """Detect doom loop. Delegates to stall_detector module."""
        return is_tool_doom_loop(
            recent_tool_fingerprints=recent_tool_fingerprints,
            threshold=self._config.tool_doom_loop_threshold,
            enabled=self._config.tool_doom_loop_enabled,
        )

    async def _execute_tool(self, tc: ToolCallEvent) -> ToolResult:
        """Execute a tool call, handling both sync and async executors.

        Applies ``tool_call_timeout_seconds`` from LoopConfig to prevent
        hung MCP servers from blocking the event loop indefinitely.
        The initial executor call is offloaded to a thread pool so that
        sync executors (MCP STDIO tools that block on ``future.result()``)
        don't freeze the event loop.
        """
        result = await execute_tool(
            tool_executor=self._tool_executor,
            tc=tc,
            timeout=self._config.tool_call_timeout_seconds,
            skill_dirs=getattr(self, "_skill_dirs", []),
        )
        # Cheap post-hoc classification: the timeout handler in
        # execute_tool builds a canned error message we can recognise
        # here without threading a callback through. Good enough for
        # telemetry; the content format is stable framework-internal.
        if result.is_error and "timed out after" in (result.content or ""):
            self._bump("tool_call_timeout")
        elif result.is_error:
            self._bump("tool_error")
        return result

    def _next_spill_filename(self, tool_name: str) -> str:
        """Return a short, monotonic filename for a tool result spill."""
        self._spill_counter += 1
        # Shorten common tool name prefixes to save tokens
        short = tool_name.removeprefix("tool_").removeprefix("mcp_")
        return f"{short}_{self._spill_counter}.txt"

    def _restore_spill_counter(self) -> None:
        """Scan spillover_dir for existing spill files and restore the counter."""
        self._spill_counter = restore_spill_counter(
            spillover_dir=self._config.spillover_dir,
        )

    # ------------------------------------------------------------------
    # JSON metadata / smart preview helpers for truncation
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_json_metadata(parsed: Any, *, _depth: int = 0, _max_depth: int = 3) -> str:
        """Return a concise structural summary of parsed JSON.

        Reports key names, value types, and — crucially — array lengths so
        the LLM knows how much data exists beyond the preview.

        Returns an empty string for simple scalars.
        """
        return extract_json_metadata(
            parsed=parsed,
        )

    @staticmethod
    def _build_json_preview(parsed: Any, *, max_chars: int = 5000) -> str | None:
        """Build a smart preview of parsed JSON, truncating large arrays.

        Shows first 3 + last 1 items of large arrays with explicit count
        markers so the LLM cannot mistake the preview for the full dataset.

        Returns ``None`` if no truncation was needed (no large arrays).
        """
        return build_json_preview(
            parsed=parsed,
            max_chars=max_chars,
        )

    async def _truncate_tool_result(
        self,
        result: ToolResult,
        tool_name: str,
    ) -> ToolResult:
        """Persist tool result to file and optionally truncate for context.

        When *spillover_dir* is configured, EVERY non-error tool result is
        saved to a file (short filename like ``web_search_1.txt``).  A
        ``[Saved to '...']`` annotation is appended so the reference
        survives pruning and compaction.

        - Small results (≤ limit): full content kept + file annotation
        - Large results (> limit): preview + file reference
        - Errors: pass through unchanged
        - read_file results: truncate with pagination hint (no re-spill)

        For large results this does a synchronous JSON round-trip
        (``json.loads`` + pretty-print ``json.dumps(indent=2)``) plus a
        file write. On big payloads — web_search, web_fetch, full-page
        extractions — this can block the event loop for hundreds of ms
        per call. We offload to a worker thread so concurrent tool
        executions keep running while one large result is being
        pretty-printed and spilled to disk.
        """
        # Fast path: small results don't need thread offload. The
        # function only touches disk / does heavy JSON work when the
        # result exceeds either the truncation or spillover threshold,
        # so cheap pass-throughs stay on the main loop.
        needs_offload = len(result.content) > 10_000 and not result.is_error
        if not needs_offload:
            return truncate_tool_result(
                result=result,
                tool_name=tool_name,
                max_tool_result_chars=self._config.max_tool_result_chars,
                spillover_dir=self._config.spillover_dir,
                next_spill_filename_fn=self._next_spill_filename,
            )
        return await asyncio.to_thread(
            truncate_tool_result,
            result=result,
            tool_name=tool_name,
            max_tool_result_chars=self._config.max_tool_result_chars,
            spillover_dir=self._config.spillover_dir,
            next_spill_filename_fn=self._next_spill_filename,
        )

    # --- Compaction -----------------------------------------------------------

    # Max chars of formatted messages before proactively splitting for LLM.
    _LLM_COMPACT_CHAR_LIMIT = 240_000
    # Max recursion depth for binary-search splitting.
    _LLM_COMPACT_MAX_DEPTH = 10

    async def _compact(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator | None = None,
    ) -> None:
        """Compact conversation history to stay within token budget.

        1. Prune old tool results (always, free).
        2. Structure-preserving compaction (standard, free) — removes freeform text
           to spillover files, retains tool-call structure.
        3. LLM summary compaction — generates a summary and places it as the first
           message, replacing old messages. Used whenever structural compaction
           does not fully resolve the budget.
        4. Emergency deterministic summary only if LLM failed or unavailable.
        """
        return await compact(
            ctx=ctx,
            conversation=conversation,
            accumulator=accumulator,
            config=self._config,
            event_bus=self._event_bus,
            char_limit=self._LLM_COMPACT_CHAR_LIMIT,
            max_depth=self._LLM_COMPACT_MAX_DEPTH,
        )

    # --- LLM compaction with binary-search splitting ----------------------

    async def _llm_compact(
        self,
        ctx: AgentContext,
        messages: list,
        accumulator: OutputAccumulator | None = None,
        _depth: int = 0,
    ) -> str:
        """Summarise *messages* with LLM, splitting recursively if too large.

        If the formatted text exceeds ``_LLM_COMPACT_CHAR_LIMIT`` or the LLM
        rejects the call with a context-length error, the messages are split
        in half and each half is summarised independently.  Tool history is
        appended once at the top-level call (``_depth == 0``).
        """
        return await llm_compact(
            ctx=ctx,
            messages=messages,
            accumulator=accumulator,
            _depth=_depth,
            char_limit=self._LLM_COMPACT_CHAR_LIMIT,
            max_depth=self._LLM_COMPACT_MAX_DEPTH,
            max_context_tokens=self._config.max_context_tokens,
        )

    # --- Compaction helpers ------------------------------------------------

    @staticmethod
    def _format_messages_for_summary(messages: list) -> str:
        """Format messages as text for LLM summarisation."""
        return format_messages_for_summary(messages)

    def _build_llm_compaction_prompt(
        self,
        ctx: AgentContext,
        accumulator: OutputAccumulator | None,
        formatted_messages: str,
    ) -> str:
        """Build prompt for LLM compaction targeting 50% of token budget."""
        return build_llm_compaction_prompt(
            ctx,
            accumulator,
            formatted_messages,
            max_context_tokens=self._config.max_context_tokens,
        )

    def _build_emergency_summary(
        self,
        ctx: AgentContext,
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
        return build_emergency_summary(ctx, accumulator, conversation, self._config)

    # -------------------------------------------------------------------
    # Persistence: restore, cursor, injection, pause
    # -------------------------------------------------------------------

    async def _restore(
        self,
        ctx: AgentContext,
    ) -> RestoredState | None:
        """Attempt to restore from a previous checkpoint.

        Returns a ``RestoredState`` with conversation, accumulator, iteration
        counter, and stall/doom-loop detection state — everything needed to
        resume exactly where execution stopped.
        """
        return await restore(
            conversation_store=self._conversation_store,
            ctx=ctx,
            config=self._config,
        )

    async def _write_cursor(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        iteration: int,
        *,
        recent_responses: list[str] | None = None,
        recent_tool_fingerprints: list[list[tuple[str, str]]] | None = None,
        pending_input: dict[str, Any] | None = None,
    ) -> None:
        """Write checkpoint cursor for crash recovery.

        Persists iteration counter, accumulator outputs, and stall/doom-loop
        detection state so that resume picks up exactly where execution stopped.
        """
        return await write_cursor(
            conversation_store=self._conversation_store,
            ctx=ctx,
            conversation=conversation,
            accumulator=accumulator,
            iteration=iteration,
            recent_responses=recent_responses,
            recent_tool_fingerprints=recent_tool_fingerprints,
            pending_input=pending_input,
        )

    async def _drain_injection_queue(self, conversation: NodeConversation, ctx: AgentContext) -> int:
        """Drain all pending injected events as user messages. Returns count."""
        return await drain_injection_queue(
            queue=self._injection_queue,
            conversation=conversation,
            ctx=ctx,
            describe_images_as_text_fn=_describe_images_as_text,
        )

    async def _drain_trigger_queue(self, conversation: NodeConversation) -> int:
        """Drain all pending trigger events as a single batched user message.

        Multiple triggers are merged so the LLM sees them atomically and can
        reason about all pending triggers before acting.
        """
        return await drain_trigger_queue(
            queue=self._trigger_queue,
            conversation=conversation,
        )

    async def _check_pause(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        iteration: int,
    ) -> bool:
        """
        Check if pause has been requested. Returns True if paused.

        Note: This check happens BEFORE starting iteration N, after completing N-1.
        If paused, the node exits having completed {iteration} iterations (0 to iteration-1).
        """
        return await check_pause(
            ctx=ctx,
            conversation=conversation,
            iteration=iteration,
        )

    # -------------------------------------------------------------------
    # EventBus publishing helpers
    # -------------------------------------------------------------------

    async def _publish_loop_started(self, stream_id: str, node_id: str, execution_id: str = "") -> None:
        return await publish_loop_started(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            max_iterations=self._config.max_iterations,
            execution_id=execution_id,
        )

    async def _generate_action_plan(
        self,
        ctx: AgentContext,
        stream_id: str,
        node_id: str,
        execution_id: str,
    ) -> None:
        """Generate a brief action plan via LLM and emit it as an SSE event.

        Runs as a fire-and-forget task so it never blocks the main loop.
        """
        return await generate_action_plan(
            event_bus=self._event_bus,
            ctx=ctx,
            stream_id=stream_id,
            node_id=node_id,
            execution_id=execution_id,
        )

    async def _run_hooks(
        self,
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
        return await run_hooks(
            hooks_config=self._config.hooks,
            event=event,
            conversation=conversation,
            trigger=trigger,
        )

    async def _publish_context_usage(
        self,
        ctx: AgentContext,
        conversation: NodeConversation,
        trigger: str,
    ) -> None:
        """Emit a CONTEXT_USAGE_UPDATED event with current context window state."""
        return await publish_context_usage(
            event_bus=self._event_bus,
            ctx=ctx,
            conversation=conversation,
            trigger=trigger,
        )

    async def _publish_iteration(
        self,
        stream_id: str,
        node_id: str,
        iteration: int,
        execution_id: str = "",
        extra_data: dict | None = None,
    ) -> None:
        return await publish_iteration(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            iteration=iteration,
            execution_id=execution_id,
            extra_data=extra_data,
        )

    async def _publish_llm_turn_complete(
        self,
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
        return await publish_llm_turn_complete(
            event_bus=self._event_bus,
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

    def _log_skip_judge(
        self,
        ctx: AgentContext,
        node_id: str,
        iteration: int,
        feedback: str,
        tool_calls: list[dict],
        llm_text: str,
        turn_tokens: dict[str, int],
        iter_start: float,
    ) -> None:
        """Log a CONTINUE step that skips judge evaluation (e.g., waiting for input)."""
        return log_skip_judge(
            ctx=ctx,
            node_id=node_id,
            iteration=iteration,
            feedback=feedback,
            tool_calls=tool_calls,
            llm_text=llm_text,
            turn_tokens=turn_tokens,
            iter_start=iter_start,
        )

    async def _publish_loop_completed(
        self, stream_id: str, node_id: str, iterations: int, execution_id: str = ""
    ) -> None:
        return await publish_loop_completed(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            iterations=iterations,
            execution_id=execution_id,
        )

    async def _publish_stalled(self, stream_id: str, node_id: str, execution_id: str = "") -> None:
        return await publish_stalled(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            execution_id=execution_id,
        )

    async def _publish_text_delta(
        self,
        stream_id: str,
        node_id: str,
        content: str,
        snapshot: str,
        ctx: AgentContext,
        execution_id: str = "",
        iteration: int | None = None,
        inner_turn: int = 0,
    ) -> None:
        # Strip leading whitespace from first output chunk for client_facing nodes
        # (some LLMs like Kimi output leading whitespace before text)
        if ctx.agent_spec.client_facing and not snapshot and content:
            content = content.lstrip()
            if not content:  # Content was all whitespace
                return

        return await publish_text_delta(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            content=content,
            snapshot=snapshot,
            ctx=ctx,
            execution_id=execution_id,
            iteration=iteration,
            inner_turn=inner_turn,
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
        return await publish_tool_started(
            event_bus=self._event_bus,
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
        return await publish_tool_completed(
            event_bus=self._event_bus,
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
        return await publish_judge_verdict(
            event_bus=self._event_bus,
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
        return await publish_output_key_set(
            event_bus=self._event_bus,
            stream_id=stream_id,
            node_id=node_id,
            key=key,
            execution_id=execution_id,
        )

    # -------------------------------------------------------------------
    # Subagent Execution
    # -------------------------------------------------------------------
