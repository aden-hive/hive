"""Context handoff: summarize a completed NodeConversation for the next graph node."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from framework.graph.conversation import _try_extract_key

if TYPE_CHECKING:
    from framework.graph.conversation import NodeConversation
    from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)

_TRUNCATE_CHARS = 500


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
