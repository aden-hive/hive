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
    # 0 (or any non-positive value) disables the per-turn hard limit,
    # letting a single assistant turn fan out arbitrarily many tool
    # calls. Models like Gemini 3.1 Pro routinely emit 40-80 tool
    # calls in one turn during browser exploration; capping them
    # strands work half-finished and makes the next turn repeat the
    # discarded calls, which is worse than just running them.
    max_tool_calls_per_turn: int = 0
    judge_every_n_turns: int = 1
    stall_detection_threshold: int = 3
    stall_similarity_threshold: float = 0.85
    max_context_tokens: int = 32_000
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
    # without tripping the mid-turn pre-send guard. Defaults: 8k + 15%.
    # On 32k that's a 12.8k buffer (~60% trigger); on 200k it's 38k
    # (~81% trigger); on 1M it's 158k (~84% trigger).
    compaction_buffer_ratio: float = 0.15
    # Warning is emitted one buffer earlier so the user/telemetry gets
    # a "we're close" signal without triggering a compaction pass.
    compaction_warning_buffer_tokens: int = 12_000
    store_prefix: str = ""

    # Overflow margin for max_tool_calls_per_turn. When the limit is
    # enabled (>0), tool calls are only discarded when the count
    # exceeds max_tool_calls_per_turn * (1 + margin). Ignored when
    # max_tool_calls_per_turn is 0.
    tool_call_overflow_margin: float = 0.5

    # Tool result context management.
    max_tool_result_chars: int = 30_000
    spillover_dir: str | None = None

    # Image retention in conversation history.
    # Screenshots from ``browser_screenshot`` are inlined as base64
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
    # Worker auto-escalation: text-only turns before escalating to queen.
    worker_escalation_grace_turns: int = 1
    tool_doom_loop_enabled: bool = True
    # Silent worker: consecutive tool-only turns (no user-facing text)
    # before injecting a nudge to communicate progress.
    silent_tool_streak_threshold: int = 5

    # Per-tool-call timeout.
    tool_call_timeout_seconds: float = 60.0

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

    # Tool-call replay detector. When the model emits a tool call whose
    # (name + canonical-args) matches a prior successful call in the last
    # K assistant turns, emit telemetry and prepend a short steer onto the
    # tool result — but still execute. Weaker models legitimately repeat
    # read-only calls (screenshot, evaluate), so silent skipping would
    # cause surprising behavior.
    replay_detector_enabled: bool = True
    replay_detector_within_last_turns: int = 3

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
            write_content = (
                json.dumps(value, indent=2, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
            )
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
            return (
                f"Output saved at: {abs_path} ({file_size:,} bytes). "
                f"Read the full data with read_file(path='{abs_path}')."
            )

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
