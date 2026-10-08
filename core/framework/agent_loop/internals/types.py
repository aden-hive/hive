"""Shared types and state containers for the event loop package."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from framework.agent_loop.conversation import (
    ConversationStore,
)

logger = logging.getLogger(__name__)


@dataclass
class TriggerEvent:
    """A framework-level trigger signal (timer tick or webhook hit)."""

    trigger_type: str
    source_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


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
    """Protocol for event-loop judges."""

    async def evaluate(self, context: dict[str, Any]) -> JudgeVerdict: ...


@dataclass
class LoopConfig:
    """Configuration for the event loop."""

    max_iterations: int = 50
    # Extra iterations granted after ``max_iterations`` is exhausted, during
    # which tool dispatch is restricted to a terminal-tool whitelist
    # (``report_to_parent``, ``tracker_upsert``, ``task_update``) so the
    # agent can wrap up and report instead of dying silently. A single
    # ``<system-reminder>`` is injected at the start of the first grace
    # iteration explaining the restriction. 0 disables grace (current
    # behavior — loop terminates at ``max_iterations`` with whatever the
    # worker last did). Workers default to 1; queens default to 0 because
    # they don't call ``report_to_parent``.
    grace_iterations: int = 0
    # Tool-call pacing budget for one agent turn-loop (a single judge
    # iteration of _run_turn_loop, which may itself span several inner
    # model<->tool turns). The counter resets at the start of each
    # turn-loop. While running, the loop emits an escalating *soft*
    # checkpoint reminder every `tool_call_budget` calls — a nudge to
    # reassess, never a stop — and a *hard* stop once the count exceeds
    # `tool_call_budget * tool_call_hard_multiple` (see that field).
    # 0 (or any non-positive value) disables both the soft reminders
    # and the hard stop, letting a turn-loop fan out arbitrarily many
    # tool calls.
    tool_call_budget: int = 0
    judge_every_n_turns: int = 1
    stall_detection_threshold: int = 3
    stall_similarity_threshold: float = 0.85
    max_context_tokens: int = 180_000
    # Headroom reserved for the NEXT turn's input + output so that
    # proactive compaction always finishes before the hard context limit
    # is hit mid-stream. Scaled to match Claude Code's 13k-buffer-on-
    # 200k-window ratio (~6.5%) applied to hive's default 32k window,
    # with extra margin because hive's token estimator is char-based
    # and less tight than Anthropic's own counting. Override via
    # LoopConfig for larger windows.
    compaction_buffer_tokens: int = 8_000
    # Ratio-based component of the hybrid compaction buffer. Effective
    # headroom reserved before compaction fires is
    #   compaction_buffer_tokens + compaction_buffer_ratio * max_context_tokens
    # The ratio scales with the model's window where the absolute fixed
    # component does not (an 8k absolute buffer is 75% trigger on a 32k
    # window but 96% on a 200k window). Combining them gives an absolute
    # floor sized for the worst-case single tool result (one un-spilled
    # max_tool_result_chars payload ≈ 30k chars ≈ 7.5k tokens, rounded to
    # 8k) plus a fractional headroom that keeps the trigger meaningful on
    # large windows, so the inner tool loop always has room to grow
    # without tripping the mid-turn pre-send guard. Defaults: 8k + 40%.
    # On the hive default 180k window that's an 80k buffer (trigger at
    # ~100k, ~56%); on 32k it's 20.8k (~35% trigger); on 1M it's 408k
    # (~59% trigger). Raised from 0.25 (trigger ~127k on 180k) in 2026-07:
    # the cost analysis showed queen sessions plateauing at p50 ~110k
    # context tokens per call — dozens of turns cruising just under the
    # old trigger, re-sending ~270 messages of history on every call.
    # Firing at ~100k trades more frequent compaction summaries (and a
    # cache-prefix rebuild after each) for a materially smaller resent-
    # history base; the char-based estimator also under-counts vs billed
    # tokens, so the effective billed trigger sits above this number.
    compaction_buffer_ratio: float = 0.4
    # Warning is emitted one buffer earlier so the user/telemetry gets
    # a "we're close" signal without triggering a compaction pass.
    compaction_warning_buffer_tokens: int = 12_000
    store_prefix: str = ""

    # Hard-stop multiple for `tool_call_budget`. The turn-loop hard-stops
    # and defers any remaining tool calls once the running count exceeds
    # `tool_call_budget * tool_call_hard_multiple`. Soft checkpoint
    # reminders fire at every budget multiple strictly below the hard
    # stop (1x .. (hard_multiple - 1)x). Default 5 (e.g. budget 30 ->
    # reminders at 30/60/90/120, hard stop at 150); workers run tighter
    # at 2. Ignored when `tool_call_budget` is 0.
    tool_call_hard_multiple: int = 5

    # Cumulative (lifetime) tool-call budget for the WHOLE execute() run,
    # across every turn-loop — distinct from `tool_call_budget`, which
    # resets each turn. 0 disables (default; queens / overseers / node
    # workers leave it 0). When the running total of executed tool calls
    # reaches this, the loop enters its grace wind-down early: a stop
    # reminder is injected telling the worker to call report_to_parent
    # with partial results, dispatch is restricted to the terminal-tool
    # whitelist, and the loop exits after grace_iterations wrap-up turn(s).
    # Set for workers via worker_definition.DEFAULT_LOOP_CONFIG.
    tool_call_lifetime_budget: int = 0

    # Tool result context management.
    #
    # Results larger than this are replaced in-context with a preview +
    # spillover file reference; the full payload is written to
    # ``spillover_dir`` so the agent can re-read it via terminal_exec on
    # demand. See tool_result_handler.truncate_tool_result.
    #
    # 30k matches the value stamped by every production spawn site
    # (orchestrator, node_worker, colony_runtime, queen_orchestrator)
    # and is the size the compaction buffer above is sized against
    # (~7.5k tokens worst-case single payload). A lower cap (8-12k) has
    # been hypothesized to reduce per-turn request density on the theory
    # that heads carry most information density, but that experiment is
    # not shipped — change the overrides, not just this default, if you
    # want to try it.
    max_tool_result_chars: int = 30_000
    spillover_dir: str | None = None

    # Image retention in conversation history.
    # Screenshots from ``hive-browser screenshot`` (re-inlined by the framework
    # from the terminal result) are stored as base64
    # data URLs inside message ``image_content``. Each full-page
    # screenshot costs ~250k tokens when the provider counts the
    # base64 as text (gemini, most non-Anthropic providers). Four
    # screenshots in one conversation push gemini's 1M context over
    # the limit and the model starts emitting garbage.
    #
    # The framework strips image_content from older messages after
    # every tool-result batch, keeping only the most recent N
    # screenshots. The text metadata on evicted messages (url, size,
    # scale hints) is preserved so the agent can still reason about
    # "I took a screenshot at step N that showed the compose modal".
    # Raise this only if you genuinely need longer visual history AND
    # you know your provider is using native image tokenization.
    max_retained_screenshots: int = 2

    # set_output value spilling.
    max_output_value_chars: int = 2_000

    # Stream retry.
    max_stream_retries: int = 5
    stream_retry_backoff_base: float = 2.0
    stream_retry_max_delay: float = 60.0
    # Persistent retry for capacity-class errors (429, 529, overloaded).
    # Unlike the bounded retry above, these keep trying until the wall-clock
    # budget below is exhausted — modelled after claude-code's withRetry.
    # The loop still publishes a retry event each attempt so the UI can
    # see progress. Set to 0 to disable and fall back to bounded retry.
    capacity_retry_max_seconds: float = 600.0
    capacity_retry_max_delay: float = 60.0

    # Tool doom loop detection.
    tool_doom_loop_threshold: int = 3

    # Client-facing auto-block grace period.
    cf_grace_turns: int = 1
    # Worker stall grace: consecutive text-only turns (no tool calls,
    # no set_output, no ask_user) before the framework auto-fails the
    # worker. Behavior diverges by worker type:
    #   - Parallel workers (stream_id="worker:*"): synthesize a
    #     report_to_parent(status='failed') and exit. Per the BRD's
    #     fail-fast model — queen reads the failure as a
    #     [WORKER_REPORT] and re-dispatches as needed. NO escalation
    #     to the queen, NO synchronous wait.
    #   - Legacy primary worker (stream_id="worker"): emit
    #     ESCALATION_REQUESTED and pause for queen guidance via
    #     inject_message. Pre-BRD behavior, retained for legacy flows.
    # Grace=2 means: first plan-text turn is fine (chain-of-thought),
    # second consecutive text-only turn is also tolerated (rare-but-OK
    # for genuinely-thinking models), third triggers the auto-fail.
    worker_escalation_grace_turns: int = 2
    tool_doom_loop_enabled: bool = True
    # Silent worker: consecutive tool-only turns (no user-facing text)
    # before injecting a nudge to communicate progress.
    silent_tool_streak_threshold: int = 5

    # Per-tool-call timeout.
    tool_call_timeout_seconds: float = 60.0
    # Per-class overrides, matched by tool-name prefix (longest prefix
    # wins; falls back to tool_call_timeout_seconds). browser_* defaults
    # higher: heavy-page evaluates legitimately run past 60s, and N
    # workers share one MCP client per server, so a queued call behind a
    # slow one needs the same headroom. INVARIANT: every value here must
    # stay below MCPClient._CALL_RESULT_TIMEOUT (default 240s).
    tool_timeout_overrides: dict[str, float] = field(default_factory=lambda: {"browser_": 180.0})

    # Tools the caller runs in the BACKGROUND: the call returns a handle
    # immediately and the agent collects the result later via the synthetic
    # ``collect_result`` tool. For tools whose work legitimately exceeds the
    # per-call timeout (e.g. image generation, which can take minutes). This
    # keeps the agent loop — and the shared MCP server — unblocked. See
    # ``AgentLoop._execute_tool`` / ``_start_background_tool``.
    background_tools: set[str] = field(default_factory=lambda: {"image_generate", "terminal_exec"})
    # Timeout for a backgrounded tool's underlying call. Must stay below
    # MCPClient._CALL_RESULT_TIMEOUT (240s), same invariant as the overrides.
    background_tool_timeout_seconds: float = 235.0
    # Grace window before a background tool actually backgrounds. Work that
    # finishes inside it returns on the original call and never mints a
    # handle. This is a CEILING, not a sleep: a 10ms command returns in
    # 10ms; only work that overruns the window pays it, and the command is
    # running throughout. Sized from a production terminal_exec session
    # (median command 1.5s vs 4.9s of model latency per collect_result
    # turn a handle forces). Set 0 to always background immediately.
    background_tool_grace_seconds: float = 5.0

    # LLM stream inactivity watchdog. Split into two budgets so legitimate
    # slow TTFT on large contexts doesn't get mistaken for a dead connection.
    # - ttft: stream open -> first event. Large-context local models can
    #   legitimately take minutes before the first token arrives.
    # - inter_event: last event -> now, ONLY after the first event. A stream
    #   that started producing and then went silent is a real stall.
    # Whichever fires first cancels the stream. Set to 0 to disable that
    # individual budget; set both to 0 to fully disable the watchdog.
    llm_stream_ttft_timeout_seconds: float = 600.0
    llm_stream_inter_event_idle_seconds: float = 120.0
    # Deprecated alias — kept so existing configs keep working. If set to a
    # non-default value it overrides inter_event_idle (historical behavior).
    llm_stream_inactivity_timeout_seconds: float = 120.0

    # Continue-nudge recovery. When the idle watchdog fires on a live but
    # stuck stream, cancel the stream and append a short continuation
    # hint to the conversation instead of raising a ConnectionError and
    # re-running the whole turn. Preserves any partial text/tool-calls the
    # stream emitted before the stall.
    continue_nudge_enabled: bool = True
    # Cap so a truly dead endpoint eventually falls back to the error path
    # instead of nudging forever.
    continue_nudge_max_per_turn: int = 3

    # Session-level idle watchdog. Fires when the session has been alive but
    # silent (no stream events, no tool completions, no iteration boundary)
    # for this many seconds AND _awaiting_input is False. Complements the
    # stream-level TTFT/inter-event budgets above, which are blind to gaps
    # between turns (no _stream_task) and to slow-TTFT silence under the
    # generous 600s ceiling. Set seconds or cap to 0 to disable.
    session_idle_nudge_seconds: float = 120.0
    session_idle_nudge_max_per_session: int = 3
    # Budget for an *invalid* awaiting-input park — the loop is blocked on
    # user input but presented no question, so there is nothing to answer.
    # Kept at the generous general budget rather than a shorter one: a
    # shorter (45s) budget fired while a user was still composing a long
    # message, so the queen began responding before it was submitted. A
    # full 120s pause is well past any normal typing gap. 0 disables.
    session_idle_nudge_awaiting_seconds: float = 120.0
    # Budget for a *broken* park — the loop parked after a failure (LLM
    # error, doom loop, repeated empty turns), not by design. Shorter than
    # the questionless budget: a stranded loop should be recovered quickly,
    # and there is no "user mid-typing" risk to weigh against it. 0 disables.
    session_idle_nudge_broken_seconds: float = 30.0

    # Tool-call replay detector. When the model emits a tool call whose
    # (name + canonical-args) matches a prior successful call in the last
    # K assistant turns, emit telemetry and prepend a short steer onto the
    # tool result — but still execute. Weaker models legitimately repeat
    # read-only calls (screenshot, evaluate), so silent skipping would
    # cause surprising behavior.
    replay_detector_enabled: bool = True
    replay_detector_within_last_turns: int = 3
    # Tools fully EXEMPT from BOTH the replay detector and the doom-loop
    # breaker: ones the agent legitimately calls repeatedly with identical
    # args — async-job polls, idempotent reads, status/observe calls, and
    # synthetic control tools. The breaker exists to catch a model stuck
    # re-issuing the same FAILING action; these repeat by design, so counting
    # them is a false positive (the symptom: a 3-minute image poll, or a
    # re-screenshot loop, tripping the breaker). Mutating/action tools
    # (edits, sends, terminal_exec — which now also carries browser actions
    # via the hive-browser CLI, …)
    # deliberately stay guarded. Extend per deployment as needed.
    replay_exempt_tools: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                # Synthetic control / poll tools.
                "ask_user",
                "escalate",
                "collect_result",
                # Async-job polling (terminal jobs).
                "terminal_job_logs",
                "terminal_job_manage",
                "terminal_output_get",
                # NOTE: browser observation/scripting now runs via the
                # `hive-browser` CLI under terminal_exec (guarded above), not as
                # distinct browser_* tools. Re-observation with identical args
                # (re-screenshot / re-snapshot after acting) is normal browser
                # behaviour; if the replay breaker false-positives on repeated
                # `hive-browser ...` terminal calls, exempt them command-aware
                # here (this list keys on tool name, which is now terminal_exec).
                # Lookups / context reads.
                "search_tools",
                "search_messages",
                "get_current_time",
                "get_account_info",
            }
        )
    )

    # Subagent delegation timeout (wall-clock max).
    subagent_timeout_seconds: float = 3600.0

    # Subagent inactivity timeout - only timeout if no activity for this duration.
    # This resets whenever the subagent makes progress (tool calls, LLM responses).
    # Set to 0 to use only the wall-clock timeout.
    subagent_inactivity_timeout_seconds: float = 300.0

    # Lifecycle hooks.
    hooks: dict[str, list] | None = None

    def __post_init__(self) -> None:
        if self.hooks is None:
            object.__setattr__(self, "hooks", {})


@dataclass
class HookContext:
    """Context passed to every lifecycle hook."""

    event: str
    trigger: str | None
    system_prompt: str


@dataclass
class HookResult:
    """What a hook may return to modify node state."""

    system_prompt: str | None = None
    inject: str | None = None


@dataclass
class OutputAccumulator:
    """Accumulates output key-value pairs with optional write-through persistence."""

    values: dict[str, Any] = field(default_factory=dict)
    store: ConversationStore | None = None
    spillover_dir: str | None = None
    max_value_chars: int = 0
    run_id: str | None = None

    async def set(self, key: str, value: Any) -> None:
        """Set a key-value pair, auto-spilling large values to files."""
        value = await self._auto_spill(key, value)
        self.values[key] = value
        if self.store:
            cursor = await self.store.read_cursor() or {}
            outputs = cursor.get("outputs", {})
            outputs[key] = value
            cursor["outputs"] = outputs
            await self.store.write_cursor(cursor)

    async def _auto_spill(self, key: str, value: Any) -> Any:
        """Save large values to a file and return a reference string.

        Runs the JSON serialization and file write on a worker thread
        so they don't block the asyncio event loop. For a 100k-char
        dict this used to freeze every concurrent tool call for ~50ms
        of ``json.dumps(indent=2)`` + a sync disk write; for bigger
        payloads or slow storage (NFS, networked FS) the freeze was
        proportionally worse.
        """
        if self.max_value_chars <= 0 or not self.spillover_dir:
            return value

        # Cheap size probe first — if the value is already a short
        # string we can skip both the JSON round-trip and the thread
        # hop entirely.
        if isinstance(value, str) and len(value) <= self.max_value_chars:
            return value

        def _spill_sync() -> Any:
            # JSON serialization for size check (only for non-strings).
            if isinstance(value, str):
                val_str = value
            else:
                val_str = json.dumps(value, ensure_ascii=False)
            if len(val_str) <= self.max_value_chars:
                return value

            spill_path = Path(self.spillover_dir)
            spill_path.mkdir(parents=True, exist_ok=True)
            ext = ".json" if isinstance(value, (dict, list)) else ".txt"
            filename = f"output_{key}{ext}"
            write_content = json.dumps(value, indent=2, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            file_path = spill_path / filename
            file_path.write_text(write_content, encoding="utf-8")
            file_size = file_path.stat().st_size
            logger.info(
                "set_output value auto-spilled: key=%s, %d chars -> %s (%d bytes)",
                key,
                len(val_str),
                filename,
                file_size,
            )
            # Use absolute path so parent agents can find files from subagents.
            #
            # Prose format (no brackets) — same fix as tool_result_handler:
            # frontier pattern-matching models autocomplete bracketed
            # `[Saved to '...']` trailers into their own assistant turns,
            # eventually degenerating into echoing the file path as text.
            # Keep the path accessible but frame it as plain prose.
            abs_path = str(file_path.resolve())
            return f'Output saved at: {abs_path} ({file_size:,} bytes). Read the full data with terminal_exec("cat {abs_path}").'

        return await asyncio.to_thread(_spill_sync)

    def get(self, key: str) -> Any | None:
        return self.values.get(key)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)

    def has_all_keys(self, required: list[str]) -> bool:
        return all(key in self.values and self.values[key] is not None for key in required)

    @classmethod
    async def restore(
        cls,
        store: ConversationStore,
        run_id: str | None = None,
    ) -> OutputAccumulator:
        cursor = await store.read_cursor()
        values = cursor.get("outputs", {}) if cursor else {}
        return cls(values=values, store=store, run_id=run_id)


__all__ = [
    "HookContext",
    "HookResult",
    "JudgeProtocol",
    "JudgeVerdict",
    "LoopConfig",
    "OutputAccumulator",
    "TriggerEvent",
]
