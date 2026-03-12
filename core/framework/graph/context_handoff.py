"""Context handoff helpers for node-to-node and worker-to-queen transfers."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from framework.graph.conversation import _try_extract_key

if TYPE_CHECKING:
    from framework.graph.conversation import NodeConversation
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_TRUNCATE_CHARS = 500
_HANDOFF_CONTEXT_MAX_CHARS = 1200
_HANDOFF_CONTEXT_MAX_LINES = 18
_HANDOFF_CONTEXT_HEAD_LINES = 4
_HANDOFF_CONTEXT_TAIL_LINES = 4
_HANDOFF_CONTEXT_MIDDLE_LINES = 6
_HANDOFF_CONTEXT_LINE_LIMIT = 220
_HANDOFF_CONTEXT_KEYWORDS = (
    "error",
    "exception",
    "traceback",
    "failed",
    "failure",
    "blocked",
    "retry",
    "warning",
    "timeout",
    "auth",
    "login",
    "credential",
    "token",
    "captcha",
    "status",
    "result",
    "output",
    "http",
)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


@dataclass
class HandoffContext:
    """Structured summary of a completed node conversation."""

    source_node_id: str
    summary: str
    key_outputs: dict[str, Any]
    turn_count: int
    total_tokens_used: int


@dataclass(frozen=True)
class CompactedHandoffText:
    """Deterministically compacted free-form text for cross-agent handoffs."""

    text: str
    original_chars: int
    compacted_chars: int

    @property
    def was_compacted(self) -> bool:
        return self.compacted_chars < self.original_chars

    @property
    def original_tokens_estimate(self) -> int:
        return self.original_chars // 4

    @property
    def compacted_tokens_estimate(self) -> int:
        return self.compacted_chars // 4


def compact_handoff_text(
    text: str,
    *,
    max_chars: int = _HANDOFF_CONTEXT_MAX_CHARS,
    max_lines: int = _HANDOFF_CONTEXT_MAX_LINES,
) -> CompactedHandoffText:
    """Compact large handoff text before injecting it into another agent.

    This is intentionally deterministic and lightweight: it avoids an extra LLM
    call while still preserving the first/last context plus the most
    signal-dense middle lines.
    """
    normalized = _normalize_handoff_text(text)
    original_chars = len(normalized)
    if not normalized:
        return CompactedHandoffText(text="", original_chars=0, compacted_chars=0)

    lines = _normalize_handoff_lines(normalized)
    if original_chars <= max_chars and len(lines) <= max_lines:
        return CompactedHandoffText(
            text=normalized,
            original_chars=original_chars,
            compacted_chars=original_chars,
        )

    if len(lines) <= 1:
        compacted = _compact_single_line(normalized, max_chars=max_chars)
    else:
        compacted = _compact_multiline(
            lines,
            max_chars=max_chars,
            max_lines=max_lines,
        )

    if len(compacted) > max_chars:
        compacted = _compact_single_line(compacted, max_chars=max_chars)

    return CompactedHandoffText(
        text=compacted,
        original_chars=original_chars,
        compacted_chars=len(compacted),
    )


def _normalize_handoff_text(text: str) -> str:
    """Normalize whitespace without destroying the evidence structure."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return normalized


def _normalize_handoff_lines(text: str) -> list[str]:
    """Strip noisy spacing and collapse repeated blank lines."""
    cleaned: list[str] = []
    previous_blank = False
    for raw_line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line:
            if not previous_blank:
                cleaned.append("")
            previous_blank = True
            continue
        cleaned.append(line)
        previous_blank = False

    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return cleaned


def _compact_single_line(text: str, *, max_chars: int) -> str:
    """Compact a long single-line context with head/tail preservation."""
    if len(text) <= max_chars:
        return text

    available = max(80, max_chars - 7)
    head = max(30, available // 2)
    tail = max(20, available - head)
    return f"{text[:head].rstrip()} [...] {text[-tail:].lstrip()}"


def _compact_multiline(
    lines: list[str],
    *,
    max_chars: int,
    max_lines: int,
) -> str:
    """Keep the edges and most relevant middle lines from a multiline handoff."""
    total = len(lines)
    head_count = min(_HANDOFF_CONTEXT_HEAD_LINES, total, max_lines)
    tail_count = min(_HANDOFF_CONTEXT_TAIL_LINES, total - head_count, max_lines - head_count)

    selected: set[int] = set(range(head_count))
    if tail_count:
        selected.update(range(total - tail_count, total))

    candidates: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        if idx in selected or not line:
            continue
        candidates.append((_score_handoff_line(line), idx))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    for score, idx in candidates:
        if len(selected) >= max_lines:
            break
        if score <= 0 and len(selected) >= head_count + tail_count + _HANDOFF_CONTEXT_MIDDLE_LINES:
            break
        selected.add(idx)

    compacted_lines: list[str] = []
    last_idx: int | None = None
    for idx in sorted(selected):
        if last_idx is not None and idx - last_idx > 1:
            compacted_lines.append("[...]")
        compacted_lines.append(_trim_handoff_line(lines[idx]))
        last_idx = idx

    compacted = "\n".join(compacted_lines)
    if len(compacted) <= max_chars:
        return compacted

    overflow = len(compacted) - max_chars
    trimmed_lines = list(compacted_lines)
    for i, line in enumerate(trimmed_lines):
        if overflow <= 0:
            break
        if line == "[...]":
            continue
        new_limit = max(80, min(_HANDOFF_CONTEXT_LINE_LIMIT, len(line) - overflow))
        shortened = _trim_handoff_line(line, max_len=new_limit)
        overflow -= len(line) - len(shortened)
        trimmed_lines[i] = shortened

    compacted = "\n".join(trimmed_lines)
    return compacted if len(compacted) <= max_chars else _compact_single_line(compacted, max_chars=max_chars)


def _score_handoff_line(line: str) -> int:
    """Prefer lines that carry actionable evidence over generic narration."""
    lower = line.lower()
    score = 0
    if any(keyword in lower for keyword in _HANDOFF_CONTEXT_KEYWORDS):
        score += 4
    if line.startswith(("Traceback", "File ", "{", "[")):
        score += 2
    if line.lstrip().startswith(("-", "*", "•")) or ":" in line or "=" in line:
        score += 1
    if "http" in lower or "/" in line or "\\" in line:
        score += 1
    if any(ch.isdigit() for ch in line):
        score += 1
    return score


def _trim_handoff_line(line: str, max_len: int = _HANDOFF_CONTEXT_LINE_LIMIT) -> str:
    """Trim a line while preserving both the prefix and suffix."""
    if len(line) <= max_len:
        return line

    available = max(20, max_len - 5)
    head = max(12, available // 2)
    tail = max(8, available - head)
    return f"{line[:head].rstrip()} [...] {line[-tail:].lstrip()}"


# ---------------------------------------------------------------------------
# ContextHandoff
# ---------------------------------------------------------------------------


class ContextHandoff:
    """Summarize a completed NodeConversation into a HandoffContext.

    Parameters
    ----------
    llm : LLMProvider | None
        Optional LLM provider for abstractive summarization.
        When *None*, all summarization uses the extractive fallback.
    """

    def __init__(self, llm: LLMProvider | None = None) -> None:
        self.llm = llm

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def summarize_conversation(
        self,
        conversation: NodeConversation,
        node_id: str,
        output_keys: list[str] | None = None,
    ) -> HandoffContext:
        """Produce a HandoffContext from *conversation*.

        1. Extracts turn_count & total_tokens_used (sync properties).
        2. Extracts key_outputs by scanning assistant messages most-recent-first.
        3. Builds a summary via the LLM (if available) or extractive fallback.
        """
        turn_count = conversation.turn_count
        total_tokens_used = conversation.estimate_tokens()
        messages = conversation.messages  # defensive copy

        # --- key outputs ---------------------------------------------------
        key_outputs: dict[str, Any] = {}
        if output_keys:
            remaining = set(output_keys)
            for msg in reversed(messages):
                if msg.role != "assistant" or not remaining:
                    continue
                for key in list(remaining):
                    value = _try_extract_key(msg.content, key)
                    if value is not None:
                        key_outputs[key] = value
                        remaining.discard(key)

        # --- summary -------------------------------------------------------
        if self.llm is not None:
            try:
                summary = self._llm_summary(messages, output_keys or [])
            except Exception:
                logger.warning(
                    "LLM summarization failed; falling back to extractive.",
                    exc_info=True,
                )
                summary = self._extractive_summary(messages)
        else:
            summary = self._extractive_summary(messages)

        return HandoffContext(
            source_node_id=node_id,
            summary=summary,
            key_outputs=key_outputs,
            turn_count=turn_count,
            total_tokens_used=total_tokens_used,
        )

    @staticmethod
    def format_as_input(handoff: HandoffContext) -> str:
        """Render *handoff* as structured plain text for the next node's input."""
        header = (
            f"--- CONTEXT FROM: {handoff.source_node_id} "
            f"({handoff.turn_count} turns, ~{handoff.total_tokens_used} tokens) ---"
        )

        sections: list[str] = [header, ""]

        if handoff.key_outputs:
            sections.append("KEY OUTPUTS:")
            for k, v in handoff.key_outputs.items():
                sections.append(f"- {k}: {v}")
            sections.append("")

        summary_text = handoff.summary or "No summary available."
        sections.append("SUMMARY:")
        sections.append(summary_text)
        sections.append("")
        sections.append("--- END CONTEXT ---")

        return "\n".join(sections)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extractive_summary(messages: list) -> str:
        """Build a summary from key assistant messages without an LLM.

        Strategy:
        - Include the first assistant message (initial assessment).
        - Include the last assistant message (final conclusion).
        - Truncate each to ~500 chars.
        """
        if not messages:
            return "Empty conversation."

        assistant_msgs = [m for m in messages if m.role == "assistant"]
        if not assistant_msgs:
            return "No assistant responses."

        parts: list[str] = []

        first = assistant_msgs[0].content
        parts.append(first[:_TRUNCATE_CHARS])

        if len(assistant_msgs) > 1:
            last = assistant_msgs[-1].content
            parts.append(last[:_TRUNCATE_CHARS])

        return "\n\n".join(parts)

    def _llm_summary(self, messages: list, output_keys: list[str]) -> str:
        """Produce a summary by calling the LLM provider."""
        if self.llm is None:
            raise ValueError("_llm_summary called without an LLM provider")

        conversation_text = "\n".join(f"[{m.role}]: {m.content}" for m in messages)

        key_hint = ""
        if output_keys:
            key_hint = (
                "\nThe following output keys are especially important: "
                + ", ".join(output_keys)
                + ".\n"
            )

        system_prompt = (
            "You are a concise summarizer. Given the conversation below, "
            "produce a brief summary (at most ~500 tokens) that captures the "
            "key decisions, findings, and outcomes. Focus on what was concluded "
            "rather than the back-and-forth process." + key_hint
        )

        response = self.llm.complete(
            messages=[{"role": "user", "content": conversation_text}],
            system=system_prompt,
            max_tokens=500,
        )

        return response.content.strip()
