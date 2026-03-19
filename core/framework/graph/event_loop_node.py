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
import re
import time

try:
    from litellm.exceptions import RateLimitError
except ImportError:
    class RateLimitError(Exception):
        pass
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
from framework.runtime.llm_debug_logger import log_llm_turn

logger = logging.getLogger(__name__)


@dataclass
class TriggerEvent:
    """A framework-level trigger signal (timer tick or webhook hit).

    Triggers are queued separately from user messages / external events
    and drained atomically so the LLM sees all pending triggers at once.
    """

    trigger_type: str  # "timer" | "webhook"
    source_id: str  # entry point ID or webhook route ID
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


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


# ---------------------------------------------------------------------------
# Escalation receiver (temporary routing target for subagent → user input)
# ---------------------------------------------------------------------------


class _EscalationReceiver:
    """Temporary receiver registered in node_registry for subagent escalation routing.

    When a subagent calls ``report_to_parent(wait_for_response=True)``, the callback
    creates one of these, registers it under a unique escalation ID in the executor's
    ``node_registry``, and awaits ``wait()``.  The TUI / runner calls
    ``inject_input(escalation_id, content)`` which the ``ExecutionStream`` routes here
    via ``inject_event()`` — matching the same ``hasattr(node, "inject_event")`` check
    used for regular ``EventLoopNode`` instances.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._response: str | None = None
        self._awaiting_input = True  # So inject_worker_message() can prefer us

    async def inject_event(self, content: str, *, is_client_input: bool = False) -> None:
        """Called by ExecutionStream.inject_input() when the user responds."""
        self._response = content
        self._event.set()

    async def wait(self) -> str | None:
        """Block until inject_event() delivers the user's response."""
        await self._event.wait()
        return self._response


# ---------------------------------------------------------------------------
# Judge protocol (simple 3-action interface for event loop evaluation)
# ---------------------------------------------------------------------------


class TurnCancelled(Exception):
    """Raised when a turn is cancelled mid-stream."""

    pass


@dataclass
class JudgeVerdict:
    """Result of judge evaluation for the event loop."""

    action: Literal["ACCEPT", "RETRY", "ESCALATE"]
    # None  = no evaluation happened (skip_judge, tool-continue); not logged.
    # ""    = evaluated but no feedback; logged with default text.
    # "..." = evaluated with feedback; logged as-is.
    feedback: str | None = None


@runtime_checkable
class JudgeProtocol(Protocol):
    """Protocol for event-loop judges.

    Implementations evaluate the current state of the event loop and
    decide whether to accept the output, retry with feedback, or escalate.
    """

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict: ...


class SubagentJudge:
    """Judge for subagent execution.

    Accepts immediately when all required output keys are filled,
    regardless of whether real tool calls were also made in the same turn.
    On RETRY, reminds the subagent of its specific task with progressive
    urgency based on remaining iterations.
    """

    def __init__(self, task: str, max_iterations: int = 10):
        self._task = task
        self._max_iterations = max_iterations

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict:
        missing = context.get("missing_keys", [])
        if not missing:
            return JudgeVerdict(action="ACCEPT", feedback="")

        iteration = context.get("iteration", 0)
        remaining = self._max_iterations - iteration - 1

        if remaining <= 3:
            urgency = (
                f"URGENT: Only {remaining} iterations left. "
                f"Stop all other work and call set_output NOW for: {missing}"
            )
        elif remaining <= self._max_iterations // 2:
            urgency = (
                f"WARNING: {remaining} iterations remaining. "
                f"You must call set_output for: {missing}"
            )
        else:
            urgency = f"Missing output keys: {missing}. Use set_output to provide them."

        return JudgeVerdict(action="RETRY", feedback=f"Your task: {self._task}\n{urgency}")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class LoopConfig:
    """Configuration for the event loop."""

    max_iterations: int = 50
    max_tool_calls_per_turn: int = 30
    judge_every_n_turns: int = 1
    stall_detection_threshold: int = 3
    stall_similarity_threshold: float = 0.85
    max_context_tokens: int = 32_000
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
    max_tool_result_chars: int = 30_000
    spillover_dir: str | None = None  # Path string; created on first use

    # --- set_output value spilling ---
    # When a set_output value exceeds this character count it is auto-saved
    # to a file in *spillover_dir* and the stored value is replaced with a
    # lightweight file reference.  This keeps shared memory / adapt.md /
    # transition markers small and forces the next node to load the full
    # data from the file.  Set to 0 to disable.
    max_output_value_chars: int = 2_000

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

    # --- Client-facing auto-block grace period ---
    # When a client-facing node produces text-only turns (no tools, no
    # set_output), the judge is skipped for this many consecutive auto-block
    # turns.  After the grace period, the judge runs to apply RETRY pressure
    # on models stuck in a clarification loop.  Explicit ask_user() calls
    # always skip the judge regardless of this setting.
    cf_grace_turns: int = 1
    tool_doom_loop_enabled: bool = True

    # --- Per-tool-call timeout ---
    # Maximum seconds a single tool call may take before being killed.
    # Prevents hung MCP servers (especially browser/GCU tools) from
    # blocking the entire event loop indefinitely.  0 = no timeout.
    tool_call_timeout_seconds: float = 60.0

    # --- Subagent delegation timeout ---
    # Maximum seconds a delegate_to_sub_agent call may run before being
    # killed.  Subagents run a full event-loop so they naturally take
    # longer than a single tool call — default is 10 minutes.  0 = no timeout.
    subagent_timeout_seconds: float = 600.0

    # --- Lifecycle hooks ---
    # Hooks are async callables keyed by event name.  Supported events:
    #   "session_start"    — fires once after the first user message is added,
    #                        before the first LLM turn.  trigger = initial message.
    #   "external_message" — fires when inject_notification() delivers a message.
    #                        trigger = injected message text.
    # Each hook receives a HookContext and may return a HookResult to patch
    # the system prompt and/or inject a follow-up user message.
    hooks: dict[str, list] = None  # dict[str, list[HookFn]]  (None → no hooks)

    def __post_init__(self) -> None:
        if self.hooks is None:
            object.__setattr__(self, "hooks", {})


# ---------------------------------------------------------------------------
# Hook types
# ---------------------------------------------------------------------------


@dataclass
class HookContext:
    """Context passed to every lifecycle hook."""

    event: str  # event name, e.g. "session_start"
    trigger: str | None  # message that triggered the hook, if any
    system_prompt: str  # current system prompt at hook invocation time


@dataclass
class HookResult:
    """What a hook may return to modify node state."""

    system_prompt: str | None = None  # replace current system prompt
    inject: str | None = None  # inject an additional user message


# ---------------------------------------------------------------------------
# Output accumulator with write-through persistence
# ---------------------------------------------------------------------------


@dataclass
class OutputAccumulator:
    """Accumulates output key-value pairs with optional write-through persistence.

    Values are stored in memory and optionally written through to a
    ConversationStore's cursor data for crash recovery.

    When *spillover_dir* and *max_value_chars* are set, large values are
    automatically saved to files and replaced with lightweight file
    references.  This guarantees auto-spill fires on **every** ``set()``
    call regardless of code path (resume, checkpoint restore, etc.).
    """

    values: dict[str, Any] = field(default_factory=dict)
    store: ConversationStore | None = None
    spillover_dir: str | None = None
    max_value_chars: int = 0  # 0 = disabled

    async def set(self, key: str, value: Any) -> None:
        """Set a key-value pair, auto-spilling large values to files.

        When the serialised value exceeds *max_value_chars*, the data is
        saved to ``<spillover_dir>/output_<key>.<ext>`` and *value* is
        replaced with a compact file-reference string.
        """
        value = self._auto_spill(key, value)
        self.values[key] = value
        if self.store:
            cursor = await self.store.read_cursor() or {}
            outputs = cursor.get("outputs", {})
            outputs[key] = value
            cursor["outputs"] = outputs
            await self.store.write_cursor(cursor)

    def _auto_spill(self, key: str, value: Any) -> Any:
        """Save large values to a file and return a reference string."""
        if self.max_value_chars <= 0 or not self.spillover_dir:
            return value

        val_str = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
        if len(val_str) <= self.max_value_chars:
            return value

        spill_path = Path(self.spillover_dir)
        spill_path.mkdir(parents=True, exist_ok=True)
        ext = ".json" if isinstance(value, (dict, list)) else ".txt"
        filename = f"output_{key}{ext}"
        write_content = (
            json.dumps(value, indent=2, ensure_ascii=False)
            if isinstance(value, (dict, list))
            else str(value)
        )
        (spill_path / filename).write_text(write_content, encoding="utf-8")
        file_size = (spill_path / filename).stat().st_size
        logger.info(
            "set_output value auto-spilled: key=%s, %d chars → %s (%d bytes)",
            key,
            len(val_str),
            filename,
            file_size,
        )
        return (
            f"[Saved to '{filename}' ({file_size:,} bytes). "
            f"Use load_data(filename='{filename}') "
            f"to access full data.]"
        )

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
        self._trigger_queue: asyncio.Queue[TriggerEvent] = asyncio.Queue()
        # Client-facing input blocking state
        self._input_ready = asyncio.Event()
        self._awaiting_input = False
        self._shutdown = False
        self._stream_task: asyncio.Task | None = None
        self._tool_task: asyncio.Task | None = None  # gather task while tools run
        # Track which nodes already have an action plan emitted (skip on revisit)
        self._action_plan_emitted: set[str] = set()
        # Monotonic counter for spillover file naming (web_search_1.txt, etc.)
        self._spill_counter: int = 0
        # Subagent mark_complete: when True, _evaluate returns ACCEPT immediately
        self._mark_complete_flag = False
        # Counter for subagent instances (1, 2, 3, ...)
        self._subagent_instance_counter: dict[str, int] = {}

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

        # Client-facing auto-block grace: consecutive text-only turns without
        # any real tool call or set_output.  Resets on progress.
        _cf_text_only_streak = 0

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
            accumulator = OutputAccumulator(
                store=self._conversation_store,
                spillover_dir=self._config.spillover_dir,
                max_value_chars=self._config.max_output_value_chars,
            )
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

                # Refresh the system prompt with full 3-layer composition.
                # The stored prompt may be stale after code changes or when
                # runtime-injected context (e.g. worker identity) has changed.
                # On resume, we rebuild identity + narrative + focus so the LLM
                # understands the session history, not just the node directive.
                from framework.graph.prompt_composer import compose_system_prompt

                _current_prompt = compose_system_prompt(
                    identity_prompt=ctx.identity_prompt or None,
                    focus_prompt=ctx.node_spec.system_prompt,
                    narrative=ctx.narrative or None,
                    accounts_prompt=ctx.accounts_prompt or None,
                    skills_catalog_prompt=ctx.skills_catalog_prompt or None,
                    protocols_prompt=ctx.protocols_prompt or None,
                )
                if conversation.system_prompt != _current_prompt:
                    conversation.update_system_prompt(_current_prompt)
                    logger.info("Refreshed system prompt for restored conversation")
            else:
                _restored_recent_responses = []
                _restored_tool_fingerprints = []

                # Fresh conversation: either isolated mode or first node in continuous mode.
                from framework.graph.prompt_composer import (
                    EXECUTION_SCOPE_PREAMBLE,
                    _with_datetime,
                )

                system_prompt = _with_datetime(ctx.node_spec.system_prompt or "")
                # Prepend execution-scope preamble for worker nodes so the
                # LLM knows it is one step in a pipeline and should not try
                # to perform work that belongs to other nodes.
                if (
                    not ctx.is_subagent_mode
                    and ctx.node_spec.node_type in ("event_loop", "gcu")
                    and ctx.node_spec.output_keys
                ):
                    system_prompt = f"{EXECUTION_SCOPE_PREAMBLE}\n\n{system_prompt}"
                # Prepend GCU browser best-practices prompt for gcu nodes
                if ctx.node_spec.node_type == "gcu":
                    from framework.graph.gcu import GCU_BROWSER_SYSTEM_PROMPT

                    system_prompt = f"{GCU_BROWSER_SYSTEM_PROMPT}\n\n{system_prompt}"
                # Append connected accounts info if available
                if ctx.accounts_prompt:
                    system_prompt = f"{system_prompt}\n\n{ctx.accounts_prompt}"

                # Append skill catalog and operational protocols
                if ctx.skills_catalog_prompt:
                    system_prompt = f"{system_prompt}\n\n{ctx.skills_catalog_prompt}"
                    logger.info(
                        "[%s] Injected skills catalog (%d chars)",
                        node_id,
                        len(ctx.skills_catalog_prompt),
                    )
                if ctx.protocols_prompt:
                    system_prompt = f"{system_prompt}\n\n{ctx.protocols_prompt}"
                    logger.info(
                        "[%s] Injected operational protocols (%d chars)",
                        node_id,
                        len(ctx.protocols_prompt),
                    )

                # Inject agent working memory (adapt.md).
                # If it doesn't exist yet, seed it with available context.
                if self._config.spillover_dir:
                    _adapt_path = Path(self._config.spillover_dir) / "adapt.md"
                    if not _adapt_path.exists():
                        _adapt_path.parent.mkdir(parents=True, exist_ok=True)
                        seed = (
                            f"## Identity\n{ctx.accounts_prompt}\n"
                            if ctx.accounts_prompt
                            else "# Session Working Memory\n"
                        )
                        _adapt_path.write_text(seed, encoding="utf-8")
                    if _adapt_path.exists():
                        _adapt_text = _adapt_path.read_text(encoding="utf-8").strip()
                        if _adapt_text:
                            system_prompt = (
                                f"{system_prompt}\n\n"
                                "--- Session Working Memory ---\n"
                                f"{_adapt_text}\n"
                                "--- End Session Working Memory ---\n\n"
                                "Maintain your session working memory by calling "
                                'save_data("adapt.md", ...) or edit_data("adapt.md", ...)'
                                " as you work.\n"
                                "This is session-scoped scratch space. "
                                "IMMEDIATELY save: account/identity rules, "
                                "behavioral constraints, and preferences specific to "
                                "this session. Also record current task state, "
                                "decisions, and working notes. "
                                "For lasting knowledge about the user, use "
                                "update_queen_memory() and append_queen_journal() instead."
                            )

                conversation = NodeConversation(
                    system_prompt=system_prompt,
                    max_context_tokens=self._config.max_context_tokens,
                    output_keys=ctx.node_spec.output_keys or None,
                    store=self._conversation_store,
                )
                # Stamp phase for first node in continuous mode
                if _is_continuous:
                    conversation.set_current_phase(ctx.node_id)
                accumulator = OutputAccumulator(
                    store=self._conversation_store,
                    spillover_dir=self._config.spillover_dir,
                    max_value_chars=self._config.max_output_value_chars,
                )
                start_iteration = 0

                # Add initial user message from input data
                initial_message = self._build_initial_message(ctx)
                if initial_message:
                    await conversation.add_user_message(initial_message)

                # Fire session_start hooks (e.g. persona selection)
                await self._run_hooks("session_start", conversation, trigger=initial_message)

        # 2a. Guard: ensure at least one non-system message exists.
        # A restored conversation may have 0 messages if phase_id filtering
        # removes them all, or if a prior run stored metadata without messages
        # (e.g. subagent that failed before the first LLM call).
        if conversation.message_count == 0:
            initial_message = self._build_initial_message(ctx)
            if initial_message:
                await conversation.add_user_message(initial_message)

        # 2b. Restore spill counter from existing files (resume safety)
        self._restore_spill_counter()

        # 3. Build tool list: node tools + synthetic framework tools + delegate tools
        tools = list(ctx.available_tools)
        set_output_tool = self._build_set_output_tool(ctx.node_spec.output_keys)
        if set_output_tool:
            tools.append(set_output_tool)
        if ctx.node_spec.client_facing and not ctx.event_triggered:
            tools.append(self._build_ask_user_tool())
            if stream_id == "queen":
                tools.append(self._build_ask_user_multiple_tool())
        # Workers/subagents can escalate blockers to the queen.
        if stream_id not in ("queen", "judge"):
            tools.append(self._build_escalate_tool())

        # Add delegate_to_sub_agent tool if:
        # - Node has sub_agents defined
        # - We are NOT in subagent mode (prevents nested delegation)
        if not ctx.is_subagent_mode:
            sub_agents = getattr(ctx.node_spec, "sub_agents", None) or []
            if sub_agents:
                delegate_tool = self._build_delegate_tool(sub_agents, ctx.node_registry)
                if delegate_tool:
                    tools.append(delegate_tool)
                    logger.info(
                        "[%s] delegate_to_sub_agent injected (sub_agents=%s)",
                        node_id,
                        sub_agents,
                    )
                else:
                    logger.error(
                        "[%s] _build_delegate_tool returned None for sub_agents=%s",
                        node_id,
                        sub_agents,
                    )
        else:
            logger.debug("[%s] Skipped delegate tool (is_subagent_mode=True)", node_id)

        # Add report_to_parent tool for sub-agents with a report callback
        if ctx.is_subagent_mode and ctx.report_callback is not None:
            tools.append(self._build_report_to_parent_tool())

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
        _consecutive_empty_turns: int = 0

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
            # 6b1. Drain trigger queue (framework-level signals)
            await self._drain_trigger_queue(conversation)

            # 6b2. Dynamic tool refresh (mode switching)
            if ctx.dynamic_tools_provider is not None:
                _synthetic_names = {
                    "set_output",
                    "ask_user",
                    "ask_user_multiple",
                    "escalate",
                    "delegate_to_sub_agent",
                    "report_to_parent",
                }
                synthetic = [t for t in tools if t.name in _synthetic_names]
                tools.clear()
                tools.extend(ctx.dynamic_tools_provider())
                tools.extend(synthetic)

            # 6b3. Dynamic prompt refresh (phase switching)
            if ctx.dynamic_prompt_provider is not None:
                from framework.graph.prompt_composer import _with_datetime

                _new_prompt = _with_datetime(ctx.dynamic_prompt_provider())
                if _new_prompt != conversation.system_prompt:
                    conversation.update_system_prompt(_new_prompt)
                    logger.info("[%s] Dynamic prompt updated (phase switch)", node_id)

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
            _stream_retry_count = 0
            _turn_cancelled = False
            _llm_turn_failed_waiting_input = False
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
                        ask_user_options,
                        queen_input_requested,
                        request_system_prompt,
                        request_messages,
                        reported_to_parent,
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
                    break  # success — exit retry loop

                except TurnCancelled:
                    _turn_cancelled = True
                    break

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
                    # For client-facing nodes, surface the error and wait
                    # for user input instead of killing the loop. The user
                    # can retry or adjust the request.
                    turn_tokens = {"input": 0, "output": 0}

                    if ctx.node_spec.client_facing:
                        if isinstance(e, RateLimitError):
                            error_msg = "Model rate limit reached"
                        else:
                            error_msg = f"LLM call failed: {str(e)}"

                        error_msg = f"LLM call failed: {e}"
                        _guardrail_phrase = (
                            "no endpoints available matching your guardrail restrictions "
                            "and data policy"
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
                            # Reviewer: do NOT emit execution_failed here
                            await self._event_bus.emit_node_retry(
                                stream_id=stream_id,
                                node_id=node_id,
                                retry_count=_stream_retry_count,
                                max_retries=self._config.max_stream_retries,
                                error=error_msg,
                                execution_id=execution_id,
                            )

                        await conversation.add_assistant_message(
                            f"[Error: {error_msg}. Please try again.]"
                        )
                        await self._await_user_input(ctx, prompt="")
                        break

                    # Non-client-facing path
                    if isinstance(e, RateLimitError):
                        if self._event_bus:
                            await self._event_bus.emit_node_retry(
                                stream_id=stream_id,
                                node_id=node_id,
                                retry_count=_stream_retry_count,
                                max_retries=self._config.max_stream_retries,
                                error="Model rate limit reached",
                                execution_id=execution_id,
                            )
                            await self._event_bus.emit_execution_failed(
                                stream_id=stream_id,
                                execution_id=execution_id,
                                error="Model rate limit reached",
                            )
                        _llm_turn_failed_waiting_input = True
                        break  # exit retry loop, continue outer iteration

                    # Logging and metrics MUST run before raising
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

                    raise

            if _turn_cancelled:
                logger.info("[%s] iter=%d: turn cancelled by user", node_id, iteration)
                if ctx.node_spec.client_facing and not ctx.event_triggered:
                    await self._await_user_input(ctx, prompt="")
                continue  # back to top of for-iteration loop

            # Client-facing non-transient LLM failures wait for user input and then
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
                and not reported_to_parent
            )
            if truly_empty and accumulator is not None:
                missing = self._get_missing_output_keys(
                    accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
                )
                # Only accept on empty response if the node actually has
                # output_keys that are all satisfied.  Nodes with NO
                # output_keys (e.g. the forever-alive queen) should never
                # be terminated by a ghost empty stream — "missing" is
                # trivially empty when there are no required outputs.
                has_real_outputs = bool(ctx.node_spec.output_keys)
                if not missing and has_real_outputs:
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
                                node_name=ctx.node_spec.name,
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
                        await self._await_user_input(ctx, prompt="")
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
                        f"Node stalled: {self._config.stall_detection_threshold} similar "
                        f"responses ({self._config.stall_similarity_threshold * 100:.0f}+"
                        " threshold)"
                    ),
                    output=accumulator.to_dict(),
                    tokens_used=total_input_tokens + total_output_tokens,
                    latency_ms=latency_ms,
                    conversation=conversation if _is_continuous else None,
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
                    "set_output",
                    "ask_user",
                    "ask_user_multiple",
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
                        ctx.node_spec.client_facing
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
                        )
                        await conversation.add_user_message(
                            "[SYSTEM] Escalated tool doom loop to queen for intervention."
                        )
                        recent_tool_fingerprints.clear()
                        recent_responses.clear()
                    elif ctx.node_spec.client_facing and not ctx.event_triggered:
                        await conversation.add_user_message(warning_msg)
                        await self._await_user_input(ctx, prompt=doom_desc)
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

            # 6h'. Client-facing input blocking
            #
            # Two triggers:
            # (a) Explicit ask_user() — blocks, then skips judge (6i).
            #     The LLM intentionally asked a question; judging before the
            #     user answers would inject confusing "missing outputs"
            #     feedback.  Works for all client-facing nodes.
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
            _cf_prompt = ""
            if ctx.node_spec.client_facing and not ctx.event_triggered:
                if user_input_requested:
                    _cf_block = True
                    _cf_prompt = ask_user_prompt
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
                            ctx.node_spec.output_keys,
                            ctx.node_spec.nullable_output_keys,
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
                                        "Auto-block grace"
                                        f" ({_cf_text_only_streak}"
                                        f"/{self._config.cf_grace_turns})"
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
                # Check for multi-question batch from ask_user_multiple
                multi_qs = getattr(self, "_pending_multi_questions", None)
                self._pending_multi_questions = None
                got_input = await self._await_user_input(
                    ctx,
                    prompt=_cf_prompt,
                    options=ask_user_options,
                    questions=multi_qs,
                )
                # Emit deferred tool_call_completed for ask_user / ask_user_multiple
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

                # -- Judge-skip decision after client-facing blocking --
                #
                # Explicit ask_user: skip judge while the agent is
                # still gathering information from the user.  BUT if
                # all required outputs have already been set, don't
                # skip -- fall through to the judge so it can accept.
                if not _cf_auto:
                    _missing = (
                        self._get_missing_output_keys(
                            accumulator,
                            ctx.node_spec.output_keys,
                            ctx.node_spec.nullable_output_keys,
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

                # Auto-block beyond grace -- fall through to judge (6i)

            # 6h''. Worker wait for queen guidance
            # When a worker escalates, pause here and skip judge evaluation
            # until the queen injects guidance.
            if queen_input_requested:
                if self._shutdown:
                    await self._publish_loop_completed(
                        stream_id, node_id, iteration + 1, execution_id
                    )
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

                logger.info("[%s] iter=%d: waiting for queen input...", node_id, iteration)
                got_input = await self._await_user_input(ctx, prompt="", emit_client_request=False)
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
                            context=(
                                "Worker escalated but received no queen guidance before shutdown"
                            ),
                            execution_id=execution_id,
                        )
                    await self._publish_loop_completed(
                        stream_id, node_id, iteration + 1, execution_id
                    )
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
                _cf_text_only_streak = 0
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
                ctx.is_subagent_mode  # Always evaluate subagents
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
                    accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
                )
                if missing and self._judge is not None and not self._mark_complete_flag:
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
                        verdict_feedback=verdict.feedback or "",
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
                        verdict_feedback=verdict.feedback or "",
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
                return NodeResult(
                    success=False,
                    error=f"Judge escalated: {verdict.feedback or 'no feedback'}",
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
        """
        await self._injection_queue.put((content, is_client_input))
        self._input_ready.set()

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
        ctx: NodeContext,
        prompt: str = "",
        *,
        options: list[str] | None = None,
        questions: list[dict] | None = None,
        emit_client_request: bool = True,
    ) -> bool:
        """Block until user input arrives or shutdown is signaled.

        Called in two situations:
        - The LLM explicitly calls ask_user().
        - Auto-block: any text-only turn (no real tools, no set_output)
          from a client-facing node — ensures the user sees and responds
          before the judge runs.

        Args:
            options: Optional predefined choices for the user (from ask_user).
                Passed through to the CLIENT_INPUT_REQUESTED event so the
                frontend can render a QuestionWidget with buttons.
            questions: Optional list of question dicts for ask_user_multiple.
                Each dict has id, prompt, and optional options.
            emit_client_request: When False, wait silently without publishing
                CLIENT_INPUT_REQUESTED. Used for worker waits where input is
                expected from the queen via inject_worker_message().

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

        if emit_client_request and self._event_bus:
            await self._event_bus.emit_client_input_requested(
                stream_id=ctx.stream_id or ctx.node_id,
                node_id=ctx.node_id,
                prompt=prompt,
                execution_id=ctx.execution_id or "",
                options=options,
                questions=questions,
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
    ) -> tuple[
        str,
        list[dict],
        list[str],
        dict[str, int],
        list[dict],
        bool,
        str,
        list[str] | None,
        bool,
        str,
        list[dict[str, Any]],
        bool,
    ]:
        """Run a single LLM turn with streaming and tool execution.

        Returns (assistant_text, real_tool_results, outputs_set, token_counts, logged_tool_calls,
        user_input_requested, ask_user_prompt, ask_user_options, queen_input_requested,
        system_prompt, messages, reported_to_parent).

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
        stream_id = ctx.stream_id or ctx.node_id
        node_id = ctx.node_id
        execution_id = ctx.execution_id or ""
        token_counts: dict[str, int] = {"input": 0, "output": 0, "cached": 0}
        tool_call_count = 0
        final_text = ""
        final_system_prompt = conversation.system_prompt
        final_messages: list[dict[str, Any]] = []
        # Track output keys set via set_output across all inner iterations
        outputs_set_this_turn: list[str] = []
        user_input_requested = False
        ask_user_prompt = ""
        ask_user_options: list[str] | None = None
        queen_input_requested = False
        reported_to_parent = False
        # Accumulate ALL tool calls across inner iterations for L3 logging.
        # Unlike real_tool_results (reset each inner iteration), this persists.
        logged_tool_calls: list[dict] = []
        # Counter for LLM calls within a single iteration.  Each pass through
        # the inner tool loop starts a fresh LLM stream whose snapshot resets
        # to "".  Without this, all calls share the same message ID on the
        # frontend and the second call's text silently replaces the first.
        inner_turn = 0

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

            # Stream LLM response in a child task so cancel_current_turn()
            # can kill it instantly without terminating the queen's main loop.
            # Capture loop-scoped variables as defaults to satisfy B023.
            async def _do_stream(
                _msgs: list = messages,  # noqa: B006
                _tc: list[ToolCallEvent] = tool_calls,  # noqa: B006
                inner_turn: int = inner_turn,
            ) -> None:
                nonlocal accumulated_text, _stream_error
                async for event in ctx.llm.stream(
                    messages=_msgs,
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
                            inner_turn=inner_turn,
                        )

                    elif isinstance(event, ToolCallEvent):
                        _tc.append(event)

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

            self._stream_task = asyncio.create_task(_do_stream())
            try:
                await self._stream_task
            except asyncio.CancelledError:
                if accumulated_text:
                    await conversation.add_assistant_message(content=accumulated_text)
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
            finally:
                self._stream_task = None

            # If a recoverable stream error produced an empty response,
            # raise so the outer transient-error retry can handle it
            # with proper backoff instead of burning judge iterations.
            if _stream_error and not accumulated_text and not tool_calls:
                raise ConnectionError(
                    f"Stream failed with recoverable error: {_stream_error.error}"
                )

            final_text = accumulated_text
            logger.info(
                "[%s] LLM response: text=%r tool_calls=%s stop=%s model=%s",
                node_id,
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
                    ask_user_prompt,
                    ask_user_options,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    reported_to_parent,
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
            # queue real tools and subagents for parallel execution.
            results_by_id: dict[str, ToolResult] = {}
            timing_by_id: dict[
                str, dict[str, Any]
            ] = {}  # tool_use_id -> {start_timestamp, duration_s}
            pending_real: list[ToolCallEvent] = []
            pending_subagent: list[ToolCallEvent] = []

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
                    _tc_start = time.time()
                    _tc_ts = datetime.now(UTC).isoformat()
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

                        # Auto-spill happens inside accumulator.set()
                        # — it fires on every code path (fresh, resume,
                        # restore) and prevents overwrite regression.
                        await accumulator.set(key, value)
                        stored = accumulator.get(key)
                        # If the accumulator spilled, update the tool
                        # result so the LLM knows data was saved to a file.
                        if isinstance(stored, str) and stored.startswith("[Saved to '"):
                            result = ToolResult(
                                tool_use_id=tc.tool_use_id,
                                content=(
                                    f"Output '{key}' auto-saved to file "
                                    f"(value was too large for inline). "
                                    f"{stored}"
                                ),
                                is_error=False,
                            )
                        self._record_learning(key, stored)
                        outputs_set_this_turn.append(key)
                        await self._publish_output_key_set(stream_id, node_id, key, execution_id)
                    logged_tool_calls.append(
                        {
                            "tool_use_id": tc.tool_use_id,
                            "tool_name": "set_output",
                            "tool_input": tc.tool_input,
                            "content": result.content,
                            "is_error": result.is_error,
                            "start_timestamp": _tc_ts,
                            "duration_s": round(time.time() - _tc_start, 3),
                        }
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "ask_user":
                    # --- Framework-level ask_user handling ---
                    ask_user_prompt = tc.tool_input.get("question", "")
                    raw_options = tc.tool_input.get("options", None)
                    # Defensive: ensure options is a list of strings.
                    # Smaller models sometimes send a string instead of
                    # an array — try to recover gracefully.
                    ask_user_options: list[str] | None = None
                    if isinstance(raw_options, list):
                        ask_user_options = [str(o) for o in raw_options if o]
                    elif isinstance(raw_options, str) and raw_options.strip():
                        # Try JSON parse first (e.g. '["a","b"]')
                        try:
                            parsed = json.loads(raw_options)
                            if isinstance(parsed, list):
                                ask_user_options = [str(o) for o in parsed if o]
                        except (json.JSONDecodeError, TypeError):
                            pass
                    if ask_user_options is not None and len(ask_user_options) < 2:
                        ask_user_options = None  # fall back to free-text input

                    # Workers MUST provide at least 2 options — no free-text
                    # questions allowed.  Only the queen may omit options.
                    if ask_user_options is None and stream_id != "queen":
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: options are required. Provide at least "
                                "2 predefined choices in the 'options' array. "
                                'Example: {"question": "...", "options": '
                                '["Yes", "No"]}'
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    user_input_requested = True

                    # Free-form ask_user (no options): stream the question
                    # text as a chat message so the user can see it.  When
                    # options are present the QuestionWidget shows the
                    # question, but without options nothing renders it.
                    if ask_user_options is None and ask_user_prompt and ctx.node_spec.client_facing:
                        await self._publish_text_delta(
                            stream_id,
                            node_id,
                            content=ask_user_prompt,
                            snapshot=ask_user_prompt,
                            ctx=ctx,
                            execution_id=execution_id,
                            iteration=iteration,
                            inner_turn=inner_turn,
                        )

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Waiting for user input...",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "ask_user_multiple":
                    # --- Framework-level ask_user_multiple ---
                    raw_questions = tc.tool_input.get("questions", [])
                    if not isinstance(raw_questions, list) or len(raw_questions) < 2:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: questions must be an array of at "
                                "least 2 question objects. Use ask_user "
                                "for single questions."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        user_input_requested = False
                        continue

                    # Normalize each question entry
                    questions: list[dict] = []
                    for i, q in enumerate(raw_questions):
                        if not isinstance(q, dict):
                            continue
                        qid = str(q.get("id", f"q{i + 1}"))
                        prompt = str(q.get("prompt", ""))
                        opts = q.get("options", None)
                        if isinstance(opts, list):
                            opts = [str(o) for o in opts if o]
                            if len(opts) < 2:
                                opts = None
                        else:
                            opts = None
                        questions.append(
                            {
                                "id": qid,
                                "prompt": prompt,
                                **({"options": opts} if opts else {}),
                            }
                        )

                    user_input_requested = True

                    # Store as multi-question prompt/options for
                    # the event emission path
                    ask_user_prompt = ""
                    ask_user_options = None
                    # Pass the full questions list via a special
                    # key that the event emitter picks up
                    self._pending_multi_questions = questions

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
                                "ERROR: escalate is only available to worker "
                                "nodes/sub-agents, not queen/judge streams."
                            ),
                            is_error=True,
                        )
                        results_by_id[tc.tool_use_id] = result
                        continue

                    if self._event_bus is None:
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=(
                                "ERROR: EventBus unavailable. Could not emit escalation request."
                            ),
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
                    )
                    queen_input_requested = True

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content="Escalation requested to queen; waiting for guidance.",
                        is_error=False,
                    )
                    results_by_id[tc.tool_use_id] = result

                elif tc.tool_name == "delegate_to_sub_agent":
                    # --- Framework-level subagent delegation ---
                    # Queue for parallel execution in Phase 2
                    logger.info(
                        "🔄 LLM requesting subagent delegation: agent_id='%s', task='%s'",
                        tc.tool_input.get("agent_id", "?"),
                        (tc.tool_input.get("task", "")[:100] + "...")
                        if len(tc.tool_input.get("task", "")) > 100
                        else tc.tool_input.get("task", ""),
                    )
                    pending_subagent.append(tc)

                elif tc.tool_name == "report_to_parent":
                    # --- Report from sub-agent to parent (optionally blocking) ---
                    reported_to_parent = True
                    msg = tc.tool_input.get("message", "")
                    data = tc.tool_input.get("data")
                    wait = tc.tool_input.get("wait_for_response", False)
                    mark_complete = tc.tool_input.get("mark_complete", False)
                    response = None

                    if ctx.report_callback:
                        try:
                            response = await ctx.report_callback(
                                msg,
                                data,
                                wait_for_response=wait,
                            )
                        except Exception:
                            logger.warning(
                                "[%s] report_to_parent callback failed (swallowed)",
                                node_id,
                                exc_info=True,
                            )

                    if mark_complete:
                        self._mark_complete_flag = True
                        logger.info(
                            "[%s] mark_complete=True — subagent will accept on this iteration",
                            node_id,
                        )

                    result = ToolResult(
                        tool_use_id=tc.tool_use_id,
                        content=response if (wait and response) else "Report sent to parent.",
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

            # Phase 2a: execute real tools in parallel.
            if pending_real:

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

                self._tool_task = asyncio.ensure_future(
                    asyncio.gather(
                        *(_timed_execute(tc) for tc in pending_real),
                        return_exceptions=True,
                    )
                )
                try:
                    timed_results = await self._tool_task
                finally:
                    self._tool_task = None
                # gather(return_exceptions=True) captures CancelledError
                # as a return value instead of propagating it.  Re-raise
                # so stop_worker actually stops the execution.
                for entry in timed_results:
                    if isinstance(entry, asyncio.CancelledError):
                        raise entry
                for tc, entry in zip(pending_real, timed_results, strict=True):
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
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=f"Tool '{tc.tool_name}' raised: {raw}",
                            is_error=True,
                        )
                    else:
                        result = raw
                    results_by_id[tc.tool_use_id] = self._truncate_tool_result(result, tc.tool_name)

            # Phase 2b: execute subagent delegations in parallel.
            if pending_subagent:
                _subagent_timeout = self._config.subagent_timeout_seconds

                async def _timed_subagent(
                    _ctx: NodeContext,
                    _tc: ToolCallEvent,
                    _acc: OutputAccumulator = accumulator,
                    _timeout: float = _subagent_timeout,
                ) -> tuple[ToolResult | BaseException, str, float]:
                    _s = time.time()
                    _iso = datetime.now(UTC).isoformat()
                    try:
                        _coro = self._execute_subagent(
                            _ctx,
                            _tc.tool_input.get("agent_id", ""),
                            _tc.tool_input.get("task", ""),
                            accumulator=_acc,
                        )
                        if _timeout > 0:
                            _r = await asyncio.wait_for(_coro, timeout=_timeout)
                        else:
                            _r = await _coro
                    except TimeoutError:
                        _agent_id = _tc.tool_input.get("agent_id", "unknown")
                        logger.warning(
                            "Subagent '%s' timed out after %.0fs",
                            _agent_id,
                            _timeout,
                        )
                        _r = ToolResult(
                            tool_use_id=_tc.tool_use_id,
                            content=(
                                f"Subagent '{_agent_id}' timed out after "
                                f"{_timeout:.0f}s. The delegation took "
                                "too long and was cancelled. Try a simpler task "
                                "or break it into smaller pieces."
                            ),
                            is_error=True,
                        )
                    except BaseException as _exc:
                        _r = _exc
                    _dur = round(time.time() - _s, 3)
                    return _r, _iso, _dur

                subagent_timed = await asyncio.gather(
                    *(_timed_subagent(ctx, tc) for tc in pending_subagent),
                    return_exceptions=True,
                )
                for tc, entry in zip(pending_subagent, subagent_timed, strict=True):
                    if isinstance(entry, BaseException):
                        raw = entry
                        _start_iso = datetime.now(UTC).isoformat()
                        _dur_s = 0
                    else:
                        raw, _start_iso, _dur_s = entry
                    _sa_timing = {
                        "start_timestamp": _start_iso,
                        "duration_s": _dur_s,
                    }
                    if isinstance(raw, BaseException):
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=json.dumps(
                                {
                                    "message": f"Sub-agent execution raised: {raw}",
                                    "data": None,
                                    "metadata": {"success": False, "error": str(raw)},
                                }
                            ),
                            is_error=True,
                        )
                    else:
                        # Attach the tool_use_id to the result
                        result = ToolResult(
                            tool_use_id=tc.tool_use_id,
                            content=raw.content,
                            is_error=raw.is_error,
                        )
                    # Route through _truncate_tool_result so large
                    # subagent results are saved to spillover files
                    # and survive pruning (instead of being "cleared
                    # from context" with no recovery path).
                    result = self._truncate_tool_result(result, "delegate_to_sub_agent")
                    results_by_id[tc.tool_use_id] = result
                    logged_tool_calls.append(
                        {
                            "tool_use_id": tc.tool_use_id,
                            "tool_name": "delegate_to_sub_agent",
                            "tool_input": tc.tool_input,
                            "content": result.content,
                            "is_error": result.is_error,
                            **_sa_timing,
                        }
                    )

            # Phase 3: record results into conversation in original order,
            # build logged/real lists, and publish completed events.
            for tc in tool_calls[:executed_in_batch]:
                result = results_by_id.get(tc.tool_use_id)
                if result is None:
                    continue  # shouldn't happen

                # Build log entries for real tools (exclude synthetic tools)
                if tc.tool_name not in (
                    "set_output",
                    "ask_user",
                    "ask_user_multiple",
                    "escalate",
                    "delegate_to_sub_agent",
                    "report_to_parent",
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

                await conversation.add_tool_result(
                    tool_use_id=tc.tool_use_id,
                    content=result.content,
                    is_error=result.is_error,
                )
                if (
                    tc.tool_name in ("ask_user", "ask_user_multiple")
                    and user_input_requested
                    and not result.is_error
                ):
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
                    ask_user_prompt,
                    ask_user_options,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    reported_to_parent,
                )

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
                    ask_user_prompt,
                    ask_user_options,
                    queen_input_requested,
                    final_system_prompt,
                    final_messages,
                    reported_to_parent,
                )

            # Tool calls processed -- loop back to stream with updated conversation
            inner_turn += 1

    # -------------------------------------------------------------------
    # Synthetic tools: set_output, ask_user, escalate
    # ask_user is used by queen
    # escalate is used by worker
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
                "You MUST call this tool whenever you need the user's response. "
                "Always call it after greeting the user, asking a question, or "
                "requesting approval. Do NOT call it for status updates or "
                "summaries that don't require a response. "
                "Always include 2-3 predefined options. The UI automatically "
                "appends an 'Other' free-text input after your options, so NEVER "
                "include catch-all options like 'Custom idea', 'Something else', "
                "'Other', or 'None of the above' — the UI handles that. "
                "When the question primarily needs a typed answer but you must "
                "include options, make one option signal that typing is expected "
                "(e.g. 'I\\'ll type my response'). This helps users discover the "
                "free-text input. "
                "The ONLY exception: omit options when the question demands a "
                "free-form answer the user must type out (e.g. 'Describe your "
                "agent idea', 'Paste the error message'). "
                'Example: {"question": "What would you like to do?", "options": '
                '["Build a new agent", "Modify existing agent", "Run tests"]} '
                "Free-form example: "
                '{"question": "Describe the agent you want to build."}'
            ),
            parameters={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question or prompt shown to the user.",
                    },
                    "options": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "2-3 specific predefined choices. Include in most cases. "
                            'Example: ["Option A", "Option B", "Option C"]. '
                            "The UI always appends an 'Other' free-text input, so "
                            "do NOT include catch-alls like 'Custom idea' or 'Other'. "
                            "Omit ONLY when the user must type a free-form answer."
                        ),
                        "minItems": 2,
                        "maxItems": 3,
                    },
                },
                "required": ["question"],
            },
        )

    def _build_ask_user_multiple_tool(self) -> Tool:
        """Build the synthetic ask_user_multiple tool for batched questions.

        Queen-only tool that presents multiple questions at once so the user
        can answer them all in a single interaction rather than one at a time.
        """
        return Tool(
            name="ask_user_multiple",
            description=(
                "Ask the user multiple questions at once. Use this instead of "
                "ask_user when you have 2 or more questions to ask in the same "
                "turn — it lets the user answer everything in one go rather than "
                "going back and forth. Each question can have its own predefined "
                "options (2-3 choices) or be free-form. The UI renders all "
                "questions together with a single Submit button. "
                "ALWAYS prefer this over ask_user when you have multiple things "
                "to clarify. "
                "IMPORTANT: Do NOT repeat the questions in your text response — "
                "the widget renders them. Keep your text to a brief intro only. "
                'Example: {"questions": ['
                '  {"id": "scope", "prompt": "What scope?", "options": ["Full", "Partial"]},'
                '  {"id": "format", "prompt": "Output format?", "options": ["PDF", "CSV", "JSON"]},'
                '  {"id": "details", "prompt": "Any special requirements?"}'
                "]}"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "questions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {
                                    "type": "string",
                                    "description": (
                                        "Short identifier for this question (used in the response)."
                                    ),
                                },
                                "prompt": {
                                    "type": "string",
                                    "description": "The question text shown to the user.",
                                },
                                "options": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": (
                                        "2-3 predefined choices. The UI appends an "
                                        "'Other' free-text input automatically. "
                                        "Omit only when the user must type a free-form answer."
                                    ),
                                    "minItems": 2,
                                    "maxItems": 3,
                                },
                            },
                            "required": ["id", "prompt"],
                        },
                        "minItems": 2,
                        "maxItems": 8,
                        "description": "List of questions to present to the user.",
                    },
                },
                "required": ["questions"],
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
                "Use this for brief notes, counts, status, and file references — "
                "NOT for large data payloads. When a tool result was saved to a "
                "data file, pass the filename as the value "
                "(e.g. 'google_sheets_get_values_1.txt') so the next phase can "
                "load the full data. Values exceeding ~2000 characters are "
                "auto-saved to data files. "
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
                        "description": (
                            "The output value — a brief note, count, status, "
                            "or data filename reference."
                        ),
                    },
                },
                "required": ["key", "value"],
            },
        )

    def _build_escalate_tool(self) -> Tool:
        """Build the synthetic escalate tool for worker -> queen handoff."""
        return Tool(
            name="escalate",
            description=(
                "Escalate to the queen when requesting user input, "
                "blocked by errors, missing "
                "credentials, or ambiguous constraints that require supervisor "
                "guidance. Include a concise reason and optional context. "
                "The node will pause until the queen injects guidance."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": (
                            "Short reason for escalation (e.g. 'Tool repeatedly failing')."
                        ),
                    },
                    "context": {
                        "type": "string",
                        "description": "Optional diagnostic details for the queen.",
                    },
                },
                "required": ["reason"],
            },
        )

    def _build_delegate_tool(
        self, sub_agents: list[str], node_registry: dict[str, Any]
    ) -> Tool | None:
        """Build the synthetic delegate_to_sub_agent tool for subagent invocation.

        Args:
            sub_agents: List of node IDs that can be invoked as subagents.
            node_registry: Map of node_id -> NodeSpec for looking up subagent descriptions.

        Returns:
            Tool definition if sub_agents is non-empty, None otherwise.
        """
        if not sub_agents:
            return None

        agent_descriptions = []
        for agent_id in sub_agents:
            spec = node_registry.get(agent_id)
            if spec:
                desc = getattr(spec, "description", "(no description)")
                agent_descriptions.append(f"- {agent_id}: {desc}")
            else:
                agent_descriptions.append(f"- {agent_id}: (not found in registry)")

        return Tool(
            name="delegate_to_sub_agent",
            description=(
                "Delegate a task to a specialized sub-agent. The sub-agent runs "
                "autonomously with read-only access to current memory and returns "
                "its result. Use this to parallelize work or leverage specialized capabilities.\n\n"
                "Available sub-agents:\n" + "\n".join(agent_descriptions)
            ),
            parameters={
                "type": "object",
                "properties": {
                    "agent_id": {
                        "type": "string",
                        "description": f"The sub-agent to invoke. Must be one of: {sub_agents}",
                        "enum": sub_agents,
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "The task description for the sub-agent to execute. "
                            "Be specific about what you want the sub-agent to do and "
                            "what information to return."
                        ),
                    },
                },
                "required": ["agent_id", "task"],
            },
        )

    def _build_report_to_parent_tool(self) -> Tool:
        """Build the synthetic report_to_parent tool for sub-agent progress reports.

        Sub-agents call this to send one-way progress updates, partial findings,
        or status reports to the parent node (and external observers via event bus)
        without blocking execution.

        When ``wait_for_response`` is True, the sub-agent blocks until the parent
        relays the user's response — used for escalation (e.g. login pages, CAPTCHAs).

        When ``mark_complete`` is True, the sub-agent terminates immediately after
        sending the report — no need to call set_output for each output key.
        """
        return Tool(
            name="report_to_parent",
            description=(
                "Send a report to the parent agent. By default this is fire-and-forget: "
                "the parent receives the report but does not respond. "
                "Set wait_for_response=true to BLOCK until the user replies — use this "
                "when you need human intervention (e.g. login pages, CAPTCHAs, "
                "authentication walls). The user's response is returned as the tool result. "
                "Set mark_complete=true to finish your task and terminate immediately "
                "after sending the report — use this when your findings are in the "
                "message/data fields and you don't need to call set_output."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "A human-readable status or progress message.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Optional structured data to include with the report.",
                    },
                    "wait_for_response": {
                        "type": "boolean",
                        "description": (
                            "If true, block execution until the user responds. "
                            "Use for escalation scenarios requiring human intervention."
                        ),
                        "default": False,
                    },
                    "mark_complete": {
                        "type": "boolean",
                        "description": (
                            "If true, terminate the sub-agent immediately after sending "
                            "this report. The report message and data are delivered to the "
                            "parent as the final result. No set_output calls are needed."
                        ),
                        "default": False,
                    },
                },
                "required": ["message"],
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

    async def _judge_turn(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        accumulator: OutputAccumulator,
        assistant_text: str,
        tool_results: list[dict],
        iteration: int,
    ) -> JudgeVerdict:
        """Evaluate the current state using judge or implicit logic.

        Evaluation levels (in order):
          0. Short-circuits: mark_complete, skip_judge, tool-continue.
          1. Custom judge (JudgeProtocol) — full authority when set.
          2. Implicit judge — output-key check + optional conversation-aware
             quality gate (when ``success_criteria`` is defined).

        Returns a JudgeVerdict.  ``feedback=None`` means no real evaluation
        happened (skip_judge, tool-continue); the caller must not inject a
        feedback message.  Any non-None feedback (including ``""``) means a
        real evaluation occurred and will be logged into the conversation.
        """

        # --- Level 0: short-circuits (no evaluation) -----------------------

        if self._mark_complete_flag:
            return JudgeVerdict(action="ACCEPT")

        if ctx.node_spec.skip_judge:
            return JudgeVerdict(action="RETRY")  # feedback=None → not logged

        # --- Level 1: custom judge -----------------------------------------

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
            verdict = await self._judge.evaluate(context)
            # Ensure evaluated RETRY always carries feedback for logging.
            if verdict.action == "RETRY" and not verdict.feedback:
                return JudgeVerdict(action="RETRY", feedback="Custom judge returned RETRY.")
            return verdict

        # --- Level 2: implicit judge ---------------------------------------

        # Real tool calls were made — let the agent keep working.
        if tool_results:
            return JudgeVerdict(action="RETRY")  # feedback=None → not logged

        missing = self._get_missing_output_keys(
            accumulator, ctx.node_spec.output_keys, ctx.node_spec.nullable_output_keys
        )

        if missing:
            return JudgeVerdict(
                action="RETRY",
                feedback=(
                    f"Task incomplete. Required outputs not yet produced: {missing}. "
                    f"Follow your system prompt instructions to complete the work."
                ),
            )

        # All output keys present — run safety checks before accepting.

        output_keys = ctx.node_spec.output_keys or []
        nullable_keys = set(ctx.node_spec.nullable_output_keys or [])

        # All-nullable with nothing set → node produced nothing useful.
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

        # Client-facing with no output keys → continuous interaction node.
        # Inject tool-use pressure instead of auto-accepting.
        if not output_keys and ctx.node_spec.client_facing:
            return JudgeVerdict(
                action="RETRY",
                feedback=(
                    "STOP describing what you will do. "
                    "You have FULL access to all tools — file creation, "
                    "shell commands, MCP tools — and you CAN call them "
                    "directly in your response. Respond ONLY with tool "
                    "calls, no prose. Execute the task now."
                ),
            )

        # Level 2b: conversation-aware quality check (if success_criteria set)
        if ctx.node_spec.success_criteria and ctx.llm:
            from framework.graph.conversation_judge import evaluate_phase_completion

            verdict = await evaluate_phase_completion(
                llm=ctx.llm,
                conversation=conversation,
                phase_name=ctx.node_spec.name,
                phase_description=ctx.node_spec.description,
                success_criteria=ctx.node_spec.success_criteria,
                accumulator_state=accumulator.to_dict(),
                max_context_tokens=self._config.max_context_tokens,
            )
            if verdict.action != "ACCEPT":
                return JudgeVerdict(
                    action=verdict.action,
                    feedback=verdict.feedback or "Phase criteria not met.",
                )

        return JudgeVerdict(action="ACCEPT", feedback="")

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
        from framework.graph.conversation import extract_tool_call_history

        return extract_tool_call_history(conversation.messages, max_entries=max_entries)

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

    @staticmethod
    def _ngram_similarity(s1: str, s2: str, n: int = 2) -> float:
        """Jaccard similarity of n-gram sets.

        Returns 0.0-1.0, where 1.0 is exact match.
        Fast: O(len(s) + len(s2)) using set operations.
        """

        def _ngrams(s: str) -> set[str]:
            return {s[i : i + n] for i in range(len(s) - n + 1) if s.strip()}

        if not s1 or not s2:
            return 0.0

        ngrams1, ngrams2 = _ngrams(s1.lower()), _ngrams(s2.lower())
        if not ngrams1 or not ngrams2:
            return 0.0

        intersection = len(ngrams1 & ngrams2)
        union = len(ngrams1 | ngrams2)
        return intersection / union if union else 0.0

    def _is_stalled(self, recent_responses: list[str]) -> bool:
        """Detect stall using n-gram similarity.

        Detects when ALL N consecutive responses are mutually similar
        (>= threshold).  A single dissimilar response resets the signal.
        This catches phrases like "I'm still stuck" vs "I'm stuck"
        without false-positives on "attempt 1" vs "attempt 2".
        """
        if len(recent_responses) < self._config.stall_detection_threshold:
            return False
        if not recent_responses[0]:
            return False

        threshold = self._config.stall_similarity_threshold
        # Every consecutive pair must be similar
        for i in range(1, len(recent_responses)):
            if self._ngram_similarity(recent_responses[i], recent_responses[i - 1]) < threshold:
                return False
        return True

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
                "failed to parse tool call",
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
        """Detect doom loop via exact fingerprint match.

        Detects when N consecutive turns invoke the same tools with
        identical (canonicalized) arguments.  Different arguments mean
        different work, so only exact matches count.

        Returns (is_doom_loop, description).
        """
        if not self._config.tool_doom_loop_enabled:
            return False, ""
        threshold = self._config.tool_doom_loop_threshold
        if len(recent_tool_fingerprints) < threshold:
            return False, ""
        first = recent_tool_fingerprints[0]
        if not first:
            return False, ""

        # All turns in the window must match the first exactly
        if all(fp == first for fp in recent_tool_fingerprints[1:]):
            tool_names = [name for name, _ in first]
            desc = (
                f"Doom loop detected: {len(recent_tool_fingerprints)} "
                f"identical consecutive tool calls ({', '.join(tool_names)})"
            )
            return True, desc
        return False, ""

    async def _execute_tool(self, tc: ToolCallEvent) -> ToolResult:
        """Execute a tool call, handling both sync and async executors.

        Applies ``tool_call_timeout_seconds`` from LoopConfig to prevent
        hung MCP servers from blocking the event loop indefinitely.
        The initial executor call is offloaded to a thread pool so that
        sync executors (MCP STDIO tools that block on ``future.result()``)
        don't freeze the event loop.
        """
        if self._tool_executor is None:
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=f"No tool executor configured for '{tc.tool_name}'",
                is_error=True,
            )
        tool_use = ToolUse(id=tc.tool_use_id, name=tc.tool_name, input=tc.tool_input)
        timeout = self._config.tool_call_timeout_seconds

        async def _run() -> ToolResult:
            # Offload the executor call to a thread.  Sync MCP executors
            # block on future.result() — running in a thread keeps the
            # event loop free so asyncio.wait_for can fire the timeout.
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self._tool_executor, tool_use)
            # Async executors return a coroutine — await it on the loop
            if asyncio.iscoroutine(result) or asyncio.isfuture(result):
                result = await result
            return result

        try:
            if timeout > 0:
                result = await asyncio.wait_for(_run(), timeout=timeout)
            else:
                result = await _run()
        except TimeoutError:
            logger.warning("Tool '%s' timed out after %.0fs", tc.tool_name, timeout)
            return ToolResult(
                tool_use_id=tc.tool_use_id,
                content=(
                    f"Tool '{tc.tool_name}' timed out after {timeout:.0f}s. "
                    "The operation took too long and was cancelled. "
                    "Try a simpler request or a different approach."
                ),
                is_error=True,
            )
        return result

    def _record_learning(self, key: str, value: Any) -> None:
        """Append a set_output value to adapt.md as a learning entry.

        Called at set_output time — the moment knowledge is produced — so that
        adapt.md accumulates the agent's outputs across the session.  Since
        adapt.md is injected into the system prompt, these persist through
        any compaction.
        """
        if not self._config.spillover_dir:
            return
        try:
            adapt_path = Path(self._config.spillover_dir) / "adapt.md"
            adapt_path.parent.mkdir(parents=True, exist_ok=True)
            content = adapt_path.read_text(encoding="utf-8") if adapt_path.exists() else ""

            if "## Outputs" not in content:
                content += "\n\n## Outputs\n"

            # Truncate long values for memory (full value is in shared memory)
            v_str = str(value)
            if len(v_str) > 500:
                v_str = v_str[:500] + "…"

            entry = f"- {key}: {v_str}\n"

            # Replace existing entry for same key (update, not duplicate)
            lines = content.splitlines(keepends=True)
            replaced = False
            for i, line in enumerate(lines):
                if line.startswith(f"- {key}:"):
                    lines[i] = entry
                    replaced = True
                    break
            if replaced:
                content = "".join(lines)
            else:
                content += entry

            adapt_path.write_text(content, encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to record learning for key=%s: %s", key, e)

    def _next_spill_filename(self, tool_name: str) -> str:
        """Return a short, monotonic filename for a tool result spill."""
        self._spill_counter += 1
        # Shorten common tool name prefixes to save tokens
        short = tool_name.removeprefix("tool_").removeprefix("mcp_")
        return f"{short}_{self._spill_counter}.txt"

    def _restore_spill_counter(self) -> None:
        """Scan spillover_dir for existing spill files and restore the counter."""
        spill_dir = self._config.spillover_dir
        if not spill_dir:
            return
        spill_path = Path(spill_dir)
        if not spill_path.is_dir():
            return
        max_n = 0
        for f in spill_path.iterdir():
            if not f.is_file():
                continue
            m = re.search(r"_(\d+)\.txt$", f.name)
            if m:
                max_n = max(max_n, int(m.group(1)))
        if max_n > self._spill_counter:
            self._spill_counter = max_n
            logger.info("Restored spill counter to %d from existing files", max_n)

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
        if _depth >= _max_depth:
            if isinstance(parsed, dict):
                return f"dict with {len(parsed)} keys"
            if isinstance(parsed, list):
                return f"list of {len(parsed)} items"
            return type(parsed).__name__

        if isinstance(parsed, dict):
            if not parsed:
                return "empty dict"
            lines: list[str] = []
            indent = "  " * (_depth + 1)
            for key, value in list(parsed.items())[:20]:
                if isinstance(value, list):
                    line = f'{indent}"{key}": list of {len(value)} items'
                    if value:
                        first = value[0]
                        if isinstance(first, dict):
                            sample_keys = list(first.keys())[:10]
                            line += f" (each item: dict with keys {sample_keys})"
                        elif isinstance(first, list):
                            line += f" (each item: list of {len(first)} elements)"
                    lines.append(line)
                elif isinstance(value, dict):
                    child = EventLoopNode._extract_json_metadata(
                        value, _depth=_depth + 1, _max_depth=_max_depth
                    )
                    lines.append(f'{indent}"{key}": {child}')
                else:
                    lines.append(f'{indent}"{key}": {type(value).__name__}')
            if len(parsed) > 20:
                lines.append(f"{indent}... and {len(parsed) - 20} more keys")
            return "\n".join(lines)

        if isinstance(parsed, list):
            if not parsed:
                return "empty list"
            desc = f"list of {len(parsed)} items"
            first = parsed[0]
            if isinstance(first, dict):
                sample_keys = list(first.keys())[:10]
                desc += f" (each item: dict with keys {sample_keys})"
            elif isinstance(first, list):
                desc += f" (each item: list of {len(first)} elements)"
            return desc

        return ""

    @staticmethod
    def _build_json_preview(parsed: Any, *, max_chars: int = 5000) -> str | None:
        """Build a smart preview of parsed JSON, truncating large arrays.

        Shows first 3 + last 1 items of large arrays with explicit count
        markers so the LLM cannot mistake the preview for the full dataset.

        Returns ``None`` if no truncation was needed (no large arrays).
        """
        _LARGE_ARRAY_THRESHOLD = 10

        def _truncate_arrays(obj: Any) -> tuple[Any, bool]:
            """Return (truncated_copy, was_truncated)."""
            if isinstance(obj, list) and len(obj) > _LARGE_ARRAY_THRESHOLD:
                n = len(obj)
                head = obj[:3]
                tail = obj[-1:]
                marker = f"... ({n - 4} more items omitted, {n} total) ..."
                return head + [marker] + tail, True
            if isinstance(obj, dict):
                changed = False
                out: dict[str, Any] = {}
                for k, v in obj.items():
                    new_v, did = _truncate_arrays(v)
                    out[k] = new_v
                    changed = changed or did
                return (out, True) if changed else (obj, False)
            return obj, False

        preview_obj, was_truncated = _truncate_arrays(parsed)
        if not was_truncated:
            return None  # No large arrays — caller should use raw slicing

        try:
            result = json.dumps(preview_obj, indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            return None

        if len(result) > max_chars:
            # Even 3+1 items too big — try just 1 item
            def _minimal_arrays(obj: Any) -> Any:
                if isinstance(obj, list) and len(obj) > _LARGE_ARRAY_THRESHOLD:
                    n = len(obj)
                    return obj[:1] + [f"... ({n - 1} more items omitted, {n} total) ..."]
                if isinstance(obj, dict):
                    return {k: _minimal_arrays(v) for k, v in obj.items()}
                return obj

            preview_obj = _minimal_arrays(parsed)
            try:
                result = json.dumps(preview_obj, indent=2, ensure_ascii=False)
            except (TypeError, ValueError):
                return None
            if len(result) > max_chars:
                result = result[:max_chars] + "…"

        return result

    def _truncate_tool_result(
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
        - load_data results: truncate with pagination hint (no re-spill)
        """
        limit = self._config.max_tool_result_chars

        # Errors always pass through unchanged
        if result.is_error:
            return result

        # load_data reads FROM spilled files — never re-spill (circular).
        # Just truncate with a pagination hint if the result is too large.
        if tool_name == "load_data":
            if limit <= 0 or len(result.content) <= limit:
                return result  # Small load_data result — pass through as-is
            # Large load_data result — truncate with smart preview
            PREVIEW_CAP = min(5000, max(limit - 500, limit // 2))

            metadata_str = ""
            smart_preview: str | None = None
            try:
                parsed_ld = json.loads(result.content)
                metadata_str = self._extract_json_metadata(parsed_ld)
                smart_preview = self._build_json_preview(parsed_ld, max_chars=PREVIEW_CAP)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            if smart_preview is not None:
                preview_block = smart_preview
            else:
                preview_block = result.content[:PREVIEW_CAP] + "…"

            header = (
                f"[{tool_name} result: {len(result.content):,} chars — "
                f"too large for context. Use offset_bytes/limit_bytes "
                f"parameters to read smaller chunks.]"
            )
            if metadata_str:
                header += f"\n\nData structure:\n{metadata_str}"
            header += (
                "\n\nWARNING: This is an INCOMPLETE preview. "
                "Do NOT draw conclusions or counts from it."
            )

            truncated = f"{header}\n\nPreview (small sample only):\n{preview_block}"
            logger.info(
                "%s result truncated: %d → %d chars (use offset/limit to paginate)",
                tool_name,
                len(result.content),
                len(truncated),
            )
            return ToolResult(
                tool_use_id=result.tool_use_id,
                content=truncated,
                is_error=False,
            )

        spill_dir = self._config.spillover_dir
        if spill_dir:
            spill_path = Path(spill_dir)
            spill_path.mkdir(parents=True, exist_ok=True)
            filename = self._next_spill_filename(tool_name)

            # Pretty-print JSON content so load_data's line-based
            # pagination works correctly.
            write_content = result.content
            parsed_json: Any = None  # track for metadata extraction
            try:
                parsed_json = json.loads(result.content)
                write_content = json.dumps(parsed_json, indent=2, ensure_ascii=False)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass  # Not JSON — write as-is

            (spill_path / filename).write_text(write_content, encoding="utf-8")

            if limit > 0 and len(result.content) > limit:
                # Large result: build a small, metadata-rich preview so the
                # LLM cannot mistake it for the complete dataset.
                PREVIEW_CAP = 5000

                # Extract structural metadata (array lengths, key names)
                metadata_str = ""
                smart_preview: str | None = None
                if parsed_json is not None:
                    metadata_str = self._extract_json_metadata(parsed_json)
                    smart_preview = self._build_json_preview(parsed_json, max_chars=PREVIEW_CAP)

                if smart_preview is not None:
                    preview_block = smart_preview
                else:
                    preview_block = result.content[:PREVIEW_CAP] + "…"

                # Assemble header with structural info + warning
                header = (
                    f"[Result from {tool_name}: {len(result.content):,} chars — "
                    f"too large for context, saved to '{filename}'.]"
                )
                if metadata_str:
                    header += f"\n\nData structure:\n{metadata_str}"
                header += (
                    f"\n\nWARNING: The preview below is INCOMPLETE. "
                    f"Do NOT draw conclusions or counts from it. "
                    f"Use load_data(filename='{filename}') to read the "
                    f"full data before analysis."
                )

                content = f"{header}\n\nPreview (small sample only):\n{preview_block}"
                logger.info(
                    "Tool result spilled to file: %s (%d chars → %s)",
                    tool_name,
                    len(result.content),
                    filename,
                )
            else:
                # Small result: keep full content + annotation
                content = f"{result.content}\n\n[Saved to '{filename}']"
                logger.info(
                    "Tool result saved to file: %s (%d chars → %s)",
                    tool_name,
                    len(result.content),
                    filename,
                )

            return ToolResult(
                tool_use_id=result.tool_use_id,
                content=content,
                is_error=False,
            )

        # No spillover_dir — truncate in-place if needed
        if limit > 0 and len(result.content) > limit:
            PREVIEW_CAP = min(5000, max(limit - 500, limit // 2))

            metadata_str = ""
            smart_preview: str | None = None
            try:
                parsed_inline = json.loads(result.content)
                metadata_str = self._extract_json_metadata(parsed_inline)
                smart_preview = self._build_json_preview(parsed_inline, max_chars=PREVIEW_CAP)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            if smart_preview is not None:
                preview_block = smart_preview
            else:
                preview_block = result.content[:PREVIEW_CAP] + "…"

            header = (
                f"[Result from {tool_name}: {len(result.content):,} chars — "
                f"truncated to fit context budget.]"
            )
            if metadata_str:
                header += f"\n\nData structure:\n{metadata_str}"
            header += (
                "\n\nWARNING: This is an INCOMPLETE preview. "
                "Do NOT draw conclusions or counts from the preview alone."
            )

            truncated = f"{header}\n\n{preview_block}"
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

        return result

    # --- Compaction -----------------------------------------------------------

    # Max chars of formatted messages before proactively splitting for LLM.
    _LLM_COMPACT_CHAR_LIMIT = 240_000
    # Max recursion depth for binary-search splitting.
    _LLM_COMPACT_MAX_DEPTH = 10

    async def _compact(
        self,
        ctx: NodeContext,
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
        ratio_before = conversation.usage_ratio()
        phase_grad = getattr(ctx, "continuous_mode", False)

        # --- Step 1: Prune old tool results (free, no LLM) ---
        protect = max(2000, self._config.max_context_tokens // 12)
        pruned = await conversation.prune_old_tool_results(
            protect_tokens=protect,
            min_prune_tokens=max(1000, protect // 3),
        )
        if pruned > 0:
            logger.info(
                "Pruned %d old tool results: %.0f%% -> %.0f%%",
                pruned,
                ratio_before * 100,
                conversation.usage_ratio() * 100,
            )
        if not conversation.needs_compaction():
            await self._log_compaction(ctx, conversation, ratio_before)
            return

        # --- Step 2: Standard structure-preserving compaction (free, no LLM) ---
        # Removes freeform text to spillover files; keeps tool-call pairs in context.
        spill_dir = self._config.spillover_dir
        if spill_dir:
            await conversation.compact_preserving_structure(
                spillover_dir=spill_dir,
                keep_recent=4,
                phase_graduated=phase_grad,
            )
        if not conversation.needs_compaction():
            await self._log_compaction(ctx, conversation, ratio_before)
            return

        # --- Step 3: LLM summary compaction ---
        # Structural compaction alone did not hit target. Generate an LLM summary
        # and place it as the first message — more reliable for token reduction
        # than offloading more content to files.
        if ctx.llm is not None:
            logger.info(
                "LLM summary compaction triggered (%.0f%% usage)",
                conversation.usage_ratio() * 100,
            )
            try:
                summary = await self._llm_compact(
                    ctx,
                    list(conversation.messages),
                    accumulator,
                )
                await conversation.compact(
                    summary,
                    keep_recent=2,
                    phase_graduated=phase_grad,
                )
            except Exception as e:
                logger.warning("LLM compaction failed: %s", e)

        if not conversation.needs_compaction():
            await self._log_compaction(ctx, conversation, ratio_before)
            return

        # --- Step 4: Emergency deterministic summary (LLM failed/unavailable) ---
        logger.warning(
            "Emergency compaction (%.0f%% usage)",
            conversation.usage_ratio() * 100,
        )
        summary = self._build_emergency_summary(ctx, accumulator, conversation)
        await conversation.compact(
            summary,
            keep_recent=1,
            phase_graduated=phase_grad,
        )
        await self._log_compaction(ctx, conversation, ratio_before)

    # --- LLM compaction with binary-search splitting ----------------------

    async def _llm_compact(
        self,
        ctx: NodeContext,
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
        from framework.graph.conversation import extract_tool_call_history

        if _depth > self._LLM_COMPACT_MAX_DEPTH:
            raise RuntimeError(f"LLM compaction recursion limit ({self._LLM_COMPACT_MAX_DEPTH})")

        formatted = self._format_messages_for_summary(messages)

        # Proactive split: avoid wasting an API call on oversized input
        if len(formatted) > self._LLM_COMPACT_CHAR_LIMIT and len(messages) > 1:
            summary = await self._llm_compact_split(
                ctx,
                messages,
                accumulator,
                _depth,
            )
        else:
            prompt = self._build_llm_compaction_prompt(
                ctx,
                accumulator,
                formatted,
            )
            summary_budget = max(1024, self._config.max_context_tokens // 2)
            try:
                response = await ctx.llm.acomplete(
                    messages=[{"role": "user", "content": prompt}],
                    system=(
                        "You are a conversation compactor for an AI agent. "
                        "Write a detailed summary that allows the agent to "
                        "continue its work. Preserve user-stated rules, "
                        "constraints, and account/identity preferences verbatim."
                    ),
                    max_tokens=summary_budget,
                )
                summary = response.content
            except Exception as e:
                if _is_context_too_large_error(e) and len(messages) > 1:
                    logger.info(
                        "LLM context too large (depth=%d, msgs=%d) — splitting",
                        _depth,
                        len(messages),
                    )
                    summary = await self._llm_compact_split(
                        ctx,
                        messages,
                        accumulator,
                        _depth,
                    )
                else:
                    raise

        # Append tool history at top level only
        if _depth == 0:
            tool_history = extract_tool_call_history(messages)
            if tool_history and "TOOLS ALREADY CALLED" not in summary:
                summary += "\n\n" + tool_history

        return summary

    async def _llm_compact_split(
        self,
        ctx: NodeContext,
        messages: list,
        accumulator: OutputAccumulator | None,
        _depth: int,
    ) -> str:
        """Split messages in half and summarise each half independently."""
        mid = max(1, len(messages) // 2)
        s1 = await self._llm_compact(ctx, messages[:mid], None, _depth + 1)
        s2 = await self._llm_compact(
            ctx,
            messages[mid:],
            accumulator,
            _depth + 1,
        )
        return s1 + "\n\n" + s2

    # --- Compaction helpers ------------------------------------------------

    @staticmethod
    def _format_messages_for_summary(messages: list) -> str:
        """Format messages as text for LLM summarisation."""
        lines: list[str] = []
        for m in messages:
            if m.role == "tool":
                content = m.content[:500]
                if len(m.content) > 500:
                    content += "..."
                lines.append(f"[tool result]: {content}")
            elif m.role == "assistant" and m.tool_calls:
                names = [tc.get("function", {}).get("name", "?") for tc in m.tool_calls]
                text = m.content[:200] if m.content else ""
                lines.append(f"[assistant (calls: {', '.join(names)})]: {text}")
            else:
                lines.append(f"[{m.role}]: {m.content}")
        return "\n\n".join(lines)

    def _build_llm_compaction_prompt(
        self,
        ctx: NodeContext,
        accumulator: OutputAccumulator | None,
        formatted_messages: str,
    ) -> str:
        """Build prompt for LLM compaction targeting 50% of token budget."""
        spec = ctx.node_spec
        ctx_lines = [f"NODE: {spec.name} (id={spec.id})"]
        if spec.description:
            ctx_lines.append(f"PURPOSE: {spec.description}")
        if spec.success_criteria:
            ctx_lines.append(f"SUCCESS CRITERIA: {spec.success_criteria}")

        if accumulator:
            acc = accumulator.to_dict()
            done = {k: v for k, v in acc.items() if v is not None}
            todo = [k for k, v in acc.items() if v is None]
            if done:
                ctx_lines.append(
                    "OUTPUTS ALREADY SET:\n"
                    + "\n".join(f"  {k}: {str(v)[:150]}" for k, v in done.items())
                )
            if todo:
                ctx_lines.append(f"OUTPUTS STILL NEEDED: {', '.join(todo)}")
        elif spec.output_keys:
            ctx_lines.append(f"OUTPUTS STILL NEEDED: {', '.join(spec.output_keys)}")

        target_tokens = self._config.max_context_tokens // 2
        target_chars = target_tokens * 4
        node_ctx = "\n".join(ctx_lines)

        return (
            "You are compacting an AI agent's conversation history. "
            "The agent is still working and needs to continue.\n\n"
            f"AGENT CONTEXT:\n{node_ctx}\n\n"
            f"CONVERSATION MESSAGES:\n{formatted_messages}\n\n"
            "INSTRUCTIONS:\n"
            f"Write a summary of approximately {target_chars} characters "
            f"(~{target_tokens} tokens).\n"
            "1. Preserve ALL user-stated rules, constraints, and preferences "
            "verbatim.\n"
            "2. Preserve key decisions made and results obtained.\n"
            "3. Preserve in-progress work state so the agent can continue.\n"
            "4. Be detailed enough that the agent can resume without "
            "re-doing work.\n"
        )

    async def _log_compaction(
        self,
        ctx: NodeContext,
        conversation: NodeConversation,
        ratio_before: float,
    ) -> None:
        """Log compaction result to runtime logger and event bus."""
        ratio_after = conversation.usage_ratio()
        before_pct = round(ratio_before * 100)
        after_pct = round(ratio_after * 100)

        # Determine label from what happened
        if after_pct >= before_pct - 1:
            level = "prune_only"
        elif ratio_after <= 0.6:
            level = "llm"
        else:
            level = "structural"

        logger.info(
            "Compaction complete (%s): %d%% -> %d%%",
            level,
            before_pct,
            after_pct,
        )

        if ctx.runtime_logger:
            ctx.runtime_logger.log_step(
                node_id=ctx.node_id,
                node_type="event_loop",
                step_index=-1,
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
                        "usage_before": before_pct,
                        "usage_after": after_pct,
                    },
                )
            )

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

                    all_files = sorted(
                        f.name for f in data_dir.iterdir() if f.is_file() and f.name != "adapt.md"
                    )
                    # Separate conversation history files from regular data files
                    conv_files = [f for f in all_files if re.match(r"conversation_\d+\.md$", f)]
                    data_files = [f for f in all_files if f not in conv_files]

                    if conv_files:
                        conv_list = "\n".join(
                            f"  - {f}  (full path: {data_dir / f})" for f in conv_files
                        )
                        parts.append(
                            "CONVERSATION HISTORY (freeform messages saved during compaction — "
                            "use load_data('<filename>') to review earlier dialogue):\n" + conv_list
                        )
                    if data_files:
                        file_list = "\n".join(
                            f"  - {f}  (full path: {data_dir / f})" for f in data_files[:30]
                        )
                        parts.append(
                            "DATA FILES (use load_data('<filename>') to read):\n" + file_list
                        )
                    if not all_files:
                        parts.append(
                            "NOTE: Large tool results may have been saved to files. "
                            "Use list_directory to check the data directory."
                        )
            except Exception:
                parts.append(
                    "NOTE: Large tool results were saved to files. "
                    "Use read_file(path='<path>') to read them."
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
        accumulator.spillover_dir = self._config.spillover_dir
        accumulator.max_value_chars = self._config.max_output_value_chars

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

    async def _drain_trigger_queue(self, conversation: NodeConversation) -> int:
        """Drain all pending trigger events as a single batched user message.

        Multiple triggers are merged so the LLM sees them atomically and can
        reason about all pending triggers before acting.
        """
        triggers: list[TriggerEvent] = []
        while not self._trigger_queue.empty():
            try:
                triggers.append(self._trigger_queue.get_nowait())
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
                max_tokens=1024,
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
        hook_list = self._config.hooks.get(event, [])
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
                import logging

                logging.getLogger(__name__).warning(
                    "Hook '%s' raised an exception", event, exc_info=True
                )
                continue
            if result is None:
                continue
            if result.system_prompt:
                conversation.update_system_prompt(result.system_prompt)
            if result.inject:
                await conversation.add_user_message(result.inject)

    async def _publish_iteration(
        self,
        stream_id: str,
        node_id: str,
        iteration: int,
        execution_id: str = "",
        extra_data: dict | None = None,
    ) -> None:
        if self._event_bus:
            await self._event_bus.emit_node_loop_iteration(
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
        if self._event_bus:
            await self._event_bus.emit_llm_turn_complete(
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
                reason="Consecutive similar responses detected",
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
        inner_turn: int = 0,
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
                    inner_turn=inner_turn,
                )
            else:
                await self._event_bus.emit_llm_text_delta(
                    stream_id=stream_id,
                    node_id=node_id,
                    content=content,
                    snapshot=snapshot,
                    execution_id=execution_id,
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
                stream_id=stream_id, node_id=node_id, key=key, execution_id=execution_id
            )

    # -------------------------------------------------------------------
    # Subagent Execution
    # -------------------------------------------------------------------

    async def _execute_subagent(
        self,
        ctx: NodeContext,
        agent_id: str,
        task: str,
        *,
        accumulator: OutputAccumulator | None = None,
    ) -> ToolResult:
        """Execute a subagent and return the result as a ToolResult.

        The subagent:
        - Gets a fresh conversation with just the task
        - Has read-only access to the parent's readable memory
        - Cannot delegate to its own subagents (prevents recursion)
        - Returns its output in structured JSON format

        Args:
            ctx: Parent node's context (for memory, tools, LLM access).
            agent_id: The node ID of the subagent to invoke.
            task: The task description to give the subagent.
            accumulator: Parent's OutputAccumulator — provides outputs that
                have been set via ``set_output`` but not yet written to
                shared memory (which only happens after the node completes).

        Returns:
            ToolResult with structured JSON output containing:
            - message: Human-readable summary
            - data: Subagent's output (free-form JSON)
            - metadata: Execution metadata (success, tokens, latency)
        """
        from framework.graph.node import NodeContext, SharedMemory

        # Log subagent invocation start
        logger.info(
            "\n" + "=" * 60 + "\n"
            "🤖 SUBAGENT INVOCATION\n"
            "=" * 60 + "\n"
            "Parent Node: %s\n"
            "Subagent ID: %s\n"
            "Task: %s\n" + "=" * 60,
            ctx.node_id,
            agent_id,
            task[:500] + "..." if len(task) > 500 else task,
        )

        # 1. Validate agent exists in registry
        if agent_id not in ctx.node_registry:
            return ToolResult(
                tool_use_id="",
                content=json.dumps(
                    {
                        "message": f"Sub-agent '{agent_id}' not found in registry",
                        "data": None,
                        "metadata": {"agent_id": agent_id, "success": False, "error": "not_found"},
                    }
                ),
                is_error=True,
            )

        subagent_spec = ctx.node_registry[agent_id]

        # 2. Create read-only memory snapshot
        # Start with everything the parent can read from shared memory.
        parent_data = ctx.memory.read_all()

        # Merge in-flight outputs from the parent's accumulator.
        # set_output() writes to the accumulator but shared memory is only
        # updated after the parent node completes — so the subagent would
        # otherwise miss any keys the parent set before delegating.
        if accumulator:
            for key, value in accumulator.to_dict().items():
                if key not in parent_data:
                    parent_data[key] = value

        subagent_memory = SharedMemory()
        for key, value in parent_data.items():
            subagent_memory.write(key, value, validate=False)

        # Allow reads for parent data AND the subagent's declared input_keys
        # (input_keys may reference keys that exist but weren't in read_all,
        # or keys that were just written by the accumulator).
        read_keys = set(parent_data.keys()) | set(subagent_spec.input_keys or [])
        scoped_memory = subagent_memory.with_permissions(
            read_keys=list(read_keys),
            write_keys=[],  # Read-only!
        )

        # 2b. Set up report callback (one-way channel to parent / event bus)
        subagent_reports: list[dict] = []

        async def _report_callback(
            message: str,
            data: dict | None = None,
            *,
            wait_for_response: bool = False,
        ) -> str | None:
            subagent_reports.append({"message": message, "data": data, "timestamp": time.time()})
            if self._event_bus:
                await self._event_bus.emit_subagent_report(
                    stream_id=ctx.node_id,
                    node_id=f"{ctx.node_id}:subagent:{agent_id}",
                    subagent_id=agent_id,
                    message=message,
                    data=data,
                    execution_id=ctx.execution_id,
                )

            if not wait_for_response:
                return None

            if not self._event_bus:
                logger.warning(
                    "Subagent '%s' requested user response but no event_bus available",
                    agent_id,
                )
                return None

            # Create isolated receiver and register for input routing
            import uuid

            escalation_id = f"{ctx.node_id}:escalation:{uuid.uuid4().hex[:8]}"
            receiver = _EscalationReceiver()
            registry = ctx.shared_node_registry

            registry[escalation_id] = receiver
            try:
                # Escalate to the queen instead of asking the user directly.
                # The queen handles the request and injects the response via
                # inject_worker_message(), which finds this receiver through
                # its _awaiting_input flag.
                await self._event_bus.emit_escalation_requested(
                    stream_id=ctx.stream_id or ctx.node_id,
                    node_id=escalation_id,
                    reason=f"Subagent report (wait_for_response) from {agent_id}",
                    context=message,
                    execution_id=ctx.execution_id,
                )
                # Block until queen responds
                return await receiver.wait()
            finally:
                registry.pop(escalation_id, None)

        # 3. Filter tools for subagent
        # Use the full tool catalog (ctx.all_tools) so subagents can access tools
        # that aren't in the parent node's filtered set (e.g. browser tools for a
        # GCU subagent when the parent only has web_scrape/save_data).
        # Falls back to ctx.available_tools if all_tools is empty (e.g. in tests).
        subagent_tool_names = set(subagent_spec.tools or [])
        tool_source = ctx.all_tools if ctx.all_tools else ctx.available_tools

        # GCU auto-population: GCU nodes declare tools=[] because the runner
        # auto-populates them at setup time.  But that expansion doesn't reach
        # subagents invoked via delegate_to_sub_agent — the subagent spec still
        # has the original empty list.  When a GCU subagent has no declared
        # tools, include all catalog tools so browser tools are available.
        if subagent_spec.node_type == "gcu" and not subagent_tool_names:
            subagent_tools = [t for t in tool_source if t.name != "delegate_to_sub_agent"]
        else:
            subagent_tools = [
                t
                for t in tool_source
                if t.name in subagent_tool_names and t.name != "delegate_to_sub_agent"
            ]

        missing = subagent_tool_names - {t.name for t in subagent_tools}
        if missing:
            logger.warning(
                "Subagent '%s' requested tools not found in catalog: %s",
                agent_id,
                sorted(missing),
            )

        logger.info(
            "📦 Subagent '%s' configuration:\n"
            "   - System prompt: %s\n"
            "   - Tools available (%d): %s\n"
            "   - Memory keys inherited: %s",
            agent_id,
            (subagent_spec.system_prompt[:200] + "...")
            if subagent_spec.system_prompt and len(subagent_spec.system_prompt) > 200
            else subagent_spec.system_prompt,
            len(subagent_tools),
            [t.name for t in subagent_tools],
            list(parent_data.keys()),
        )

        # 4. Build subagent context
        max_iter = min(self._config.max_iterations, 10)
        subagent_ctx = NodeContext(
            runtime=ctx.runtime,
            node_id=f"{ctx.node_id}:subagent:{agent_id}",
            node_spec=subagent_spec,
            memory=scoped_memory,
            input_data={"task": task, **parent_data},
            llm=ctx.llm,
            available_tools=subagent_tools,
            goal_context=(
                f"Your specific task: {task}\n\n"
                f"COMPLETION REQUIREMENTS:\n"
                f"When your task is done, you MUST call set_output() "
                f"for each required key: {subagent_spec.output_keys}\n"
                f"Alternatively, call report_to_parent(mark_complete=true) "
                f"with your findings in message/data.\n"
                f"You have a maximum of {max_iter} turns to complete this task."
            ),
            goal=ctx.goal,
            max_tokens=ctx.max_tokens,
            runtime_logger=ctx.runtime_logger,
            is_subagent_mode=True,  # Prevents nested delegation
            report_callback=_report_callback,
            node_registry={},  # Empty - no nested subagents
            shared_node_registry=ctx.shared_node_registry,  # For escalation routing
        )

        # 5. Create and execute subagent EventLoopNode
        # Derive a conversation store for the subagent from the parent's store.
        # Each invocation gets a unique path so that repeated delegate calls
        # (e.g. one per profile) don't restore a stale completed conversation.
        self._subagent_instance_counter.setdefault(agent_id, 0)
        self._subagent_instance_counter[agent_id] += 1
        subagent_instance = str(self._subagent_instance_counter[agent_id])

        subagent_conv_store = None
        if self._conversation_store is not None:
            from framework.storage.conversation_store import FileConversationStore

            parent_base = getattr(self._conversation_store, "_base", None)
            if parent_base is not None:
                # Store subagent conversations parallel to the parent node,
                # not nested inside it.  e.g. conversations/{node}:subagent:{agent_id}:{instance}/
                conversations_dir = parent_base.parent  # e.g. conversations/
                subagent_dir_name = f"{agent_id}-{subagent_instance}"
                subagent_store_path = conversations_dir / subagent_dir_name
                subagent_conv_store = FileConversationStore(base_path=subagent_store_path)

        # Derive a subagent-scoped spillover dir so large tool results
        # (e.g. browser_snapshot) get written to disk instead of being
        # silently truncated.  Each instance gets its own directory to
        # avoid file collisions between concurrent subagents.
        subagent_spillover = None
        if self._config.spillover_dir:
            subagent_spillover = str(
                Path(self._config.spillover_dir) / agent_id / subagent_instance
            )

        subagent_node = EventLoopNode(
            event_bus=self._event_bus,  # Subagent events visible to Queen via shared bus
            judge=SubagentJudge(task=task, max_iterations=max_iter),
            config=LoopConfig(
                max_iterations=max_iter,  # Tighter budget
                max_tool_calls_per_turn=self._config.max_tool_calls_per_turn,
                tool_call_overflow_margin=self._config.tool_call_overflow_margin,
                max_context_tokens=self._config.max_context_tokens,
                stall_detection_threshold=self._config.stall_detection_threshold,
                max_tool_result_chars=self._config.max_tool_result_chars,
                spillover_dir=subagent_spillover,
            ),
            tool_executor=self._tool_executor,
            conversation_store=subagent_conv_store,
        )

        # Inject a unique GCU browser profile for this subagent so that
        # concurrent GCU subagents (run via asyncio.gather) each get their own
        # isolated BrowserContext.  asyncio.gather copies the current context
        # for each coroutine, so the reset token is safe to call in finally.
        _profile_token = None
        try:
            from gcu.browser.session import set_active_profile as _set_gcu_profile

            _profile_token = _set_gcu_profile(f"{agent_id}-{subagent_instance}")
        except ImportError:
            pass  # GCU tools not installed; no-op

        try:
            logger.info("🚀 Starting subagent '%s' execution...", agent_id)
            start_time = time.time()
            result = await subagent_node.execute(subagent_ctx)
            latency_ms = int((time.time() - start_time) * 1000)

            separator = "-" * 60
            logger.info(
                "\n%s\n"
                "✅ SUBAGENT '%s' COMPLETED\n"
                "%s\n"
                "Success: %s\n"
                "Latency: %dms\n"
                "Tokens used: %s\n"
                "Output keys: %s\n"
                "%s",
                separator,
                agent_id,
                separator,
                result.success,
                latency_ms,
                result.tokens_used,
                list(result.output.keys()) if result.output else [],
                separator,
            )

            result_json = {
                "message": (
                    f"Sub-agent '{agent_id}' completed successfully"
                    if result.success
                    else f"Sub-agent '{agent_id}' failed: {result.error}"
                ),
                "data": result.output,
                "reports": subagent_reports if subagent_reports else None,
                "metadata": {
                    "agent_id": agent_id,
                    "success": result.success,
                    "tokens_used": result.tokens_used,
                    "latency_ms": latency_ms,
                    "report_count": len(subagent_reports),
                },
            }

            return ToolResult(
                tool_use_id="",
                content=json.dumps(result_json, indent=2, default=str),
                is_error=not result.success,
            )

        except Exception as e:
            logger.exception(
                "\n" + "!" * 60 + "\n❌ SUBAGENT '%s' FAILED\nError: %s\n" + "!" * 60,
                agent_id,
                str(e),
            )
            result_json = {
                "message": f"Sub-agent '{agent_id}' raised exception: {e}",
                "data": None,
                "metadata": {
                    "agent_id": agent_id,
                    "success": False,
                    "error": str(e),
                },
            }
            return ToolResult(
                tool_use_id="",
                content=json.dumps(result_json, indent=2),
                is_error=True,
            )
        finally:
            # Restore the GCU profile context that was set before this subagent ran.
            if _profile_token is not None:
                from gcu.browser.session import _active_profile as _gcu_profile_var

                _gcu_profile_var.reset(_profile_token)

                # Stop the browser session for this subagent's profile so tabs are
                # closed immediately rather than accumulating until server shutdown.
                if self._tool_executor is not None:
                    _subagent_profile = f"{agent_id}-{subagent_instance}"
                    try:
                        _stop_use = ToolUse(
                            id="gcu-cleanup",
                            name="browser_stop",
                            input={"profile": _subagent_profile},
                        )
                        _stop_result = self._tool_executor(_stop_use)
                        if asyncio.iscoroutine(_stop_result) or asyncio.isfuture(_stop_result):
                            await _stop_result
                    except Exception as _gcu_exc:
                        logger.warning(
                            "GCU browser_stop failed for profile %r: %s",
                            _subagent_profile,
                            _gcu_exc,
                        )
