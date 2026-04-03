"""Shared types and state containers for the event loop package."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from framework.graph.conversation import ConversationStore
from framework.utils.io import atomic_write

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
    max_tool_calls_per_turn: int = 30
    judge_every_n_turns: int = 1
    stall_detection_threshold: int = 3
    stall_similarity_threshold: float = 0.85
    max_context_tokens: int = 32_000
    store_prefix: str = ""

    # Overflow margin for max_tool_calls_per_turn. Tool calls are only
    # discarded when the count exceeds max_tool_calls_per_turn * (1 + margin).
    tool_call_overflow_margin: float = 0.5

    # Tool result context management.
    max_tool_result_chars: int = 30_000
    spillover_dir: str | None = None

    # set_output value spilling.
    max_output_value_chars: int = 2_000

    # Stream retry.
    max_stream_retries: int = 3
    stream_retry_backoff_base: float = 2.0
    stream_retry_max_delay: float = 60.0

    # Tool doom loop detection.
    tool_doom_loop_threshold: int = 3

    # Client-facing auto-block grace period.
    cf_grace_turns: int = 1
    tool_doom_loop_enabled: bool = True

    # Per-tool-call timeout.
    tool_call_timeout_seconds: float = 60.0

    # Subagent delegation timeout.
    subagent_timeout_seconds: float = 600.0

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

    async def set(self, key: str, value: Any) -> None:
        """Set a key-value pair, auto-spilling large values to files."""
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
        with atomic_write(spill_path / filename, mode="w", encoding="utf-8") as f:
            f.write(write_content)
        file_size = (spill_path / filename).stat().st_size
        logger.info(
            "set_output value auto-spilled: key=%s, %d chars -> %s (%d bytes)",
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
        return self.values.get(key)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)

    def has_all_keys(self, required: list[str]) -> bool:
        return all(key in self.values and self.values[key] is not None for key in required)

    @classmethod
    async def restore(cls, store: ConversationStore) -> OutputAccumulator:
        cursor = await store.read_cursor()
        values = {}
        if cursor and "outputs" in cursor:
            values = cursor["outputs"]
        return cls(values=values, store=store)


__all__ = [
    "HookContext",
    "HookResult",
    "JudgeProtocol",
    "JudgeVerdict",
    "LoopConfig",
    "OutputAccumulator",
    "TriggerEvent",
]
