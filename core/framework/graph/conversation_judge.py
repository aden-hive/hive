"""Level 2 Conversation-Aware Judge.

When a node has `success_criteria` set, the implicit judge upgrades:
after Level 0 passes (all output keys set), a fast LLM call evaluates
whether the conversation actually meets the criteria.

This prevents nodes from "checking boxes" (setting output keys) without
doing quality work. The LLM reads the recent conversation and assesses
whether the phase's goal was genuinely accomplished.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from framework.graph.conversation import NodeConversation
from framework.llm.provider import LLMProvider

logger = logging.getLogger(__name__)


@dataclass
class PhaseVerdict:
    """Result of Level 2 conversation-aware evaluation."""

    action: str  # "ACCEPT" or "RETRY"
    confidence: float = 0.8
    feedback: str = ""


async def evaluate_phase_completion(
    llm: LLMProvider,
    conversation: NodeConversation,
    phase_name: str,
    phase_description: str,
    success_criteria: str,
    accumulator_state: dict[str, Any],
    max_history_tokens: int = 8_196,
) -> PhaseVerdict:
    """Level 2 judge: read the conversation and evaluate quality.

    Only called after Level 0 passes (all output keys set).

    Args:
        llm: LLM provider for evaluation
        conversation: The current conversation to evaluate
        phase_name: Name of the current phase/node
        phase_description: Description of the phase
        success_criteria: Natural-language criteria for phase completion
        accumulator_state: Current output key values
        max_history_tokens: Main conversation token budget (judge gets 20%)

    Returns:
        PhaseVerdict with action and optional feedback
    """
    # Build a compact view of the recent conversation
    recent_messages = _extract_recent_context(conversation, max_messages=10)
    outputs_summary = _format_outputs(accumulator_state)

    system_prompt = (
        "You are a quality judge evaluating whether a phase of work is complete. "
        "Be concise. Evaluate based on the success criteria, not on style."
    )

    user_prompt = f"""Evaluate this phase:

PHASE: {phase_name}
DESCRIPTION: {phase_description}

SUCCESS CRITERIA:
{success_criteria}

OUTPUTS SET:
{outputs_summary}

RECENT CONVERSATION:
{recent_messages}

Has this phase accomplished its goal based on the success criteria?

Respond in exactly this format:
ACTION: ACCEPT or RETRY
CONFIDENCE: 0.X
FEEDBACK: (reason if RETRY, empty if ACCEPT)"""

    try:
        response = llm.complete(
            messages=[{"role": "user", "content": user_prompt}],
            system=system_prompt,
            max_tokens=max(1024, max_history_tokens // 5),
            max_retries=1,
        )
        if not response.content or not response.content.strip():
            logger.debug("Level 2 judge: empty response, accepting by default")
            return PhaseVerdict(action="ACCEPT", confidence=0.5, feedback="")
        return _parse_verdict(response.content)
    except Exception as e:
        logger.warning(f"Level 2 judge failed, accepting by default: {e}")
        # On failure, don't block — Level 0 already passed
        return PhaseVerdict(action="ACCEPT", confidence=0.5, feedback="")


def _extract_recent_context(conversation: NodeConversation, max_messages: int = 10) -> str:
    """Extract recent conversation messages for evaluation."""
    messages = conversation.messages
    recent = messages[-max_messages:] if len(messages) > max_messages else messages

    parts = []
    for msg in recent:
        role = msg.role.upper()
        content = msg.content or ""
        # Truncate long tool results
        if msg.role == "tool" and len(content) > 200:
            content = content[:200] + "..."
        if content.strip():
            parts.append(f"[{role}]: {content.strip()}")

    return "\n".join(parts) if parts else "(no messages)"


def _format_outputs(accumulator_state: dict[str, Any]) -> str:
    """Format output key values for evaluation.

    Lists and dicts get structural formatting so the judge can assess
    quantity and structure, not just a truncated stringification.
    """
    if not accumulator_state:
        return "(none)"
    parts = []
    for key, value in accumulator_state.items():
        if isinstance(value, list):
            # Show count + brief per-item preview so the judge can
            # verify quantity without the full serialization.
            items_preview = []
            for i, item in enumerate(value[:8]):
                item_str = str(item)
                if len(item_str) > 150:
                    item_str = item_str[:150] + "..."
                items_preview.append(f"    [{i}]: {item_str}")
            val_str = f"list ({len(value)} items):\n" + "\n".join(items_preview)
            if len(value) > 8:
                val_str += f"\n    ... and {len(value) - 8} more"
        elif isinstance(value, dict):
            val_str = str(value)
            if len(val_str) > 400:
                val_str = val_str[:400] + "..."
        else:
            val_str = str(value)
            if len(val_str) > 300:
                val_str = val_str[:300] + "..."
        parts.append(f"  {key}: {val_str}")
    return "\n".join(parts)


def _parse_verdict(response: str) -> PhaseVerdict:
    """Parse LLM response into PhaseVerdict."""
    action = "ACCEPT"
    confidence = 0.8
    feedback = ""

    for line in response.strip().split("\n"):
        line = line.strip()
        if line.startswith("ACTION:"):
            action_str = line.split(":", 1)[1].strip().upper()
            if action_str in ("ACCEPT", "RETRY"):
                action = action_str
        elif line.startswith("CONFIDENCE:"):
            try:
                confidence = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("FEEDBACK:"):
            feedback = line.split(":", 1)[1].strip()

    return PhaseVerdict(action=action, confidence=confidence, feedback=feedback)
